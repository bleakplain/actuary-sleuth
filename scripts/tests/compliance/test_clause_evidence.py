from dataclasses import dataclass
from typing import Optional, Tuple

import pytest

from lib.compliance.clause_evidence import (
    EvidenceSourceLayer,
    FactEvidenceReference,
    select_clause_evidence,
)


@dataclass(frozen=True)
class _Clause:
    clause_id: str
    number: str
    title: str
    text: str
    topics: Tuple[str, ...] = ()
    parent_number: Optional[str] = None
    ancestor_numbers: Tuple[str, ...] = ()
    hierarchy_path: str = ""
    container_only: bool = False


def test_policy_loan_does_not_match_cash_value_alone() -> None:
    result = select_clause_evidence(
        ("policy.loan",),
        "保单贷款比例不得超过现金价值的百分之八十",
        (
            _Clause(
                "cash-value",
                "3.3",
                "被保险人变动",
                "解除被保险人资格时退还该被保险人的现金价值。",
            ),
        ),
        min_bm25_score=0.01,
    )

    assert result.selected_clause_ids == ()
    assert result.matches == ()
    assert result.warnings


def test_policy_loan_business_object_phrase_is_selected() -> None:
    result = select_clause_evidence(
        ("policy.loan",),
        "保单贷款比例不得超过现金价值的百分之八十",
        (
            _Clause(
                "loan",
                "6.2",
                "合同权益",
                "投保人可以申请保单贷款，贷款金额不得超过现金价值的80%。",
            ),
        ),
        min_bm25_score=999.0,
    )

    assert result.selected_clause_ids == ("loan",)
    assert any(
        match.source_layer is EvidenceSourceLayer.BUSINESS_TERMS
        and match.selection_reason
        and match.score == 1.0
        for match in result.matches
    )


@pytest.mark.parametrize(
    "loan_term",
    ("质押贷款", "保险单质押借款", "质押借款"),
)
def test_policy_loan_accepts_controlled_pledge_loan_phrase(
    loan_term: str,
) -> None:
    result = select_clause_evidence(
        ("policy.loan",),
        "保单贷款比例不得超过现金价值的百分之八十",
        (
            _Clause(
                "pledge-loan",
                "6.2",
                "合同权益",
                f"投保人可以申请{loan_term}，贷款金额不得超过现金价值的80%。",
            ),
        ),
        min_bm25_score=999.0,
    )

    assert result.selected_clause_ids == ("pledge-loan",)
    assert any(
        match.source_layer is EvidenceSourceLayer.BUSINESS_TERMS
        and loan_term in match.matched_values
        for match in result.matches
    )


def test_zero_bm25_score_never_creates_a_candidate() -> None:
    result = select_clause_evidence(
        (),
        "保单贷款比例",
        (_Clause("beneficiary", "4.1", "受益人", "可以指定受益人。"),),
        min_bm25_score=0.0,
    )

    assert result.selected_clause_ids == ()
    assert not any(
        match.source_layer is EvidenceSourceLayer.BM25
        for match in result.matches
    )


def test_fact_exact_and_controlled_related_candidates_are_preserved() -> None:
    clauses = (
        _Clause("fact", "2.1", "特别约定", "本合同有等待期。"),
        _Clause(
            "direct",
            "2.2",
            "等待期",
            "等待期为30日。",
            ("coverage.waiting_period",),
        ),
        _Clause(
            "related",
            "2.3",
            "保险期间",
            "保险期间为一年。",
            ("coverage.period",),
        ),
    )

    result = select_clause_evidence(
        ("coverage.waiting_period",),
        "等待期不得超过规定天数",
        clauses,
        fact_evidence_clause_ids=("fact",),
        fact_evidence=(FactEvidenceReference("has_waiting_period", "fact"),),
        min_bm25_score=999.0,
    )

    assert result.selected_clause_ids == ("fact", "direct", "related")
    assert {match.source_layer for match in result.matches} == {
        EvidenceSourceLayer.TRIGGER_FACT,
        EvidenceSourceLayer.EXACT_TOPIC,
        EvidenceSourceLayer.RELATED_TOPIC,
    }


def test_parent_body_is_not_expanded_and_complete_outline_is_retained() -> None:
    clauses = (
        _Clause(
            "parent",
            "2",
            "保险责任",
            "本章包含多项保险责任。",
            hierarchy_path="2 保险责任",
        ),
        _Clause(
            "child",
            "2.5",
            "等待期",
            "本责任等待期为30日。",
            ("coverage.waiting_period",),
            parent_number="2",
            ancestor_numbers=("2",),
            hierarchy_path="2 保险责任 / 2.5 等待期",
        ),
    )

    result = select_clause_evidence(
        ("coverage.waiting_period",),
        "等待期不得超过规定天数",
        clauses,
        min_bm25_score=999.0,
    )

    assert result.selected_clause_ids == ("child",)
    assert tuple(item.clause_id for item in result.full_outline) == (
        "parent",
        "child",
    )
    assert result.full_outline[1].parent_number == "2"
    assert result.full_outline[1].hierarchy_path.endswith("2.5 等待期")


def test_bm25_candidate_must_reach_minimum_score() -> None:
    clauses = (
        _Clause("notice", "5.1", "保险事故通知", "发生事故后应及时通知保险人。"),
        _Clause("beneficiary", "5.2", "受益人", "可以指定受益人。"),
    )

    accepted = select_clause_evidence(
        (),
        "保险事故发生后应及时通知",
        clauses,
        min_bm25_score=0.01,
    )
    rejected = select_clause_evidence(
        (),
        "保险事故发生后应及时通知",
        clauses,
        min_bm25_score=999.0,
    )

    assert accepted.selected_clause_ids == ("notice",)
    assert any(
        match.source_layer is EvidenceSourceLayer.BM25
        and match.score >= 0.01
        for match in accepted.matches
    )
    assert rejected.selected_clause_ids == ()


def test_one_topics_business_constraint_does_not_gate_other_topic_branch() -> None:
    waiting_clause = _Clause(
        "waiting-untagged",
        "2.1",
        "其他约定",
        "本合同等待期为三十日。",
    )
    clauses = (
        waiting_clause,
        _Clause("unrelated", "2.2", "其他约定", "可以指定受益人。"),
    )

    waiting_only = select_clause_evidence(
        ("coverage.waiting_period",),
        "等待期为三十日",
        clauses,
        min_bm25_score=0.01,
    )
    with_loan_topic = select_clause_evidence(
        ("coverage.waiting_period", "policy.loan"),
        "等待期为三十日",
        clauses,
        min_bm25_score=0.01,
    )

    assert waiting_only.selected_clause_ids == ("waiting-untagged",)
    assert with_loan_topic.selected_clause_ids == ("waiting-untagged",)
    assert not any(
        match.source_layer is EvidenceSourceLayer.BUSINESS_TERMS
        for match in with_loan_topic.matches
    )


def test_empty_container_is_outline_only_even_when_title_and_topic_match() -> None:
    container = _Clause(
        "waiting-parent",
        "2",
        "等待期",
        "",
        topics=("coverage.waiting_period",),
        container_only=True,
    )

    result = select_clause_evidence(
        ("coverage.waiting_period",),
        "等待期不得超过一百八十日",
        (container,),
        min_bm25_score=0.01,
    )

    assert result.selected_clause_ids == ()
    assert result.full_outline[0].clause_id == "waiting-parent"
