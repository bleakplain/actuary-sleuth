#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GGUF Reranker

基于 Jina Reranker v3 GGUF 模型的精排器，实现 BaseReranker 接口。
运行时失败时抛出 RerankerError，由调用方决定是否回退到其他精排策略。
"""
import logging
from typing import List, Dict, Any, Optional

from .reranker_base import BaseReranker

logger = logging.getLogger(__name__)


class RerankerError(Exception):
    """精排器运行时错误，用于触发回退逻辑。"""
    pass


class GGUFReranker(BaseReranker):
    """GGUF Reranker 精排器实现"""

    def __init__(self, gguf_reranker):
        self._reranker = gguf_reranker

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        documents = [c.get('content', '') for c in candidates]

        try:
            rerank_results = self._reranker.rerank(
                query=query,
                documents=documents,
                top_n=top_k,
            )
        except Exception as e:
            raise RerankerError(f"GGUF reranker 精排失败: {e}") from e

        results: List[Dict[str, Any]] = []
        for item in rerank_results:
            idx = item['index']
            candidate = dict(candidates[idx])
            candidate['rerank_score'] = item['relevance_score']
            candidate['reranked'] = True
            results.append(candidate)

        return results
