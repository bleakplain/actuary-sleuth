"""LangGraph 工作流单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
from lib.rag_engine.graph import (
    create_ask_graph, AskState, GraphContext,
    retrieve_memory, extract_memory, update_user_profile
)


@pytest.fixture
def mock_memory_service():
    svc = MagicMock()
    svc.search.return_value = [
        {"memory": "重疾产品等待期180天", "created_at": "2026-04-01T10:00:00"},
    ]
    svc.get_user_profile.return_value = None
    svc.add.return_value = ["mem_1"]
    return svc


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.search.return_value = [{"content": "等待期不得超过90天"}]
    engine.config.generation.max_context_chars = 12000
    return engine


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "test-model"
    llm.chat.return_value = "根据法规，等待期不得超过90天。"
    return llm


@pytest.fixture
def mock_context(mock_engine, mock_llm, mock_memory_service):
    return GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )


def _make_base_state(**kwargs):
    """创建基础状态，包含所有必需字段"""
    base = {
        "question": "", "mode": "qa", "user_id": "test", "session_id": "sess_1",
        "search_results": [], "memory_context": "", "answer": "", "sources": [],
        "citations": [], "unverified_claims": [], "content_mismatches": [],
        "faithfulness_score": None, "error": None,
        "messages": [], "session_context": {}, "skip_clarify": True,
        "iteration_count": 0, "next_action": "search",
        "clarification_message": None, "clarification_options": None,
        "loop_detected": None, "loop_hint": None,
    }
    base.update(kwargs)
    return base


@pytest.fixture
def base_state():
    return AskState(**_make_base_state(question="等待期是多少"))


def test_retrieve_memory_returns_context(mock_context, base_state):
    from langgraph.runtime import Runtime
    result = retrieve_memory(base_state, runtime=Runtime(context=mock_context))
    assert "重疾产品等待期180天" in result["memory_context"]


def test_retrieve_memory_with_user_profile(mock_context, base_state):
    mock_context.memory_service.get_user_profile.return_value = {
        "focus_areas": ["重疾险", "医疗险"],
        "preference_tags": ["等待期"],
        "summary": "关注健康保险"
    }

    from langgraph.runtime import Runtime
    result = retrieve_memory(base_state, runtime=Runtime(context=mock_context))
    assert "关注领域" in result["memory_context"]
    assert "重疾险" in result["memory_context"]


def test_retrieve_memory_empty(mock_memory_service, mock_engine, mock_llm, base_state):
    mock_memory_service.search.return_value = []
    mock_memory_service.get_user_profile.return_value = None
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = retrieve_memory(base_state, runtime=Runtime(context=context))
    assert result["memory_context"] == ""


def test_extract_memory_adds_conversation(mock_memory_service, mock_engine, mock_llm, base_state):
    base_state["answer"] = "等待期不得超过180天"
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = extract_memory(base_state, runtime=Runtime(context=context))

    mock_memory_service.add.assert_called_once()
    assert result == {}


def test_extract_memory_handles_exception(mock_memory_service, mock_engine, mock_llm, base_state):
    mock_memory_service.add.side_effect = Exception("DB error")
    base_state["answer"] = "测试回答"
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = extract_memory(base_state, runtime=Runtime(context=context))
    assert result == {}


def test_update_user_profile_calls_service(mock_memory_service, mock_engine, mock_llm, base_state):
    base_state["answer"] = "等待期不得超过180天"
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = update_user_profile(base_state, runtime=Runtime(context=context))

    mock_memory_service.update_user_profile.assert_called_once_with(
        base_state["question"],
        base_state["answer"],
        base_state["user_id"]
    )
    assert result == {}


def test_update_user_profile_handles_exception(mock_memory_service, mock_engine, mock_llm, base_state):
    mock_memory_service.update_user_profile.side_effect = Exception("LLM error")
    base_state["answer"] = "测试回答"
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = update_user_profile(base_state, runtime=Runtime(context=context))
    assert result == {}


def test_graph_end_to_end(mock_context, base_state):
    graph = create_ask_graph()

    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        result = graph.invoke(base_state, context=mock_context)

    assert result["answer"] != ""
    assert len(result["sources"]) > 0


def test_graph_parallel_retrieval(mock_context, base_state):
    graph = create_ask_graph()

    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        graph.invoke(base_state, context=mock_context)

    mock_context.memory_service.search.assert_called()
    mock_context.rag_engine.search.assert_called()


def test_retrieve_memory_triggered_by_topic_keyword(mock_engine, mock_llm, mock_memory_service):
    """测试话题关键词触发记忆检索。"""
    state = AskState(**_make_base_state(question="等待期是多少天？"))
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = retrieve_memory(state, runtime=Runtime(context=context))

    mock_memory_service.search.assert_called()
    assert "重疾产品等待期180天" in result["memory_context"]


def test_retrieve_memory_triggered_by_company_keyword(mock_engine, mock_llm, mock_memory_service):
    """测试公司关键词触发记忆检索。"""
    state = AskState(**_make_base_state(question="平安的产品怎么样？"))
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = retrieve_memory(state, runtime=Runtime(context=context))

    mock_memory_service.search.assert_called()


def test_retrieve_memory_skips_when_no_trigger(mock_engine, mock_llm, mock_memory_service):
    """测试无触发词时跳过记忆检索。"""
    state = AskState(**_make_base_state(question="你好"))
    context = GraphContext(
        rag_engine=mock_engine,
        llm_client=mock_llm,
        memory_service=mock_memory_service
    )

    from langgraph.runtime import Runtime
    result = retrieve_memory(state, runtime=Runtime(context=context))

    mock_memory_service.search.assert_not_called()
    assert result["memory_context"] == ""
