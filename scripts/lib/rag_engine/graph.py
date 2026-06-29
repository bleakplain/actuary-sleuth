"""LangGraph 审核工作流。"""
from __future__ import annotations

import logging
import operator
import re
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

from lib.common.middleware import (
    SessionContextMiddleware,
    LoopDetectionMiddleware,
    IterationLimitMiddleware,
    MAX_ENTITIES,
)
from lib.llm.trace import trace_span
from lib.memory.triggers import should_retrieve_memory
from lib.memory.compression import compress_memory_context
from lib.rag_engine.attribution import parse_citations
from lib.rag_engine.intent import classify_intent
from lib.rag_engine.registry import RegulationRegistry, format_registry_context
from lib.rag_engine.rag_engine import _SYSTEM_PROMPT, RAGEngine

logger = logging.getLogger(__name__)

_context_mw = SessionContextMiddleware()
_loop_mw = LoopDetectionMiddleware()
_limit_mw = IterationLimitMiddleware()

_CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100}
_ARTICLE_RE = re.compile(r'第([一二三四五六七八九十百零]+)条')
_BRACKET_RE = re.compile(r'[（(]([一二三四五六七八九十百零\d]+)[）)]')


def _cn_to_int(s: str) -> int:
    """中文数字转阿拉伯数字（支持到百位）。"""
    if s in _CN_NUM:
        return _CN_NUM[s]
    result = 0
    current = 0
    for ch in s:
        v = _CN_NUM.get(ch, 0)
        if v >= 10:
            if current == 0:
                current = 1
            result += current * v
            current = 0
        else:
            current = v
    return result + current


def _actual_articles(content: str) -> str:
    """从内容文本中提取实际出现的条款号，返回显示用字符串。"""
    nums: set[int] = set()
    for m in _ARTICLE_RE.finditer(content):
        nums.add(_cn_to_int(m.group(1)))
    for m in _BRACKET_RE.finditer(content):
        s = m.group(1)
        nums.add(int(s) if s.isdigit() else _cn_to_int(s))
    if not nums:
        return ""
    sorted_nums = sorted(nums)
    parts: List[str] = []
    start = end = sorted_nums[0]
    for n in sorted_nums[1:]:
        if n == end + 1:
            end = n
        else:
            parts.append(f"第{start}条" if start == end else f"第{start}-{end}条")
            start = end = n
    parts.append(f"第{start}条" if start == end else f"第{start}-{end}条")
    return ", ".join(parts)


