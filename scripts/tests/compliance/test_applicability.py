from lib.common.product_tags import (
    ContractRole,
    CustomerScope,
    ProductLine,
    ProductDesignType,
    ProductSubtype,
    ProductTags,
    ProductTermClass,
    RenewalType,
)
from lib.compliance.applicability import (
    MatchStatus,
    RegulationApplicability,
    match_regulation_applicability,
)
from lib.doc_parser.pd.product_tagging import build_product_tags


def _health_product(**overrides) -> ProductTags:
    values = {
        "line": ProductLine.HEALTH,
        "primary_subtype": ProductSubtype.MEDICAL,
        "term_class": ProductTermClass.SHORT_TERM,
        "customer_scope": CustomerScope.INDIVIDUAL,
        "contract_role": ContractRole.MAIN,
    }
    values.update(overrides)
    return ProductTags(**values)


def test_empty_regulation_dimensions_are_unrestricted():
    result = match_regulation_applicability(_health_product(), RegulationApplicability())

    assert result.status is MatchStatus.APPLICABLE
    assert not result.excluded_by


def test_values_within_same_dimension_are_or():
    regulation = RegulationApplicability(lines=frozenset({"health", "accident"}))

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.APPLICABLE
    assert result.matched_dimensions == ("line",)


def test_different_dimensions_are_and_and_conflict_excludes():
    regulation = RegulationApplicability(
        lines=frozenset({"health"}),
        contract_roles=frozenset({"rider"}),
    )

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.NOT_APPLICABLE
    assert result.excluded_by == ("contract_role",)


def test_subtype_constraint_excludes_different_known_subtype():
    regulation = RegulationApplicability(subtypes=frozenset({"nursing"}))

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.NOT_APPLICABLE
    assert result.excluded_by == ("subtype",)


def test_unknown_product_value_is_indeterminate_not_excluded():
    product = _health_product(term_class=ProductTermClass.UNKNOWN)
    regulation = RegulationApplicability(term_classes=frozenset({"short_term"}))

    result = match_regulation_applicability(product, regulation)

    assert result.status is MatchStatus.INDETERMINATE
    assert result.indeterminate_dimensions == ("term_class",)


def test_explicit_special_feature_false_excludes_and_none_is_indeterminate():
    regulation = RegulationApplicability(special_features=frozenset({"internet_exclusive"}))

    excluded = match_regulation_applicability(
        _health_product(is_internet_exclusive=False), regulation,
    )
    unknown = match_regulation_applicability(
        _health_product(is_internet_exclusive=None), regulation,
    )

    assert excluded.status is MatchStatus.NOT_APPLICABLE
    assert unknown.status is MatchStatus.INDETERMINATE


def test_special_features_within_same_dimension_are_or():
    regulation = RegulationApplicability(
        special_features=frozenset({"internet_exclusive", "rate_adjustable"}),
    )

    result = match_regulation_applicability(
        _health_product(
            is_internet_exclusive=True,
            is_rate_adjustable=False,
        ),
        regulation,
    )

    assert result.status is MatchStatus.APPLICABLE
    assert "special_feature" in result.matched_dimensions
    assert "special_feature" not in result.excluded_by


def test_explicit_conflict_wins_over_an_unknown_dimension():
    product = _health_product(
        line=ProductLine.LIFE,
        term_class=ProductTermClass.UNKNOWN,
    )
    regulation = RegulationApplicability(
        lines=frozenset({"health"}),
        term_classes=frozenset({"short_term"}),
    )

    result = match_regulation_applicability(product, regulation)

    assert result.status is MatchStatus.NOT_APPLICABLE
    assert "line" in result.excluded_by
    assert "term_class" in result.indeterminate_dimensions


def test_not_applicable_design_is_known_and_excludes_designed_product_rule():
    product = _health_product(design_type=ProductDesignType.NOT_APPLICABLE)
    regulation = RegulationApplicability(design_types=frozenset({"ordinary"}))

    result = match_regulation_applicability(product, regulation)

    assert result.status is MatchStatus.NOT_APPLICABLE
    assert result.excluded_by == ("design_type",)


def test_metadata_parser_groups_tags_topics_and_unknown_values():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": (
            "health,medical,short_term,main,has_renewal,"
            "internet_exclusive,future_tag"
        ),
        "条款主题": "renewal.general,renewal.non_guaranteed",
    })

    assert regulation.lines == {"health"}
    assert regulation.subtypes == {"medical"}
    assert regulation.term_classes == {"short_term"}
    assert regulation.contract_roles == {"main"}
    assert regulation.renewal_conditions == {"has_renewal"}
    assert regulation.special_features == {"internet_exclusive"}
    assert regulation.clause_topics == {"renewal.general", "renewal.non_guaranteed"}
    assert regulation.unknown_tags == {"future_tag"}


