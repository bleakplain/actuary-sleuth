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

    assert route_by_action({"next_action": "clarify"}) == "clarify"
    assert route_by_action({"next_action": "search"}) == "search"
    assert route_by_action({}) == "search"


def test_ask_state_fields():
    """验证 AskState 包含新字段"""
    from lib.rag_engine.graph import AskState
    import typing

    hints = typing.get_type_hints(AskState)
    assert "session_context" in hints
    assert "skip_clarify" in hints
    assert "next_action" in hints
    assert "clarification_message" in hints
    assert "loop_detected" in hints


def test_graph_structure():
    """验证 graph 节点结构"""
    from lib.rag_engine.graph import create_ask_graph

    graph = create_ask_graph()
    nodes = list(graph.nodes.keys())

    assert "load_session_context" in nodes
    assert "clarify_user_query" in nodes
    assert "parallel_retrieval_entry" in nodes
    assert "save_session_context" in nodes


def test_loop_detection_in_clarify():
    """验证循环检测在 clarify 节点执行"""
    from lib.rag_engine.graph import clarify_user_query
    import hashlib

    # 计算 "测试问题" 的 hash
    normalized = "测试问题".strip().lower()
    question_hash = hashlib.md5(normalized.encode()).hexdigest()[:8]

    # 模拟循环状态：最近 3 条都是相同问题
    state = {
        "question": "测试问题",
        "session_context": {
            "query_history": [question_hash, question_hash, question_hash]
        },
        "mode": "qa",
        "user_id": "test",
        "session_id": "test_session",
    }

    result = clarify_user_query(state)

    # 应该检测到循环
    assert result.get("loop_detected") is True
    assert "loop_hint" in result
    # 循环时应该继续搜索而不是阻塞
    assert result.get("next_action") == "search"


def test_no_loop_normal_flow():
    """验证正常流程不触发循环检测"""
    from lib.rag_engine.graph import clarify_user_query

    state = {
        "question": "新问题",
        "session_context": {
            "query_history": ["a", "b", "c"]  # 不同的历史
        },
        "mode": "qa",
        "user_id": "test",
        "session_id": "test_session",
        "skip_clarify": True,
    }

    result = clarify_user_query(state)

    # 不应该检测到循环
    assert result.get("loop_detected") is None


if __name__ == "__main__":
    test_route_by_action()
    print("test_route_by_action passed")

    test_ask_state_fields()
    print("test_ask_state_fields passed")

    test_graph_structure()
    print("test_graph_structure passed")

    test_loop_detection_in_clarify()
    print("test_loop_detection_in_clarify passed")

    test_no_loop_normal_flow()
    print("test_no_loop_normal_flow passed")

    print("")
    print("All workflow tests passed!")