def _fix_source_display(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """修正 source 的 article_number 为内容中实际出现的条款号。"""
    fixed = []
    for s in sources:
        content = s.get("content", "")
        actual = _actual_articles(content)
        if actual:
            s = {**s, "article_number": actual}
        fixed.append(s)
    return fixed


def merge_session_context(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """会话上下文合并 Reducer。"""
    if not left:
        return right
    if not right:
        return left
    merged_entities = list(dict.fromkeys(
        right.get("mentioned_entities", []) + left.get("mentioned_entities", [])
    ))[:MAX_ENTITIES]
    return {
        **left,
        **right,
        "mentioned_entities": merged_entities,
    }


class AskState(TypedDict):
    """LangGraph 工作流状态。"""

    question: str
    user_id: str
    session_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str
    registry_context: str
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]
    messages: Annotated[List[Dict[str, str]], operator.add]
    session_context: Annotated[Dict[str, Any], merge_session_context]
    iteration_count: int
    next_action: Literal["search", "registry", "generate", "end"]
    loop_detected: Optional[bool]
    loop_hint: Optional[str]


@dataclass(frozen=True)
class GraphContext:
    """LangGraph 依赖注入上下文。"""

    rag_engine: Any
    llm_client: Any
    memory_service: Any


def load_session_context(state: AskState) -> dict:
    """加载会话上下文、循环检测、话题提取、对话历史。

    澄清步骤已移除，本节点承接原 clarify_user_query 的循环检测和话题提取职责，
    保证 retrieve_memory 同轮内能拿到 current_topic 触发 topic-continuation 记忆召回。
    """
    result = _context_mw.before_invoke(state)
    ctx = result.get("session_context", {})

    loop_result = _loop_mw.after_invoke(ctx, state["question"])
    loop_detected = loop_result.get("loop_detected")
    loop_hint = loop_result.get("loop_hint")
    ctx = loop_result.get("session_context", ctx)

    # 同步提取话题，让本轮 retrieve_memory 即可使用（原本由 clarify_user_query 提供）
    from lib.common.middleware import _extract_topic
    topic = _extract_topic(state["question"])
    if topic:
        ctx["current_topic"] = topic

    from api.database import get_messages
    history = get_messages(state.get("session_id", ""))
    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    return {
        "session_context": ctx,
        "messages": messages,
        "loop_detected": loop_detected,
        "loop_hint": loop_hint,
    }


def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    ctx = state.get("session_context", {})

    last_retrieve = ctx.get("_last_memory_retrieve", 0.0)
    trigger = should_retrieve_memory(
        state["question"],
        session_context=ctx,
        last_retrieve_time=last_retrieve,
        interval_seconds=60,
    )
    if not trigger.should_retrieve:
        return {"memory_context": ""}

    import time
    ctx["_last_memory_retrieve"] = time.time()

    with trace_span("memory_retrieve", "memory") as span:
        span.input = {"question": state["question"], "user_id": state["user_id"], "trigger_type": trigger.trigger_type}
        parts = []

        memories = memory_svc.search(state["question"], state["user_id"])
        if memories:
            memory_context = compress_memory_context(memories, max_chars=1500)
            if memory_context:
                parts.append(memory_context)

        profile = memory_svc.get_user_profile(state["user_id"])
        if profile:
            profile_lines = []
            if profile.get("focus_areas"):
                profile_lines.append(f"关注领域: {', '.join(profile['focus_areas'])}")
            if profile.get("preference_tags"):
                profile_lines.append(f"偏好类型: {', '.join(profile['preference_tags'])}")
            if profile.get("summary"):
                profile_lines.append(f"画像摘要: {profile['summary']}")
            if profile_lines:
                parts.append("【用户画像】\n" + "\n".join(profile_lines))

        context = "\n\n".join(parts)
        if len(context) > 2000:
            context = context[:2000] + "..."

        span.output = {
            "memory_count": len(memories),
            "has_profile": bool(profile),
            "memories": [m.get("memory", "") for m in memories],
            "trigger_type": trigger.trigger_type,
        }
        return {"memory_context": context, "session_context": ctx}


def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    engine = runtime.context.rag_engine
    question = state["question"]
    ctx = state.get("session_context", {})
    if ctx.get("product_type"):
        question = f"{ctx['product_type']} {question}"

    with trace_span("graph_retrieve", "rag") as span:
        span.input = {"question": question, "original": state["question"]}
        results = engine.search(question)
        span.output = {"result_count": len(results), "enhanced_query": question}
        return {"search_results": results}


def registry_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """元数据查询路径：从法规注册表获取信息，不走 chunk 检索。"""
    engine = runtime.context.rag_engine
    question = state["question"]
    intent, law_name = classify_intent(question)

    registry = RegulationRegistry(engine.config.vector_db_path)
    context = format_registry_context(intent, registry, law_name)

    with trace_span("registry_search", "registry") as span:
        span.input = {"question": question, "intent": intent, "law_name": law_name}
        span.output = {"context_length": len(context)}
        return {
            "registry_context": context,
            "search_results": [],
        }


_REGISTRY_PROMPT_TEMPLATE = """## 法规库概况

{context}

## 用户问题

{question}

## 重要提醒
请仅依据上方提供的法规库概况回答。直接陈述事实，不需要标注来源编号。
- 如果用户问"有哪些法规"或要求列清单，**逐个列出法规名称**，不要只说分类。
- 如果概况中没有相关信息，请说明"提供的法规库概况中未找到相关信息"。"""


def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    engine = runtime.context.rag_engine
    llm = runtime.context.llm_client
    registry_ctx = state.get("registry_context") or ""
    is_registry_mode = bool(registry_ctx)

    with trace_span("graph_generate", "llm", model=getattr(llm, 'model', '')) as span:
        span.input = {
            "question": state["question"],
            "context_chunk_count": len(state["search_results"]),
            "has_memory_context": bool(state.get("memory_context")),
            "is_registry_mode": is_registry_mode,
        }

        if is_registry_mode:
            user_prompt = _REGISTRY_PROMPT_TEMPLATE.format(
                context=registry_ctx, question=state["question"]
            )
            included_count = 0
        else:
            user_prompt, included_count = RAGEngine._build_qa_prompt(
                engine.config.generation, state["question"], state["search_results"]
            )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
        ]
        if state.get("memory_context"):
            messages.append({"role": "system", "content": f"【用户历史信息】\n{state['memory_context']}"})

        with trace_span("llm_generate", "llm", model=getattr(llm, 'model', '')) as inner:
            inner.input = {
                "question": state["question"],
                "context_chunk_count": len(state["search_results"]),
                "system_prompt": _SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "has_memory_context": bool(state.get("memory_context")),
                "is_registry_mode": is_registry_mode,
            }
            messages.append({"role": "user", "content": user_prompt})
            answer = llm.chat(messages)
            answer_str = str(answer)
            inner.output = {"answer_length": len(answer_str), "answer": answer_str}

        included_sources = state["search_results"][:included_count] if state["search_results"] else []
        attribution = parse_citations(answer_str, included_sources)

        result: Dict[str, Any] = {
            "answer": answer_str,
            "sources": _fix_source_display(state["search_results"]) if not is_registry_mode else [],
            "citations": [
                {"source_idx": c.source_idx, "law_name": c.law_name, "article_number": c.article_number, "content": c.content}
                for c in attribution.citations
            ],
            "unverified_claims": attribution.unverified_claims,
            "content_mismatches": attribution.content_mismatches,
        }
        span.output = {"answer_length": len(answer_str), "citation_count": len(attribution.citations)}

    # Extract entities and topics from conversation
    ctx_result = _context_mw.after_invoke(state)
    merged_ctx = ctx_result.get("session_context", {})

    # Update session_context (loop detection done in load_session_context)
    result["session_context"] = merged_ctx

    limit_result = _limit_mw.after_invoke(state.get("iteration_count", 0))
    result["iteration_count"] = limit_result["iteration_count"]
    if limit_result.get("error"):
        result["error"] = limit_result["error"]
        result["next_action"] = limit_result.get("next_action")

    return result


