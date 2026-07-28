import json

import pytest

from lib.common.product_tags import ClauseTopic
from lib.compliance.clause_routing import (
    ClauseRoute,
    ClauseRoutingInput,
    load_topic_relation_registry,
    route_product_clauses,
)
from lib.doc_parser.pd.clause_topics import (
    ClauseTopicConfigError,
    load_clause_topic_keywords,
    load_clause_topic_registry,
)


def _clause(clause_id: str, *topics: str) -> ClauseRoutingInput:
    return ClauseRoutingInput(clause_id=clause_id, topics=tuple(topics))


def test_registry_is_versioned_and_covers_enum_and_keyword_references():
    registry = load_clause_topic_registry()
    keywords = load_clause_topic_keywords(registry)

    assert registry.schema_version == "1.0.0"
    assert registry.codes == frozenset(topic.value for topic in ClauseTopic)
    assert set(keywords).issubset(registry.codes)


def test_renewal_routes_direct_related_unknown_and_fixture_controlled_exclusion():
    clauses = (
        _clause("direct", "renewal.non_guaranteed"),
        _clause("related", "coverage.period"),
        _clause("unknown"),
        _clause("excluded", "policy.beneficiary"),
    )

    result = route_product_clauses(("renewal.non_guaranteed",), clauses)

    assert result.config_valid
    assert result.topic_schema_version == "1.0.0"
    assert result.relation_schema_version == "1.0.0"
    assert [(item.clause_id, item.route) for item in result.items] == [
        ("direct", ClauseRoute.DIRECT),
        ("related", ClauseRoute.RELATED),
        ("unknown", ClauseRoute.UNKNOWN),
        ("excluded", ClauseRoute.NOT_RELEVANT),
    ]
    assert result.selected_clause_ids == ("direct", "related", "unknown")
    assert result.excluded_clause_ids == ("excluded",)
    assert result.items[-1].fixture_ids == ("renewal-beneficiary-v1",)


@pytest.mark.parametrize(
    ("regulation_topic", "clause_topic"),
    (
        ("renewal.general", "coverage.period"),
        ("coverage.period", "renewal.general"),
        ("coverage.exclusion", "coverage.responsibility"),
        ("coverage.waiting_period", "coverage.period"),
    ),
)
def test_first_controlled_relation_families_preserve_required_context(
    regulation_topic: str,
    clause_topic: str,
):
    result = route_product_clauses(
        (regulation_topic,),
        (_clause("related", clause_topic),),
    )

    assert result.items[0].route is ClauseRoute.RELATED
    assert result.selected_clause_ids == ("related",)


def test_uncovered_topic_pair_is_unknown_not_excluded():
    result = route_product_clauses(
        ("renewal.general",),
        (_clause("dividend", "policy.dividend"),),
    )

    assert result.items[0].route is ClauseRoute.UNKNOWN
    assert result.selected_clause_ids == ("dividend",)


def test_unknown_clause_topic_is_preserved():
    result = route_product_clauses(
        ("renewal.general",),
        (_clause("future", "future.topic"),),
    )

    assert result.items[0].route is ClauseRoute.UNKNOWN
    assert result.selected_clause_ids == ("future",)


def test_multi_topic_regulation_requires_every_pair_to_be_fixture_covered():
    excluded = route_product_clauses(
        ("renewal.general", "coverage.period"),
        (_clause("beneficiary", "policy.beneficiary"),),
    )
    retained = route_product_clauses(
        ("renewal.general", "coverage.exclusion"),
        (_clause("beneficiary", "policy.beneficiary"),),
    )

    assert excluded.items[0].route is ClauseRoute.NOT_RELEVANT
    assert retained.items[0].route is ClauseRoute.UNKNOWN


def test_missing_relation_file_degrades_every_clause_to_unknown(tmp_path):
    result = route_product_clauses(
        ("renewal.general",),
        (
            _clause("renewal", "renewal.general"),
            _clause("beneficiary", "policy.beneficiary"),
        ),
        relation_registry_path=tmp_path / "missing.json",
    )

    assert not result.config_valid
    assert {item.route for item in result.items} == {ClauseRoute.UNKNOWN}
    assert result.selected_clause_ids == ("renewal", "beneficiary")
    assert result.warnings


def test_incompatible_relation_version_degrades_to_unknown(tmp_path):
    path = tmp_path / "relations.json"
    path.write_text(json.dumps({
        "schema_version": "2.0.0",
        "topic_schema_version": "1.0.0",
        "relations": [],
    }), encoding="utf-8")

    result = route_product_clauses(
        ("renewal.general",),
        (_clause("beneficiary", "policy.beneficiary"),),
        relation_registry_path=path,
    )

    assert not result.config_valid
    assert result.items[0].route is ClauseRoute.UNKNOWN


def test_unknown_relation_reference_fails_strict_configuration_validation(tmp_path):
    path = tmp_path / "relations.json"
    path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "topic_schema_version": "1.0.0",
        "relations": [{
            "regulation_topic": "renewal.general",
            "related_topics": ["future.topic"],
            "not_relevant_topics": [],
        }],
    }), encoding="utf-8")

    with pytest.raises(ClauseTopicConfigError, match="未注册主题"):
        load_topic_relation_registry(load_clause_topic_registry(), path)


def test_keyword_reference_must_be_registered(tmp_path):
    path = tmp_path / "keywords.json"
    path.write_text(
        json.dumps({"future.topic": ["未来条款"]}),
        encoding="utf-8",
    )

    with pytest.raises(ClauseTopicConfigError, match="未注册主题"):
        load_clause_topic_keywords(load_clause_topic_registry(), path)
