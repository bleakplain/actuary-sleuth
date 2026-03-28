#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果融合模块

使用 Reciprocal Rank Fusion (RRF) 融合向量检索和关键词检索的结果。
"""
from collections import defaultdict
from typing import List, Dict, Any

from llama_index.core.schema import NodeWithScore


def _chunk_key(scored: NodeWithScore) -> str:
    """生成 chunk 的稳定标识"""
    return scored.node.node_id if scored.node.node_id else str(id(scored.node))


def _deduplicate_by_article(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按法规名称+条款号去重，保留 RRF 分数最高的"""
    seen: Dict[tuple, Dict[str, Any]] = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', ''))
        if key not in seen or r.get('score', 0) > seen[key].get('score', 0):
            seen[key] = r
    return list(seen.values())


def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion 融合两路检索结果

    Args:
        vector_results: 向量检索结果
        keyword_results: 关键词检索结果
        k: RRF 常数，默认 60

    Returns:
        List[Dict]: 融合后的结果列表，按 RRF 分数降序
    """
    if not vector_results and not keyword_results:
        return []

    scores: Dict[str, float] = defaultdict(float)
    chunks = {}

    for result_list in (vector_results, keyword_results):
        for rank, scored in enumerate(result_list):
            key = _chunk_key(scored)
            scores[key] += 1.0 / (k + rank + 1)
            chunks[key] = scored.node

    results = []
    for key, rrf_score in scores.items():
        chunk = chunks[key]
        results.append({
            'law_name': chunk.metadata.get('law_name', '未知'),
            'article_number': chunk.metadata.get('article_number', '未知'),
            'category': chunk.metadata.get('category', ''),
            'content': chunk.text,
            'source_file': chunk.metadata.get('source_file', ''),
            'hierarchy_path': chunk.metadata.get('hierarchy_path', ''),
            'score': rrf_score,
        })

    results = _deduplicate_by_article(results)
    return sorted(results, key=lambda x: x['score'], reverse=True)
