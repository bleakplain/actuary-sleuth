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
