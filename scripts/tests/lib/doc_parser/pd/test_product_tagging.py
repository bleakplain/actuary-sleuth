import pytest

from lib.common.product_tags import (
    ContractRole, CustomerScope, DiseasePaymentPattern, HealthTermClass,
    MedicalBenefitBasis, ProductDesignType, ProductLine, ProductSubtype,
    ProductTags, ProductTermClass, ProductTermForm, RenewalType, TagEvidence,
)
from lib.doc_parser.pd.product_name_recognizer import (
    _extract_felicity_text,
    recognize_product_name,
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
    assert tags.design_type is ProductDesignType.ORDINARY
    assert tags.is_internet_exclusive is True
    assert tags.is_rate_adjustable is True


def test_one_year_guaranteed_renewal_is_long_health():
    tags = build_product_tags(
        "某某长期医疗保险条款",
        "保险期间为1年。本合同保证续保。保证续保期间为20年。",
        complete_document=True,
    )

    assert tags.renewal_type is RenewalType.GUARANTEED
    assert tags.term_class is ProductTermClass.LONG_TERM
    assert tags.health_term_class is HealthTermClass.LONG_HEALTH
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms
    assert ProductTermForm.GUARANTEED_RENEWAL_PERIOD in tags.term_forms
    assert {
        (option.kind, option.value, option.unit)
        for option in tags.term_options
    } == {
        ("fixed_duration", 1.0, "year"),
        ("guaranteed_renewal_period", 20.0, "year"),
    }


def test_guaranteed_renewal_period_uses_definition_not_application_window():
    tags = build_product_tags(
        "人保健康附加互联网恶性肿瘤特定药品费用医疗保险条款",
        (
            "本附加险合同保险期间为1年。\n"
            "保证续保期间\n"
            "若投保人首次投保本保险，自合同生效日起，"
            "每 3 年为一个保证续保期间。\n"
            "保证续保期间届满时，投保人可在上一保险合同届满后的"
            "60日内向本公司提出续保申请。"
        ),
        complete_document=True,
    )

    assert {
        (option.value, option.unit)
        for option in tags.term_options
        if option.kind == "guaranteed_renewal_period"
    } == {(3.0, "year")}
    assert ProductTermForm.MULTIPLE_OPTIONS not in tags.term_forms


def test_chinese_numeral_one_year_is_short_without_guaranteed_renewal():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。本产品不保证续保。",
        complete_document=True,
    )

    assert tags.term_class is ProductTermClass.SHORT_TERM
    assert tags.health_term_class is HealthTermClass.SHORT_HEALTH
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms


def test_chinese_numeral_twenty_year_term_is_long():
    tags = build_product_tags("某某疾病保险条款", "保险期间为二十年。")

    assert tags.term_class is ProductTermClass.LONG_TERM
    assert ProductTermForm.OVER_ONE_YEAR in tags.term_forms


@pytest.mark.parametrize(
    ("duration", "expected"),
    (
        ("365日", ProductTermClass.UNKNOWN),
        ("366天", ProductTermClass.LONG_TERM),
        ("12个月", ProductTermClass.UNKNOWN),
        ("13月", ProductTermClass.LONG_TERM),
        ("一年", ProductTermClass.UNKNOWN),
        ("二年", ProductTermClass.LONG_TERM),
    ),
)
def test_term_thresholds_cover_day_month_and_year_units(duration, expected):
    tags = build_product_tags(
        "某某医疗保险条款",
        f"本合同保险期间为{duration}。",
    )

    assert tags.term_class is expected


def test_same_insurance_period_segment_keeps_all_term_options():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间可选择365日、366天、12个月、13个月、一年或二年。",
    )

    options = {
        (option.value, option.unit)
        for option in tags.term_options
        if option.kind == "fixed_duration"
    }
    assert options == {
        (365.0, "day"),
        (366.0, "day"),
        (12.0, "month"),
        (13.0, "month"),
        (1.0, "year"),
        (2.0, "year"),
    }
    assert ProductTermForm.MULTIPLE_OPTIONS in tags.term_forms
    assert tags.term_class is ProductTermClass.LONG_TERM


def test_incidental_durations_do_not_change_defined_insurance_period():
    tags = build_product_tags(
        "某某重大疾病保险条款",
        (
            "本合同保险期间为1年。"
            "保险期间届满后15天内可以重新投保。"
            "保险期间内确诊疾病的，确诊之日起2年内承担责任。"
            "退费按保险期间实际天数计算，不足一天按一天计算。"
            "本合同不保证续保，亦不承诺终身保障。"
        ),
        complete_document=True,
    )

    assert tags.term_class is ProductTermClass.SHORT_TERM
    assert {
        (option.value, option.unit)
        for option in tags.term_options
        if option.kind == "fixed_duration"
    } == {(1.0, "year")}
    assert ProductTermForm.WHOLE_LIFE not in tags.term_forms


def test_whole_life_requires_name_or_insurance_period_definition():
    from_name = build_product_tags("某某终身护理保险条款")
    from_clause = build_product_tags(
        "某某护理保险条款",
        "本合同保险期间为终身。",
    )

    assert from_name.term_class is ProductTermClass.LONG_TERM
    assert from_clause.term_class is ProductTermClass.LONG_TERM
    assert ProductTermForm.WHOLE_LIFE in from_clause.term_forms


