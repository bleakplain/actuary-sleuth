#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果融合模块

使用 Reciprocal Rank Fusion (RRF) 融合向量检索和关键词检索的结果。
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    vector_nodes: List,
    keyword_nodes: List,
    k: int = 60
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion 融合两路检索结果

    Args:
        vector_nodes: 向量检索结果 (NodeWithScore list)
        keyword_nodes: 关键词检索结果 (NodeWithScore list)
        k: RRF 常数，默认 60

    Returns:
        List[Dict]: 融合后的结果列表，按 RRF 分数降序
    """
    if not vector_nodes and not keyword_nodes:
        return []

    rrf_scores: Dict[int, float] = {}
    nodes_map: Dict[int, Any] = {}

    for rank, node in enumerate(vector_nodes):
        node_id = id(node.node)
        rrf_scores[node_id] = rrf_scores.get(node_id, 0) + 1.0 / (k + rank + 1)
        nodes_map[node_id] = node.node

    for rank, node in enumerate(keyword_nodes):
        node_id = id(node.node)
        rrf_scores[node_id] = rrf_scores.get(node_id, 0) + 1.0 / (k + rank + 1)
        nodes_map[node_id] = node.node

    results = []
    for node_id, rrf_score in rrf_scores.items():
        node = nodes_map[node_id]
        results.append({
            'law_name': node.metadata.get('law_name', '未知'),
            'article_number': node.metadata.get('article_number', '未知'),
            'category': node.metadata.get('category', ''),
            'content': node.text,
            'score': rrf_score,
        })

    return sorted(results, key=lambda x: x['score'], reverse=True)
