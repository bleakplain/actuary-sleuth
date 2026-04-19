"""AskState Reducer 合并测试"""
import operator


def test_operator_add_reducer():
    """验证 operator.add 正确合并列表"""
    left = {"messages": [{"role": "user", "content": "Q1"}]}
    right = {"messages": [{"role": "assistant", "content": "A1"}]}

    merged = left.copy()
    merged["messages"] = operator.add(left["messages"], right["messages"])

    assert len(merged["messages"]) == 2
    assert merged["messages"][0]["content"] == "Q1"
    assert merged["messages"][1]["content"] == "A1"


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
    """验证实体合并去重并限制 10 个"""
    from lib.rag_engine.graph import merge_session_context

    left = {"mentioned_entities": ["重疾险", "泰康"]}
    right = {"mentioned_entities": ["医疗险", "重疾险"], "product_type": "医疗险"}
    merged = merge_session_context(left, right)

    assert "重疾险" in merged["mentioned_entities"]
    assert "医疗险" in merged["mentioned_entities"]
    assert "泰康" in merged["mentioned_entities"]
    assert merged["product_type"] == "医疗险"
    assert len(merged["mentioned_entities"]) == 3


def test_merge_session_context_max_entities():
    """验证实体最多 10 个"""
    from lib.rag_engine.graph import merge_session_context

    entities = [f"产品{i}" for i in range(8)]
    left = {"mentioned_entities": entities[:4]}
    right = {"mentioned_entities": entities[4:]}
    merged = merge_session_context(left, right)

    assert len(merged["mentioned_entities"]) <= 10
