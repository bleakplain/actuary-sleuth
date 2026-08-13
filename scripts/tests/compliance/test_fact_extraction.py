from dataclasses import dataclass
from typing import Tuple

import pytest

from lib.common.compliance_audit import (
    FactKind,
    FactTruth,
    ProofStrategy,
    RegulationTriggerSpec,
    TriggerFactName,
    TriggerOperator,
)
from lib.common.constants import CoverageFactKeys
from lib.common.product_tags import ProductTags, TagEvidence
from lib.compliance.fact_extraction import (
    build_product_fact_ledger,
    extract_audit_facts,
)
from lib.doc_parser.pd.product_tagging import build_product_tags


@dataclass(frozen=True)
class _Block:
    clause_id: str
    title: str
    text: str
    topics: Tuple[str, ...] = ()


def _facts(text: str, title: str = ""):
    return extract_audit_facts(
        (_Block("c-1", title, text),),
        ProductTags(),
    )


def test_extracts_chinese_waiting_and_hesitation_periods() -> None:
    facts = _facts("等待期为一百八十日，犹豫期为十五天。")
    assert (FactKind.WAITING_PERIOD, "180", "day") in {
        (item.kind, item.value, item.unit) for item in facts
    }
    assert (FactKind.HESITATION_PERIOD, "15", "day") in {
        (item.kind, item.value, item.unit) for item in facts
    }


def test_waiting_period_does_not_capture_nearby_insurance_term() -> None:
    facts = _facts(
        "等待期自本合同生效日开始计算，保险期间为一年，等待期为30日。"
    )

    waiting = [item for item in facts if item.kind is FactKind.WAITING_PERIOD]
    assert [(item.value, item.unit) for item in waiting] == [("30", "day")]


def test_multiple_waiting_period_facts_are_preserved() -> None:
    facts = _facts(
        "疾病医疗责任等待期为30日；重大疾病责任等待期为180日。"
    )

    waiting = [item for item in facts if item.kind is FactKind.WAITING_PERIOD]
    assert {(item.value, item.unit) for item in waiting} == {
        ("30", "day"),
        ("180", "day"),
    }


def test_extracts_renewal_facts_without_forming_conclusion() -> None:
    facts = _facts("保险期间届满后可以申请续保，但本产品不保证续保。", "续保")
    assert {item.kind for item in facts} == {
        FactKind.RENEWAL_ARRANGEMENT,
        FactKind.NON_GUARANTEED_RENEWAL,
    }
    assert all(item.clause_id == "c-1" for item in facts)
    arrangement = next(
        item for item in facts if item.kind is FactKind.RENEWAL_ARRANGEMENT
    )
    assert arrangement.value == "available"


def test_negative_renewal_statement_is_not_recorded_as_present() -> None:
    facts = _facts("本产品不提供续保。", "续保")

    arrangement = next(
        item for item in facts if item.kind is FactKind.RENEWAL_ARRANGEMENT
    )
    assert arrangement.value == "none"


def test_conditional_renewal_keeps_both_available_and_none_facts() -> None:
    facts = _facts(
        "不符合续保条件时不得续保；符合续保条件时可以申请续保。",
        "续保",
    )

    values = {
        item.value
        for item in facts
        if item.kind is FactKind.RENEWAL_ARRANGEMENT
    }
    assert values == {"none", "available"}


def test_negated_prohibited_language_is_not_reported_as_fact() -> None:
    facts = _facts("本产品不得承诺续保，也不提供自动续保。")
    assert FactKind.PROHIBITED_RENEWAL_LANGUAGE not in {item.kind for item in facts}


def test_extracts_rate_adjustment_intervals_with_units() -> None:
    facts = _facts(
        "首次费率调整应在产品上市满三年后进行，"
        "相邻两次费率调整的时间间隔不得短于一年。",
        "费率调整",
    )
    values = {(item.kind, item.value, item.unit) for item in facts}
    assert (FactKind.FIRST_RATE_ADJUSTMENT_INTERVAL, "3", "year") in values
    assert (FactKind.SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL, "1", "year") in values


def test_rate_adjustable_identity_uses_product_name_evidence() -> None:
    from lib.doc_parser.pd.product_tagging import build_product_tags

    tags = build_product_tags("某某费率可调医疗保险", "")
    facts = extract_audit_facts((), tags)
    fact = next(item for item in facts if item.kind is FactKind.RATE_ADJUSTABLE)
    assert fact.value == "true"
    assert fact.clause_id == "product-name"


