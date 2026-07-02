"""多轮对话工作流测试"""
import sys
sys.path.insert(0, 'scripts')


def test_merge_session_context_left_empty():
    """验证左空时返回右"""
    from lib.rag_engine.graph import merge_session_context

    result = merge_session_context({}, {"product_type": "重疾险"})
    assert result == {"product_type": "重疾险"}


def test_merge_session_context_right_empty():
    """验证右空时返回左"""
    from lib.rag_engine.graph import merge_session_context

    result = merge_session_context({"product_type": "医疗险"}, {})
    assert result == {"product_type": "医疗险"}


def test_merge_session_context_entities():
    """验证实体合并、去重、限制"""
    from lib.rag_engine.graph import merge_session_context

    left = {"mentioned_entities": ["重疾险", "泰康"]}
    right = {"mentioned_entities": ["医疗险", "重疾险"], "product_type": "医疗险"}
    merged = merge_session_context(left, right)

    assert "重疾险" in merged["mentioned_entities"]
    assert "医疗险" in merged["mentioned_entities"]
    assert "泰康" in merged["mentioned_entities"]
    assert merged["product_type"] == "医疗险"


def test_merge_session_context_max_entities():
    """验证实体限制为 10 个"""
    from lib.rag_engine.graph import merge_session_context, MAX_ENTITIES

    left = {"mentioned_entities": [f"entity_{i}" for i in range(8)]}
    right = {"mentioned_entities": [f"entity_{i}" for i in range(5, 15)]}
    merged = merge_session_context(left, right)

    assert len(merged["mentioned_entities"]) <= MAX_ENTITIES


def test_route_by_action():
    """验证 route_by_action 路由"""
    from lib.rag_engine.graph import route_by_action

    assert route_by_action({}) == "search"
    assert route_by_action({"question": "有哪些法规"}) == "registry"
    assert route_by_action({"question": "重疾险的等待期多长"}) == "search"


def test_ask_state_fields():
    """验证 AskState 包含核心字段（已去除 clarify 相关）"""
    from lib.rag_engine.graph import AskState
    import typing

    hints = typing.get_type_hints(AskState)
    assert "session_context" in hints
    assert "next_action" in hints
    assert "loop_detected" in hints
    assert "skip_clarify" not in hints
    assert "clarification_message" not in hints


def test_graph_structure():
    """验证 graph 节点结构（已去除 clarify_user_query）"""
    from lib.rag_engine.graph import create_ask_graph

    graph = create_ask_graph()
    nodes = list(graph.nodes.keys())

    assert "load_session_context" in nodes
    assert "parallel_retrieval_entry" in nodes
    assert "save_session_context" in nodes
    assert "clarify_user_query" not in nodes


def test_loop_detection_in_load_session():
    """验证循环检测在 load_session_context 执行"""
    from unittest.mock import patch
    from lib.rag_engine.graph import load_session_context
    import hashlib

    normalized = "测试问题".strip().lower()
    question_hash = hashlib.md5(normalized.encode()).hexdigest()[:8]
    preloaded_ctx = {"query_history": [question_hash, question_hash, question_hash]}

    state = {
        "question": "测试问题",
        "session_context": preloaded_ctx,
        "user_id": "test",
        "session_id": "test_session",
    }

    # mock SessionContextMiddleware.before_invoke 跳过 DB 加载，保留测试输入
    with patch("lib.rag_engine.graph._context_mw") as mock_ctx_mw:
        mock_ctx_mw.before_invoke.return_value = {"session_context": preloaded_ctx}
        result = load_session_context(state)

    assert result.get("loop_detected") is True
    assert "loop_hint" in result


def test_no_loop_normal_flow():
    """验证正常流程不触发循环检测"""
    from unittest.mock import patch
    from lib.rag_engine.graph import load_session_context

    preloaded_ctx = {"query_history": ["a", "b", "c"]}
    state = {
        "question": "新问题",
        "session_context": preloaded_ctx,
        "user_id": "test",
        "session_id": "test_session",
    }

    with patch("lib.rag_engine.graph._context_mw") as mock_ctx_mw:
        mock_ctx_mw.before_invoke.return_value = {"session_context": preloaded_ctx}
        result = load_session_context(state)

    assert result.get("loop_detected") is None


def _make_generate_state(question: str, registry_context: str = ""):
    """构造 generate 节点所需 state。"""
    from lib.rag_engine.graph import AskState

    base = {
        "question": question, "user_id": "test", "session_id": "sess_1",
        "search_results": [], "memory_context": "", "answer": "", "sources": [],
        "citations": [], "unverified_claims": [], "content_mismatches": [],
        "faithfulness_score": None, "error": None,
        "messages": [], "session_context": {},
        "iteration_count": 0, "next_action": "search",
        "loop_detected": None, "loop_hint": None,
        "registry_context": registry_context,
    }
    return AskState(**base)


