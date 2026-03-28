#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rerank 精排模块

使用 LLM 批量排序方式做精排，单次调用完成所有候选的排序。
"""
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BATCH_RERANK_PROMPT = """请根据用户问题，对以下法规条款按相关性从高到低排序。

## 用户问题
{query}

## 法规条款列表
{candidates}

## 排序要求
请直接输出排序后的编号，从最相关到最不相关，用逗号分隔。
只输出编号，不要输出其他内容。

示例输出：2,5,1,4,3"""


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

        ranked_indices = self._batch_rank(query, candidates)
        if not ranked_indices:
            return candidates[:top_k]

        results: List[Dict[str, Any]] = []
        for rank, idx in enumerate(ranked_indices[:top_k]):
            candidate = candidates[idx]
            result = dict(candidate)
            result['rerank_score'] = 1.0 / (rank + 1)
            results.append(result)

        return results

    def _batch_rank(self, query: str, candidates: List[Dict[str, Any]]) -> List[int]:
        parts = []
        for i, candidate in enumerate(candidates, 1):
            content = candidate.get('content', '')
            law_name = candidate.get('law_name', '')
            article = candidate.get('article_number', '')
            truncated = content[:800] if len(content) > 800 else content
            parts.append(f"[{i}] 【{law_name}】{article}\n{truncated}")

        prompt = _BATCH_RERANK_PROMPT.format(
            query=query,
            candidates="\n\n".join(parts),
        )

        try:
            response = self._llm.generate(prompt)
            return self._parse_ranking(str(response).strip(), len(candidates))
        except Exception as e:
            logger.warning(f"Rerank 批量排序失败: {e}")
            return list(range(len(candidates)))

    @staticmethod
    def _parse_ranking(response: str, total: int) -> List[int]:
        numbers = re.findall(r'\d+', response)
        result: List[int] = []
        seen: set[int] = set()
        for num_str in numbers:
            num = int(num_str)
            if 1 <= num <= total:
                idx = num - 1
                if idx not in seen:
                    result.append(idx)
                    seen.add(idx)

        for i in range(total):
            if i not in seen:
                result.append(i)

        return result
