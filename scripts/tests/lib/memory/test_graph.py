"""LangGraph 工作流单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
from lib.rag_engine.graph import create_ask_graph, AskState, GraphContext, retrieve_memory


@pytest.fixture
def mock_context():
    memory_svc = MagicMock()
    memory_svc.search.return_value = [
        {"memory": "重疾产品等待期180天", "created_at": "2026-04-01T10:00:00"},
    ]
    memory_svc.get_user_profile.return_value = None
    engine = MagicMock()
    engine.search.return_value = [{"content": "等待期不得超过90天"}]
    engine.config.generation.max_context_chars = 12000
    llm = MagicMock()
    llm.model = "test-model"
    llm.chat.return_value = "根据法规，等待期不得超过90天。"
    return GraphContext(rag_engine=engine, llm_client=llm, memory_service=memory_svc)


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


def test_retrieve_memory_returns_context(mock_context):
    state = AskState(**_make_base_state(question="等待期是多少"))
    from langgraph.runtime import Runtime
    result = retrieve_memory(state, runtime=Runtime(context=mock_context))
    assert "重疾产品等待期180天" in result["memory_context"]


def test_graph_end_to_end(mock_context):
    graph = create_ask_graph()
    state = AskState(**_make_base_state(question="等待期"))
    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        result = graph.invoke(state, context=mock_context)
    assert result["answer"] != ""
