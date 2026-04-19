"""LangGraph 审核工作流。"""
from __future__ import annotations

import logging
import operator
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

from lib.common.middleware import (
    SessionContextMiddleware,
    ClarificationMiddleware,
    LoopDetectionMiddleware,
    IterationLimitMiddleware,
    MAX_ENTITIES,
)
from lib.llm.trace import trace_span
from lib.memory.config import MemoryConfig
from lib.rag_engine.attribution import parse_citations
from lib.rag_engine.rag_engine import _SYSTEM_PROMPT, RAGEngine

logger = logging.getLogger(__name__)

_memory_config = MemoryConfig()
_clarification_mw = ClarificationMiddleware()
_context_mw = SessionContextMiddleware()
_loop_mw = LoopDetectionMiddleware()
_limit_mw = IterationLimitMiddleware()


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
    mode: str
    user_id: str
    session_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]
    messages: Annotated[List[Dict[str, str]], operator.add]
    session_context: Annotated[Dict[str, Any], merge_session_context]
    skip_clarify: bool
    iteration_count: int
    next_action: Literal["clarify", "search", "generate", "end"]
    clarification_message: Optional[str]
    clarification_options: Optional[List[str]]
    loop_detected: Optional[bool]
    loop_hint: Optional[str]


@dataclass(frozen=True)
class GraphContext:
    """LangGraph 依赖注入上下文。"""

    rag_engine: Any
    llm_client: Any
    memory_service: Any


def load_context(state: AskState) -> dict:
    """加载会话上下文和对话历史"""
    result = _context_mw.before_invoke(state)
    from api.database import get_messages
    history = get_messages(state.get("session_id", ""))
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    return {"session_context": result.get("session_context", {}), "messages": messages}


def clarify_check(state: AskState) -> dict:
    """澄清检测"""
    result = _clarification_mw.before_invoke(state)
    return {
        "next_action": result.get("next_action", "search"),
        "clarification_message": result.get("clarification_message"),
        "clarification_options": result.get("clarification_options"),
        "session_context": result.get("session_context", {}),
    }


def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    max_chars = _memory_config.memory_context_max_chars
    with trace_span("memory_retrieve", "memory") as span:
        span.input = {"question": state["question"], "user_id": state["user_id"]}
        parts = []

        memories = memory_svc.search(state["question"], state["user_id"])
        if memories:
            lines = [f"- {m['memory']} (记录于 {m['created_at'][:10]})" for m in memories]
            parts.append("\n".join(lines))

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
        if len(context) > max_chars:
            context = context[:max_chars] + "..."

        span.output = {
            "memory_count": len(memories),
            "has_profile": bool(profile),
            "memories": [m.get("memory", "") for m in memories],
        }
        return {"memory_context": context}


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


def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    engine = runtime.context.rag_engine
    llm = runtime.context.llm_client
    with trace_span("graph_generate", "llm", model=getattr(llm, 'model', '')) as span:
        span.input = {
            "question": state["question"],
            "context_chunk_count": len(state["search_results"]),
            "has_memory_context": bool(state.get("memory_context")),
        }

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
            }
            messages.append({"role": "user", "content": user_prompt})
            answer = llm.chat(messages)
            answer_str = str(answer)
            inner.output = {"answer_length": len(answer_str), "answer": answer_str}

        included_sources = state["search_results"][:included_count] if state["search_results"] else []
        attribution = parse_citations(answer_str, included_sources)

        result: Dict[str, Any] = {
            "answer": answer_str,
            "sources": state["search_results"],
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

    # Apply loop detection (updates query_history)
    loop_result = _loop_mw.after_invoke(
        merged_ctx,
        state["question"],
    )
    result["session_context"] = loop_result.get("session_context", merged_ctx)
    if loop_result.get("loop_detected"):
        result["loop_detected"] = loop_result["loop_detected"]
        result["loop_hint"] = loop_result.get("loop_hint")

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
        logger.debug("记忆提取失败，跳过", exc_info=True)
    return {}


def update_user_profile(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    try:
        memory_svc.update_user_profile(state["question"], state["answer"], state["user_id"])
    except Exception:
        logger.debug("用户画像更新失败，跳过", exc_info=True)
    return {}


def save_context(state: AskState) -> dict:
    """保存会话上下文"""
    ctx = state.get("session_context", {})
    session_id = state.get("session_id")
    if session_id and ctx:
        from api.database import save_session_context
        try:
            save_session_context(session_id, ctx)
        except Exception:
            logger.debug("保存会话上下文失败", exc_info=True)
    return {}


def route_by_action(state: AskState) -> str:
    """根据 next_action 路由"""
    action = state.get("next_action", "search")
    if action == "clarify":
        return "clarify"
    return "search"


def create_ask_graph():
    """创建审核问答工作流图（多轮对话增强版）。"""
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("load_context", load_context)
    graph.add_node("clarify_check", clarify_check)
    graph.add_node("parallel_retrieval_entry", lambda state: {})
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_user_profile)
    graph.add_node("save_context", save_context)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "clarify_check")

    graph.add_conditional_edges(
        "clarify_check",
        route_by_action,
        {"clarify": END, "search": "parallel_retrieval_entry"}
    )

    graph.add_edge("parallel_retrieval_entry", "retrieve_memory")
    graph.add_edge("parallel_retrieval_entry", "rag_search")

    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")

    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("update_profile", "save_context")
    graph.add_edge("save_context", END)

    return graph.compile()
