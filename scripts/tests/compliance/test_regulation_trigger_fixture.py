import json
from pathlib import Path

from lib.common.compliance_audit import AuditClauseSnapshot, TriggerFactName
from lib.common.product_tags import ProductTags
from lib.compliance.clause_evidence import select_clause_evidence
from lib.compliance.fact_extraction import build_product_fact_ledger
from lib.compliance.regulation_trigger_metadata import (
    parse_regulation_trigger_metadata,
)
from lib.compliance.regulation_triggers import evaluate_regulation_triggers


_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "compliance_trigger"
    / "v1"
    / "regulation-trigger-cases.json"
)


def _metadata(raw: dict[str, object]) -> dict[str, object]:
    return {
        "触发事实": raw.get("fact_name"),
        "触发运算符": raw.get("operator"),
        "触发期望值": raw.get("expected_value"),
        "目标条款主题": raw.get("target_topics", ()),
        "所需事实": raw.get("required_facts", ()),
        "证明策略": raw.get("proof_strategy"),
        "检索必含词组": raw.get("search_all_terms", ()),
        "检索任一词组": raw.get("search_any_terms", ()),
    }


def test_engineering_trigger_fixture_runs_through_metadata_fact_and_evidence() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        specs = parse_regulation_trigger_metadata(_metadata(case["trigger"]))
        clauses = tuple(
            AuditClauseSnapshot(
                clause_id=raw["clause_id"],
                number=raw["number"],
                title=raw["title"],
                text=raw["text"],
                block_type="clause",
                topics=tuple(raw["topics"]),
            )
            for raw in case["product_clauses"]
        )
        required_names = tuple(dict.fromkeys(
            fact_name
            for spec in specs
            for fact_name in (spec.fact_name, *spec.required_facts)
        ))
        ledger = build_product_fact_ledger(
            clauses,
            ProductTags(),
            required_names,
            complete_document=case.get("complete_document", False),
            trigger_specs=specs,
        )
        evaluation = evaluate_regulation_triggers(
            specs,
            {fact.name: fact for fact in ledger},
        )

        assert evaluation.status.value == case["expected_trigger_status"]
        assert set(evaluation.evidence_clause_ids) == set(
            case["expected_evidence_clause_ids"]
        )
        selection = select_clause_evidence(
            tuple(case["regulation_topics"]),
            " ".join(spec.description for spec in specs),
            clauses,
            fact_evidence_clause_ids=evaluation.evidence_clause_ids,
            search_all_terms=tuple(
                term for spec in specs for term in spec.search_all_terms
            ),
            search_any_terms=tuple(
                term for spec in specs for term in spec.search_any_terms
            ),
            min_bm25_score=999.0,
        )
        if evaluation.evidence_clause_ids:
            assert set(evaluation.evidence_clause_ids) <= set(
                selection.selected_clause_ids
            )
        assert set(required_names) <= set(TriggerFactName)
