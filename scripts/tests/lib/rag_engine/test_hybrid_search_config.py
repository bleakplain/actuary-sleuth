#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HybridQueryConfig 配置和阈值过滤测试"""
import pytest
from lib.rag_engine.config import HybridQueryConfig


class TestHybridQueryConfig:

    def test_default_reranker_type_is_gguf(self):
        config = HybridQueryConfig()
        assert config.reranker_type == "gguf"

    def test_rerank_min_score_default_zero(self):
        config = HybridQueryConfig()
        assert config.rerank_min_score == 0.0

    def test_rerank_min_score_valid_range(self):
        config = HybridQueryConfig(rerank_min_score=0.5)
        assert config.rerank_min_score == 0.5

    def test_rerank_min_score_negative_rejected(self):
        with pytest.raises(ValueError, match="rerank_min_score"):
            HybridQueryConfig(rerank_min_score=-0.1)

    def test_rerank_min_score_above_one_rejected(self):
        with pytest.raises(ValueError, match="rerank_min_score"):
            HybridQueryConfig(rerank_min_score=1.1)

    def test_min_rrf_score_preserved(self):
        config = HybridQueryConfig(min_rrf_score=0.3)
        assert config.min_rrf_score == 0.3

    def test_both_thresholds_can_coexist(self):
        config = HybridQueryConfig(
            min_rrf_score=0.2,
            rerank_min_score=0.5,
        )
        assert config.min_rrf_score == 0.2
        assert config.rerank_min_score == 0.5


class TestRerankThresholdFilter:

    @staticmethod
    def _apply_filter(results, threshold):
        if not results or threshold <= 0:
            return results
        return [
            r for r in results
            if not r.get('reranked', False)
            or r.get('rerank_score', 0) >= threshold
        ]

    def test_filter_removes_low_score_results(self):
        results = [
            {'content': 'A', 'rerank_score': 0.8, 'reranked': True},
            {'content': 'B', 'rerank_score': 0.3, 'reranked': True},
            {'content': 'C', 'rerank_score': 0.6, 'reranked': True},
        ]
        filtered = self._apply_filter(results, 0.5)
        assert len(filtered) == 2
        assert filtered[0]['content'] == 'A'
        assert filtered[1]['content'] == 'C'

    def test_filter_returns_empty_when_all_below(self):
        results = [
            {'content': 'A', 'rerank_score': 0.2, 'reranked': True},
            {'content': 'B', 'rerank_score': 0.1, 'reranked': True},
        ]
        filtered = self._apply_filter(results, 0.5)
        assert filtered == []

    def test_filter_disabled_when_zero(self):
        results = [
            {'content': 'A', 'rerank_score': 0.1, 'reranked': True},
        ]
        filtered = self._apply_filter(results, 0.0)
        assert len(filtered) == 1

    def test_filter_preserves_unreranked_results(self):
        results = [
            {'content': 'A', 'score': 0.5},
            {'content': 'B', 'rerank_score': 0.1, 'reranked': False},
        ]
        filtered = self._apply_filter(results, 0.5)
        assert len(filtered) == 2

    def test_filter_preserves_reranked_false(self):
        results = [
            {'content': 'A', 'rerank_score': 0.1, 'reranked': False},
            {'content': 'B', 'rerank_score': 0.8, 'reranked': True},
        ]
        filtered = self._apply_filter(results, 0.5)
        assert len(filtered) == 2

    def test_empty_input(self):
        filtered = self._apply_filter([], 0.5)
        assert filtered == []
