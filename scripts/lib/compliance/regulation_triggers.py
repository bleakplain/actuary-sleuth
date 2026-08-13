"""用受控产品事实求值法规触发条件。

求值器只组合已经提取并留有证据的事实，不执行表达式，也不从提取方法名称
推断事实是否可靠。尤其是条件不满足时，只有事实提取层显式标记
``safe_for_exclusion`` 才能输出 ``not_triggered``；否则保守返回
``indeterminate``，让法规继续进入审核。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable, Mapping, Optional, Tuple

from lib.common.compliance_audit import (
    FactTruth,
    ProofStrategy,
    ProductFact,
    RegulationTriggerSpec,
    TriggerEvaluation,
    TriggerFactName,
    TriggerOperator,
    TriggerStatus,
    TriggerValue,
)


_MIN_TRIGGER_FACT_CONFIDENCE = 0.8
_NUMERIC_FACT_UNITS: Mapping[TriggerFactName, str] = {
    TriggerFactName.WAITING_PERIOD_DAYS: "day",
    TriggerFactName.HESITATION_PERIOD_DAYS: "day",
    TriggerFactName.FIRST_RATE_ADJUSTMENT_INTERVAL_YEARS: "year",
    TriggerFactName.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL_YEARS: "year",
}


class _ConditionStatus(str, Enum):
    MATCHED = "matched"
    SAFE_MISMATCH = "safe_mismatch"
    INDETERMINATE = "indeterminate"


def _as_decimal(value: Optional[TriggerValue]) -> Optional[Decimal]:
    if value is None or isinstance(value, (bool, tuple)):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fact_value(fact: ProductFact) -> TriggerValue:
    if fact.value is not None:
        return fact.value
    return fact.truth is FactTruth.TRUE


def _equals(fact: ProductFact, expected: Optional[TriggerValue]) -> Optional[bool]:
    if expected is None:
        return None
    return _fact_value(fact) == expected


def _exists(fact: ProductFact, expected: Optional[TriggerValue]) -> Optional[bool]:
    if expected is not None and not isinstance(expected, bool):
        return None
    exists = fact.truth is FactTruth.TRUE
    return exists is (True if expected is None else expected)


def _contains_any(
    fact: ProductFact,
    expected: Optional[TriggerValue],
) -> Optional[bool]:
    expected_values: Tuple[str, ...]
    if isinstance(expected, str):
        expected_values = (expected,)
    elif isinstance(expected, tuple) and all(
        isinstance(item, str) for item in expected
    ):
        expected_values = expected
    else:
        return None
    if not expected_values:
        return None
    if fact.truth is FactTruth.FALSE:
        return False

    actual = _fact_value(fact)
    actual_values: Tuple[str, ...]
    if isinstance(actual, str):
        actual_values = (actual,)
    elif isinstance(actual, tuple) and all(isinstance(item, str) for item in actual):
        actual_values = actual
    else:
        return None
    return any(
        expected_item in actual_item
        for expected_item in expected_values
        for actual_item in actual_values
    )


def _less_than_or_equal(
    spec: RegulationTriggerSpec,
    fact: ProductFact,
) -> Optional[bool]:
    expected = _as_decimal(spec.expected_value)
    actual = _as_decimal(fact.value)
    if expected is None or actual is None:
        return None
    required_unit = _NUMERIC_FACT_UNITS.get(spec.fact_name)
    if required_unit is not None and fact.unit != required_unit:
        return None
    return actual <= expected


def _operator_matches(
    spec: RegulationTriggerSpec,
    fact: ProductFact,
) -> Optional[bool]:
    if spec.operator is TriggerOperator.EQUALS:
        return _equals(fact, spec.expected_value)
    if spec.operator is TriggerOperator.EXISTS:
        return _exists(fact, spec.expected_value)
    if spec.operator is TriggerOperator.CONTAINS_ANY:
        return _contains_any(fact, spec.expected_value)
    if spec.operator is TriggerOperator.LESS_THAN_OR_EQUAL:
        return _less_than_or_equal(spec, fact)
    return None


def _has_compatible_negative_proof(
    spec: RegulationTriggerSpec,
    fact: ProductFact,
) -> bool:
    if not fact.safe_for_exclusion or fact.proof_strategy is not spec.proof_strategy:
        return False
    if spec.proof_strategy is ProofStrategy.CLOSED_PHRASE_SCAN:
        configured_terms = frozenset((*spec.search_all_terms, *spec.search_any_terms))
        return (
            fact.complete_document_proof
            and bool(configured_terms)
            and configured_terms.issubset(fact.proof_terms)
        )
    if spec.proof_strategy is ProofStrategy.CONTROLLED_CLASSIFICATION:
        return bool(fact.evidence)
    return False


def _has_compatible_false_assertion(
    spec: RegulationTriggerSpec,
    fact: ProductFact,
) -> bool:
    """Validate a false-valued fact used to positively trigger a regulation.

    This is deliberately broader than exclusion proof: accepting an evidenced
    false assertion here only keeps a regulation in scope.  It never proves a
    regulation is not triggered.
    """
    if fact.proof_strategy is not spec.proof_strategy:
        return False
    if spec.proof_strategy is ProofStrategy.CLOSED_PHRASE_SCAN:
        configured_terms = frozenset((*spec.search_all_terms, *spec.search_any_terms))
        return (
            fact.complete_document_proof
            and bool(configured_terms)
            and configured_terms.issubset(fact.proof_terms)
        )
    return (
        spec.proof_strategy
        in {
            ProofStrategy.EXPLICIT_NEGATION,
            ProofStrategy.CONTROLLED_CLASSIFICATION,
            ProofStrategy.SEMANTIC_FACT,
        }
        and bool(fact.evidence)
    )


def _evaluate_condition(
    spec: RegulationTriggerSpec,
    fact: Optional[ProductFact],
) -> Tuple[_ConditionStatus, str]:
    label = spec.fact_name.value
    if fact is None:
        return _ConditionStatus.INDETERMINATE, f"{label}: 产品事实缺失，保守保留"
    if fact.name is not spec.fact_name:
        return (
            _ConditionStatus.INDETERMINATE,
            f"{label}: 事实账本键值不一致，保守保留",
        )
    if fact.truth is FactTruth.UNKNOWN:
        return _ConditionStatus.INDETERMINATE, f"{label}: 产品事实未知，保守保留"
    if fact.confidence < _MIN_TRIGGER_FACT_CONFIDENCE:
        return (
            _ConditionStatus.INDETERMINATE,
            f"{label}: 事实置信度不足，保守保留",
        )
    if fact.truth is FactTruth.TRUE and not fact.evidence:
        return (
            _ConditionStatus.INDETERMINATE,
            f"{label}: true 缺少逐字证据，保守保留",
        )

    matched = _operator_matches(spec, fact)
    if matched is None:
        return (
            _ConditionStatus.INDETERMINATE,
            f"{label}: 事实值或单位不满足 {spec.operator.value} 的类型要求",
        )
    if matched and fact.truth is FactTruth.FALSE:
        if not _has_compatible_false_assertion(spec, fact):
            return (
                _ConditionStatus.INDETERMINATE,
                f"{label}: false 虽满足目标值，但缺少与法规规格匹配的"
                "可追溯 false 证据，保守保留",
            )
        return _ConditionStatus.MATCHED, f"{label}: false 目标值已有证据满足"
    if matched:
        return _ConditionStatus.MATCHED, f"{label}: 触发条件已满足"
    if spec.operator is TriggerOperator.LESS_THAN_OR_EQUAL:
        return (
            _ConditionStatus.INDETERMINATE,
            f"{label}: 数值不满足可能正是违规情形，触发层不得据此排除法规",
        )
    if _has_compatible_negative_proof(spec, fact):
        return (
            _ConditionStatus.SAFE_MISMATCH,
            f"{label}: 触发条件有安全反证，明确不触发",
        )
    return (
        _ConditionStatus.INDETERMINATE,
        f"{label}: 条件不满足且缺少安全负向证明，或证明策略与"
        "法规规格不匹配，保守保留",
    )


def evaluate_regulation_triggers(
    specs: Iterable[RegulationTriggerSpec],
    facts: Mapping[TriggerFactName, ProductFact],
) -> TriggerEvaluation:
    """按 AND 求值法规触发条件；未配置或未决条件绝不排除法规。"""
    conditions = tuple(specs)
    if not conditions:
        return TriggerEvaluation(
            status=TriggerStatus.TRIGGERED,
            fact_names=(),
            reasons=("法规未配置触发条件，保留检查",),
            evidence_clause_ids=(),
        )

    outcomes = tuple(
        _evaluate_condition(spec, facts.get(spec.fact_name))
        for spec in conditions
    )
    if any(status is _ConditionStatus.SAFE_MISMATCH for status, _ in outcomes):
        status = TriggerStatus.NOT_TRIGGERED
    elif any(status is _ConditionStatus.INDETERMINATE for status, _ in outcomes):
        status = TriggerStatus.INDETERMINATE
    else:
        status = TriggerStatus.TRIGGERED

    fact_names = tuple(dict.fromkeys(spec.fact_name for spec in conditions))
    evidence_clause_ids = tuple(dict.fromkeys(
        evidence.clause_id
        for fact_name in fact_names
        for evidence in (
            facts[fact_name].evidence if fact_name in facts else ()
        )
        if evidence.clause_id
    ))
    return TriggerEvaluation(
        status=status,
        fact_names=fact_names,
        reasons=tuple(reason for _, reason in outcomes),
        evidence_clause_ids=evidence_clause_ids,
    )
