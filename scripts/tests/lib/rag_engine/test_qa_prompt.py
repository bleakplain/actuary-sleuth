#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 生成环节测试 - Prompt 构建、引用解析、幻觉检测
"""
import pytest
from unittest.mock import MagicMock

pytest.importorskip("llama_index.vector_stores", reason="llama_index.vector_stores not installed")

from lib.rag_engine.rag_engine import RAGEngine
from lib.rag_engine.config import RAGConfig


@pytest.fixture
def engine():
    config = RAGConfig(
        max_context_chars=8000,
        enable_faithfulness=True,
    )
    mock_provider = MagicMock()
    return RAGEngine(config=config, llm_provider=mock_provider)


class TestQAPrompt:

    def test_prompt_uses_numbered_list(self, engine):
        results = [
            {'law_name': '健康保险', 'article_number': '第一条', 'content': '等待期90天'},
            {'law_name': '保险法', 'article_number': '第十六条', 'content': '如实告知'},
        ]
        prompt, count = engine._build_qa_prompt("等待期规定", results)
        assert '1. 【健康保险】第一条' in prompt
        assert '2. 【保险法】第十六条' in prompt
        assert count == 2

    def test_prompt_contains_fewshot_example(self, engine):
        results = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        prompt, count = engine._build_qa_prompt("测试问题", results)
        assert '## 回答示例' in prompt

    def test_prompt_uses_only_based_wording(self, engine):
        results = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        prompt, count = engine._build_qa_prompt("测试", results)
        assert '仅依据' in prompt

    def test_context_truncation_respects_config(self, engine):
        engine.config.max_context_chars = 100
        results = [
            {'law_name': '测试', 'article_number': f'第{i}条', 'content': 'A' * 200}
            for i in range(10)
        ]
        prompt, count = engine._build_qa_prompt("测试", results)
        assert '1. 【测试】第0条' in prompt
        assert count == 1

    def test_build_prompt_returns_included_count(self, engine):
        results = [
            {'law_name': '测试', 'article_number': '第一条', 'content': '短'},
            {'law_name': '测试', 'article_number': '第二条', 'content': '短'},
        ]
        _, count = engine._build_qa_prompt("测试", results)
        assert count == 2

    def test_empty_results_returns_zero_count(self, engine):
        _, count = engine._build_qa_prompt("测试", [])
        assert count == 0


class TestCitationParsing:

    def test_parse_valid_citations(self, engine):
        from lib.rag_engine.attribution import parse_citations
        answer = "根据《健康保险管理办法》第一条[来源1]，等待期不超过90天。"
        sources = [
            {'law_name': '健康保险管理办法', 'article_number': '第一条', 'content': '等待期90天'},
        ]
        result = parse_citations(answer, sources)
        assert len(result.citations) == 1
        assert result.citations[0].law_name == '健康保险管理办法'

    def test_parse_ignores_out_of_range(self, engine):
        from lib.rag_engine.attribution import parse_citations
        answer = "根据[来源5]的规定"
        sources = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        result = parse_citations(answer, sources)
        assert len(result.citations) == 0

    def test_parse_empty_answer(self, engine):
        from lib.rag_engine.attribution import parse_citations
        result = parse_citations("", [])
        assert result.citations == []
        assert result.unverified_claims == []


class TestFaithfulness:

    def test_high_faithfulness(self, engine):
        contexts = ["健康保险产品的等待期不得超过90天"]
        answer = "健康保险产品的等待期不得超过90天"
        score = engine._compute_faithfulness(contexts, answer)
        assert score > 0.8

    def test_low_faithfulness(self, engine):
        contexts = ["健康保险产品的等待期不得超过90天"]
        answer = "根据宇宙大爆炸理论，宇宙已有138亿年历史"
        score = engine._compute_faithfulness(contexts, answer)
        assert score < 0.3

    def test_empty_inputs(self, engine):
        assert engine._compute_faithfulness([], "答案") == 0.0
        assert engine._compute_faithfulness(["上下文"], "") == 0.0
