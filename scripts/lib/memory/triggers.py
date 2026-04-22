"""记忆检索触发器。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from lib.common.middleware import TOPIC_KEYWORDS, COMPANY_KEYWORDS


@dataclass(frozen=True)
class TriggerResult:
    """触发判断结果。"""
    should_retrieve: bool
    trigger_type: str
    matched_keywords: tuple[str, ...]
    confidence: float


def should_retrieve_memory(question: str) -> TriggerResult:
    """判断是否需要触发记忆检索。

    触发条件（优先级从高到低）：
    1. 话题关键词（等待期、保费等）
    2. 公司关键词（平安、泰康等）
    """
    matched: List[str] = []

    for kw in TOPIC_KEYWORDS:
        if kw in question:
            matched.append(kw)

    if matched:
        return TriggerResult(
            should_retrieve=True,
            trigger_type="topic",
            matched_keywords=tuple(matched),
            confidence=0.9,
        )

    for kw in COMPANY_KEYWORDS:
        if kw in question:
            matched.append(kw)

    if matched:
        return TriggerResult(
            should_retrieve=True,
            trigger_type="company",
            matched_keywords=tuple(matched),
            confidence=0.8,
        )

    return TriggerResult(
        should_retrieve=False,
        trigger_type="skip",
        matched_keywords=(),
        confidence=0.0,
    )
