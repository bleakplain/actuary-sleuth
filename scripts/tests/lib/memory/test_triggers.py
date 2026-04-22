"""记忆触发器单元测试。"""
import pytest

from lib.memory.triggers import should_retrieve_memory, TriggerResult


def test_topic_keyword_triggers_retrieval():
    """测试话题关键词触发检索。"""
    result = should_retrieve_memory("等待期是多少天？")
    assert result.should_retrieve is True
    assert result.trigger_type == "topic"
    assert "等待期" in result.matched_keywords
    assert result.confidence == 0.9


def test_company_keyword_triggers_retrieval():
    """测试公司关键词触发检索。"""
    result = should_retrieve_memory("平安的产品怎么样？")
    assert result.should_retrieve is True
    assert result.trigger_type == "company"
    assert "平安" in result.matched_keywords
    assert result.confidence == 0.8


def test_multiple_topic_keywords():
    """测试多个话题关键词。"""
    result = should_retrieve_memory("等待期和保费的规则是什么？")
    assert result.should_retrieve is True
    assert result.trigger_type == "topic"
    assert len(result.matched_keywords) >= 1


def test_no_trigger_keyword():
    """测试无触发词时不检索。"""
    result = should_retrieve_memory("你好")
    assert result.should_retrieve is False
    assert result.trigger_type == "skip"
    assert result.matched_keywords == ()
    assert result.confidence == 0.0


def test_partial_match_not_triggered():
    """测试部分匹配不触发。"""
    result = should_retrieve_memory("你好世界")
    assert result.should_retrieve is False


def test_trigger_result_is_frozen():
    """测试 TriggerResult 是不可变的。"""
    result = TriggerResult(
        should_retrieve=True,
        trigger_type="topic",
        matched_keywords=("等待期",),
        confidence=0.9,
    )
    with pytest.raises(AttributeError):
        result.should_retrieve = False
