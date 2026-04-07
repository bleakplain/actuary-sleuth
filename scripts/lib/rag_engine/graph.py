"""LangGraph 审核工作流。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

from lib.llm.trace import trace_span
from lib.memory.config import MemoryConfig
from lib.rag_engine.attribution import parse_citations
from lib.rag_engine.rag_engine import _SYSTEM_PROMPT, RAGEngine

logger = logging.getLogger(__name__)

_memory_config: MemoryConfig | None = None


def _get_memory_config() -> MemoryConfig:
    global _memory_config
    if _memory_config is None:
        _memory_config = MemoryConfig()
    return _memory_config


class AskState(TypedDict):
    """LangGraph 工作流状态。"""

    question: str
    mode: str
    user_id: str
    conversation_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]


@dataclass(frozen=True)
class GraphContext:
    """LangGraph 依赖注入上下文。"""

    rag_engine: Any
    llm_client: Any
    memory_service: Any


def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆检索 + 用户画像注入。"""
    memory_svc = runtime.context.memory_service
    max_chars = _get_memory_config().memory_context_max_chars
    with trace_span("memory_retrieve", "memory") as span:
        parts = []

        memories = memory_svc.search(state["question"], state["user_id"])
        if memories:
            lines = [f"- {m['memory']} (记录于 {m['created_at'][:10]})" for m in memories]
            parts.append("\n".join(lines))

        profile = memory_svc.get_profile(state["user_id"])
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
        return {"memory_context": context}


def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """语义记忆检索。"""
    engine = runtime.context.rag_engine
    with trace_span("graph_retrieve", "rag") as span:
        results = engine.search(state["question"])
        return {"search_results": results}


def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """LLM 生成 — 融合语义记忆 + 情节记忆 + 程序性记忆。"""
    engine = runtime.context.rag_engine
    llm = runtime.context.llm_client
    with trace_span("graph_generate", "llm", model=getattr(llm, 'model', '')) as span:
        user_prompt, included_count = RAGEngine._build_qa_prompt(
            engine.config.generation, state["question"], state["search_results"]
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
        ]
        if state.get("memory_context"):
            messages.append({"role": "system", "content": f"【用户历史信息】\n{state['memory_context']}"})
        messages.append({"role": "user", "content": user_prompt})

        span.input = {
            "question": state["question"],
            "context_chunk_count": len(state["search_results"]),
            "has_memory_context": bool(state.get("memory_context")),
        }
        answer = llm.chat(messages)
        answer_str = str(answer)

        included_sources = state["search_results"][:included_count] if state["search_results"] else []
        attribution = parse_citations(answer_str, included_sources)

        result = {
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
        return result


def extract_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆写入。失败不阻塞。"""
    memory_svc = runtime.context.memory_service
    conversation = [
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": state["answer"]},
    ]
    try:
        memory_svc.add(
            conversation, state["user_id"],
            metadata={"conversation_id": state["conversation_id"]},
        )
    except Exception:
        logger.debug("记忆提取失败，跳过", exc_info=True)
    return {}


def update_profile_node(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """用户画像更新。失败不阻塞。"""
    memory_svc = runtime.context.memory_service
    try:
        memory_svc.update_profile(state["question"], state["answer"], state["user_id"])
    except Exception:
        logger.debug("用户画像更新失败，跳过", exc_info=True)
    return {}


def create_ask_graph():
    """创建审核问答工作流图（并行双检索 + 线性后处理）。"""
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_profile_node)

    graph.add_edge(START, "retrieve_memory")
    graph.add_edge(START, "rag_search")
    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")
    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("update_profile", END)

    return graph.compile()
