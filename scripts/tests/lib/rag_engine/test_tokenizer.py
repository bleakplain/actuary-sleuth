#!/usr/bin/env python3
"""测试 tokenizer 模块 - jieba 分词"""
import pytest

from lib.rag_engine.tokenizer import tokenize_chinese


class TestTokenizer:
    """测试分词器"""

    def test_tokenize_empty_string(self):
        result = tokenize_chinese("")
        assert result == []

    def test_tokenize_chinese_text(self):
        result = tokenize_chinese("保险法规定")
        assert len(result) > 0
        # jieba should produce meaningful tokens, not the whole string
        assert any("保险" in t for t in result)

    def test_tokenize_removes_punctuation(self):
        result = tokenize_chinese("保险法、民法典。")
        # No punctuation in results
        assert not any(t in ("、", "。") for t in result)

    def test_tokenize_long_text(self):
        text = "健康保险产品的等待期不得超过90天。" * 100
        result = tokenize_chinese(text)
        assert len(result) > 0

    def test_tokenize_english_and_numbers(self):
        result = tokenize_chinese("保险条款Insurance2024年")
        assert len(result) > 0
        # Should contain English/number tokens
        assert any(t.isascii() and t.isalnum() for t in result)
