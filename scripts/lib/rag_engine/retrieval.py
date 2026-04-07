#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索模块

负责向量检索和 BM25 关键词检索，以及 RRF 融合。
"""
import logging
from contextvars import copy_context
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from llama_index.core import QueryBundle
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.core.schema import NodeWithScore

from .fusion import reciprocal_rank_fusion
from .query_preprocessor import QueryPreprocessor
from lib.llm.trace import trace_span

logger = logging.getLogger(__name__)


def _run_with_ctx(fn, *args, **kwargs):
    """在子线程中复制当前 contextvars，确保 trace_span 传播。"""
    return copy_context().run(fn, *args, **kwargs)


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
    with trace_span("vector_search", "retrieval", top_k=top_k) as span:
        span.input = {"query": query_text, "top_k": top_k}
        metadata_filters = None
        if filters:
            filter_list = [
                ExactMatchFilter(key=k, value=v)
                for k, v in filters.items()
            ]
            metadata_filters = MetadataFilters(filters=filter_list)  # type: ignore[arg-type]

        vector_retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=metadata_filters
        )
        query_bundle = QueryBundle(query_str=query_text)
        results = vector_retriever.retrieve(query_bundle)
        span.output = {
            "result_count": len(results),
            "results": [
                {
                    "law_name": r.node.metadata.get("law_name", ""),
                    "article_number": r.node.metadata.get("article_number", ""),
                    "score": round(r.score, 4) if r.score is not None else None,
                    "content_preview": r.node.text[:200],
                }
                for r in results
            ],
        }
    return results


def _extract_node_info(node_with_score) -> Dict[str, Any]:
    """从 NodeWithScore 提取关键信息。"""
    node = node_with_score.node
    return {
        "law_name": node.metadata.get("law_name", ""),
        "article_number": node.metadata.get("article_number", ""),
        "score": round(node_with_score.score, 4) if node_with_score.score is not None else None,
        "content_preview": node.text[:200],
    }


def hybrid_search(
    index,
    bm25_index,
    query_text: str,
    vector_top_k: int,
    keyword_top_k: int,
    k: int = 60,
    filters: Optional[Dict[str, Any]] = None,
    preprocessor: Optional[QueryPreprocessor] = None,
    max_chunks_per_article: int = 3,
) -> List[Dict[str, Any]]:
    """混合检索（向量 + BM25 关键词，RRF 融合 + Query 预处理）"""
    if not index or not bm25_index:
        return []

    pp = preprocessor or _get_default_preprocessor()
    preprocessed = pp.preprocess(query_text)

    with trace_span("hybrid_search", "retrieval") as span:
        span.input = {
            "original_query": query_text,
            "normalized_query": preprocessed.normalized,
            "did_expand": preprocessed.did_expand,
            "expanded": preprocessed.expanded if preprocessed.did_expand else [],
            "vector_top_k": vector_top_k,
            "keyword_top_k": keyword_top_k,
        }
        span.metadata = {
            "vector_top_k": vector_top_k,
            "keyword_top_k": keyword_top_k,
            "rrf_k": k,
            "max_chunks_per_article": max_chunks_per_article,
        }

        # 按查询分组记录检索结果
        per_query_results: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_vector = executor.submit(
                _run_with_ctx, vector_search, index, preprocessed.normalized, vector_top_k, filters
            )
            future_keyword = executor.submit(
                bm25_index.search, preprocessed.normalized, top_k=keyword_top_k, filters=filters
            )

            vector_nodes = future_vector.result()
            keyword_results = future_keyword.result()

        keyword_nodes = _to_node_with_scores(keyword_results)
        per_query_results.append({
            "query": preprocessed.normalized,
            "label": "主查询",
            "vector_count": len(vector_nodes),
            "keyword_count": len(keyword_nodes),
            "vector_top": [_extract_node_info(n) for n in vector_nodes[:5]],
            "keyword_top": [
                {
                    "law_name": n.node.metadata.get("law_name", ""),
                    "article_number": n.node.metadata.get("article_number", ""),
                    "score": round(n.score, 4) if n.score is not None else None,
                    "content_preview": n.node.text[:200],
                }
                for n in keyword_nodes[:5]
            ],
        })

        if preprocessed.did_expand:
            expanded_queries = preprocessed.expanded[1:]
            if expanded_queries:
                vector_futures = []
                keyword_futures = []
                with ThreadPoolExecutor(max_workers=min(8, 2 * len(expanded_queries))) as executor:
                    for expanded_query in expanded_queries:
                        vector_futures.append(
                            executor.submit(_run_with_ctx, vector_search, index, expanded_query, vector_top_k, filters)
                        )
                        keyword_futures.append(
                            executor.submit(bm25_index.search, expanded_query, top_k=keyword_top_k, filters=filters)
                        )
                for i, fv in enumerate(vector_futures):
                    exp_nodes = fv.result()
                    vector_nodes.extend(exp_nodes)
                    per_query_results.append({
                        "query": expanded_queries[i],
                        "label": f"扩写 {i + 1}",
                        "vector_count": len(exp_nodes),
                        "vector_top": [_extract_node_info(n) for n in exp_nodes[:5]],
                    })
                for i, fk in enumerate(keyword_futures):
                    exp_kw = _to_node_with_scores(fk.result())
                    keyword_nodes.extend(exp_kw)
                    per_query_results[-1 - len(keyword_futures) + i]["keyword_count"] = len(exp_kw)
                    per_query_results[-1 - len(keyword_futures) + i]["keyword_top"] = [
                        {
                            "law_name": n.node.metadata.get("law_name", ""),
                            "article_number": n.node.metadata.get("article_number", ""),
                            "score": round(n.score, 4) if n.score is not None else None,
                            "content_preview": n.node.text[:200],
                        }
                        for n in exp_kw[:5]
                    ]

        fusion_results = reciprocal_rank_fusion(
            vector_nodes, keyword_nodes, k=k,
            max_chunks_per_article=max_chunks_per_article,
        )

        span.output = {
            "fusion_result_count": len(fusion_results),
            "vector_result_count": len(vector_nodes),
            "keyword_result_count": len(keyword_nodes),
            "per_query_results": per_query_results,
            "fusion_results": [
                {
                    "law_name": r.get("law_name", ""),
                    "article_number": r.get("article_number", ""),
                    "score": round(r.get("score", 0), 4),
                    "content_preview": r.get("content", "")[:200],
                }
                for r in fusion_results[:10]
            ],
        }
        return fusion_results

    return []