def extract_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    conversation = [
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": state["answer"]},
    ]
    try:
        memory_svc.add(
            conversation, state["user_id"],
            metadata={"session_id": state["session_id"]},
        )
    except Exception:
        logger.warning("记忆提取失败，跳过", exc_info=True)
    return {}


def update_user_profile(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    try:
        memory_svc.update_user_profile(state["question"], state["answer"], state["user_id"])
    except Exception:
        logger.warning("用户画像更新失败，跳过", exc_info=True)
    return {}


def save_session_context(state: AskState) -> dict:
    """保存会话上下文"""
    ctx = state.get("session_context", {})
    session_id = state.get("session_id")
    if session_id and ctx:
        from api.database import save_session_context
        try:
            save_session_context(session_id, ctx)
        except Exception:
            logger.warning("保存会话上下文失败", exc_info=True)
    return {}


def route_by_action(state: AskState) -> str:
    """根据意图路由：catalog/count/metadata 类走注册表，其他走 search。"""
    question = state.get("question", "")
    if question:
        intent, _ = classify_intent(question)
        if intent in ("catalog", "count", "metadata"):
            return "registry"
    return "search"


def create_ask_graph():
    """创建审核问答工作流图（多轮对话增强版）。"""
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("load_session_context", load_session_context)
    graph.add_node("parallel_retrieval_entry", lambda state: {})
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("registry_search", registry_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_user_profile", update_user_profile)
    graph.add_node("save_session_context", save_session_context)

    graph.add_edge(START, "load_session_context")

    graph.add_conditional_edges(
        "load_session_context",
        route_by_action,
        {"search": "parallel_retrieval_entry", "registry": "registry_search"}
    )

    graph.add_edge("registry_search", "generate")

    graph.add_edge("parallel_retrieval_entry", "retrieve_memory")
    graph.add_edge("parallel_retrieval_entry", "rag_search")

    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")

    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_user_profile")
    graph.add_edge("update_user_profile", "save_session_context")
    graph.add_edge("save_session_context", END)

    return graph.compile()