def test_generate_catalog_skips_llm():
    """catalog 意图：registry_context 已结构化，跳过 LLM 调用。"""
    from unittest.mock import MagicMock, patch
    from langgraph.runtime import Runtime
    from lib.rag_engine.graph import generate, GraphContext

    registry_ctx = "当前知识库共收录 5 部法规，按分类列出：\n【行政法规】(2 部)\n  - 保险法（120 个条款单元）"
    state = _make_generate_state("有哪些法规", registry_context=registry_ctx)

    llm = MagicMock()
    llm.model = "test"
    engine = MagicMock()
    ctx = GraphContext(rag_engine=engine, llm_client=llm, memory_service=MagicMock())

    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        result = generate(state, runtime=Runtime(context=ctx))

    llm.chat.assert_not_called()
    assert result["answer"] == registry_ctx
    assert result["sources"] == []


def test_generate_count_skips_llm():
    """count 意图：跳过 LLM 调用。"""
    from unittest.mock import MagicMock, patch
    from langgraph.runtime import Runtime
    from lib.rag_engine.graph import generate, GraphContext

    registry_ctx = "知识库共收录 5 部法规，合计 120 个条款单元"
    state = _make_generate_state("法规总数是多少", registry_context=registry_ctx)

    llm = MagicMock()
    llm.model = "test"
    engine = MagicMock()
    ctx = GraphContext(rag_engine=engine, llm_client=llm, memory_service=MagicMock())

    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        result = generate(state, runtime=Runtime(context=ctx))

    llm.chat.assert_not_called()
    assert result["answer"] == registry_ctx


def test_generate_metadata_calls_llm():
    """metadata 意图：保留 LLM 调用做语言化润色。"""
    from unittest.mock import MagicMock, patch
    from langgraph.runtime import Runtime
    from lib.rag_engine.graph import generate, GraphContext

    registry_ctx = "法规名称：保险法\n所属分类：法律\n条款单元数：120"
    state = _make_generate_state("保险法什么时候实施", registry_context=registry_ctx)

    llm = MagicMock()
    llm.model = "test"
    llm.chat.return_value = "《保险法》是一部法律，共 120 个条款单元。"
    engine = MagicMock()
    ctx = GraphContext(rag_engine=engine, llm_client=llm, memory_service=MagicMock())

    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MagicMock()
        mock_span.return_value.__exit__ = MagicMock(return_value=False)
        result = generate(state, runtime=Runtime(context=ctx))

    llm.chat.assert_called_once()
    assert result["answer"] == "《保险法》是一部法律，共 120 个条款单元。"


def test_generate_content_calls_llm():
    """content 意图（无 registry_context）：走常规 RAG LLM 路径。"""
    from unittest.mock import MagicMock, patch
    from langgraph.runtime import Runtime
    from lib.rag_engine.graph import generate, GraphContext

    state = _make_generate_state("重疾险等待期最长多少天", registry_context="")
    state["search_results"] = [{"content": "等待期不得超过 90 天", "law_name": "健康保险管理办法"}]

    llm = MagicMock()
    llm.model = "test"
    llm.chat.return_value = "等待期不得超过 90 天。"
    engine = MagicMock()
    engine.config.generation.max_context_chars = 12000
    engine._build_qa_prompt = MagicMock(return_value=("user prompt", 1))
    ctx = GraphContext(rag_engine=engine, llm_client=llm, memory_service=MagicMock())

    with patch("lib.rag_engine.graph.RAGEngine._build_qa_prompt", return_value=("user prompt", 1)):
        with patch("lib.rag_engine.graph.trace_span") as mock_span:
            mock_span.return_value.__enter__ = MagicMock()
            mock_span.return_value.__exit__ = MagicMock(return_value=False)
            result = generate(state, runtime=Runtime(context=ctx))

    llm.chat.assert_called_once()


if __name__ == "__main__":
    test_route_by_action()
    print("test_route_by_action passed")

    test_ask_state_fields()
    print("test_ask_state_fields passed")

    test_graph_structure()
    print("test_graph_structure passed")

    test_loop_detection_in_load_session()
    print("test_loop_detection_in_load_session passed")

    test_no_loop_normal_flow()
    print("test_no_loop_normal_flow passed")

    test_generate_catalog_skips_llm()
    print("test_generate_catalog_skips_llm passed")

    test_generate_count_skips_llm()
    print("test_generate_count_skips_llm passed")

    test_generate_metadata_calls_llm()
    print("test_generate_metadata_calls_llm passed")

    test_generate_content_calls_llm()
    print("test_generate_content_calls_llm passed")

    print("")
    print("All workflow tests passed!")
