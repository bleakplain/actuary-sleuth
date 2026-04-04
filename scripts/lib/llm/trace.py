"""LLM 调用链路追踪。

提供 TraceSpan 模型和跨线程传播机制，
用于记录 RAG 管线中各环节的输入、输出、耗时和错误信息。
参考 OpenTelemetry 规范设计，支持 span 级别持久化。

跨线程传播：ContextVar 只在 asyncio.to_thread 中自动复制，
对 llama_index 内部线程池等场景不生效。因此 trace_span 使用
_active_trace_id 全局变量作为跨线程 fallback。
"""
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_trace_context: ContextVar[Optional["TraceSpan"]] = ContextVar("trace", default=None)

# 跨线程计数器（按 trace_id 隔离，线程安全）
_counters: dict[str, dict[str, int]] = {}
_counters_lock = threading.Lock()

# 当前活跃的 trace_id（线程安全，供 ContextVar 无法传播的线程访问）
_active_trace_id: Optional[str] = None
_active_trace_id_lock = threading.Lock()


def _get_counter(trace_id: str, key: str) -> int:
    with _counters_lock:
        return _counters.setdefault(trace_id, {}).get(key, 0)


def _set_counter(trace_id: str, key: str, value: int) -> None:
    with _counters_lock:
        _counters.setdefault(trace_id, {})[key] = value


def _increment_counter(trace_id: str, key: str) -> int:
    with _counters_lock:
        bucket = _counters.setdefault(trace_id, {})
        bucket[key] = bucket.get(key, 0) + 1
        return bucket[key]


def _get_active_trace_id() -> Optional[str]:
    global _active_trace_id
    with _active_trace_id_lock:
        return _active_trace_id


def _set_active_trace_id(tid: Optional[str]) -> None:
    global _active_trace_id
    with _active_trace_id_lock:
        _active_trace_id = tid


def reset_llm_call_count() -> None:
    """重置当前 trace 的 LLM 调用计数。"""
    tid = _get_active_trace_id()
    if tid:
        _set_counter(tid, "llm_calls", 0)


def incr_llm_call_count() -> None:
    """在当前 trace 中累加 LLM 调用计数（线程安全）。"""
    tid = _get_active_trace_id()
    if tid:
        _increment_counter(tid, "llm_calls")


def get_llm_call_count() -> int:
    """读取当前 trace 的 LLM 调用计数。"""
    tid = _get_active_trace_id()
    if tid:
        return _get_counter(tid, "llm_calls")
    return 0


class IDGenerator:
    """生成 trace/span 唯一标识。

    trace_id: uuid4 hex (16 chars)
    span_id: {trace_id}-{seq} (同一 trace 下严格递增)
    """

    def __init__(self) -> None:
        self._seq: dict[str, int] = {}
        self._lock = threading.Lock()

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def new_span_id(self, trace_id: str) -> str:
        with self._lock:
            seq = self._seq.get(trace_id, 0) + 1
            self._seq[trace_id] = seq
        return f"{trace_id}-{seq}"


_id_generator = IDGenerator()


def get_id_generator() -> IDGenerator:
    return _id_generator


@dataclass
class TraceSpan:
    span_id: str = ""
    trace_id: str = ""
    parent_span_id: Optional[str] = None
    name: str = ""
    category: str = ""
    input: Optional[object] = None
    output: Optional[object] = None
    metadata: dict = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    error: Optional[str] = None
    children: list["TraceSpan"] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return round((self.end_time - self.start_time) * 1000, 1)
        return 0.0

    @property
    def status(self) -> str:
        return "error" if self.error else "ok"

    def iter_spans(self):
        """Yield self and all descendant spans (flat iteration)."""
        yield self
        for child in self.children:
            yield from child.iter_spans()

    def to_dict(self) -> dict:
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

    跨线程传播策略：
    1. 优先使用 ContextVar（asyncio.to_thread 自动复制）
    2. ContextVar 丢失时（llama_index 线程池等），fallback 到 _active_trace_id
    3. 子 span 在跨线程场景下无法挂载到父 span 的 children 中，
       但仍共享同一 trace_id，数据通过 _active_trace_id 关联
    """

    def __init__(self, name: str, category: str, **metadata):
        self.span = TraceSpan(name=name, category=category, metadata=metadata)
        self._parent: Optional[TraceSpan] = None
        self._is_root: bool = False

    def __enter__(self) -> TraceSpan:
        parent = _trace_context.get()
        active_tid = _get_active_trace_id()

        if parent:
            # ContextVar 正常传播，挂载到父 span
            self.span.trace_id = parent.trace_id
            self.span.parent_span_id = parent.span_id
            parent.children.append(self.span)
            self.span.span_id = _id_generator.new_span_id(self.span.trace_id)
        elif active_tid:
            # ContextVar 未传播（跨线程），但全局 trace_id 存在
            self.span.trace_id = active_tid
            self.span.span_id = _id_generator.new_span_id(active_tid)
            # 无法挂载到父 span.children（跨线程无引用）
        else:
            # 真正的 root span
            self.span.trace_id = _id_generator.new_trace_id()
            self.span.span_id = self.span.trace_id
            _set_active_trace_id(self.span.trace_id)
            self._is_root = True

        self._parent = parent
        _trace_context.set(self.span)
        self.span.start_time = time.time()
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.span.end_time = time.time()
        if exc_val is not None:
            self.span.error = str(exc_val)
        _trace_context.set(self._parent)
        if self._is_root:
            _set_active_trace_id(None)
        return False


def get_current_trace() -> Optional[TraceSpan]:
    """Get the current active trace span (top of stack)."""
    return _trace_context.get()


def get_trace_dict() -> Optional[dict]:
    """Serialize the current trace tree to a dict."""
    root = _trace_context.get()
    if root is None:
        return None
    return root.to_dict()
