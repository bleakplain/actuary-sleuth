#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检索模块

负责向量检索和 BM25 关键词检索，以及 RRF 融合。
"""
import logging
from typing import List, Dict, Any, Optional

from llama_index.core import QueryBundle
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.core.schema import NodeWithScore

from .fusion import reciprocal_rank_fusion

logger = logging.getLogger(__name__)


def vector_search(
    index,
    query_text: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None
) -> List:
    """向量检索

    Args:
        index: 向量索引
        query_text: 查询文本
        top_k: 返回结果数量
        filters: 元数据过滤条件

    Returns:
        List: 向量检索结果 (NodeWithScore)
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


def hybrid_search(
    index,
    bm25_index,
    query_text: str,
    vector_top_k: int,
    keyword_top_k: int,
    k: int = 60,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """混合检索（向量 + BM25 关键词，RRF 融合）

    Args:
        index: 向量索引
        bm25_index: BM25Index 实例
        query_text: 查询文本
        vector_top_k: 向量检索返回数量
        keyword_top_k: 关键词检索返回数量
        k: RRF 常数，默认 60
        filters: 元数据过滤条件

    Returns:
        List[Dict]: RRF 融合后的结果列表
    """
    if not index or not bm25_index:
        return []

    vector_nodes = vector_search(index, query_text, vector_top_k, filters)
    keyword_results = bm25_index.search(query_text, top_k=keyword_top_k, filters=filters)

    keyword_nodes = [
        NodeWithScore(node=node, score=score)
        for node, score in keyword_results
    ]

    return reciprocal_rank_fusion(vector_nodes, keyword_nodes, k=k)