def test_product_fact_ledger_extracts_only_requested_facts_with_evidence() -> None:
    ledger = build_product_fact_ledger(
        (
            _Block(
                "c-waiting",
                "等待期",
                "自本合同生效之日起三十日为等待期。",
                ("coverage.waiting_period",),
            ),
        ),
        ProductTags(),
        (
            TriggerFactName.HAS_WAITING_PERIOD,
            TriggerFactName.WAITING_PERIOD_DAYS,
        ),
    )

    by_name = {item.name: item for item in ledger}
    assert tuple(by_name) == (
        TriggerFactName.HAS_WAITING_PERIOD,
        TriggerFactName.WAITING_PERIOD_DAYS,
    )
    assert by_name[TriggerFactName.HAS_WAITING_PERIOD].truth is FactTruth.TRUE
    assert by_name[TriggerFactName.HAS_WAITING_PERIOD].evidence[0].clause_id == (
        "c-waiting"
    )
    numeric = by_name[TriggerFactName.WAITING_PERIOD_DAYS]
    assert (numeric.truth, numeric.value, numeric.unit) == (
        FactTruth.TRUE,
        "30",
        "day",
    )
    assert not numeric.safe_for_exclusion


def test_zero_keyword_hit_stays_unknown_without_closed_scan_proof() -> None:
    ledger = build_product_fact_ledger(
        (_Block("c-cash", "现金价值", "本合同具有现金价值。"),),
        ProductTags(),
        (TriggerFactName.HAS_POLICY_LOAN,),
        complete_document=True,
    )

    fact = ledger[0]
    assert fact.truth is FactTruth.UNKNOWN
    assert not fact.safe_for_exclusion


