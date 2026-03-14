#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检索模块

负责向量检索和关键词检索。
"""
import logging
from typing import List, Dict, Any, Optional

from llama_index.core import QueryBundle
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.core.schema import NodeWithScore

from .fusion import compute_bm25_score, fuse_results
from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)


def vector_search(
    index,
    query_text: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None
) -> List:
    """
    向量检索

    Args:
        index: 向量索引
        query_text: 查询文本
        top_k: 返回结果数量
        filters: 元数据过滤条件

    Returns:
        List: 向量检索结果
    """
    metadata_filters = None
    if filters:
        filter_list = [
            ExactMatchFilter(key=k, value=v)
            for k, v in filters.items()
        ]
        metadata_filters = MetadataFilters(filters=filter_list)

    vector_retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=metadata_filters
    )
    query_bundle = QueryBundle(query_str=query_text)
    return vector_retriever.retrieve(query_bundle)


def keyword_search(
    index,
    query_text: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None,
    avg_doc_len: float = 100
) -> List:
    """
    BM25 关键词检索

    Args:
        index: 向量索引
        query_text: 查询文本
        top_k: 返回结果数量
        filters: 元数据过滤条件
        avg_doc_len: 平均文档长度

    Returns:
        List: 关键词检索结果
    """
    all_nodes = list(index.docstore.docs.values())

    if filters:
        all_nodes = [
            node for node in all_nodes
            if all(node.metadata.get(k) == v for k, v in filters.items())
        ]

    query_tokens = tokenize_chinese(query_text)

    scores = []
    for node in all_nodes:
        node_tokens = tokenize_chinese(node.text)
        score = compute_bm25_score(query_tokens, node_tokens, avg_doc_len)
        scores.append((node, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return [
        NodeWithScore(node=node, score=score)
        for node, score in scores[:top_k] if score > 0
    ]


def hybrid_search(
    index,
    query_text: str,
    vector_top_k: int,
    keyword_top_k: int,
    alpha: float,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    混合检索（向量 + 关键词）

    Args:
        index: 向量索引
        query_text: 查询文本
        vector_top_k: 向量检索返回数量
        keyword_top_k: 关键词检索返回数量
        alpha: 向量检索权重
        filters: 元数据过滤条件

    Returns:
        List[Dict]: 融合后的结果列表
    """
    if not index:
        return []

    # 向量检索
    vector_nodes = vector_search(index, query_text, vector_top_k, filters)

    # 关键词检索
    keyword_nodes = keyword_search(index, query_text, keyword_top_k, filters)

    # 融合结果
    return fuse_results(vector_nodes, keyword_nodes, alpha)
