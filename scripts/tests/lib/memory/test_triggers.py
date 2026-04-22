"""记忆触发器单元测试。"""
import time
import pytest

from lib.memory.triggers import should_retrieve_memory, TriggerResult


def test_topic_keyword_triggers_retrieval():
    """测试话题关键词触发检索。"""
    result = should_retrieve_memory("等待期是多少天？")
    assert result.should_retrieve is True
    assert result.trigger_type == "keyword"
    assert "等待期" in result.matched
    assert result.confidence == 0.9


def test_company_keyword_triggers_retrieval():
    """测试公司关键词触发检索。"""
    result = should_retrieve_memory("泰康的产品怎么样？")
    assert result.should_retrieve is True
    assert result.trigger_type == "company"
    assert "泰康" in result.matched
    assert result.confidence == 0.85


def test_entity_trigger():
    """测试实体关联触发。"""
    ctx = {"mentioned_entities": ["康健无忧"]}
    result = should_retrieve_memory("康健无忧怎么样？", session_context=ctx, last_retrieve_time=time.time())
    assert result.should_retrieve is True
    assert result.trigger_type == "entity"


def test_topic_continuation_trigger():
    """测试话题延续触发。"""
    ctx = {"current_topic": "核保规则"}
    result = should_retrieve_memory("核保规则有什么要求？", session_context=ctx, last_retrieve_time=time.time())
    assert result.should_retrieve is True
    assert result.trigger_type == "topic"


def test_interval_trigger():
    """测试时间间隔触发。"""
    result = should_retrieve_memory("普通问题", last_retrieve_time=0.0, interval_seconds=60)
    assert result.should_retrieve is True
    assert result.trigger_type == "interval"

    result = should_retrieve_memory("普通问题", last_retrieve_time=time.time(), interval_seconds=60)
    assert result.should_retrieve is False


def test_no_trigger_when_recent():
    """测试刚检索过时不触发。"""
    result = should_retrieve_memory("你好", last_retrieve_time=time.time(), interval_seconds=60)
    assert result.should_retrieve is False
    assert result.trigger_type == "skip"


def test_trigger_result_is_frozen():
    """测试 TriggerResult 是不可变的。"""
    result = TriggerResult(
        should_retrieve=True,
        trigger_type="keyword",
        matched=("等待期",),
        confidence=0.9,
    )
    with pytest.raises(AttributeError):
        result.should_retrieve = False
