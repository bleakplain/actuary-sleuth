from dataclasses import dataclass
from typing import Tuple

from lib.common.compliance_audit import FactKind
from lib.common.product_tags import ProductTags
from lib.compliance.fact_extraction import extract_audit_facts


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