def test_metadata_parser_separates_risk_triggers_and_check_targets():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health,medical,long_term",
        "风险触发标签": "rate_adjustable,future_trigger",
        "检查目标标签": "long_term,rate_adjustment_interval",
    })

    assert regulation.term_classes == {"long_term"}
    assert regulation.risk_triggers == {"rate_adjustable", "future_trigger"}
    assert regulation.normative_requirements == {
        "long_term",
        "rate_adjustment_interval",
    }
    assert regulation.unknown_tags == set()
    assert regulation.unknown_risk_triggers == {"future_trigger"}


def test_fact_trigger_prevents_old_subject_tag_from_excluding_early():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health",
        "触发事实": "has_renewal",
    })
    life_product = ProductTags(
        line=ProductLine.LIFE,
        renewal_type=RenewalType.GUARANTEED,
    )

    result = match_regulation_applicability(life_product, regulation)

    assert regulation.has_fact_triggers
    assert result.status is MatchStatus.INDETERMINATE
    assert result.excluded_by == ()
    assert "fact_trigger" in result.indeterminate_dimensions


def test_old_subject_tag_still_excludes_without_fact_trigger():
    regulation = RegulationApplicability.from_metadata({"适用标签": "health"})
    life_product = ProductTags(
        line=ProductLine.LIFE,
        renewal_type=RenewalType.GUARANTEED,
    )

    result = match_regulation_applicability(life_product, regulation)

    assert not regulation.has_fact_triggers
    assert result.status is MatchStatus.NOT_APPLICABLE
    assert result.excluded_by == ("line",)


def test_numbered_fact_trigger_metadata_also_prevents_early_exclusion():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health",
        "触发事实2": "has_renewal",
    })

    result = match_regulation_applicability(
        ProductTags(line=ProductLine.LIFE),
        regulation,
    )

    assert regulation.has_fact_triggers
    assert result.status is MatchStatus.INDETERMINATE


def test_incomplete_fact_trigger_metadata_prevents_early_exclusion():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health",
        "触发运算符": "exists",
        "证明策略": "explicit_negation",
    })

    result = match_regulation_applicability(
        ProductTags(line=ProductLine.LIFE),
        regulation,
    )

    assert regulation.has_fact_triggers
    assert result.status is MatchStatus.INDETERMINATE
    assert result.excluded_by == ()


def test_critical_illness_definition_term_risk_trigger_is_three_state():
    regulation = RegulationApplicability.from_metadata({
        "风险触发标签": "critical_illness_definition_term",
    })

    assert match_regulation_applicability(
        _health_product(mentions_critical_illness_definition_term=True),
        regulation,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        _health_product(mentions_critical_illness_definition_term=False),
        regulation,
    ).status is MatchStatus.NOT_APPLICABLE
    assert match_regulation_applicability(
        _health_product(mentions_critical_illness_definition_term=None),
        regulation,
    ).status is MatchStatus.INDETERMINATE


def test_increasing_whole_life_requires_all_three_strict_dimensions():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "life,whole_life,increasing_sum_assured",
    })

    assert match_regulation_applicability(
        ProductTags(
            line=ProductLine.LIFE,
            primary_subtype=ProductSubtype.WHOLE_LIFE,
            is_increasing_sum_assured_product=True,
        ),
        regulation,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        ProductTags(
            line=ProductLine.LIFE,
            primary_subtype=ProductSubtype.ENDOWMENT,
            is_increasing_sum_assured_product=True,
        ),
        regulation,
    ).status is MatchStatus.NOT_APPLICABLE
    assert match_regulation_applicability(
        ProductTags(
            line=ProductLine.LIFE,
            primary_subtype=ProductSubtype.WHOLE_LIFE,
            is_increasing_sum_assured_product=None,
        ),
        regulation,
    ).status is MatchStatus.INDETERMINATE


def test_other_health_scope_excludes_disease_family_but_keeps_unknown():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": (
            "health,medical,disability_income,nursing,medical_accident,other_health"
        ),
    })

    assert match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.MEDICAL), regulation,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.NURSING), regulation,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.DISEASE), regulation,
    ).status is MatchStatus.NOT_APPLICABLE
    assert match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.CRITICAL_ILLNESS), regulation,
    ).status is MatchStatus.NOT_APPLICABLE
    assert match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.UNKNOWN), regulation,
    ).status is MatchStatus.INDETERMINATE


