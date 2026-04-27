#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精排器抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseReranker(ABC):
    """精排器统一接口"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...

    @staticmethod
    def _apply_scores(
        candidates: List[Dict[str, Any]],
        scores: List[float],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Annotate candidates with scores, sort descending, optionally truncate."""
        scored: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            item = dict(candidate)
            item["rerank_score"] = float(scores[idx])
            item["reranked"] = True
            scored.append(item)
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored
