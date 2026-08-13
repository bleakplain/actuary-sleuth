"""法规触发规格的受控 metadata 解析。"""
from __future__ import annotations

import re
from typing import Mapping, Tuple

from lib.common.compliance_audit import (
    ProofStrategy,
    RegulationTriggerSpec,
    TriggerFactName,
    TriggerOperator,
    TriggerValue,
)
from lib.doc_parser.pd.clause_topics import load_clause_topic_registry


class RegulationTriggerMetadataError(ValueError):
    pass


_TRIGGER_FIELDS = (
    "触发事实",
    "触发运算符",
    "触发期望值",
    "目标条款主题",
    "所需事实",
    "证明策略",
    "检索必含词组",
    "检索任一词组",
    "触发条件说明",
    "触发排除验收状态",
)
_NUMBERED_TRIGGER_FIELD_PATTERN = re.compile(
    rf"^({'|'.join(re.escape(field) for field in _TRIGGER_FIELDS)})([1-9]\d*)$"
)
_INTEGER_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)$")
_NUMBER_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)\.\d+$")
_CLOSED_SCAN_FACTS = frozenset({
    TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
    TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM,
})
_NUMERIC_FACTS = frozenset({
    TriggerFactName.WAITING_PERIOD_DAYS,
    TriggerFactName.HESITATION_PERIOD_DAYS,
    TriggerFactName.FIRST_RATE_ADJUSTMENT_INTERVAL_YEARS,
    TriggerFactName.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL_YEARS,
})


def _is_blank(value: object) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegulationTriggerMetadataError(f"{field_name}必须是非空字符串")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str:
    if _is_blank(value):
        return ""
    if not isinstance(value, str):
        raise RegulationTriggerMetadataError(f"{field_name}必须是字符串")
    return value.strip()


def _string_list(value: object, field_name: str) -> Tuple[str, ...]:
    if _is_blank(value):
        return ()
    if isinstance(value, str):
        normalized = (
            value.replace("，", ",")
            .replace("、", ",")
            .replace("；", ",")
            .replace(";", ",")
            .replace("\n", ",")
        )
        items = tuple(part.strip() for part in normalized.split(",") if part.strip())
    elif isinstance(value, (list, tuple)):
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise RegulationTriggerMetadataError(
                f"{field_name} 数组元素必须是非空字符串"
            )
        items = tuple(item.strip() for item in value)
    else:
        raise RegulationTriggerMetadataError(f"{field_name}必须是字符串或字符串数组")
    return tuple(dict.fromkeys(items))


def _fact_name(value: object, field_name: str) -> TriggerFactName:
    raw = _required_text(value, field_name)
    try:
        return TriggerFactName(raw)
    except ValueError as exc:
        raise RegulationTriggerMetadataError(f"{field_name}未注册: {raw}") from exc


def _fact_names(value: object, field_name: str) -> Tuple[TriggerFactName, ...]:
    return tuple(_fact_name(item, field_name) for item in _string_list(value, field_name))


def _expected_scalar(value: object) -> bool | int | float | str | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise RegulationTriggerMetadataError("触发期望值必须是有限数值")
        return value
    if not isinstance(value, str):
        raise RegulationTriggerMetadataError(
            "触发期望值只允许布尔值、有限数值或字符串"
        )
    text = value.strip()
    normalized = text.lower()
    if normalized in {"true", "是"}:
        return True
    if normalized in {"false", "否"}:
        return False
    if _INTEGER_PATTERN.fullmatch(text):
        return int(text)
    if _NUMBER_PATTERN.fullmatch(text):
        return float(text)
    if text.endswith("%"):
        raise RegulationTriggerMetadataError(
            "触发期望值百分比必须使用数值表示，例如 80% 填写为 0.8"
        )
    return text


def _parse_expected_value(
    operator: TriggerOperator,
    value: object,
) -> TriggerValue | None:
    if operator is TriggerOperator.EXISTS:
        expected_value = _expected_scalar(value)
        if expected_value is not None and not isinstance(expected_value, bool):
            raise RegulationTriggerMetadataError(
                "exists 的触发期望值只能为空、true 或 false"
            )
        return expected_value
    if operator is TriggerOperator.CONTAINS_ANY:
        expected_values = _string_list(value, "触发期望值")
        if not expected_values:
            raise RegulationTriggerMetadataError(
                "contains_any 运算符必须配置触发期望值"
            )
        return expected_values
    expected_value = _expected_scalar(value)
    if expected_value is None:
        raise RegulationTriggerMetadataError(
            f"{operator.value} 运算符必须配置触发期望值"
        )
    if operator is TriggerOperator.LESS_THAN_OR_EQUAL and (
        isinstance(expected_value, bool)
        or not isinstance(expected_value, (int, float))
    ):
        raise RegulationTriggerMetadataError(
            "less_than_or_equal 的触发期望值必须是数值"
        )
    return expected_value


def _trigger_operator(value: object) -> TriggerOperator:
    raw = _required_text(value, "触发运算符")
    try:
        return TriggerOperator(raw)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TriggerOperator)
        raise RegulationTriggerMetadataError(
            f"触发运算符非法: {raw}；允许值: {supported}"
        ) from exc


def _proof_strategy(value: object) -> ProofStrategy:
    raw = _required_text(value, "证明策略")
    try:
        return ProofStrategy(raw)
    except ValueError as exc:
        supported = ", ".join(item.value for item in ProofStrategy)
        raise RegulationTriggerMetadataError(
            f"证明策略非法: {raw}；允许值: {supported}"
        ) from exc