def test_guaranteed_and_non_guaranteed_are_strict_renewal_conditions():
    guaranteed = RegulationApplicability.from_metadata({
        "适用标签": "health,guaranteed_renewal",
    })
    non_guaranteed = RegulationApplicability.from_metadata({
        "适用标签": "health,non_guaranteed_renewal",
    })

    assert match_regulation_applicability(
        _health_product(renewal_type=RenewalType.GUARANTEED), guaranteed,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        _health_product(renewal_type=RenewalType.NON_GUARANTEED), guaranteed,
    ).status is MatchStatus.NOT_APPLICABLE
    assert match_regulation_applicability(
        _health_product(renewal_type=RenewalType.NON_GUARANTEED), non_guaranteed,
    ).status is MatchStatus.APPLICABLE


def test_unknown_risk_trigger_bypasses_conflict_as_indeterminate():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "life",
        "风险触发标签": "future_trigger",
    })

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.INDETERMINATE
    assert result.excluded_by == ()
    assert "risk_trigger" in result.indeterminate_dimensions


def test_unknown_risk_trigger_does_not_downgrade_matched_subject():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health",
        "风险触发标签": "future_trigger",
    })

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.APPLICABLE
    assert result.indeterminate_dimensions == ()
    assert any("未识别风险触发标签" in reason for reason in result.reasons)


def test_risk_trigger_bypasses_conflicting_subject_for_abnormal_product():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health,medical,long_term",
        "风险触发标签": "rate_adjustable",
        "检查目标标签": "long_term",
    })
    product = _health_product(
        term_class=ProductTermClass.SHORT_TERM,
        is_rate_adjustable=True,
    )

    result = match_regulation_applicability(product, regulation)

    assert result.status is MatchStatus.APPLICABLE
    assert "risk_trigger" in result.matched_dimensions
    assert result.excluded_by == ()
    assert any("检查目标标签仅供审核判断" in reason for reason in result.reasons)


def test_risk_trigger_unknown_keeps_conflicting_subject_indeterminate():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health,medical,long_term",
        "风险触发标签": "rate_adjustable",
    })

    result = match_regulation_applicability(
        _health_product(
            term_class=ProductTermClass.SHORT_TERM,
            is_rate_adjustable=None,
        ),
        regulation,
    )

    assert result.status is MatchStatus.INDETERMINATE
    assert "risk_trigger" in result.indeterminate_dimensions
    assert result.excluded_by == ()


def test_subject_match_does_not_require_optional_risk_trigger():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health,medical,long_term",
        "风险触发标签": "rate_adjustable",
    })

    result = match_regulation_applicability(
        _health_product(
            term_class=ProductTermClass.LONG_TERM,
            is_rate_adjustable=False,
        ),
        regulation,
    )

    assert result.status is MatchStatus.APPLICABLE
    assert result.excluded_by == ()


def test_trigger_only_rule_uses_three_state_product_fact():
    regulation = RegulationApplicability.from_metadata({
        "风险触发标签": "specific_disease",
    })

    matched = match_regulation_applicability(
        _health_product(is_specific_disease_product=True),
        regulation,
    )
    excluded = match_regulation_applicability(
        _health_product(is_specific_disease_product=False),
        regulation,
    )
    unknown = match_regulation_applicability(
        _health_product(is_specific_disease_product=None),
        regulation,
    )

    assert matched.status is MatchStatus.APPLICABLE
    assert excluded.status is MatchStatus.NOT_APPLICABLE
    assert excluded.excluded_by == ("risk_trigger",)
    assert unknown.status is MatchStatus.INDETERMINATE


def test_out_of_hospital_trigger_uses_clause_mention_fact():
    regulation = RegulationApplicability.from_metadata({
        "风险触发标签": "out_of_hospital_drug",
    })

    matched = match_regulation_applicability(
        _health_product(mentions_out_of_hospital_drug=True),
        regulation,
    )
    excluded = match_regulation_applicability(
        _health_product(mentions_out_of_hospital_drug=False),
        regulation,
    )
    unknown = match_regulation_applicability(
        _health_product(mentions_out_of_hospital_drug=None),
        regulation,
    )

    assert matched.status is MatchStatus.APPLICABLE
    assert excluded.status is MatchStatus.NOT_APPLICABLE
    assert unknown.status is MatchStatus.INDETERMINATE


