"""记忆检索触发器。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from lib.common.middleware import TOPIC_KEYWORDS, COMPANY_KEYWORDS


@dataclass(frozen=True)
class TriggerResult:
    """触发判断结果。"""
    should_retrieve: bool
    trigger_type: str
    matched: tuple[str, ...]
    confidence: float


def should_retrieve_memory(
    question: str,
    session_context: Optional[Dict] = None,
    last_retrieve_time: float = 0.0,
    interval_seconds: int = 60,
) -> TriggerResult:
    """判断是否需要触发记忆检索。

    触发策略（优先级从高到低）：
    1. 关键词触发 - 保险术语、公司名
    2. 实体关联 - 问题涉及会话中提到的实体
    3. 话题延续 - 问题包含当前话题
    4. 时间间隔 - 距上次检索超过 interval_seconds

    Args:
        question: 用户问题
        session_context: 会话上下文，包含 mentioned_entities、current_topic 等
        last_retrieve_time: 上次检索时间戳
        interval_seconds: 检索间隔秒数

    Returns:
        TriggerResult: 触发判断结果
    """
    session_context = session_context or {}

    # 1. 关键词触发（保险术语）
    for kw in TOPIC_KEYWORDS:
        if kw in question:
            return TriggerResult(True, "keyword", (kw,), 0.9)

    # 2. 关键词触发（公司名）
    for kw in COMPANY_KEYWORDS:
        if kw in question:
            return TriggerResult(True, "company", (kw,), 0.85)

    # 3. 实体关联触发
    entities = session_context.get("mentioned_entities", [])
    for entity in entities:
        if entity in question:
            return TriggerResult(True, "entity", (entity,), 0.7)

    # 4. 话题延续触发
    topic = session_context.get("current_topic")
    if topic and topic in question:
        return TriggerResult(True, "topic", (topic,), 0.6)

    # 5. 时间间隔触发
    if time.time() - last_retrieve_time > interval_seconds:
        return TriggerResult(True, "interval", (), 0.5)

    return TriggerResult(False, "skip", (), 0.0)
