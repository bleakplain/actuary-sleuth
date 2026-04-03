#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用解析和归因模块

解析 LLM 回答中的引用标注，建立句子→来源映射。
"""
import re
import logging
from typing import List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_SOURCE_TAG_PATTERN = re.compile(r'\[来源(\d+)\]')

_FACTUAL_PATTERNS = [
    re.compile(r'\d+天'),
    re.compile(r'\d+年'),
    re.compile(r'\d+个月'),
    re.compile(r'\d+%'),
    re.compile(r'\d+元'),
    re.compile(r'\d+万元'),
    re.compile(r'\d+周岁'),
    re.compile(r'第[一二三四五六七八九十百千\d]+条'),
    re.compile(r'《[^》]+》'),
    re.compile(r'(必须|应当|不得|禁止|严禁|不得以)'),
    re.compile(r'(有权|无权|免除|承担)'),
    re.compile(r'\d{4}年\d{1,2}月'),
    re.compile(r'\d{4}年'),
    re.compile(r'(赔偿|赔付|给付|退还|返还)\s*\d+'),
]


@dataclass(frozen=True)
class Citation:
    """单条引用"""
    source_idx: int
    law_name: str
    article_number: str
    content: str
    confidence: str = 'tagged'


@dataclass(frozen=True)
class AttributionResult:
    """归因分析结果"""
    citations: List[Citation] = field(default_factory=list)
    unverified_claims: List[str] = field(default_factory=list)
    uncited_sources: List[int] = field(default_factory=list)


def parse_citations(
    answer: str,
    sources: List[Dict[str, Any]],
) -> AttributionResult:
    """解析 LLM 回答中的引用标注"""
    if not answer or not sources:
        return AttributionResult()

    cited_indices: set[int] = set()
    citations: List[Citation] = []

    for match in _SOURCE_TAG_PATTERN.finditer(answer):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(sources):
            cited_indices.add(idx)
            source = sources[idx]
            citations.append(Citation(
                source_idx=idx,
                law_name=source.get('law_name', '未知'),
                article_number=source.get('article_number', '未知'),
                content=source.get('content', ''),
            ))

    all_indices = set(range(len(sources)))
    uncited = sorted(all_indices - cited_indices)

    unverified = _detect_unverified_claims(answer)

    return AttributionResult(
        citations=citations,
        unverified_claims=unverified,
        uncited_sources=uncited,
    )


def _detect_unverified_claims(answer: str) -> List[str]:
    if not answer:
        return []

    tag_matches = list(_SOURCE_TAG_PATTERN.finditer(answer))
    if not tag_matches:
        for pattern in _FACTUAL_PATTERNS:
            if pattern.search(answer):
                return [answer.strip()]
        return []

    last_tag_end = tag_matches[-1].end()
    if last_tag_end >= len(answer):
        return []

    tail = answer[last_tag_end:].strip()
    if not tail or len(tail) < 5 or tail[-1].isdigit():
        return []

    for pattern in _FACTUAL_PATTERNS:
        if pattern.search(tail):
            return [tail]

    return []

