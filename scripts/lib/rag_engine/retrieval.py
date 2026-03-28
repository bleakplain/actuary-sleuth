#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索模块

负责向量检索和 BM25 关键词检索，以及 RRF 融合。
"""
import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from llama_index.core import QueryBundle
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.core.schema import NodeWithScore

from .fusion import reciprocal_rank_fusion
from .query_preprocessor import QueryPreprocessor

logger = logging.getLogger(__name__)


def _to_node_with_scores(bm25_results: List) -> List[NodeWithScore]:
    return [NodeWithScore(node=node, score=score) for node, score in bm25_results]

_default_preprocessor: Optional[QueryPreprocessor] = None


def _get_default_preprocessor() -> QueryPreprocessor:
    global _default_preprocessor
    if _default_preprocessor is None:
        _default_preprocessor = QueryPreprocessor()
    return _default_preprocessor


def vector_search(
    index,
    query_text: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None
) -> List:
    """向量检索"""
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
    filters: Optional[Dict[str, Any]] = None,
    preprocessor: QueryPreprocessor = None,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> List[Dict[str, Any]]:
    """混合检索（向量 + BM25 关键词，RRF 融合 + Query 预处理）"""
    if not index or not bm25_index:
        return []

    pp = preprocessor or _get_default_preprocessor()
    preprocessed = pp.preprocess(query_text)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_vector = executor.submit(
            vector_search, index, preprocessed.normalized, vector_top_k, filters
        )
        future_keyword = executor.submit(
            bm25_index.search, preprocessed.normalized, top_k=keyword_top_k, filters=filters
        )

        vector_nodes = future_vector.result()
        keyword_results = future_keyword.result()

    keyword_nodes = _to_node_with_scores(keyword_results)

    if preprocessed.did_expand:
        expanded_queries = preprocessed.expanded[1:]
        if expanded_queries:
            vector_futures = []
            keyword_futures = []
            with ThreadPoolExecutor(max_workers=min(8, 2 * len(expanded_queries))) as executor:
                for expanded_query in expanded_queries:
                    vector_futures.append(
                        executor.submit(vector_search, index, expanded_query, vector_top_k, filters)
                    )
                    keyword_futures.append(
                        executor.submit(bm25_index.search, expanded_query, top_k=keyword_top_k, filters=filters)
                    )
            for fv in vector_futures:
                vector_nodes.extend(fv.result())
            for fk in keyword_futures:
                keyword_nodes.extend(_to_node_with_scores(fk.result()))

    return reciprocal_rank_fusion(
        vector_nodes, keyword_nodes, k=k,
        vector_weight=vector_weight, keyword_weight=keyword_weight,
    )
