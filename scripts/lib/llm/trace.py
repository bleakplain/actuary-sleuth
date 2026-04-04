"""LLM 调用链路追踪。

提供 TraceSpan 模型和 contextvars 传播机制，
用于记录 RAG 管线中各环节的输入、输出、耗时和错误信息。
参考 OpenTelemetry 规范设计，支持 span 级别持久化。
"""
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Literal, Optional

_trace_context: ContextVar[Optional["TraceSpan"]] = ContextVar("trace", default=None)


@dataclass
class TraceSpan:
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_span_id: Optional[str] = None
    name: str = ""
    category: str = ""
    input: Any = None
    output: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    error: Optional[str] = None
    children: List["TraceSpan"] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return round((self.end_time - self.start_time) * 1000, 1)
        return 0.0

    @property
    def status(self) -> str:
        return "error" if self.error else "ok"

    def iter_spans(self) -> Generator["TraceSpan", None, None]:
        """Yield self and all descendant spans (flat iteration)."""
        yield self
        for child in self.children:
            yield from child.iter_spans()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "category": self.category,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "children": [c.to_dict() for c in self.children],
        }


class trace_span:
    """Context manager for recording a trace span.

    Automatically builds a tree structure via contextvars propagation.
    Each span records its parent_span_id for database persistence.
    """

    def __init__(self, name: str, category: str, **metadata: Any):
        self.span = TraceSpan(name=name, category=category, metadata=metadata)
        self._parent: Optional[TraceSpan] = None

    def __enter__(self) -> TraceSpan:
        parent = _trace_context.get()
        if parent:
            self.span.trace_id = parent.trace_id
            self.span.parent_span_id = parent.span_id
            parent.children.append(self.span)
        self._parent = parent
        _trace_context.set(self.span)
        self.span.start_time = time.time()
        return self.span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        self.span.end_time = time.time()
        if exc_val is not None:
            self.span.error = str(exc_val)
        _trace_context.set(self._parent)
        return False


def get_current_trace() -> Optional[TraceSpan]:
    """Get the current active trace span (top of stack)."""
    return _trace_context.get()


def get_trace_dict() -> Optional[Dict[str, Any]]:
    """Serialize the current trace tree to a dict."""
    root = _trace_context.get()
    if root is None:
        return None
    return root.to_dict()
