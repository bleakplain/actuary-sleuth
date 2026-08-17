import json
from dataclasses import replace

import pytest

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    ProofStrategy,
    RegulationTriggerSpec,
    TriggerFactName,
    TriggerOperator,
)
from lib.common.product_tags import ProductTags
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    build_regulation_audit_packages,
)
from lib.compliance.regulation_units import RegulationChunk, RegulationUnit
from lib.compliance.trigger_ab_measurement import (
    PilotTriggerCatalog,
    PilotTriggerRule,
    _change_label,
    _dynamic_package,
    inject_pilot_trigger_specs,
    load_pilot_trigger_catalog,
    measure_product_trigger_ab,
    validate_pilot_units_exist,
)


def _unit(
    unit_id: str,
    topic: str,
    regulation_text: str,
) -> RegulationUnit:
    chunk = RegulationChunk(
        chunk_id=f"chunk-{unit_id}",
        law_name=f"{unit_id}法规",
        article_number="第一条",
        section_path="第一条",
        source_file=f"{unit_id}.md",
        chunk_index=0,
        content=regulation_text,
        regulation_topics=(topic,),
    )
    return RegulationUnit(
        unit_id=unit_id,
        kb_version="v5",
        source_file=chunk.source_file,
        locator="第一条",
        locator_type="article_number",
        law_name=chunk.law_name,
        article_number="第一条",
        section_path="第一条",
        chunks=(chunk,),
        applicability_status="applicable",
        regulation_topics=(topic,),
    )


def _pilot() -> PilotTriggerCatalog:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("coverage.medical",),
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
    )
    return PilotTriggerCatalog(
        schema_version="test",
        sha256="a" * 64,
        rules=(PilotTriggerRule("R001", "unit-drug", (spec,)),),
    )


def _request() -> AuditPipelineRequest:
    clauses = (
        AuditClauseSnapshot(
            clause_id="waiting",
            number="2.1",
            title="等待期",
            text="本产品等待期为三十日。",
            block_type="clause",
            topics=("coverage.waiting_period",),
        ),
        AuditClauseSnapshot(
            clause_id="other",
            number="2.2",
            title="其他约定",
            text="本条约定其他事项。",
            block_type="clause",
        ),
    )
    return AuditPipelineRequest(
        product_name="测试医疗保险",
        document_content="\n".join(clause.text for clause in clauses),
        product_tags=ProductTags(),
        clauses=clauses,
        coverage_attested=True,
    )


def test_pilot_catalog_loads_metadata_and_injects_without_mutation(tmp_path) -> None:
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps({
        "schema_version": "pilot-v1",
        "rules": [{
            "rule_id": "R001",
            "unit_id": "unit-drug",
            "draft_metadata": {
                "触发事实": "mentions_out_of_hospital_drug",
                "触发运算符": "equals",
                "触发期望值": True,
                "目标条款主题": ["coverage.medical"],
                "证明策略": "closed_phrase_scan",
                "检索任一词组": ["院外购药", "药店"],
                "触发排除验收状态": "pending",
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")
    pilot = load_pilot_trigger_catalog(path)
    original = _unit("unit-drug", "coverage.medical", "院外购药责任应合规。")

    injected = inject_pilot_trigger_specs((original,), pilot)

    assert original.trigger_specs == ()
    assert injected[0] is not original
    assert injected[0].trigger_specs[0].fact_name is (
        TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG
    )
    assert injected[0].chunks[0].trigger_specs == injected[0].trigger_specs


def test_pilot_catalog_rejects_duplicates_and_missing_catalog_units(tmp_path) -> None:
    rule = {
        "rule_id": "R001",
        "unit_id": "unit-drug",
        "draft_metadata": {},
    }
    path = tmp_path / "duplicate.json"
    path.write_text(
        json.dumps({"rules": [rule, rule]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="试点法规单元重复"):
        load_pilot_trigger_catalog(path)
    with pytest.raises(ValueError, match="不在当前知识库目录"):
        validate_pilot_units_exist(
            _pilot(),
            (_unit("another-unit", "coverage.medical", "其他法规"),),
        )


def test_measurement_filters_only_safe_not_triggered_and_preserves_outline() -> None:
    existing_spec = _pilot().rules[0].specs
    existing = _unit(
        "unit-existing-trigger",
        "coverage.medical",
        "另一条院外购药法规。",
    )
    existing = replace(
        existing,
        trigger_specs=existing_spec,
        chunks=(replace(existing.chunks[0], trigger_specs=existing_spec),),
    )
    units = (
        _unit("unit-drug", "coverage.medical", "院外购药责任应合规。"),
        existing,
        _unit(
            "unit-waiting",
            "coverage.waiting_period",
            "等待期不得超过规定上限。",
        ),
    )

    measurement, _ = measure_product_trigger_ab(
        "sample-1",
        "sample.docx",
        _request(),
        units,
        _pilot(),
    )

    assert measurement.simulated_safe_exclusion_unit_ids == ("unit-drug",)
    assert measurement.trigger_status_counts == {
        "triggered": 0,
        "not_triggered": 1,
        "indeterminate": 0,
    }
    assert measurement.arm_a.candidate_regulation_count == 3
    assert measurement.arm_b.candidate_regulation_count == 2
    assert measurement.arm_c.candidate_regulation_count == 2
    assert measurement.arm_a.submitted_body_clause_occurrence_count == 6
    assert measurement.arm_b.submitted_body_clause_occurrence_count == 4
    assert measurement.arm_c.submitted_body_clause_occurrence_count == 3
    assert measurement.arm_c.outline_clause_occurrence_count == (
        measurement.arm_b.outline_clause_occurrence_count
    )
    assert measurement.arm_c.full_document_fallback_count == 1
    assert measurement.arm_c.prompt_chars_total < measurement.arm_b.prompt_chars_total
    arm_payload = measurement.arm_c.to_dict()
    assert arm_payload["submitted_body_clause_occurrence_count"] == 3
    assert arm_payload["outline_clause_occurrence_count"] == 4
    assert "submitted_body_clause_count" not in arm_payload
    assert "outline_clause_count" not in arm_payload


def test_dynamic_evidence_unknown_clause_id_falls_back_to_full_document() -> None:
    package = build_regulation_audit_packages(
        _request(),
        (_unit(
            "unit-waiting",
            "coverage.waiting_period",
            "等待期不得超过规定上限。",
        ),),
    )[0][0]

    dynamic, fell_back = _dynamic_package(
        package,
        ("missing-clause",),
        config_valid=True,
    )

    assert fell_back is True
    assert dynamic is package
    assert all(routed.submitted for routed in dynamic.clauses)
    assert _change_label(-11.98) == "增加 11.98%"
