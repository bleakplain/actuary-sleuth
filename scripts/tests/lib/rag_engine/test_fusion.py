#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 fusion 模块 - RRF 融合
"""
import pytest

from lib.rag_engine.fusion import reciprocal_rank_fusion


class TestReciprocalRankFusion:

    def test_fuse_empty_results(self):
        result = reciprocal_rank_fusion([], [])
        assert result == []

    def test_fuse_single_list(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc = Document(
            text="测试内容",
            metadata={'law_name': '测试法规', 'article_number': '第一条', 'category': '测试'}
        )
        nodes = [NodeWithScore(node=doc, score=0.9)]
        result = reciprocal_rank_fusion(nodes, [])

        assert len(result) == 1
        assert result[0]['law_name'] == '测试法规'
        assert result[0]['score'] > 0

    def test_fuse_overlapping_results(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc = Document(
            text="共同结果",
            metadata={'law_name': '保险法', 'article_number': '第十条', 'category': '通用'}
        )
        vector_nodes = [NodeWithScore(node=doc, score=0.9)]
        keyword_nodes = [NodeWithScore(node=doc, score=0.8)]

        result = reciprocal_rank_fusion(vector_nodes, keyword_nodes)

        assert len(result) == 1
        # RRF: rank 1 in both lists => 1/(k+1) + 1/(k+1) = 2/(k+1)
        assert result[0]['score'] > 0

    def test_fuse_non_overlapping_results(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc1 = Document(
            text="向量结果",
            metadata={'law_name': '法规A', 'article_number': '第一条', 'category': 'A'}
        )
        doc2 = Document(
            text="关键词结果",
            metadata={'law_name': '法规B', 'article_number': '第二条', 'category': 'B'}
        )

        vector_nodes = [NodeWithScore(node=doc1, score=0.9)]
        keyword_nodes = [NodeWithScore(node=doc2, score=0.8)]

        result = reciprocal_rank_fusion(vector_nodes, keyword_nodes)

        assert len(result) == 2
        # Both should have the same RRF score (rank 1 in their respective list)
        assert result[0]['score'] == result[1]['score']

    def test_fuse_ranking(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        docs = [
            Document(text=f"内容{i}", metadata={'law_name': f'法规{i}', 'article_number': f'第{i}条', 'category': '测试'})
            for i in range(5)
        ]
        nodes = [NodeWithScore(node=docs[i], score=1.0 - i * 0.1) for i in range(5)]

        result = reciprocal_rank_fusion(nodes, [])
        assert len(result) == 5
        # Results should be sorted by RRF score descending
        for i in range(len(result) - 1):
            assert result[i]['score'] >= result[i + 1]['score']

    def test_fuse_custom_k(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc = Document(
            text="测试",
            metadata={'law_name': '测试', 'article_number': '第一条', 'category': '测试'}
        )
        nodes = [NodeWithScore(node=doc, score=0.9)]

        result_k60 = reciprocal_rank_fusion(nodes, [], k=60)
        result_k5 = reciprocal_rank_fusion(nodes, [], k=5)

        # Smaller k => larger RRF score for same rank
        assert result_k5[0]['score'] > result_k60[0]['score']

    def test_fuse_result_format(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc = Document(
            text="格式测试",
            metadata={'law_name': '测试法规', 'article_number': '第一条', 'category': '测试'}
        )
        nodes = [NodeWithScore(node=doc, score=0.9)]

        result = reciprocal_rank_fusion(nodes, [])

        assert 'law_name' in result[0]
        assert 'article_number' in result[0]
        assert 'category' in result[0]
        assert 'content' in result[0]
        assert 'score' in result[0]
        assert isinstance(result[0]['score'], float)

    def test_deduplicate_keeps_top_two(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        doc1 = Document(
            text="等待期90天部分",
            metadata={'law_name': '健康保险', 'article_number': '第一条', 'category': '健康'}
        )
        doc2 = Document(
            text="等待期例外情况部分",
            metadata={'law_name': '健康保险', 'article_number': '第一条', 'category': '健康'}
        )
        doc3 = Document(
            text="其他法规内容",
            metadata={'law_name': '保险法', 'article_number': '第十条', 'category': '通用'}
        )
        doc4 = Document(
            text="等待期第三部分",
            metadata={'law_name': '健康保险', 'article_number': '第一条', 'category': '健康'}
        )

        nodes = [
            NodeWithScore(node=doc1, score=0.9),
            NodeWithScore(node=doc2, score=0.7),
            NodeWithScore(node=doc3, score=0.5),
            NodeWithScore(node=doc4, score=0.3),
        ]

        result = reciprocal_rank_fusion(nodes, [], max_chunks_per_article=2)
        same_article = [r for r in result if r['article_number'] == '第一条']
        assert len(same_article) == 2
        assert len(result) == 3

    def test_max_chunks_per_article_custom_limit(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        docs = [
            Document(
                text=f"内容{i}",
                metadata={'law_name': '保险法', 'article_number': '第十条', 'category': '通用'}
            )
            for i in range(5)
        ]
        nodes = [NodeWithScore(node=d, score=1.0 - i * 0.1) for i, d in enumerate(docs)]

        result = reciprocal_rank_fusion(nodes, [], max_chunks_per_article=1)
        same_article = [r for r in result if r['article_number'] == '第十条']
        assert len(same_article) == 1

    def test_max_chunks_per_article_zero_keeps_all(self):
        from llama_index.core import Document
        from llama_index.core.schema import NodeWithScore

        docs = [
            Document(
                text=f"内容{i}",
                metadata={'law_name': '保险法', 'article_number': '第十条', 'category': '通用'}
            )
            for i in range(3)
        ]
        nodes = [NodeWithScore(node=d, score=1.0 - i * 0.1) for i, d in enumerate(docs)]

        result = reciprocal_rank_fusion(nodes, [], max_chunks_per_article=0)
        assert len(result) == 3
