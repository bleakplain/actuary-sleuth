from dataclasses import FrozenInstanceError, replace

import pytest

from lib.common.compliance_audit import (
    FactTruth,
    ProductFact,
    ProductFactEvidence,
    ProofStrategy,
    RegulationTriggerSpec,
    TriggerFactName,
    TriggerOperator,
    TriggerStatus,
    TriggerValue,
)
from lib.compliance.regulation_triggers import evaluate_regulation_triggers


def _evidence(clause_id: str = "c-1") -> tuple[ProductFactEvidence, ...]:
    return (ProductFactEvidence(clause_id, "产品条款逐字证据"),)


def _fact(
    name: TriggerFactName,
    truth: FactTruth,
    value: TriggerValue | None = None,
    *,
    unit: str = "",
    confidence: float = 1.0,
    evidence: tuple[ProductFactEvidence, ...] = (),
    safe_for_exclusion: bool = False,
    proof_strategy: ProofStrategy | None = None,
    proof_terms: tuple[str, ...] = (),
    complete_document_proof: bool = False,
) -> ProductFact:
    return ProductFact(
        name=name,
        truth=truth,
        value=value,
        unit=unit,
        method="test",
        confidence=confidence,
        evidence=evidence,
        reason="fixture",
        safe_for_exclusion=safe_for_exclusion,
        proof_strategy=proof_strategy,
        proof_terms=proof_terms,
        complete_document_proof=complete_document_proof,
    )


def _spec(
    name: TriggerFactName,
    operator: TriggerOperator = TriggerOperator.EQUALS,
    expected: TriggerValue | None = True,
    proof_strategy: ProofStrategy = ProofStrategy.EXPLICIT_PRESENCE,
) -> RegulationTriggerSpec:
    return RegulationTriggerSpec(
        fact_name=name,
        operator=operator,
        expected_value=expected,
        proof_strategy=proof_strategy,
    )


def test_trigger_models_are_frozen_and_validate_confidence() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN, FactTruth.UNKNOWN)

    with pytest.raises(FrozenInstanceError):
        fact.truth = FactTruth.TRUE  # type: ignore[misc]
    with pytest.raises(ValueError, match="confidence"):
        _fact(
            TriggerFactName.HAS_POLICY_LOAN,
            FactTruth.UNKNOWN,
            confidence=1.1,
        )


def test_unconfigured_regulation_is_preserved_as_triggered() -> None:
    result = evaluate_regulation_triggers((), {})

    assert result.status is TriggerStatus.TRIGGERED
    assert result.fact_names == ()
    assert "未配置触发条件" in result.reasons[0]


def test_explicit_true_fact_triggers_and_keeps_evidence() -> None:
    name = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (_spec(name),),
        {name: _fact(name, FactTruth.TRUE, evidence=_evidence("loan-1"))},
    )

    assert result.status is TriggerStatus.TRIGGERED
    assert result.evidence_clause_ids == ("loan-1",)


def test_false_without_safe_negative_proof_is_indeterminate() -> None:
    name = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (_spec(name),),
        {name: _fact(name, FactTruth.FALSE)},
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "缺少安全负向证明" in result.reasons[0]


def test_explicit_negation_cannot_exclude_open_world_function() -> None:
    name = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (_spec(name, proof_strategy=ProofStrategy.EXPLICIT_NEGATION),),
        {
            name: _fact(
                name,
                FactTruth.FALSE,
                safe_for_exclusion=True,
                evidence=_evidence("loan-negation"),
                proof_strategy=ProofStrategy.EXPLICIT_NEGATION,
            )
        },
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert result.evidence_clause_ids == ("loan-negation",)


def test_explicit_negation_can_trigger_expected_false_without_excluding_rule() -> None:
    name = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (
            _spec(
                name,
                TriggerOperator.EXISTS,
                False,
                ProofStrategy.EXPLICIT_NEGATION,
            ),
        ),
        {
            name: _fact(
                name,
                FactTruth.FALSE,
                evidence=_evidence("loan-negation"),
                proof_strategy=ProofStrategy.EXPLICIT_NEGATION,
            )
        },
    )

    assert result.status is TriggerStatus.TRIGGERED
    assert result.evidence_clause_ids == ("loan-negation",)