@pytest.mark.parametrize(
    ("fact_name", "title", "text"),
    [
        (
            TriggerFactName.HAS_WAITING_PERIOD,
            "等待期",
            "本合同不设置等待期。",
        ),
        (
            TriggerFactName.HAS_HESITATION_PERIOD,
            "犹豫期",
            "本合同不设犹豫期。",
        ),
        (
            TriggerFactName.HAS_POLICY_LOAN,
            "保单贷款",
            "本合同不提供保单贷款。",
        ),
        (
            TriggerFactName.HAS_CASH_VALUE,
            "现金价值",
            "本合同无现金价值。",
        ),
        (
            TriggerFactName.HAS_GRACE_PERIOD,
            "宽限期",
            "本合同不设宽限期。",
        ),
        (
            TriggerFactName.HAS_RENEWAL,
            "续保",
            "本产品不提供续保。",
        ),
        (
            TriggerFactName.IS_RATE_ADJUSTABLE,
            "费率调整",
            "本产品费率不可调。",
        ),
        (
            TriggerFactName.HAS_DEATH_BENEFIT,
            "身故责任",
            "本产品不包含身故保险金责任。",
        ),
    ],
)
def test_explicit_negation_is_not_misclassified_as_presence(
    fact_name: TriggerFactName,
    title: str,
    text: str,
) -> None:
    fact = build_product_fact_ledger(
        (_Block("c-negative", title, text),),
        ProductTags(),
        (fact_name,),
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert not fact.safe_for_exclusion
    assert fact.proof_strategy is ProofStrategy.EXPLICIT_NEGATION
    assert fact.evidence[0].clause_id == "c-negative"


@pytest.mark.parametrize(
    ("fact_name", "title", "text"),
    [
        (
            TriggerFactName.HAS_POLICY_LOAN,
            "合同权益",
            "本合同无保单贷款手续费，投保人可以按现金价值的一定比例申请借款。",
        ),
        (
            TriggerFactName.HAS_CASH_VALUE,
            "现金价值",
            "本合同无现金价值最低保证，但保单实际具有现金价值。",
        ),
        (
            TriggerFactName.HAS_RENEWAL,
            "续保",
            "本产品不提供续保优惠，保险期间届满后可以申请续保。",
        ),
        (
            TriggerFactName.IS_RATE_ADJUSTABLE,
            "费率调整",
            "本产品费率不可调低，但公司有权调整保险费率。",
        ),
        (
            TriggerFactName.HAS_DEATH_BENEFIT,
            "保险责任",
            "本产品不包含身故保险金预支服务，但另行承担身故保险金责任。",
        ),
    ],
)
def test_negation_prefix_with_qualifier_is_not_safe_absence(
    fact_name: TriggerFactName,
    title: str,
    text: str,
) -> None:
    fact = build_product_fact_ledger(
        (_Block("c-qualified", title, text),),
        ProductTags(),
        (fact_name,),
    )[0]

    assert fact.truth is not FactTruth.FALSE
    assert not fact.safe_for_exclusion


def test_rate_fixed_for_limited_period_is_not_safe_non_adjustable_proof() -> None:
    fact = build_product_fact_ledger(
        (_Block(
            "c-rate-window",
            "费率调整",
            "保证续保期间内前3年费率固定，此后可根据赔付经验调整。",
            ("premium.rate_adjustment", "renewal.guaranteed"),
        ),),
        build_product_tags("某某医疗保险", ""),
        (TriggerFactName.IS_RATE_ADJUSTABLE,),
    )[0]

    assert fact.truth is not FactTruth.FALSE
    assert not fact.safe_for_exclusion


def test_waiting_period_self_description_cannot_hide_actual_waiting_design() -> None:
    fact = build_product_fact_ledger(
        (_Block(
            "c-hidden-waiting",
            "保险责任",
            "本产品无等待期，但被保险人自合同生效之日起90日内"
            "发生疾病，本公司不承担保险责任。",
        ),),
        ProductTags(),
        (TriggerFactName.HAS_WAITING_PERIOD,),
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert not fact.safe_for_exclusion


def test_scoped_death_exclusion_cannot_prove_no_death_benefit() -> None:
    fact = build_product_fact_ledger(
        (_Block(
            "c-death-scope",
            "保险责任",
            "本合同不承担意外身故责任；被保险人因疾病导致死亡的，"
            "按已交保险费进行赔付。",
        ),),
        ProductTags(),
        (TriggerFactName.HAS_DEATH_BENEFIT,),
    )[0]

    assert fact.truth is not FactTruth.FALSE
    assert not fact.safe_for_exclusion


def test_conflicting_positive_and_negative_product_facts_stay_unknown() -> None:
    fact = build_product_fact_ledger(
        (_Block(
            "c-waiting-conflict",
            "等待期",
            "一般医疗责任不设置等待期，疾病医疗责任等待期为30日。",
        ),),
        ProductTags(),
        (TriggerFactName.HAS_WAITING_PERIOD,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert fact.method == "conflict"
    assert not fact.safe_for_exclusion


def test_literal_mention_fact_stays_true_inside_prohibition() -> None:
    fact = build_product_fact_ledger(
        (_Block(
            "c-drug-prohibition",
            "保险责任",
            "本产品不包含院外购药责任。",
        ),),
        ProductTags(),
        (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
    )[0]

    assert fact.truth is FactTruth.TRUE
    assert not fact.safe_for_exclusion


def test_closed_scan_tag_false_cannot_override_normalized_phrase_match() -> None:
    content = "被保险人可在指定药 店购买药品。"
    tags = build_product_tags(
        "测试医疗保险",
        content,
        complete_document=True,
    )
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )

    fact = build_product_fact_ledger(
        (_Block("c-drug", "购药", content),),
        tags,
        (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
        complete_document=True,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert not fact.safe_for_exclusion


def test_renewal_whitespace_cannot_be_used_as_safe_absence() -> None:
    content = "保险期间届满后，投保人可以申请续 保。"
    tags = build_product_tags(
        "测试医疗保险",
        content,
        complete_document=True,
    )

    fact = build_product_fact_ledger(
        (_Block("c-renewal", "合同届满", content),),
        tags,
        (TriggerFactName.HAS_RENEWAL,),
        complete_document=True,
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert not fact.safe_for_exclusion


def test_document_tag_evidence_is_bound_back_to_real_clause_id() -> None:
    quote = "恶性肿瘤——重度"
    tags = ProductTags(
        mentions_critical_illness_definition_term=True,
        evidence=(TagEvidence(
            field_name="mentions_critical_illness_definition_term",
            value="true",
            source="product_clause",
            evidence=quote,
            confidence=1.0,
        ),),
    )

    fact = build_product_fact_ledger(
        (_Block("c-disease", "疾病定义", f"本条定义{quote}。"),),
        tags,
        (TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM,),
    )[0]

    assert fact.truth is FactTruth.TRUE
    assert fact.evidence[0].clause_id == "c-disease"


def test_complete_closed_phrase_scan_can_safely_prove_false() -> None:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )

    fact = build_product_fact_ledger(
        (_Block("c-cash", "现金价值", "本合同具有现金价值。"),),
        ProductTags(),
        (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
        complete_document=True,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert fact.safe_for_exclusion
    assert fact.method == "closed_phrase_scan"


def test_incomplete_document_never_uses_closed_scan_to_prove_false() -> None:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )

    fact = build_product_fact_ledger(
        (), ProductTags(), (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
        complete_document=False,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert not fact.safe_for_exclusion


def test_open_world_function_cannot_use_zero_phrase_hit_for_exclusion() -> None:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.HAS_POLICY_LOAN,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("保单贷款", "保单借款"),
    )

    fact = build_product_fact_ledger(
        (_Block("c-cash", "现金价值", "本合同具有现金价值。"),),
        ProductTags(),
        (TriggerFactName.HAS_POLICY_LOAN,),
        complete_document=True,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert not fact.safe_for_exclusion


def test_closed_scan_normalizes_whitespace_before_proving_absence() -> None:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )

    fact = build_product_fact_ledger(
        (_Block("c-drug", "购药", "被保险人可在指定药 店购买药品。"),),
        ProductTags(),
        (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
        complete_document=True,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.TRUE
    assert not fact.safe_for_exclusion


@pytest.mark.parametrize("separator", ("\u200b", "\u00ad", "\u180e"))
def test_closed_scan_normalizes_unicode_format_characters(separator: str) -> None:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )

    fact = build_product_fact_ledger(
        (_Block("c-drug", "购药", f"被保险人可在指定地点院外{separator}购药。"),),
        ProductTags(),
        (TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,),
        complete_document=True,
        trigger_specs=(spec,),
    )[0]

    assert fact.truth is FactTruth.TRUE
    assert not fact.safe_for_exclusion


def test_rate_name_classification_false_cannot_exclude_actual_design_rule() -> None:
    tags = ProductTags(
        is_rate_adjustable=False,
        evidence=(TagEvidence(
            field_name="is_rate_adjustable",
            value="false",
            source="product_name",
            evidence="测试医疗保险",
            confidence=1.0,
        ),),
    )

    fact = build_product_fact_ledger(
        (), tags, (TriggerFactName.IS_RATE_ADJUSTABLE,),
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert not fact.safe_for_exclusion
    assert fact.evidence[0].clause_id == "product-name"
    assert fact.proof_strategy is None


def test_rate_adjustment_clause_conflicts_with_negative_name_tag() -> None:
    content = "公司可以根据整体赔付经验重新厘定保险费。"
    tags = build_product_tags(
        "测试医疗保险",
        content,
        complete_document=True,
    )

    fact = build_product_fact_ledger(
        (_Block("c-rate", "保险费", content),),
        tags,
        (TriggerFactName.IS_RATE_ADJUSTABLE,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert fact.method == "conflict"
    assert not fact.safe_for_exclusion


def test_renewal_absence_attestation_is_not_an_explicit_negation() -> None:
    tags = build_product_tags(
        "测试医疗保险",
        "本合同保险期间为一年。",
        complete_document=True,
    )

    fact = build_product_fact_ledger(
        (_Block("c-period", "保险期间", "本合同保险期间为一年。"),),
        tags,
        (TriggerFactName.HAS_RENEWAL,),
        complete_document=True,
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert not fact.safe_for_exclusion


def test_explicit_no_renewal_clause_is_evidence_but_not_safe_exclusion() -> None:
    content = "本产品不提供续保。"
    tags = build_product_tags(
        "测试医疗保险",
        content,
        complete_document=True,
    )

    fact = build_product_fact_ledger(
        (_Block("c-renewal-none", "续保", content),),
        tags,
        (TriggerFactName.HAS_RENEWAL,),
        complete_document=True,
    )[0]

    assert fact.truth is FactTruth.FALSE
    assert not fact.safe_for_exclusion
    assert fact.proof_strategy is ProofStrategy.EXPLICIT_NEGATION


def test_conflicting_tag_and_clause_signal_downgrades_to_unknown() -> None:
    tags = ProductTags(
        is_rate_adjustable=False,
        evidence=(TagEvidence(
            field_name="is_rate_adjustable",
            value="false",
            source="product_name",
            evidence="测试医疗保险",
            confidence=1.0,
        ),),
    )

    fact = build_product_fact_ledger(
        (_Block("c-rate", "费率调整", "本产品为费率可调产品。"),),
        tags,
        (TriggerFactName.IS_RATE_ADJUSTABLE,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert fact.method == "conflict"
    assert not fact.safe_for_exclusion


def test_multiple_numeric_values_stay_unknown_without_unsafe_aggregation() -> None:
    fact = build_product_fact_ledger(
        (
            _Block(
                "c-waiting",
                "等待期",
                "疾病医疗等待期为30日；重大疾病等待期为180日。",
            ),
        ),
        ProductTags(),
        (TriggerFactName.WAITING_PERIOD_DAYS,),
    )[0]

    assert fact.truth is FactTruth.UNKNOWN
    assert fact.method == "numeric_fact_conflict"
    assert {item.clause_id for item in fact.evidence} == {"c-waiting"}


def test_closed_scan_uses_matching_per_fact_coverage_only() -> None:
    out_of_hospital_spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )
    critical_illness_spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("重大疾病",),
    )

    facts = build_product_fact_ledger(
        (_Block("c-medical", "保险责任", "承担住院医疗费用。"),),
        ProductTags(),
        (
            TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
            TriggerFactName.MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM,
        ),
        complete_document=False,
        coverage_attested_facts=(
            CoverageFactKeys.OUT_OF_HOSPITAL_DRUG_TEXT,
        ),
        trigger_specs=(out_of_hospital_spec, critical_illness_spec),
    )

    assert facts[0].truth is FactTruth.FALSE
    assert facts[0].safe_for_exclusion
    assert facts[0].complete_document_proof
    assert facts[1].truth is FactTruth.UNKNOWN
    assert not facts[1].safe_for_exclusion
