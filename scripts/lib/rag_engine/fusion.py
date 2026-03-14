#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果融合模块

负责融合向量检索和关键词检索的结果。
"""
import logging
from typing import List, Dict, Any

from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)


def _normalize_scores(scores: List[float]) -> List[float]:
    """归一化分数到 [0, 1]"""
    if not scores:
        return []
    max_score = max(scores)
    min_score = min(scores)
    if max_score == min_score:
        return [1.0] * len(scores)
    return [(s - min_score) / (max_score - min_score) for s in scores]


def compute_bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    avg_doc_len: float = 100
) -> float:
    """
    计算 BM25 分数

    Args:
        query_tokens: 查询分词
        doc_tokens: 文档分词
        avg_doc_len: 平均文档长度

    Returns:
        float: BM25 分数
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    k1 = 1.5
    b = 0.75

    doc_len = len(doc_tokens)
    doc_freq = {}
    for token in doc_tokens:
        doc_freq[token] = doc_freq.get(token, 0) + 1

    score = 0.0
    for token in query_tokens:
        if token in doc_freq:
            tf = doc_freq[token]
            idf = 1.0
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))

    return score


def fuse_results(
    vector_nodes: List,
    keyword_nodes: List,
    alpha: float
) -> List[Dict[str, Any]]:
    """
    融合向量检索和关键词检索结果

    Args:
        vector_nodes: 向量检索结果
        keyword_nodes: 关键词检索结果
        alpha: 向量检索权重

    Returns:
        List[Dict]: 融合后的结果列表
    """
    # 归一化分数
    vector_scores = _normalize_scores([n.score for n in vector_nodes])
    keyword_scores = _normalize_scores([n.score for n in keyword_nodes])

    # 合并结果
    merged = {}

    for node, norm_score in zip(vector_nodes, vector_scores):
        node_id = id(node.node)
        merged[node_id] = {
            'node': node.node,
            'vector_score': norm_score,
            'keyword_score': 0.0,
        }

    for node, norm_score in zip(keyword_nodes, keyword_scores):
        node_id = id(node.node)
        if node_id in merged:
            merged[node_id]['keyword_score'] = norm_score
        else:
            merged[node_id] = {
                'node': node.node,
                'vector_score': 0.0,
                'keyword_score': norm_score,
            }

    # 计算融合分数并格式化结果
    results = []
    for item in merged.values():
        fused_score = alpha * item['vector_score'] + (1 - alpha) * item['keyword_score']
        node = item['node']
        results.append({
            'law_name': node.metadata.get('law_name', '未知'),
            'article_number': node.metadata.get('article_number', '未知'),
            'category': node.metadata.get('category', ''),
            'content': node.text,
            'score': fused_score
        })

    return sorted(results, key=lambda x: x['score'], reverse=True)
