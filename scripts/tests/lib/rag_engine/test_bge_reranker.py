#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
from unittest.mock import patch
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.normpath(os.path.join(_test_dir, '..', '..', '..'))
sys.path.insert(0, _scripts_dir)


def _make_candidates(n: int) -> list:
    return [
        {'content': f'健康保险产品的等待期不得超过180天，这是保险监管的重要规定。条款内容第{i}条', 'law_name': f'健康保险管理办法{i}', 'article_number': f'第{i}条'}
        for i in range(1, n + 1)
    ]


class TestBgeReranker:

    @pytest.fixture(scope="class")
    def reranker(self):
        from lib.rag_engine.bge_reranker import BgeReranker
        return BgeReranker(batch_size=8)

    def test_rerank_basic(self, reranker):
        candidates = _make_candidates(5)
        results = reranker.rerank('健康保险等待期有什么规定', candidates)
        assert len(results) == 5
        assert all('rerank_score' in r for r in results)
        assert all(r['reranked'] is True for r in results)

    def test_rerank_sorted_by_score(self, reranker):
        candidates = _make_candidates(5)
        results = reranker.rerank('健康保险等待期有什么规定', candidates)
        scores = [r['rerank_score'] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_rerank_with_top_k(self, reranker):
        candidates = _make_candidates(5)
        results = reranker.rerank('健康保险等待期有什么规定', candidates, top_k=3)
        assert len(results) == 3

    def test_rerank_empty_candidates(self, reranker):
        results = reranker.rerank('健康保险等待期', [])
        assert results == []

    def test_rerank_preserves_metadata(self, reranker):
        candidates = [
            {'content': '健康保险产品等待期不得超过180天', 'law_name': '健康保险管理办法', 'article_number': '第十七条', 'extra': 'important'},
            {'content': '财产保险合同的相关规定', 'law_name': '保险法', 'article_number': '第十条'},
        ]
        results = reranker.rerank('健康保险等待期', candidates)
        assert results[0]['law_name'] in ['健康保险管理办法', '保险法']
        assert 'extra' in results[0] or results[0].get('law_name') == '保险法'

    def test_rerank_no_mutation(self, reranker):
        candidates = _make_candidates(3)
        original_content = candidates[0]['content']
        reranker.rerank('测试查询', candidates)
        assert candidates[0]['content'] == original_content
        assert 'reranked' not in candidates[0]

    def test_rerank_batch_processing(self):
        from lib.rag_engine.bge_reranker import BgeReranker
        reranker = BgeReranker(batch_size=2)
        candidates = _make_candidates(6)
        results = reranker.rerank('健康保险', candidates)
        assert len(results) == 6
        assert all('rerank_score' in r for r in results)


class TestBgeRerankerImport:

    def test_import_error_message(self):
        with patch.dict('sys.modules', {'sentence_transformers': None}):
            if 'lib.rag_engine.bge_reranker' in sys.modules:
                del sys.modules['lib.rag_engine.bge_reranker']
            with pytest.raises(ImportError, match="sentence-transformers"):
                from lib.rag_engine.bge_reranker import BgeReranker
                BgeReranker()


class TestApplyScores:

    def test_apply_scores_basic(self):
        from lib.rag_engine.reranker_base import BaseReranker
        candidates = [{'content': 'a'}, {'content': 'b'}, {'content': 'c'}]
        scores = [0.3, 0.9, 0.6]
        result = BaseReranker._apply_scores(candidates, scores)
        assert [r['rerank_score'] for r in result] == [0.9, 0.6, 0.3]
        assert result[0]['content'] == 'b'

    def test_apply_scores_with_top_k(self):
        from lib.rag_engine.reranker_base import BaseReranker
        candidates = [{'content': 'a'}, {'content': 'b'}, {'content': 'c'}]
        scores = [0.3, 0.9, 0.6]
        result = BaseReranker._apply_scores(candidates, scores, top_k=2)
        assert len(result) == 2
        assert result[0]['content'] == 'b'

    def test_apply_scores_no_mutation(self):
        from lib.rag_engine.reranker_base import BaseReranker
        candidates = [{'content': 'a'}]
        BaseReranker._apply_scores(candidates, [0.5])
        assert 'reranked' not in candidates[0]


class TestRerankConfigValidation:

    def test_quantized_requires_model_path(self):
        from lib.rag_engine.config import RerankConfig
        with pytest.raises(ValueError, match="model is required"):
            RerankConfig(reranker_type="bge", quantized=True, model="")

    def test_quantized_with_model_path_ok(self):
        from lib.rag_engine.config import RerankConfig
        config = RerankConfig(reranker_type="bge", quantized=True, model="/path/to/model")
        assert config.quantized is True
