#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 retrieval 模块 - 使用真实索引
"""
import pytest

pytest.importorskip("llama_index", reason="llama_index not installed")

from lib.rag_engine.retrieval import vector_search, keyword_search, hybrid_search


class TestVectorSearch:
    """测试向量检索"""

    def test_vector_search_with_real_index(self, real_vector_index):
        """测试使用真实索引的向量检索"""
        results = vector_search(real_vector_index, "等待期", top_k=3)

        assert isinstance(results, list)
        assert len(results) <= 3
        # 验证返回的节点有正确的属性
        if results:
            node = results[0]
            assert hasattr(node, 'node')
            assert hasattr(node, 'score')

    def test_vector_search_with_filters(self, real_vector_index):
        """测试带过滤条件的向量检索"""
        results = vector_search(
            real_vector_index,
            "保险",
            top_k=5,
            filters={'category': '健康保险'}
        )

        assert isinstance(results, list)
        # 验证过滤条件被应用
        if results:
            for node in results:
                category = node.node.metadata.get('category')
                if category:
                    assert category == '健康保险'

    def test_vector_search_empty_query(self, real_vector_index):
        """测试空查询"""
        results = vector_search(real_vector_index, "", top_k=3)
        assert isinstance(results, list)

    def test_vector_search_top_k_limit(self, real_vector_index):
        """测试top_k限制"""
        for k in [1, 2, 5, 10]:
            results = vector_search(real_vector_index, "保险", top_k=k)
            assert len(results) <= k


class TestKeywordSearch:
    """测试关键词检索"""

    def test_keyword_search_with_real_index(self, real_vector_index):
        """测试使用真实索引的关键词检索"""
        results = keyword_search(
            real_vector_index,
            "等待期",
            top_k=3,
            avg_doc_len=50
        )

        assert isinstance(results, list)
        assert len(results) <= 3

        # 验证返回的节点有正确的属性
        if results:
            node = results[0]
            assert hasattr(node, 'node')
            assert hasattr(node, 'score')

    def test_keyword_search_with_filters(self, real_vector_index):
        """测试带过滤条件的关键词检索"""
        results = keyword_search(
            real_vector_index,
            "保险",
            top_k=5,
            filters={'law_name': '保险法'},
            avg_doc_len=50
        )

        assert isinstance(results, list)
        # 验证过滤条件
        if results:
            for node in results:
                law_name = node.node.metadata.get('law_name')
                if law_name:
                    assert law_name == '保险法'

    def test_keyword_search_exact_match(self, real_vector_index):
        """测试精确匹配"""
        # 搜索文档中的确切词汇
        results = keyword_search(
            real_vector_index,
            "等待期不得超过90天",
            top_k=3,
            avg_doc_len=50
        )

        assert isinstance(results, list)
        # 如果有结果，检查相关性
        if results:
            assert all(node.score > 0 for node in results)

    def test_keyword_search_no_match(self, real_vector_index):
        """测试无匹配结果"""
        results = keyword_search(
            real_vector_index,
            "不存在的特殊词汇xyz123",
            top_k=3,
            avg_doc_len=50
        )

        assert isinstance(results, list)
        # 无匹配时应该返回空列表或低分结果
        if results:
            assert all(node.score == 0 for node in results)


class TestHybridSearch:
    """测试混合检索"""

    def test_hybrid_search_with_real_index(self, real_vector_index):
        """测试使用真实索引的混合检索"""
        results = hybrid_search(
            real_vector_index,
            "健康保险等待期",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.5
        )

        assert isinstance(results, list)
        assert len(results) > 0

        # 验证结果格式
        for result in results:
            assert 'law_name' in result
            assert 'article_number' in result
            assert 'content' in result
            assert 'score' in result
            assert isinstance(result['score'], (int, float))

    def test_hybrid_search_alpha_weighting(self, real_vector_index):
        """测试alpha权重对混合检索的影响"""
        # 向量权重高
        results_vector = hybrid_search(
            real_vector_index,
            "保险",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.9
        )

        # 关键词权重高
        results_keyword = hybrid_search(
            real_vector_index,
            "保险",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.1
        )

        assert isinstance(results_vector, list)
        assert isinstance(results_keyword, list)

    def test_hybrid_search_with_filters(self, real_vector_index):
        """测试带过滤条件的混合检索"""
        results = hybrid_search(
            real_vector_index,
            "保险",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.5,
            filters={'category': '意外保险'}
        )

        assert isinstance(results, list)
        # 验证过滤条件
        if results:
            for result in results:
                assert result.get('category') == '意外保险'

    def test_hybrid_search_result_ranking(self, real_vector_index):
        """测试混合检索结果排序"""
        results = hybrid_search(
            real_vector_index,
            "保险费率",
            vector_top_k=5,
            keyword_top_k=5,
            alpha=0.5
        )

        assert isinstance(results, list)
        if len(results) > 1:
            # 验证结果按分数降序排列
            for i in range(len(results) - 1):
                assert results[i]['score'] >= results[i+1]['score']

    def test_hybrid_search_different_top_k(self, real_vector_index):
        """测试不同的top_k值"""
        for vk, kk in [(1, 1), (3, 2), (5, 10)]:
            results = hybrid_search(
                real_vector_index,
                "保险",
                vector_top_k=vk,
                keyword_top_k=kk,
                alpha=0.5
            )
            assert isinstance(results, list)

    def test_hybrid_search_no_index(self):
        """测试空索引的混合检索"""
        results = hybrid_search(
            None,
            "test query",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.5
        )
        assert results == []

    def test_hybrid_search_chinese_query(self, real_vector_index):
        """测试中文查询"""
        queries = [
            "健康保险等待期",
            "如实告知义务",
            "意外伤害保险期限",
            "保险费率",
            "保险期间"
        ]

        for query in queries:
            results = hybrid_search(
                real_vector_index,
                query,
                vector_top_k=3,
                keyword_top_k=3,
                alpha=0.5
            )
            assert isinstance(results, list)
            # 验证结果包含相关内容
            if results:
                assert all('content' in r for r in results)


class TestSearchQuality:
    """测试检索质量"""

    def test_retrieval_relevance(self, real_vector_index):
        """测试检索结果相关性"""
        # 搜索"等待期"相关内容
        results = hybrid_search(
            real_vector_index,
            "等待期",
            vector_top_k=3,
            keyword_top_k=3,
            alpha=0.5
        )

        if results:
            # 检查第一个结果是否包含相关关键词
            first_result = results[0]
            content = first_result['content'].lower()
            # 等待期相关内容应该包含相关词汇
            assert any(keyword in content for keyword in ['等待', '期', '天', '保险'])

    def test_retrieval_coverage(self, real_vector_index):
        """测试检索覆盖范围"""
        # 使用不同的查询词
        queries = ["保险", "费率", "期间", "如实告知"]

        all_results = set()
        for query in queries:
            results = hybrid_search(
                real_vector_index,
                query,
                vector_top_k=2,
                keyword_top_k=2,
                alpha=0.5
            )
            for result in results:
                all_results.add(result['article_number'])

        # 应该检索到不同的条款
        assert len(all_results) > 0
