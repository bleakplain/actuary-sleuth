"""LLM 调用链路追踪。

提供 TraceSpan 模型和跨线程传播机制，
用于记录 RAG 管线中各环节的输入、输出、耗时和错误信息。
参考 OpenTelemetry 规范设计，支持 span 级别持久化。

跨线程传播：ContextVar 通过 asyncio.to_thread 和 copy_context 自动复制，
对 llama_index 内部线程池等场景不生效。因此 trace_span 使用
_active_trace_id ContextVar 作为跨线程 fallback。
"""
import logging
import threading
import time
from contextvars import ContextVar

from lib.common.id_generator import _id_generator
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_trace_context: ContextVar[Optional["TraceSpan"]] = ContextVar("trace", default=None)

# 跨线程计数器（按 trace_id 隔离，线程安全）
_counters: dict[str, dict[str, int]] = {}
_counters_lock = threading.Lock()

# 当前活跃的 trace_id（ContextVar，用于 span 树构建）
_active_trace_id: ContextVar[Optional[str]] = ContextVar("active_trace_id", default=None)


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
    return _active_trace_id.get()


def _set_active_trace_id(tid: Optional[str]) -> None:
    _active_trace_id.set(tid)


def reset_llm_call_count(trace_id: Optional[str] = None) -> None:
    """重置 LLM 调用计数。trace_id 优先使用显式传入值，否则从 ContextVar 获取。"""
    tid = trace_id or _get_active_trace_id()
    if tid:
        _set_counter(tid, "llm_calls", 0)


def incr_llm_call_count(trace_id: Optional[str] = None) -> None:
    """累加 LLM 调用计数。trace_id 优先使用显式传入值，否则从 ContextVar 获取。"""
    tid = trace_id or _get_active_trace_id()
    if tid:
        _increment_counter(tid, "llm_calls")


def get_llm_call_count(trace_id: Optional[str] = None) -> int:
    """读取 LLM 调用计数。trace_id 优先使用显式传入值，否则从 ContextVar 获取。"""
    tid = trace_id or _get_active_trace_id()
    if tid:
        return _get_counter(tid, "llm_calls")
    return 0


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
            self.span.span_id = _id_generator.new_id()
        elif active_tid:
            # ContextVar 未传播（跨线程），但全局 trace_id 存在
            self.span.trace_id = active_tid
            self.span.span_id = _id_generator.new_id()
            # 无法挂载到父 span.children（跨线程无引用）
        else:
            # 真正的 root span
            self.span.trace_id = _id_generator.new_id()
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
        return False


def cleanup_trace_counters(trace_id: str) -> None:
    """清理指定 trace 的计数器和活跃 ID（在 trace 持久化后调用）。"""
    _set_active_trace_id(None)
    with _counters_lock:
        _counters.pop(trace_id, None)


def get_current_trace() -> Optional[TraceSpan]:
    """Get the current active trace span (top of stack)."""
    return _trace_context.get()


def get_trace_dict() -> Optional[dict]:
    """Serialize the current trace tree to a dict."""
    root = _trace_context.get()
    if root is None:
        return None
    return root.to_dict()
