"""变异算子的数据模型与加载校验。

算子是声明式 JSON（data/operators.v1.json），由确认工作流和论文附录直接
引用，因此 schema 校验在加载时全部完成：rule_ref 必须解析到 KB 中的真实
负面清单规则，host_tags 与 ProductTags 词汇对齐，payload 与 tier 匹配。
校验失败立即抛错而不是静默跳过——坏算子进入评测集会污染金标。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

class MutationTier(str, Enum):
    INSERTION = "insertion"
    NUMERIC = "numeric"
    DELETION = "deletion"
    REWRITE = "rewrite"

_PAYLOAD_REQUIRED_KEYS: Mapping[MutationTier, Tuple[str, ...]] = {
    MutationTier.INSERTION: ("insert_text",),
    MutationTier.NUMERIC: ("from_value", "to_value"),
    MutationTier.DELETION: ("anchor_text",),
    MutationTier.REWRITE: ("anchor_text", "replace_text"),
}

class MutationOperatorError(ValueError):
    """算子声明不合法或引用的规则不存在。"""

_HOST_TAG_VOCABULARY = frozenset({
    "life", "term_life", "whole_life", "endowment", "annuity",
    "health", "disease", "critical_illness", "medical",
    "disability_income", "nursing", "medical_accident",
    "accident", "rider",
    "participating", "universal", "unit_linked",
    "long_term", "short_term", "has_renewal",
})

@dataclass(frozen=True)
class MutationOperator:
    """一条可执行的违规变异声明。

    ``target_topics`` 用条款主题注册表代码定位宿主条款块；``payload``
    结构由 ``tier`` 决定，四类原语见 ``_PAYLOAD_REQUIRED_KEYS``。
    """
    operator_id: str
    rule_ref: str
    tier: MutationTier
    host_tags: Tuple[str, ...]
    target_topics: Tuple[str, ...]
    payload: Mapping[str, Any]
    expected_decision: str
    description: str
    def __post_init__(self) -> None:
        if self.expected_decision != "violated":
            raise MutationOperatorError(
                f"{self.operator_id}: expected_decision 只支持 violated，"
                f"得到 {self.expected_decision!r}"
            )
        if not self.host_tags or not set(self.host_tags) <= _HOST_TAG_VOCABULARY:
            unknown = sorted(set(self.host_tags) - _HOST_TAG_VOCABULARY)
            raise MutationOperatorError(
                f"{self.operator_id}: host_tags 含未知标签 {unknown}"
            )
        if not self.target_topics:
            raise MutationOperatorError(f"{self.operator_id}: target_topics 不能为空")
        missing = [
            key for key in _PAYLOAD_REQUIRED_KEYS[self.tier]
            if not str(self.payload.get(key, "")).strip()
        ]
        if missing:
            raise MutationOperatorError(
                f"{self.operator_id}: tier={self.tier.value} 缺少 payload 字段 {missing}"
            )
def parse_operator(raw: Mapping[str, Any]) -> MutationOperator:
    """解析单个算子 JSON 对象，格式错误抛 MutationOperatorError。"""
    try:
        return MutationOperator(
            operator_id=_required_text(raw, "operator_id"),
            rule_ref=_required_text(raw, "rule_ref"),
            tier=MutationTier(str(raw.get("tier", ""))),
            host_tags=tuple(_required_texts(raw, "host_tags")),
            target_topics=tuple(_required_texts(raw, "target_topics")),
            payload=_required_mapping(raw, "payload"),
            expected_decision=str(raw.get("expected_decision", "")),
            description=_required_text(raw, "description"),
        )
    except MutationOperatorError:
        raise
    except ValueError as exc:
        raise MutationOperatorError(f"算子格式错误: {exc}") from exc

def load_operators(
    path: Path | None = None,
    *,
    refs_dir: Path | None = None,
) -> Tuple[MutationOperator, ...]:
    """加载算子库并校验规则引用真实性。

    ``refs_dir`` 指向 KB references 目录时，逐条验证 rule_ref 能解析到
    负面清单文件及其中的原序号；未提供时跳过该检查（离线单测用）。
    """
    source = path or Path(__file__).parent / "data" / "operators.v1.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    entries = raw.get("operators")
    if not isinstance(entries, list) or not entries:
        raise MutationOperatorError(f"{source}: operators 必须是非空数组")
    operators = tuple(parse_operator(item) for item in entries)
    ids = [op.operator_id for op in operators]
    if len(set(ids)) != len(ids):
        raise MutationOperatorError(f"{source}: operator_id 重复")
    if refs_dir is not None:
        for op in operators:
            _verify_rule_ref(op, refs_dir)
    return operators

def _verify_rule_ref(operator: MutationOperator, refs_dir: Path) -> None:
    file_part, _, ordinal_part = operator.rule_ref.partition("#")
    rule_file = refs_dir / "01_负面清单检查" / f"{file_part}.md"
    if not rule_file.is_file():
        raise MutationOperatorError(
            f"{operator.operator_id}: 规则文件不存在 {rule_file}"
        )
    if not ordinal_part.startswith("原序号="):
        raise MutationOperatorError(
            f"{operator.operator_id}: rule_ref 缺少 '#原序号=N' 后缀"
        )
    text = rule_file.read_text(encoding="utf-8")
    if ordinal_part not in text:
        raise MutationOperatorError(
            f"{operator.operator_id}: {rule_file.name} 中未找到 {ordinal_part}"
        )
def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise MutationOperatorError(f"缺少必填字段 {key}")
    return value

def _required_texts(raw: Mapping[str, Any], key: str) -> Tuple[str, ...]:
    values = raw.get(key)
    if not isinstance(values, list) or not values:
        raise MutationOperatorError(f"{key} 必须是非空数组")
    return tuple(str(item).strip() for item in values)

def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict) or not value:
        raise MutationOperatorError(f"{key} 必须是非空对象")
    return value