@pytest.mark.parametrize(
    "content",
    (
        "保险期间：一年。",
        "保险期间由投保人与本公司约定，但最长不超过一年。",
    ),
)
def test_insurance_period_definition_variants_remain_supported(content):
    tags = build_product_tags("某某医疗保险条款", content)

    assert tags.term_class is ProductTermClass.UNKNOWN
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms


def test_chinese_to_age_is_a_long_term_option():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间至被保险人年满七十周岁或八十周岁。",
    )

    assert tags.term_class is ProductTermClass.LONG_TERM
    assert ProductTermForm.TO_AGE in tags.term_forms
    to_ages = {
        option.value
        for option in tags.term_options
        if option.kind == "to_age"
    }
    assert to_ages == {70.0, 80.0}


@pytest.mark.parametrize(
    ("name", "line", "subtype"),
    (
        ("养老护理年金保险", ProductLine.LIFE, ProductSubtype.ANNUITY),
        ("疾病身故定期寿险", ProductLine.LIFE, ProductSubtype.TERM_LIFE),
        (
            "意外伤害医疗保险",
            ProductLine.HEALTH,
            ProductSubtype.MEDICAL_ACCIDENT,
        ),
        (
            "附加出境人员团体意外医疗保险",
            ProductLine.HEALTH,
            ProductSubtype.MEDICAL_ACCIDENT,
        ),
    ),
)
def test_formal_product_type_suffix_wins_over_incidental_words(
    name,
    line,
    subtype,
):
    tags = build_product_tags(name)

    assert tags.line is line
    assert tags.primary_subtype is subtype


def test_explicit_health_design_type_is_not_overwritten_as_not_applicable():
    tags = build_product_tags("农民工团体护理保险（万能型）")

    assert tags.line is ProductLine.HEALTH
    assert tags.primary_subtype is ProductSubtype.NURSING
    assert tags.design_type is ProductDesignType.UNIVERSAL
    assert any(
        evidence.field_name == "design_type"
        and evidence.value == ProductDesignType.UNIVERSAL.value
        for evidence in tags.evidence
    )


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


def test_complete_one_year_document_without_renewal_is_short_health():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。",
        complete_document=True,
    )

    assert tags.renewal_type is RenewalType.NONE
    assert tags.term_class is ProductTermClass.SHORT_TERM
    assert tags.health_term_class is HealthTermClass.SHORT_HEALTH
    assert tags.is_tax_advantaged_health is False
    assert any(
        item.field_name == "renewal_type"
        and item.source == "document_coverage_attestation"
        for item in tags.evidence
    )


def test_incomplete_one_year_excerpt_keeps_health_term_unknown():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。",
        complete_document=False,
    )

    assert tags.term_class is ProductTermClass.UNKNOWN
    assert tags.health_term_class is HealthTermClass.UNKNOWN
    assert tags.renewal_type is RenewalType.UNKNOWN
    assert tags.is_tax_advantaged_health is None


def test_one_year_health_with_ambiguous_renewal_keeps_regulatory_term_unknown():
    tags = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。保险期间届满后可申请续保。",
        complete_document=True,
    )

    assert tags.renewal_type is RenewalType.UNKNOWN
    assert tags.term_class is ProductTermClass.UNKNOWN
    assert tags.health_term_class is HealthTermClass.UNKNOWN
    assert ProductTermForm.ONE_YEAR_OR_LESS in tags.term_forms


def test_name_term_conflict_keeps_both_sources():
    tags = build_product_tags(
        "某某短期医疗保险条款",
        "本合同保险期间为五年。",
        product_name_source="user_input",
        complete_document=True,
    )

    assert tags.term_class is ProductTermClass.LONG_TERM
    assert tags.health_term_class is HealthTermClass.LONG_HEALTH
    assert any("名称标示短期" in warning for warning in tags.warnings)
    evidence = {(item.field_name, item.value, item.source) for item in tags.evidence}
    assert ("term_class", "long_term", "product_clause") in evidence
    assert ("term_class_name_claim", "short_term", "user_input") in evidence


def test_tag_evidence_uses_context_around_late_document_matches():
    prefix = "普通约定。" * 40
    content = (
        f"{prefix}保险期间为二年。本产品不保证续保。"
        "本产品适用个人所得税优惠政策，"
        "并承担医疗费用保险金和护理保险金责任。"
    )

    tags = build_product_tags("某某医疗保险条款", content)
    evidence = {}
    for item in tags.evidence:
        evidence.setdefault(item.field_name, []).append(item.evidence)

    assert any("保险期间为二年" in text for text in evidence["term_class"])
    assert any("不保证续保" in text for text in evidence["renewal_type"])
    assert any(
        "个人所得税优惠" in text
        for text in evidence["is_tax_advantaged_health"]
    )
    assert any(
        "护理保险金" in text
        for text in evidence["coverage_components"]
    )


