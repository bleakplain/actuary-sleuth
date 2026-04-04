#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
import pytest

from lib.rag_engine.llm_reranker import LLMReranker, RerankConfig


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def reranker(mock_llm):
    config = RerankConfig(enabled=True, top_k=3)
    return LLMReranker(mock_llm, config)


def _make_candidates(n: int) -> list:
    return [
        {'content': f'条款内容第{i}条', 'law_name': f'法规{i}', 'article_number': f'第{i}条'}
        for i in range(1, n + 1)
    ]


def test_rerank_with_llm_response(reranker, mock_llm):
    mock_llm.generate.return_value = '2,1,3'
    candidates = _make_candidates(3)

    results = reranker.rerank('等待期', candidates)

    assert len(results) == 3
    assert results[0]['article_number'] == '第2条'
    assert results[0]['rerank_score'] == 1.0
    assert results[0]['reranked'] is True
    assert results[1]['rerank_score'] == 0.5
    assert results[2]['rerank_score'] == pytest.approx(1 / 3)


def test_rerank_respects_top_k(reranker, mock_llm):
    mock_llm.generate.return_value = '3,2,1'
    candidates = _make_candidates(5)

    results = reranker.rerank('等待期', candidates, top_k=2)

    assert len(results) == 2
    assert results[0]['article_number'] == '第3条'
    assert results[1]['article_number'] == '第2条'


def test_rerank_disabled(mock_llm):
    config = RerankConfig(enabled=False)
    reranker = LLMReranker(mock_llm, config)
    candidates = _make_candidates(3)

    results = reranker.rerank('test', candidates)

    assert len(results) == 3
    mock_llm.generate.assert_not_called()


def test_rerank_empty_candidates(reranker, mock_llm):
    results = reranker.rerank('test', [])
    assert results == []
    mock_llm.generate.assert_not_called()


def test_rerank_fallback_on_llm_error(reranker, mock_llm):
    mock_llm.generate.side_effect = RuntimeError("LLM 调用失败")
    candidates = _make_candidates(3)

    results = reranker.rerank('等待期', candidates)

    assert len(results) == 3
    assert results[0]['reranked'] is False


def test_rerank_fallback_no_mutation(reranker, mock_llm):
    mock_llm.generate.side_effect = RuntimeError("LLM 调用失败")
    candidates = _make_candidates(3)
    original_content = candidates[0]['content']

    results = reranker.rerank('等待期', candidates)

    assert candidates[0]['content'] == original_content
    assert 'reranked' not in candidates[0]


def test_parse_ranking_valid():
    ranking = LLMReranker._parse_ranking('2,1,3', 3)
    assert ranking == [1, 0, 2]


def test_parse_ranking_with_extra_text():
    ranking = LLMReranker._parse_ranking('排序结果：2,1,3', 3)
    assert ranking == [1, 0, 2]


def test_parse_ranking_partial():
    ranking = LLMReranker._parse_ranking('2,1', 4)
    assert ranking[:2] == [1, 0]
    assert len(ranking) == 4


def test_parse_ranking_duplicates():
    ranking = LLMReranker._parse_ranking('2,2,1,3', 3)
    assert ranking[:2] == [1, 0]
    assert len(ranking) == 3


def test_parse_ranking_out_of_range():
    ranking = LLMReranker._parse_ranking('5,1,2', 3)
    assert ranking[:2] == [0, 1]
    assert len(ranking) == 3
