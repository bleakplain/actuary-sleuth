"""中间件基类"""

from abc import ABC, abstractmethod
from typing import Callable, Any, List, Dict, Optional, TYPE_CHECKING
import logging
import time
import hashlib

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState


class Middleware(ABC):
    """中间件基类"""

    @abstractmethod
    def process(self, call: Callable, *args, **kwargs) -> Any:
        """处理调用"""
        pass


class LoggingMiddleware(Middleware):
    """日志记录中间件"""

    def __init__(self, logger_instance: logging.Logger):
        self.logger = logger_instance

    def process(self, call: Callable, *args, **kwargs) -> Any:
        self.logger.info(f"调用 {call.__name__}")
        try:
            result = call(*args, **kwargs)
            self.logger.info(f"{call.__name__} 成功")
            return result
        except Exception as e:
            self.logger.error(f"{call.__name__} 失败: {e}")
            raise


class PerformanceMiddleware(Middleware):
    """性能监控中间件"""

    def __init__(self):
        self.metrics: Dict[str, float] = {}

    def process(self, call: Callable, *args, **kwargs) -> Any:
        start = time.time()
        try:
            return call(*args, **kwargs)
        finally:
            elapsed = time.time() - start
            self.metrics[call.__name__] = elapsed


class MiddlewareChain:
    """中间件链"""

    def __init__(self, middlewares: Optional[List[Middleware]] = None):
        self.middlewares = middlewares or []

    def add(self, middleware: Middleware) -> 'MiddlewareChain':
        """添加中间件"""
        self.middlewares.append(middleware)
        return self

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """执行中间件链"""
        wrapped = func
        for middleware in reversed(self.middlewares):
            def make_wrapper(f: Callable, m: Middleware) -> Callable:
                return lambda *a, **kw: m.process(lambda: f(*a, **kw))
            wrapped = make_wrapper(wrapped, middleware)

        return wrapped(*args, **kwargs)


# === LangGraph 工作流中间件 ===

TOPIC_KEYWORDS = frozenset({
    "等待期", "犹豫期", "保费", "保额",
    "免责", "理赔", "保单", "续保"
})

PRONOUN_KEYWORDS = frozenset({
    "它", "这个产品", "该产品", "那个产品"
})

PRODUCT_TYPE_OPTIONS = ["重疾险", "医疗险", "意外险", "寿险"]

MAX_ENTITIES = 10
COMPANY_KEYWORDS = frozenset({"泰康", "平安", "国寿", "太保", "新华", "人保"})


def _extract_topic(question: str) -> str | None:
    """从问题中提取话题关键词"""
    for kw in TOPIC_KEYWORDS:
        if kw in question:
            return kw
    return None


class SessionContextMiddleware:
    """会话上下文管理：加载 → 提取 → 合并 → 保存"""

    def before_invoke(self, state: "AskState") -> "AskState":
        """加载上下文"""
        session_id = state.get("session_id")
        if not session_id:
            state["session_context"] = {}
            return state

        try:
            from api.database import get_session_context
            ctx = get_session_context(session_id)
            state["session_context"] = ctx or {}
        except Exception as e:
            logging.getLogger(__name__).warning(f"加载会话上下文失败: {e}")
            state["session_context"] = {}

        return state

    def after_invoke(self, state: "AskState") -> "AskState":
        """提取、合并上下文（不保存，由 save_context 节点统一保存）"""
        question = state.get("question", "")
        answer = state.get("answer", "")
        old_ctx = state.get("session_context", {})

        new_product_type = self._extract_product_type(question)
        new_entities = self._extract_entities(question, answer)
        new_topic = _extract_topic(question)

        product_type = new_product_type or old_ctx.get("product_type")

        merged_entities = list(dict.fromkeys(
            new_entities + old_ctx.get("mentioned_entities", [])
        ))[:MAX_ENTITIES]

        updated_ctx = {
            "mentioned_entities": merged_entities,
            "product_type": product_type,
            "current_topic": new_topic or old_ctx.get("current_topic"),
            "query_history": old_ctx.get("query_history", [])[-10:],
        }

        state["session_context"] = updated_ctx
        return state

    def _extract_product_type(self, question: str) -> str | None:
        """提取险种类型"""
        from lib.common.product import _KEYWORDS
        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in question:
                    return kw
        return None

    def _extract_entities(self, question: str, answer: str) -> List[str]:
        """提取实体"""
        from lib.common.product import _KEYWORDS
        text = question + answer
        entities = []

        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in text:
                    entities.append(kw)
                    break

        for company in COMPANY_KEYWORDS:
            if company in text:
                entities.append(company)

        return list(set(entities))