def test_regulation_book_title_is_not_mistaken_for_product_name():
    result = recognize_product_name([
        "依据《长期健康保险产品管理办法》制定本条款",
        "某某定期寿险条款",
    ])

    assert result.product_name == "某某定期寿险条款"
    regulation_only = recognize_product_name([
        "依据《长期健康保险产品管理办法》制定本条款",
    ])
    assert regulation_only.product_name is None


def test_generic_reading_notice_is_not_mistaken_for_product_name():
    result = recognize_product_name([
        "请您认真阅读保险条款，特别是责任免除和投保人义务",
        "1.1 保险合同构成",
    ])

    assert result.product_name is None


def test_product_name_subject_excludes_controlled_product_attributes():
    name = "人保健康悠优保互联网医疗保险（费率可调）条款"

    assert _extract_felicity_text(name) == "悠优保"
    result = recognize_product_name([
        f"125904《{name.removesuffix('条款')}》条款v4.doc",
    ])
    assert not any("超过法规上限" in warning for warning in result.warnings)


def test_non_health_product_marks_health_term_class_not_applicable():
    tags = build_product_tags(
        "人保健康互联网团体意外伤害保险（2025版）条款",
        "本合同保险期间为一年。",
        complete_document=True,
    )

    assert tags.line is ProductLine.ACCIDENT
    assert tags.term_class is ProductTermClass.SHORT_TERM
    assert tags.health_term_class is HealthTermClass.NOT_APPLICABLE


def test_product_name_supplies_primary_coverage_and_clause_adds_secondary():
    tags = build_product_tags(
        "某某医疗保险条款",
        "本合同另承担重大疾病保险金责任。",
    )

    assert tags.primary_subtype is ProductSubtype.MEDICAL
    assert tags.coverage_components == ("medical", "critical_illness")
    evidence = {
        (item.value, item.source)
        for item in tags.evidence
        if item.field_name == "coverage_components"
    }
    assert ("medical", "product_name") in evidence
    assert ("critical_illness", "product_clause") in evidence


def test_city_customized_identity_comes_from_product_name():
    city_product = build_product_tags(
        "人保健康城市定制型团体医疗保险（A款）条款",
        "普通保险责任。",
    )
    ordinary_product = build_product_tags(
        "人保健康互联网团体医疗保险条款",
        "被保险人应当参加某市基本医疗保险。",
    )

    assert city_product.is_city_customized_medical is True
    assert ordinary_product.is_city_customized_medical is False
    city_evidence = next(
        item
        for item in city_product.evidence
        if item.field_name == "is_city_customized_medical"
    )
    assert city_evidence.source == "product_name"
    assert "城市定制型" in city_evidence.evidence


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (
            "对实际发生的合理且必需的医疗费用，按约定给付比例给付。",
            MedicalBenefitBasis.EXPENSE_REIMBURSEMENT,
        ),
        (
            "住院津贴保险金按每日200元给付。",
            MedicalBenefitBasis.DAILY_ALLOWANCE,
        ),
        (
            "医疗意外身故保险金按本合同基本保险金额给付。",
            MedicalBenefitBasis.FIXED_BENEFIT,
        ),
        (
            "对实际发生的医疗费用按比例给付，并给付住院津贴保险金。",
            MedicalBenefitBasis.MIXED,
        ),
    ),
)
def test_medical_benefit_basis_uses_deterministic_clause_facts(
    content,
    expected,
):
    tags = build_product_tags("某某医疗保险条款", content)

    assert tags.medical_benefit_basis is expected


def test_disease_payment_pattern_extracts_single_and_multiple_payments():
    single = build_product_tags(
        "某某重大疾病保险条款",
        "本公司给付重大疾病保险金，同时对该被保险人的保险责任终止。",
    )
    multiple = build_product_tags(
        "某某重大疾病保险条款",
        "本产品提供多次给付，第二次重大疾病保险金按基本保额给付。",
    )
    not_applicable = build_product_tags(
        "某某医疗保险条款",
        "本合同仅承担医疗费用保险金责任。",
    )

    assert single.disease_payment_pattern is DiseasePaymentPattern.SINGLE
    assert multiple.disease_payment_pattern is DiseasePaymentPattern.MULTIPLE
    assert (
        not_applicable.disease_payment_pattern
        is DiseasePaymentPattern.NOT_APPLICABLE
    )


def test_complex_product_tags_have_controlled_chinese_display_labels():
    tags = build_product_tags(
        "某某长期医疗保险条款",
        (
            "保险期间为1年。本合同为保证续保产品，"
            "20年为一个保证续保期间。"
            "对实际发生的医疗费用按约定给付比例给付。"
        ),
        complete_document=True,
    )

    display = tags.to_dict()["display_labels"]

    assert display["term_forms"] == [
        "固定年期",
        "一年及以下",
        "保证续保期间",
    ]
    assert display["term_options"] == ["保险期间1年", "保证续保20年"]
    assert display["coverage_components"] == ["医疗责任"]
    assert display["medical_benefit_basis"] == "费用补偿型"
    assert display["disease_payment_pattern"] == "不适用"
    assert display["is_tax_advantaged_health"] == "否"