def test_guaranteed_renewal_trigger_can_retain_life_product():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health",
        "风险触发标签": "guaranteed_renewal",
    })
    product = ProductTags(
        line=ProductLine.LIFE,
        primary_subtype=ProductSubtype.WHOLE_LIFE,
        renewal_type=RenewalType.GUARANTEED,
    )

    result = match_regulation_applicability(product, regulation)

    assert result.status is MatchStatus.APPLICABLE
    assert "risk_trigger" in result.matched_dimensions
    assert result.excluded_by == ()


def test_critical_illness_matches_disease_parent_but_not_reverse():
    disease_rule = RegulationApplicability(subtypes=frozenset({"disease"}))
    critical_rule = RegulationApplicability(
        subtypes=frozenset({"critical_illness"}),
    )

    critical = match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.CRITICAL_ILLNESS),
        disease_rule,
    )
    disease = match_regulation_applicability(
        _health_product(primary_subtype=ProductSubtype.DISEASE),
        critical_rule,
    )

    assert critical.status is MatchStatus.APPLICABLE
    assert disease.status is MatchStatus.NOT_APPLICABLE


def test_renewal_condition_requires_a_known_renewal_responsibility():
    regulation = RegulationApplicability.from_metadata({
        "适用标签": "health,short_term,individual,has_renewal",
    })

    matching = match_regulation_applicability(
        _health_product(renewal_type=RenewalType.NON_GUARANTEED),
        regulation,
    )
    excluded = match_regulation_applicability(
        _health_product(renewal_type=RenewalType.NONE),
        regulation,
    )
    unknown = match_regulation_applicability(
        _health_product(renewal_type=RenewalType.UNKNOWN),
        regulation,
    )

    assert matching.status is MatchStatus.APPLICABLE
    assert "renewal_condition" in matching.matched_dimensions
    assert excluded.status is MatchStatus.NOT_APPLICABLE
    assert excluded.excluded_by == ("renewal_condition",)
    assert unknown.status is MatchStatus.INDETERMINATE
    assert unknown.indeterminate_dimensions == ("renewal_condition",)


def test_related_tags_do_not_constrain_applicability():
    regulation = RegulationApplicability.from_metadata({
        "涉及标签": "health,nursing",
        "适用标签": "health,nursing",
        "适用标签语义": "涉及",
    })

    result = match_regulation_applicability(_health_product(), regulation)

    assert result.status is MatchStatus.APPLICABLE
    assert regulation.lines == frozenset()
    assert regulation.subtypes == frozenset()


def test_one_year_guaranteed_health_product_keeps_long_term_regulations():
    product = build_product_tags(
        "某某长期医疗保险条款",
        "保险期间为1年。本合同保证续保。保证续保期间为20年。",
        complete_document=True,
    )
    long_term_rule = RegulationApplicability(
        lines=frozenset({"health"}),
        term_classes=frozenset({"long_term"}),
    )
    short_term_rule = RegulationApplicability(
        lines=frozenset({"health"}),
        term_classes=frozenset({"short_term"}),
    )

    assert match_regulation_applicability(
        product,
        long_term_rule,
    ).status is MatchStatus.APPLICABLE
    assert match_regulation_applicability(
        product,
        short_term_rule,
    ).status is MatchStatus.NOT_APPLICABLE


def test_one_year_health_with_unknown_renewal_keeps_both_term_rules():
    product = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。保险期间届满后可申请续保。",
        complete_document=True,
    )
    long_term_rule = RegulationApplicability(
        lines=frozenset({"health"}),
        term_classes=frozenset({"long_term"}),
    )
    short_term_rule = RegulationApplicability(
        lines=frozenset({"health"}),
        term_classes=frozenset({"short_term"}),
    )

    assert product.term_class is ProductTermClass.UNKNOWN
    assert match_regulation_applicability(
        product,
        long_term_rule,
    ).status is MatchStatus.INDETERMINATE
    assert match_regulation_applicability(
        product,
        short_term_rule,
    ).status is MatchStatus.INDETERMINATE


def test_ordinary_health_product_keeps_ordinary_regulations():
    product = build_product_tags(
        "某某医疗保险条款",
        "保险期间为一年。",
        complete_document=True,
    )
    regulation = RegulationApplicability(
        lines=frozenset({"health"}),
        subtypes=frozenset({"medical"}),
        design_types=frozenset({"ordinary"}),
    )

    assert product.design_type is ProductDesignType.ORDINARY
    assert match_regulation_applicability(
        product,
        regulation,
    ).status is MatchStatus.APPLICABLE
