#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果融合模块

使用 Reciprocal Rank Fusion (RRF) 融合向量检索和关键词检索的结果。
"""
import hashlib
from collections import defaultdict
from typing import List, Dict, Any

from llama_index.core.schema import NodeWithScore


def _chunk_key(scored: NodeWithScore) -> str:
    if scored.node.node_id:
        return scored.node.node_id
    content = scored.node.get_content() or ''
    source = scored.node.metadata.get('source_file', '')
    content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:12]
    return f"{source}:{content_hash}"


def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60,
    max_chunks_per_article: int = 3,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion 融合两路检索结果

    Args:
        vector_results: 向量检索结果
        keyword_results: 关键词检索结果
        k: RRF 常数，默认 60
        max_chunks_per_article: 每条款最大 chunk 数，默认 3

    Returns:
        List[Dict]: 融合后的结果列表，按 RRF 分数降序
    """
    if not vector_results and not keyword_results:
        return []

    scores: Dict[str, float] = defaultdict(float)
    chunks = {}

    for rank, scored in enumerate(vector_results):
        key = _chunk_key(scored)
        scores[key] += 1.0 / (k + rank + 1)
        chunks[key] = scored.node

    for rank, scored in enumerate(keyword_results):
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
            'content': chunk.text,  # type: ignore[attr-defined]
            'source_file': chunk.metadata.get('source_file', ''),
            'hierarchy_path': chunk.metadata.get('hierarchy_path', ''),
            'doc_number': chunk.metadata.get('doc_number', ''),
            'effective_date': chunk.metadata.get('effective_date', ''),
            'issuing_authority': chunk.metadata.get('issuing_authority', ''),
            'score': rrf_score,
        })

    results = _deduplicate_by_article(results, max_chunks_per_article)
    return sorted(results, key=lambda x: x['score'], reverse=True)


def _deduplicate_by_article(
    results: List[Dict[str, Any]],
    max_chunks: int = 3,
) -> List[Dict[str, Any]]:
    """按法规名称+条款号去重，每条款保留至多 max_chunks 个 chunk"""
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', ''))
        grouped.setdefault(key, []).append(r)

    deduped = []
    for chunks in grouped.values():
        chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
        if max_chunks > 0:
            deduped.extend(chunks[:max_chunks])
        else:
            deduped.extend(chunks)

    return deduped
