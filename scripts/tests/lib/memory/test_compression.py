"""记忆上下文压缩测试。"""
import pytest

from lib.memory.compression import compress_memory_context


def test_compress_empty_memories():
    """测试空记忆列表返回空字符串。"""
    result = compress_memory_context([])
    assert result == ""


def test_compress_single_memory():
    """测试单条记忆压缩。"""
    memories = [{"memory": "等待期180天", "created_at": "2026-04-01T10:00:00", "score": 0.9}]
    result = compress_memory_context(memories, max_chars=100)
    assert "等待期180天" in result
    assert "2026-04-01" in result


def test_compress_sorts_by_score():
    """测试按相关性排序。"""
    memories = [
        {"memory": "低相关记忆", "created_at": "2026-04-01", "score": 0.3},
        {"memory": "高相关记忆", "created_at": "2026-04-02", "score": 0.95},
        {"memory": "中等相关", "created_at": "2026-04-03", "score": 0.6},
    ]
    result = compress_memory_context(memories, max_chars=200)
    assert result.startswith("- 高相关记忆")


def test_compress_respects_max_chars():
    """测试超过限制时截断。"""
    memories = [
        {"memory": "第一条记忆内容", "created_at": "2026-04-01", "score": 0.9},
        {"memory": "第二条记忆内容", "created_at": "2026-04-02", "score": 0.8},
    ]
    result = compress_memory_context(memories, max_chars=20)
    assert len(result) <= 20


def test_compress_handles_missing_score():
    """测试缺失 score 时默认为 0。"""
    memories = [
        {"memory": "有score", "created_at": "2026-04-01", "score": 0.9},
        {"memory": "无score", "created_at": "2026-04-02"},
    ]
    result = compress_memory_context(memories, max_chars=100)
    assert "有score" in result


def test_compress_handles_missing_created_at():
    """测试缺失 created_at 时不显示日期。"""
    memories = [{"memory": "无日期记忆", "score": 0.9}]
    result = compress_memory_context(memories, max_chars=100)
    assert "无日期记忆" in result
    assert "记录于" not in result