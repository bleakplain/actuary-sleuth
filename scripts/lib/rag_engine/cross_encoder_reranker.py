#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-encoder reranker using sentence-transformers"""
import logging
from typing import List, Dict, Any, Optional

from .reranker_base import BaseReranker

logger = logging.getLogger(__name__)


class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker using sentence-transformers CrossEncoder"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        model_path: Optional[str] = None,
        max_length: int = 1024,
    ):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for CrossEncoderReranker. "
                "Install with: pip install sentence-transformers"
            )

        self._model_name = model_name
        self._max_length = max_length

        if model_path:
            self._model = CrossEncoder(model_path, max_length=max_length)
        else:
            self._model = CrossEncoder(model_name, max_length=max_length)

        logger.info(f"CrossEncoderReranker initialized: {model_name}")

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        texts = [c.get("content", "") for c in candidates]
        pairs = [[query, text] for text in texts]

        scores = self._model.predict(pairs, show_progress_bar=False)

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
