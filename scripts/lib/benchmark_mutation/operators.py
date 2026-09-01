"""四类变异原语的执行。

原语在条款文本层面工作，返回统一的 MutationDiff（原文与变异后全文）。
定位职责不在这里——由 variant_builder 先锁定目标块；这里只负责改写，
保证改写行为可独立单测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from lib.benchmark_mutation.operator_schema import MutationOperator, MutationTier

@dataclass(frozen=True)
class MutationDiff:
    """一次变异在单个条款块上的改写记录。"""
    operator_id: str
    clause_id: str
    original_text: str
    mutated_text: str

class MutationApplicationError(ValueError):
    """变异原语无法在给定文本上执行（锚文本不存在、数值找不到等）。"""

_SENTENCE_SPLIT = re.compile(r"(?<=[。；;])")

def apply_mutation(clause_id: str, text: str, operator: MutationOperator) -> MutationDiff:
    """对单个条款文本应用算子，返回 diff；无法执行时抛错。"""
    mutated = _MUTATORS[operator.tier](text, operator.payload)
    if mutated == text:
        raise MutationApplicationError(
            f"{operator.operator_id}: 变异未产生文本变化（条款 {clause_id}）"
        )
    return MutationDiff(
        operator_id=operator.operator_id,
        clause_id=clause_id,
        original_text=text,
        mutated_text=mutated,
    )

def _apply_insertion(text: str, payload: Mapping[str, object]) -> str:
    inserted = str(payload["insert_text"]).strip()
    return f"{text.rstrip()}{inserted}" if text.strip() else inserted

def _apply_numeric(text: str, payload: Mapping[str, object]) -> str:
    to_value = str(payload["to_value"])
    candidates = payload.get("from_values") or [payload.get("from_value")]
    # 多个候选值依次尝试：宿主交费期间可能写 10年/15年/二十年 等不同形式
    for candidate in candidates:
        from_value = str(candidate)
        if from_value in text:
            return text.replace(from_value, to_value, 1)
    raise MutationApplicationError(f"数值 {candidates} 均不在条款文本中")

def _apply_deletion(text: str, payload: Mapping[str, object]) -> str:
    anchor = str(payload["anchor_text"])
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    kept = [s for s in sentences if anchor not in s]
    if len(kept) == len(sentences):
        raise MutationApplicationError(f"锚文本 {anchor!r} 未命中任何句子")
    return "".join(kept)

def _apply_rewrite(text: str, payload: Mapping[str, object]) -> str:
    anchor, replacement = str(payload["anchor_text"]), str(payload["replace_text"])
    if anchor not in text:
        raise MutationApplicationError(f"锚文本 {anchor!r} 不在条款文本中")
    return text.replace(anchor, replacement, 1)

_MUTATORS = {
    MutationTier.INSERTION: _apply_insertion,
    MutationTier.NUMERIC: _apply_numeric,
    MutationTier.DELETION: _apply_deletion,
    MutationTier.REWRITE: _apply_rewrite,
}