def _exclusion_approved(value: object) -> bool:
    if _is_blank(value):
        return False
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise RegulationTriggerMetadataError(
            "触发排除验收状态必须是 pending 或 approved"
        )
    normalized = value.strip().lower()
    if normalized in {"pending", "待验收", "false", "否"}:
        return False
    if normalized in {"approved", "已验收", "true", "是"}:
        return True
    raise RegulationTriggerMetadataError(
        "触发排除验收状态必须是 pending 或 approved"
    )


def _validate_type_matrix(
    fact_name: TriggerFactName,
    operator: TriggerOperator,
    expected_value: TriggerValue | None,
    proof_strategy: ProofStrategy,
) -> None:
    if fact_name in _NUMERIC_FACTS:
        if operator is not TriggerOperator.LESS_THAN_OR_EQUAL:
            raise RegulationTriggerMetadataError(
                "数值事实第一版只支持 less_than_or_equal"
            )
        if proof_strategy is not ProofStrategy.NUMERIC_FACT:
            raise RegulationTriggerMetadataError(
                "数值事实必须使用 numeric_fact 证明策略"
            )
        return
    if operator not in {TriggerOperator.EQUALS, TriggerOperator.EXISTS}:
        raise RegulationTriggerMetadataError(
            "布尔产品事实第一版只支持 equals 或 exists"
        )
    if operator is TriggerOperator.EQUALS and not isinstance(expected_value, bool):
        raise RegulationTriggerMetadataError(
            "布尔产品事实的 equals 期望值必须是 true 或 false"
        )
    if proof_strategy is ProofStrategy.NUMERIC_FACT:
        raise RegulationTriggerMetadataError(
            "布尔产品事实不能使用 numeric_fact 证明策略"
        )


def _parse_trigger_spec(metadata: Mapping[str, object]) -> RegulationTriggerSpec:
    fact_name = _fact_name(metadata.get("触发事实"), "触发事实")
    operator_value = _trigger_operator(metadata.get("触发运算符"))
    proof_value = _proof_strategy(metadata.get("证明策略"))
    expected_value = _parse_expected_value(
        operator_value,
        metadata.get("触发期望值"),
    )
    _validate_type_matrix(
        fact_name,
        operator_value,
        expected_value,
        proof_value,
    )

    target_topics = _string_list(metadata.get("目标条款主题"), "目标条款主题")
    unknown_topics = tuple(
        sorted(set(target_topics).difference(load_clause_topic_registry().codes))
    )
    if unknown_topics:
        raise RegulationTriggerMetadataError(
            f"目标条款主题引用未注册主题: {', '.join(unknown_topics)}"
        )

    search_all_terms = _string_list(metadata.get("检索必含词组"), "检索必含词组")
    search_any_terms = _string_list(metadata.get("检索任一词组"), "检索任一词组")
    if proof_value is ProofStrategy.CLOSED_PHRASE_SCAN and not (
        search_all_terms or search_any_terms
    ):
        raise RegulationTriggerMetadataError(
            "closed_phrase_scan 必须配置检索必含词组或检索任一词组"
        )
    if (
        proof_value is ProofStrategy.CLOSED_PHRASE_SCAN
        and fact_name not in _CLOSED_SCAN_FACTS
    ):
        raise RegulationTriggerMetadataError(
            "closed_phrase_scan 只允许用于受控的字面出现事实；"
            f"{fact_name.value} 属于开放世界产品功能事实"
        )

    return RegulationTriggerSpec(
        fact_name=fact_name,
        operator=operator_value,
        expected_value=expected_value,
        target_topics=target_topics,
        required_facts=_fact_names(metadata.get("所需事实"), "所需事实"),
        proof_strategy=proof_value,
        search_all_terms=search_all_terms,
        search_any_terms=search_any_terms,
        description=_optional_text(metadata.get("触发条件说明"), "触发条件说明"),
        exclusion_approved=_exclusion_approved(
            metadata.get("触发排除验收状态")
        ),
    )


def _trigger_metadata_groups(
    metadata: Mapping[str, object],
) -> Tuple[Mapping[str, object], ...]:
    unnumbered = {
        field: metadata.get(field)
        for field in _TRIGGER_FIELDS
        if not _is_blank(metadata.get(field))
    }
    numbered: dict[int, dict[str, object]] = {}
    for raw_key, value in metadata.items():
        if not isinstance(raw_key, str) or _is_blank(value):
            continue
        match = _NUMBERED_TRIGGER_FIELD_PATTERN.fullmatch(raw_key.strip())
        if match is None:
            continue
        numbered.setdefault(int(match.group(2)), {})[match.group(1)] = value
    if not unnumbered and not numbered:
        return ()
    if unnumbered and 1 in numbered:
        raise RegulationTriggerMetadataError(
            "未编号触发列与编号 1 触发列不能同时使用"
        )
    groups = dict(numbered)
    if unnumbered:
        groups[1] = unnumbered
    indexes = tuple(sorted(groups))
    expected = tuple(range(1, indexes[-1] + 1))
    if indexes != expected:
        raise RegulationTriggerMetadataError(
            "多条触发条件必须从 1 开始连续编号"
        )
    return tuple(groups[index] for index in indexes)


def parse_regulation_trigger_metadata(
    metadata: Mapping[str, object],
) -> Tuple[RegulationTriggerSpec, ...]:
    """解析受控触发列；多组编号条件由求值器按 AND 组合。"""
    groups = _trigger_metadata_groups(metadata)
    return tuple(_parse_trigger_spec(group) for group in groups)
