from lib.common.product_tags import (
    ProductLine,
    ProductSubtype,
    ProductTags,
    ProductTermClass,
    ProductTermForm,
    TagEvidence,
    TermOption,
)


def test_product_tags_round_trip_preserves_controlled_values() -> None:
    original = ProductTags(
        line=ProductLine.HEALTH,
        primary_subtype=ProductSubtype.MEDICAL,
        term_class=ProductTermClass.LONG_TERM,
        term_forms=(ProductTermForm.OVER_ONE_YEAR, ProductTermForm.TO_AGE),
        term_options=(TermOption(kind="fixed_duration", value=70.0, unit="year"),),
        is_rate_adjustable=True,
        is_specific_disease_product=False,
        mentions_out_of_hospital_drug=True,
        mentions_critical_illness_definition_term=False,
        is_increasing_sum_assured_product=True,
        is_cancer_specific_product=False,
        evidence=(
            TagEvidence(
                field_name="line",
                value="health",
                source="product_name",
                evidence="医疗保险",
                confidence=1.0,
            ),
        ),
    )

    restored = ProductTags.from_dict(original.to_dict())

    assert restored == original


def test_product_tags_from_dict_rejects_unknown_or_wrongly_typed_values() -> None:
    restored = ProductTags.from_dict({
        "line": "invented",
        "term_forms": 123,
        "is_rate_adjustable": "yes",
        "is_specific_disease_product": "yes",
        "mentions_out_of_hospital_drug": 1,
        "is_cancer_specific_product": [],
        "insured_age": {"minimum": True, "maximum": "70"},
        "display_labels": {"line": "伪造标签"},
    })

    assert restored.line is ProductLine.UNKNOWN
    assert restored.term_forms == ()
    assert restored.is_rate_adjustable is None
    assert restored.is_specific_disease_product is None
    assert restored.mentions_out_of_hospital_drug is None
    assert restored.mentions_critical_illness_definition_term is None
    assert restored.is_increasing_sum_assured_product is None
    assert restored.is_cancer_specific_product is None
    assert restored.insured_age_min is None
    assert restored.insured_age_max is None
