from lib.common.product_tags import (
    ContractRole, CustomerScope, HealthTermClass, ProductLine, ProductSubtype,
    ProductTags, ProductTermClass, ProductTermForm, RenewalType, TagEvidence,
)
from lib.doc_parser.pd.product_tagging import build_product_tags


def test_name_controls_product_classification_and_binary_dimensions():
    tags = build_product_tags(
        "某某安心长期互联网费率可调医疗保险条款",
        "保险期间为一年。保证续保期间为二十年。",
    )

    assert tags.line is ProductLine.HEALTH
    assert tags.primary_subtype is ProductSubtype.MEDICAL
    assert tags.customer_scope is CustomerScope.INDIVIDUAL
    assert tags.contract_role is ContractRole.MAIN
    assert tags.is_internet_exclusive is True
    assert tags.is_rate_adjustable is True


def test_one_year_guaranteed_renewal_is_long_health():
    tags = build_product_tags(
        "某某长期医疗保险条款",
        "保险期间为1年。本合同保证续保。保证续保期间为20年。",
    )

    assert tags.renewal_type is RenewalType.GUARANTEED
    assert tags.term_class is ProductTermClass.LONG_TERM
    assert tags.health_term_class is HealthTermClass.LONG_HEALTH
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms


def test_chinese_numeral_one_year_is_short_without_guaranteed_renewal():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。本产品不保证续保。",
    )

    assert tags.term_class is ProductTermClass.SHORT_TERM
    assert tags.health_term_class is HealthTermClass.SHORT_HEALTH
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms


def test_chinese_numeral_twenty_year_term_is_long():
    tags = build_product_tags("某某疾病保险条款", "保险期间为二十年。")

    assert tags.term_class is ProductTermClass.LONG_TERM
    assert ProductTermForm.OVER_ONE_YEAR in tags.term_forms


def test_multiple_health_coverages_is_derived_not_an_input():
    tags = build_product_tags(
        "某某重大疾病保险条款",
        "重大疾病保险金；医疗费用保险金；身故保险金。",
    )

    assert tags.primary_subtype is ProductSubtype.CRITICAL_ILLNESS
    assert tags.multiple_health_coverages is True


def test_unknown_is_preserved_when_source_is_missing():
    tags = build_product_tags(None, "续保内容节选")

    assert tags.line is ProductLine.UNKNOWN
    assert tags.customer_scope is CustomerScope.UNKNOWN
    assert tags.is_internet_exclusive is None
    assert tags.is_tax_advantaged_health is None


def test_name_classification_is_kept_when_coverages_conflict():
    tags = build_product_tags(
        "某某医疗保险条款",
        "本合同仅承担重大疾病保险金责任。保险期间为一年。",
    )

    assert tags.primary_subtype is ProductSubtype.MEDICAL
    assert any("主要险种" in warning for warning in tags.warnings)


def test_product_tags_to_dict_serializes_evidence():
    evidence = TagEvidence("line", "health", "product_name", "某医疗保险", 1.0)

    result = ProductTags(evidence=(evidence,)).to_dict()

    assert result["evidence"] == [{
        "field_name": "line",
        "value": "health",
        "source": "product_name",
        "evidence": "某医疗保险",
        "confidence": 1.0,
    }]
    assert result["display_labels"]["line"] == "未知"
    assert result["display_labels"]["renewal_type"] == "未知"


def test_absence_of_word_does_not_prove_negative_tags():
    tags = build_product_tags("某某医疗保险条款", "保险期间为一年。")

    assert tags.renewal_type is RenewalType.UNKNOWN
    assert tags.is_tax_advantaged_health is None


def test_explicit_no_renewal_language_maps_to_none():
    tags = build_product_tags("某某医疗保险条款", "保险期间届满，本合同终止且不再续保。")

    assert tags.renewal_type is RenewalType.NONE


def test_prohibition_on_guaranteed_renewal_is_not_positive_guarantee():
    tags = build_product_tags("某某医疗保险条款", "本产品不得承诺保证续保。")

    assert tags.renewal_type is RenewalType.UNKNOWN


def test_tax_advantaged_requires_positive_clause_evidence():
    assert build_product_tags("某某税优健康保险条款", "普通保险责任。").is_tax_advantaged_health is None
    assert build_product_tags("某某健康保险条款", "本产品适用个人所得税优惠政策。").is_tax_advantaged_health is True


def test_contract_role_requires_explicit_insurance_name_boundary():
    assert build_product_tags("某某附加医疗保险条款").contract_role is ContractRole.RIDER
    assert build_product_tags("某某医疗保险条款").contract_role is ContractRole.MAIN
    assert build_product_tags("附加条款").contract_role is ContractRole.UNKNOWN
