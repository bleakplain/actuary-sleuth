#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pytest
from typing import List, Dict, Any, Optional

from lib.rag_engine.reranker_base import BaseReranker


class _FakeReranker(BaseReranker):
    """测试用精排器实现"""

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        scored = [
            dict(c, rerank_score=len(c.get('content', '')))
            for c in candidates
        ]
        scored.sort(key=lambda x: x['rerank_score'], reverse=True)
        return scored[:top_k] if top_k else scored


def test_cannot_instantiate_base():
    with pytest.raises(TypeError):
        BaseReranker()


def test_concrete_implementation_rerank():
    reranker = _FakeReranker()
    candidates = [
        {'content': 'short', 'law_name': 'A'},
        {'content': 'a much longer content', 'law_name': 'B'},
    ]
    results = reranker.rerank('test', candidates)

    assert len(results) == 2
    assert results[0]['content'] == 'a much longer content'
    assert results[0]['rerank_score'] == 21


def test_concrete_implementation_top_k():
    reranker = _FakeReranker()
    candidates = [
        {'content': f'item {i}', 'law_name': 'A'}
        for i in range(5)
    ]
    results = reranker.rerank('test', candidates, top_k=2)
    assert len(results) == 2


def test_concrete_implementation_empty():
    reranker = _FakeReranker()
    assert reranker.rerank('test', []) == []
