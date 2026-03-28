#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rerank 精排模块

使用 LLM-as-Judge 方式做精排，复用现有 LLM 客户端。
后续可替换为 Cross-Encoder 实现（sentence-transformers）。
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_RERANK_PROMPT_TEMPLATE = """请评估以下法规条款与用户问题的相关性。

## 用户问题
{query}

## 法规条款
{content}

## 评分标准
- 3: 直接相关，条款明确回答了用户问题
- 2: 间接相关，条款包含相关信息但不是直接回答
- 1: 弱相关，条款仅提及部分关键词
- 0: 不相关

请只输出一个数字评分（0-3），不要输出其他内容。"""


@dataclass(frozen=True)
class RerankConfig:
    enabled: bool = True
    top_k: int = 5
    max_candidates: int = 20


class LLMReranker:

    def __init__(self, llm_client, config: Optional[RerankConfig] = None):
        self._llm = llm_client
        self._config = config or RerankConfig()

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not self._config.enabled or not candidates:
            return candidates[:top_k] if top_k else candidates

        top_k = top_k or self._config.top_k
        candidates = candidates[:self._config.max_candidates]

        scored = []
        for candidate in candidates:
            score = self._score_relevance(query, candidate)
            scored.append((candidate, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: List[Dict[str, Any]] = []
        for candidate, rerank_score in scored[:top_k]:
            result = dict(candidate)
            result['rerank_score'] = rerank_score
            results.append(result)

        return results

    def _score_relevance(self, query: str, candidate: Dict[str, Any]) -> float:
        content = candidate.get('content', '')
        if len(content) > 500:
            content = content[:500] + "..."

        prompt = _RERANK_PROMPT_TEMPLATE.format(query=query, content=content)

        try:
            response = self._llm.generate(prompt)
            score = self._parse_score(str(response).strip())
            return score
        except Exception as e:
            logger.warning(f"Rerank 打分失败: {e}")
            return 0.0

    @staticmethod
    def _parse_score(response: str) -> float:
        response = response.strip()
        for char in response:
            if char in '0123':
                return float(char)
        return 0.0