def test_unknown_or_low_confidence_fact_is_indeterminate() -> None:
    waiting = TriggerFactName.HAS_WAITING_PERIOD
    renewal = TriggerFactName.HAS_RENEWAL
    result = evaluate_regulation_triggers(
        (_spec(waiting), _spec(renewal)),
        {
            waiting: _fact(waiting, FactTruth.UNKNOWN),
            renewal: _fact(
                renewal,
                FactTruth.TRUE,
                confidence=0.79,
                evidence=_evidence("renewal-1"),
            ),
        },
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert any("产品事实未知" in reason for reason in result.reasons)
    assert any("置信度不足" in reason for reason in result.reasons)


def test_true_fact_without_verbatim_evidence_is_indeterminate() -> None:
    name = TriggerFactName.HAS_RENEWAL
    result = evaluate_regulation_triggers(
        (_spec(name),),
        {name: _fact(name, FactTruth.TRUE)},
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "缺少逐字证据" in result.reasons[0]


def test_any_closed_scan_safe_false_wins_for_and_conditions() -> None:
    waiting = TriggerFactName.HAS_WAITING_PERIOD
    literal = TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG
    result = evaluate_regulation_triggers(
        (
            _spec(waiting),
            replace(
                _spec(
                    literal,
                    proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
                ),
                search_any_terms=("院外购药", "药店"),
            ),
        ),
        {
            waiting: _fact(waiting, FactTruth.UNKNOWN),
            literal: _fact(
                literal,
                FactTruth.FALSE,
                safe_for_exclusion=True,
                proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
                proof_terms=("院外购药", "药店"),
                complete_document_proof=True,
            ),
        },
    )

    assert result.status is TriggerStatus.NOT_TRIGGERED


def test_exists_can_trigger_on_closed_scan_safe_absence() -> None:
    name = TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG
    result = evaluate_regulation_triggers(
        (replace(
            _spec(
                name,
                TriggerOperator.EXISTS,
                False,
                ProofStrategy.CLOSED_PHRASE_SCAN,
            ),
            search_any_terms=("院外购药", "药店"),
        ),),
        {
            name: _fact(
                name,
                FactTruth.FALSE,
                safe_for_exclusion=True,
                proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
                proof_terms=("院外购药", "药店"),
                complete_document_proof=True,
            )
        },
    )

    assert result.status is TriggerStatus.TRIGGERED


def test_explicit_negative_proof_without_evidence_is_indeterminate() -> None:
    name = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (_spec(name, proof_strategy=ProofStrategy.EXPLICIT_NEGATION),),
        {
            name: _fact(
                name,
                FactTruth.FALSE,
                safe_for_exclusion=True,
                proof_strategy=ProofStrategy.EXPLICIT_NEGATION,
            )
        },
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "缺少安全负向证明" in result.reasons[0]


def test_contains_any_supports_controlled_string_values() -> None:
    name = TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM
    result = evaluate_regulation_triggers(
        (_spec(name, TriggerOperator.CONTAINS_ANY, ("重大疾病", "癌症")),),
        {
            name: _fact(
                name,
                FactTruth.TRUE,
                "条款使用重大疾病定义",
                evidence=_evidence("definition-1"),
            )
        },
    )

    assert result.status is TriggerStatus.TRIGGERED


def test_closed_phrase_zero_hit_safely_does_not_trigger_contains_any() -> None:
    name = TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG
    result = evaluate_regulation_triggers(
        (
            replace(_spec(
                name,
                TriggerOperator.CONTAINS_ANY,
                ("院外购药", "药店"),
                ProofStrategy.CLOSED_PHRASE_SCAN,
            ), search_any_terms=("院外购药", "药店")),
        ),
        {
            name: _fact(
                name,
                FactTruth.FALSE,
                False,
                safe_for_exclusion=True,
                proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
                proof_terms=("院外购药", "药店"),
                complete_document_proof=True,
            )
        },
    )

    assert result.status is TriggerStatus.NOT_TRIGGERED


def test_negative_proof_strategy_must_match_regulation_spec() -> None:
    name = TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG
    fact = _fact(
        name,
        FactTruth.FALSE,
        False,
        safe_for_exclusion=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        proof_terms=("院外购药", "药店"),
        complete_document_proof=True,
    )

    result = evaluate_regulation_triggers(
        (_spec(
            name,
            proof_strategy=ProofStrategy.EXPLICIT_NEGATION,
        ),),
        {name: fact},
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "匹配" in result.reasons[0]


def test_numeric_fact_accepts_numeric_string_with_canonical_unit() -> None:
    name = TriggerFactName.WAITING_PERIOD_DAYS
    result = evaluate_regulation_triggers(
        (
            _spec(
                name,
                TriggerOperator.LESS_THAN_OR_EQUAL,
                180,
                ProofStrategy.NUMERIC_FACT,
            ),
        ),
        {
            name: _fact(
                name,
                FactTruth.TRUE,
                "30",
                unit="day",
                evidence=_evidence("waiting-1"),
            )
        },
    )

    assert result.status is TriggerStatus.TRIGGERED


def test_numeric_mismatch_never_excludes_in_trigger_layer() -> None:
    name = TriggerFactName.WAITING_PERIOD_DAYS
    spec = _spec(
        name,
        TriggerOperator.LESS_THAN_OR_EQUAL,
        180,
        ProofStrategy.NUMERIC_FACT,
    )
    unsafe = evaluate_regulation_triggers(
        (spec,),
        {
            name: _fact(
                name,
                FactTruth.TRUE,
                365,
                unit="day",
                evidence=_evidence(),
            )
        },
    )
    safe = evaluate_regulation_triggers(
        (spec,),
        {
            name: _fact(
                name,
                FactTruth.TRUE,
                365,
                unit="day",
                evidence=_evidence(),
                safe_for_exclusion=True,
            )
        },
    )

    assert unsafe.status is TriggerStatus.INDETERMINATE
    assert safe.status is TriggerStatus.INDETERMINATE
    assert "可能正是违规情形" in safe.reasons[0]


def test_numeric_fact_with_wrong_unit_is_indeterminate() -> None:
    name = TriggerFactName.WAITING_PERIOD_DAYS
    result = evaluate_regulation_triggers(
        (_spec(name, TriggerOperator.LESS_THAN_OR_EQUAL, 180),),
        {
            name: _fact(
                name,
                FactTruth.TRUE,
                6,
                unit="month",
                evidence=_evidence(),
                safe_for_exclusion=True,
            )
        },
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "类型要求" in result.reasons[0]


def test_fact_mapping_name_mismatch_is_indeterminate() -> None:
    requested = TriggerFactName.HAS_POLICY_LOAN
    result = evaluate_regulation_triggers(
        (_spec(requested),),
        {
            requested: _fact(
                TriggerFactName.HAS_CASH_VALUE,
                FactTruth.TRUE,
                evidence=_evidence(),
            )
        },
    )

    assert result.status is TriggerStatus.INDETERMINATE
    assert "键值不一致" in result.reasons[0]
