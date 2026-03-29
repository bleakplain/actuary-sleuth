#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fusion 模块单元测试"""
import pytest
from llama_index.core.schema import NodeWithScore, TextNode
from lib.rag_engine.fusion import reciprocal_rank_fusion


def _make_node(node_id: str, text: str, law_name: str, article: str) -> NodeWithScore:
    node = TextNode(
        text=text,
        metadata={'law_name': law_name, 'article_number': article, 'category': '测试'},
    )
    node.node_id = node_id
    return NodeWithScore(node=node, score=0.9)


class TestReciprocalRankFusion:

    def test_empty_inputs(self):
        result = reciprocal_rank_fusion([], [])
        assert result == []

    def test_vector_only(self):
        nodes = [
            _make_node('v1', '等待期规定', '健康险', '第一条'),
            _make_node('v2', '如实告知', '保险法', '第十六条'),
        ]
        result = reciprocal_rank_fusion(nodes, [])
        assert len(result) == 2
        assert result[0]['law_name'] == '健康险'

    def test_keyword_only(self):
        nodes = [
            _make_node('k1', '等待期规定', '健康险', '第一条'),
        ]
        result = reciprocal_rank_fusion([], nodes)
        assert len(result) == 1

    def test_dedup_by_article(self):
        nodes = [
            _make_node('v1', '等待期不超过90天', '健康险', '第一条'),
            _make_node('v2', '等待期不超过180天', '健康险', '第一条'),
            _make_node('v3', '等待期不超过365天', '健康险', '第一条'),
            _make_node('v4', '等待期不超过500天', '健康险', '第一条'),
        ]
        result = reciprocal_rank_fusion(nodes, [], max_chunks_per_article=3)
        health_articles = [
            r for r in result
            if r['law_name'] == '健康险' and r['article_number'] == '第一条'
        ]
        assert len(health_articles) <= 3

    def test_weighted_fusion(self):
        v_nodes = [_make_node('v1', '向量结果', '法规A', '第一条')]
        k_nodes = [_make_node('k1', '关键词结果', '法规A', '第一条')]

        result_equal = reciprocal_rank_fusion(
            v_nodes, k_nodes, vector_weight=1.0, keyword_weight=1.0
        )
        result_vector = reciprocal_rank_fusion(
            v_nodes, k_nodes, vector_weight=2.0, keyword_weight=0.5
        )

        assert result_equal[0]['score'] != result_vector[0]['score']

    def test_result_structure(self):
        nodes = [_make_node('v1', '内容', '法规A', '第一条')]
        result = reciprocal_rank_fusion(nodes, [])

        assert 'law_name' in result[0]
        assert 'article_number' in result[0]
        assert 'content' in result[0]
        assert 'score' in result[0]
        assert 'source_file' in result[0]
        assert 'category' in result[0]

    def test_sorted_by_score(self):
        nodes = [
            _make_node('v1', '内容1', '法规A', '第一条'),
            _make_node('v2', '内容2', '法规B', '第二条'),
            _make_node('v3', '内容3', '法规C', '第三条'),
        ]
        result = reciprocal_rank_fusion(nodes, [])

        scores = [r['score'] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_overlapping_results(self):
        same_node = _make_node('s1', '共享内容', '法规A', '第一条')
        result = reciprocal_rank_fusion([same_node], [same_node])
        assert len(result) == 1
        assert result[0]['score'] > 0
