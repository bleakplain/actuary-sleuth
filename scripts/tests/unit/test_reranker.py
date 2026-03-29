#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reranker 模块单元测试"""
import pytest
from unittest.mock import MagicMock

from lib.rag_engine.reranker import LLMReranker, RerankConfig


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def reranker(mock_llm):
    config = RerankConfig(enabled=True, top_k=3, max_candidates=10)
    return LLMReranker(mock_llm, config)


@pytest.fixture
def sample_candidates():
    return [
        {'law_name': '法规1', 'article_number': '第一条', 'content': '等待期不超过90天。'},
        {'law_name': '法规2', 'article_number': '第二条', 'content': '如实告知义务。'},
        {'law_name': '法规3', 'article_number': '第三条', 'content': '保险期间不少于1年。'},
    ]


class TestParseRanking:

    def test_standard_format(self):
        result = LLMReranker._parse_ranking("2,5,1,4,3", 5)
        assert result == [1, 4, 0, 3, 2]

    def test_with_spaces(self):
        result = LLMReranker._parse_ranking("2 5 1 4 3", 5)
        assert result == [1, 4, 0, 3, 2]

    def test_partial_ranking(self):
        result = LLMReranker._parse_ranking("3,1", 5)
        assert result[:2] == [2, 0]
        assert set(result) == {0, 1, 2, 3, 4}

    def test_with_explanation_text(self):
        result = LLMReranker._parse_ranking(
            "2是最相关的，因为内容匹配了要求", 3
        )
        # Only "2" should be extracted, range validation filters the rest
        assert len(result) >= 1
        assert result[0] == 1

    def test_empty_response(self):
        result = LLMReranker._parse_ranking("", 3)
        assert result == [0, 1, 2]

    def test_duplicate_numbers(self):
        result = LLMReranker._parse_ranking("1,1,2,2,3", 3)
        assert result == [0, 1, 2]

    def test_out_of_range_numbers(self):
        result = LLMReranker._parse_ranking("1,99,2", 3)
        assert 98 not in result

    def test_single_number(self):
        result = LLMReranker._parse_ranking("3", 5)
        assert result[0] == 2
        assert set(result) == {0, 1, 2, 3, 4}

    def test_chinese_punctuation(self):
        result = LLMReranker._parse_ranking("1，2，3", 3)
        assert result[:3] == [0, 1, 2]


class TestLLMReranker:

    def test_rerank_returns_top_k(self, reranker, mock_llm, sample_candidates):
        mock_llm.generate.return_value = "1,3,2"
        results = reranker.rerank("等待期规定", sample_candidates, top_k=2)

        assert len(results) == 2
        assert results[0]['reranked'] is True
        assert results[0]['rerank_score'] == 1.0

    def test_rerank_disabled(self, mock_llm, sample_candidates):
        config = RerankConfig(enabled=False)
        reranker = LLMReranker(mock_llm, config)
        results = reranker.rerank("测试", sample_candidates)

        mock_llm.generate.assert_not_called()

    def test_rerank_failure_marks_unreranked(self, reranker, mock_llm, sample_candidates):
        mock_llm.generate.side_effect = Exception("LLM 不可用")
        results = reranker.rerank("测试", sample_candidates)

        assert all(r['reranked'] is False for r in results)

    def test_rerank_truncates_candidates(self, reranker, mock_llm):
        many_candidates = [
            {'law_name': f'法规{i}', 'article_number': f'第{i}条', 'content': f'内容{i}。'}
            for i in range(25)
        ]
        mock_llm.generate.return_value = "1,2,3"
        results = reranker.rerank("测试", many_candidates)

        assert mock_llm.generate.call_count == 1
        prompt = mock_llm.generate.call_args[0][0]
        assert '[10]' in prompt
        assert '[11]' not in prompt

    def test_rerank_empty_candidates(self, reranker, mock_llm):
        results = reranker.rerank("测试", [])
        assert results == []

    def test_rerank_score_decreases(self, reranker, mock_llm, sample_candidates):
        mock_llm.generate.return_value = "1,2,3"
        results = reranker.rerank("测试", sample_candidates, top_k=3)

        assert results[0]['rerank_score'] > results[1]['rerank_score']
        assert results[1]['rerank_score'] > results[2]['rerank_score']
