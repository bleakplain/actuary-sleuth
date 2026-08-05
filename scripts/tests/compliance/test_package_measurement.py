from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
)
from lib.common.product_tags import ProductTags
from lib.compliance.package_measurement import (
    build_measurement_report,
    measure_product_packages,
)


def _package() -> RegulationAuditPackage:
    clause = AuditClauseSnapshot(
        clause_id="clause-1",
        number="1.1",
        title="等待期",
        text="等待期为三十日。",
        block_type="clause",
    )
    return RegulationAuditPackage(
        task_id="task-1",
        input_index=0,
        product_name="测试医疗保险",
        product_tags=ProductTags(),
        regulation=RegulationUnitSnapshot(
            regulation_unit_id="unit-1",
            kb_version="v5",
            law_name="测试法规",
            source_file="law.md",
            article_number="第一条",
            section_path="第一条",
            topics=("coverage.waiting_period",),
            chunks=(RegulationChunkSnapshot(
                "chunk-1", "等待期不得超过180日。", 0,
            ),),
            applicability_status="applicable",
            applicability_reasons=("产品适用",),
        ),
        clauses=(RoutedClause(
            clause=clause,
            relation=RoutedClauseRelation.DIRECT,
            reasons=("直接相关",),
        ),),
        facts=(),
    )


def test_package_measurement_counts_segments_and_budget() -> None:
    measurement = measure_product_packages(
        "sample-1",
        "product.docx",
        1,
        20,
        (_package(),),
        max_concurrency=5,
        deadline_seconds=300,
    )

    assert measurement.audit_unit_count == 1
    assert measurement.llm_call_count == 1
    assert measurement.oversized_unit_count == 0
    assert measurement.package_prompt_chars_max > 0
    assert measurement.max_average_call_seconds_for_300s == 300

    report = build_measurement_report(
        (measurement,),
        kb_version="v5",
        max_concurrency=5,
        deadline_seconds=300,
        inputs={
            "product_manifest_sha256": "a" * 64,
            "kb_build_manifest_sha256": "b" * 64,
            "catalog_chunk_count": 174,
        },
    )
    assert report.summary["product_count"] == 1
    assert report.summary["llm_call_count"] == 1
    assert report.inputs["catalog_chunk_count"] == 174
