#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引用解析和归因模块

解析 LLM 回答中的引用标注，建立句子→来源映射。
"""
import math
import re
import logging
from typing import List, Dict, Any, Optional, Tuple, Callable
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

    unverified = _detect_unverified_claims(answer, cited_indices)

    return AttributionResult(
        citations=citations,
        unverified_claims=unverified,
        uncited_sources=uncited,
    )


def _detect_unverified_claims(
    answer: str,
    cited_indices: set[int],
) -> List[str]:
    """检测未被引用标注覆盖的事实性陈述"""
    if not answer:
        return []

    # 找到所有 [来源X] 标记的位置，标记已覆盖的文本范围
    covered_spans: List[Tuple[int, int]] = []
    for match in _SOURCE_TAG_PATTERN.finditer(answer):
        covered_spans.append((match.start(), match.end()))

    # 按 [来源X] 标记分割文本，检查每个段落
    segments = _SOURCE_TAG_PATTERN.split(answer)
    unverified: List[str] = []
    pos = 0

    for i, segment in enumerate(segments):
        segment = segment.strip()
        if not segment:
            pos += len(segment) + (len(segments[i]) if i < len(segments) else 0)
            continue

        # 如果这个段落后紧跟 [来源X] 标记，说明它已被引用覆盖
        if i < len(segments) and i + 1 <= len(_SOURCE_TAG_PATTERN.findall(answer)):
            pos += len(segment)
            continue

        # 跳过纯数字残留（引用编号）
        if segment[-1].isdigit():
            pos += len(segment)
            continue

        for pattern in _FACTUAL_PATTERNS:
            if pattern.search(segment):
                unverified.append(segment)
                break

        pos += len(segment)

    return unverified


def _split_sentences(text: str) -> List[str]:
    """按中文句号分割"""
    parts = re.split(r'(?<=[。！？\n])\s*', text)
    return [p.strip() for p in parts if p.strip()]


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算余弦相似度"""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _contains_factual_pattern(text: str) -> bool:
    """检测文本是否包含事实性陈述模式"""
    for pattern in _FACTUAL_PATTERNS:
        if pattern.search(text):
            return True
    return False


def attribute_by_similarity(
    answer: str,
    sources: List[Dict[str, Any]],
    embed_func: Optional[Callable[[str], List[float]]] = None,
    threshold: float = 0.6,
) -> AttributionResult:
    """基于 embedding 相似度的逐句归因"""
    if not answer or not sources or embed_func is None:
        return AttributionResult()

    sentences = _split_sentences(answer)
    citations: List[Citation] = []
    unverified: List[str] = []

    source_texts = [s.get('content', '') for s in sources]

    try:
        source_embeds = [embed_func(t) for t in source_texts]
    except Exception as e:
        logger.warning(f"Embedding 计算失败: {e}")
        return AttributionResult()

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 5:
            continue

        try:
            sentence_embed = embed_func(sentence)
        except Exception:
            continue

        best_idx = -1
        best_score = -1.0
        for idx, src_embed in enumerate(source_embeds):
            score = _cosine_similarity(sentence_embed, src_embed)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_score >= threshold and best_idx >= 0:
            source = sources[best_idx]
            citations.append(Citation(
                source_idx=best_idx,
                law_name=source.get('law_name', '未知'),
                article_number=source.get('article_number', '未知'),
                content=source.get('content', ''),
                confidence='similarity',
            ))
        elif _contains_factual_pattern(sentence):
            unverified.append(sentence)

    cited_indices = {c.source_idx for c in citations}
    uncited = sorted(set(range(len(sources))) - cited_indices)

    return AttributionResult(
        citations=citations,
        unverified_claims=unverified,
        uncited_sources=uncited,
    )