class ClarificationMiddleware:
    """检测模糊问题，触发澄清式追问"""

    def before_invoke(self, state: "AskState") -> "AskState":
        if state.get("skip_clarify", False):
            state["next_action"] = "search"
            return state

        question = state.get("question", "")
        ctx = state.get("session_context", {})

        clarification = self._check(question, ctx)
        if clarification:
            state["next_action"] = "clarify"
            state["clarification_message"] = clarification["message"]
            state["clarification_options"] = clarification.get("options", [])
        else:
            state["next_action"] = "search"

        return state

    def _check(self, question: str, ctx: dict) -> dict | None:
        """返回澄清问题，None 表示无需澄清"""

        topic = _extract_topic(question)
        product_type = self._extract_product_type(question)
        has_product_type = product_type or ctx.get("product_type")

        if topic and not has_product_type:
            return {
                "message": f"请问您咨询的是哪种险种的{topic}？",
                "options": PRODUCT_TYPE_OPTIONS
            }

        if any(p in question for p in PRONOUN_KEYWORDS):
            if not ctx.get("mentioned_entities"):
                return {
                    "message": "请问您指的是哪个产品或险种？",
                    "options": []
                }

        return None

    def _extract_product_type(self, question: str) -> str | None:
        """从问题中提取险种类型"""
        from lib.common.product import _KEYWORDS
        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in question:
                    return kw
        return None


class LoopDetectionMiddleware:
    """检测重复查询或无效循环

    使用 DeerFlow 模式：最近 N 条中重复占比超过一半视为循环
    """

    LOOP_THRESHOLD = 3

    def after_invoke(
        self,
        session_context: Dict[str, Any],
        question: str,
    ) -> Dict[str, Any]:
        """检测循环并返回更新的 session_context"""
        history = list(session_context.get("query_history", []))

        question_hash = self._hash_question(question)
        history.append(question_hash)

        result: Dict[str, Any] = {"session_context": session_context.copy()}
        if self._detect_loop(history):
            result["loop_detected"] = True
            result["loop_hint"] = self._generate_hint()

        result["session_context"]["query_history"] = history[-10:]
        return result

    def _hash_question(self, question: str) -> str:
        """问题签名"""
        normalized = question.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()[:8]

    def _detect_loop(self, history: List[str]) -> bool:
        """检测最近 N 条中重复占比超过一半"""
        if len(history) < self.LOOP_THRESHOLD:
            return False
        recent = history[-self.LOOP_THRESHOLD:]
        return len(set(recent)) < len(recent) / 2

    def _generate_hint(self) -> str:
        """生成干预提示"""
        return (
            "检测到您可能遇到了问题，建议：\n"
            "1. 提供更具体的产品名称\n"
            "2. 明确险种类型（重疾险/医疗险/意外险）\n"
            "3. 如需人工帮助，请联系客服"
        )


class IterationLimitMiddleware:
    """迭代次数限制"""

    MAX_ITERATIONS = 10

    def after_invoke(self, iteration_count: int) -> Dict[str, Any]:
        """检查迭代限制并返回更新"""
        count = iteration_count + 1
        result: Dict[str, Any] = {"iteration_count": count}

        if count >= self.MAX_ITERATIONS:
            result["error"] = "达到最大迭代次数，请简化问题或重新开始对话"
            result["next_action"] = "end"

        return result
