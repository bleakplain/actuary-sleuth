#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 retrieval 模块 - 使用真实索引
"""
import pytest

pytest.importorskip("llama_index", reason="llama_index not installed")

import lancedb

from lib.rag_engine.retrieval import vector_search


class TestVectorSearch:
    """测试向量检索"""

    def test_vector_search_with_real_index(self, vector_index):
        results = vector_search(vector_index, "等待期", top_k=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        if results:
            node = results[0]
            assert hasattr(node, 'node')
            assert hasattr(node, 'score')

    def test_vector_search_with_filters(self, vector_index):
        results = vector_search(
            vector_index, "保险", top_k=5,
            filters={'category': '健康保险'}
        )
        assert isinstance(results, list)
        if results:
            for node in results:
                category = node.node.metadata.get('category')
                if category:
                    assert category == '健康保险'

    @pytest.mark.skipif(
        int(lancedb.__version__.split(".")[1]) >= 21,
        reason="LanceDB 0.21+ removed nprobes from empty query builder"
    )
    def test_vector_search_empty_query(self, vector_index):
        results = vector_search(vector_index, "", top_k=3)
        assert isinstance(results, list)

    def test_vector_search_top_k_limit(self, vector_index):
        for k in [1, 2, 5, 10]:
            results = vector_search(vector_index, "保险", top_k=k)
            assert len(results) <= k


class TestBM25IndexSearch:
    """测试 BM25 索引检索（替代旧的 keyword_search）"""

    def test_bm25_search_with_documents(self, sample_documents, bm25_index):
        results = bm25_index.search("等待期", top_k=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        if results:
            node, score = results[0]
            assert hasattr(node, 'text')
            assert score > 0

    def test_bm25_search_with_filters(self, sample_documents, bm25_index):
        results = bm25_index.search(
            "保险", top_k=5, filters={'law_name': '保险法'}
        )
        if results:
            for node, _ in results:
                assert node.metadata.get('law_name') == '保险法'

    def test_bm25_search_exact_match(self, sample_documents, bm25_index):
        results = bm25_index.search("等待期不得超过90天", top_k=3)
        assert isinstance(results, list)
        if results:
            assert all(score > 0 for _, score in results)

    def test_bm25_search_no_match(self, sample_documents, bm25_index):
        results = bm25_index.search("不存在的特殊词汇xyz123", top_k=3)
        assert isinstance(results, list)


class TestHybridSearch:
    """测试混合检索"""

    def test_hybrid_search_with_real_index(self, vector_index, sample_documents, bm25_index):
        from lib.rag_engine.retrieval import hybrid_search

        results = hybrid_search(
            vector_index, bm25_index,
            "健康保险等待期",
            vector_top_k=3, keyword_top_k=3
        )
        assert isinstance(results, list)
        assert len(results) > 0

        for result in results:
            assert 'law_name' in result
            assert 'article_number' in result
            assert 'content' in result
            assert 'score' in result
            assert isinstance(result['score'], (int, float))

    def test_hybrid_search_ranking(self, vector_index, sample_documents, bm25_index):
        from lib.rag_engine.retrieval import hybrid_search

        results = hybrid_search(
            vector_index, bm25_index,
            "保险费率",
            vector_top_k=5, keyword_top_k=5
        )
        assert isinstance(results, list)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]['score'] >= results[i + 1]['score']

    def test_hybrid_search_no_index(self):
        from lib.rag_engine.retrieval import hybrid_search
        results = hybrid_search(None, None, "test query", vector_top_k=3, keyword_top_k=3)
        assert results == []

    def test_hybrid_search_with_filters(self, vector_index, sample_documents, bm25_index):
        from lib.rag_engine.retrieval import hybrid_search

        results = hybrid_search(
            vector_index, bm25_index,
            "保险",
            vector_top_k=3, keyword_top_k=3,
            filters={'category': '意外保险'}
        )
        assert isinstance(results, list)
        if results:
            for result in results:
                assert result.get('category') == '意外保险'

    def test_hybrid_search_chinese_queries(self, vector_index, sample_documents, bm25_index):
        from lib.rag_engine.retrieval import hybrid_search

        queries = [
            "健康保险等待期",
            "如实告知义务",
            "意外伤害保险期限",
            "保险费率",
            "保险期间"
        ]
        for query in queries:
            results = hybrid_search(
                vector_index, bm25_index,
                query, vector_top_k=3, keyword_top_k=3
            )
            assert isinstance(results, list)


class TestSearchQuality:
    """测试检索质量"""

    def test_retrieval_relevance(self, vector_index, sample_documents, bm25_index):
        from lib.rag_engine.retrieval import hybrid_search

        results = hybrid_search(
            vector_index, bm25_index,
            "等待期", vector_top_k=3, keyword_top_k=3
        )
        if results:
            content = results[0]['content'].lower()
            assert any(kw in content for kw in ['等待', '期', '天', '保险'])
