import time
from dataclasses import replace

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    AuditStatus,
    ComplianceConclusion,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)
from lib.common.product_tags import ProductLine, ProductTags
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    _routed_clauses,
    run_audit_pipeline,
)
from lib.compliance.clause_routing import ClauseRoutingResult
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalCoverage,
    RegulationRetrievalOutcome,
)
from lib.compliance.regulation_units import RegulationChunk, RegulationUnit


def _unit() -> RegulationUnit:
    chunk = RegulationChunk(
        chunk_id="chunk-1",
        law_name="健康险规则",
        article_number="第一条",
        section_path="第一条",
        source_file="health.md",
        chunk_index=0,
        content="等待期应符合本条规定。",
        regulation_topics=("coverage.waiting_period",),
    )
    return RegulationUnit(
        unit_id="unit-1",
        kb_version="v5",
        source_file="health.md",
        locator="第一条",
        locator_type="article_number",
        law_name="健康险规则",
        article_number="第一条",
        section_path="第一条",
        chunks=(chunk,),
        applicability_status="applicable",
        regulation_topics=("coverage.waiting_period",),
        applicability_reasons=("健康险适用",),
    )


def _request() -> AuditPipelineRequest:
    return AuditPipelineRequest(
        product_name="测试医疗保险",
        document_content="等待期为三十日。其他约定。",
        product_tags=ProductTags(line=ProductLine.HEALTH),
        clauses=(
            AuditClauseSnapshot(
                clause_id="clause-assignment",
                number="2.3",
                title="合同转让",
                text="本合同权益转让前的等待期为四十五日。",
                block_type="clause",
                topics=("policy.assignment",),
            ),
            AuditClauseSnapshot(
                clause_id="clause-waiting",
                number="2.1",
                title="等待期",
                text="等待期为三十日。",
                block_type="clause",
                topics=("coverage.waiting_period",),
            ),
            AuditClauseSnapshot(
                clause_id="clause-unknown",
                number="2.2",
                title="其他约定",
                text="其他约定。",
                block_type="clause",
                topics=(),
            ),
        ),
        category="健康险",
    )


def _retriever(*args) -> RegulationRetrievalOutcome:
    return RegulationRetrievalOutcome(
        regulations=(),
        regulation_units=(_unit(),),
        candidate_count=1,
        excluded_count=2,
    )


def _compliant_auditor(packages, max_concurrency, deadline_seconds, on_decision):
    package = tuple(packages)[0]
    assert max_concurrency == 5
    assert 0 < deadline_seconds <= 300.0
    return (
        RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.COMPLIANT,
            reasoning="未发现违反本条的内容。",
            suggestion="",
            regulation_evidence=(),
            product_evidence=(),
        ),
    )


def test_pipeline_submits_full_document_while_preserving_route_signals() -> None:
    frozen: list[RegulationRetrievalOutcome] = []
    result = run_audit_pipeline(
        _request(),
        retriever=_retriever,
        package_auditor=_compliant_auditor,
        on_candidates_frozen=frozen.append,
    )

    assert len(result.records) == 1
    package = result.records[0].package
    assert package.product_tags is result.request.product_tags
    assert [item.clause.clause_id for item in package.clauses if item.submitted] == [
        "clause-assignment",
        "clause-waiting",
        "clause-unknown",
    ]
    assignment = next(
        item for item in package.clauses
        if item.clause.clause_id == "clause-assignment"
    )
    assert assignment.relation.value == "not_relevant"
    assert any("完整条款基线" in reason for reason in assignment.reasons)
    assert package.regulation.chunks[0].chunk_id == "chunk-1"
    assert any(fact.value == "30" and fact.unit == "day" for fact in package.facts)
    assert any(
        fact.clause_id == "clause-assignment"
        and fact.value == "45"
        and fact.unit == "day"
        for fact in package.facts
    )
    assert result.summary.audit_status is AuditStatus.COMPLETED
    assert result.summary.compliance_conclusion is ComplianceConclusion.NO_VIOLATION_FOUND
    assert frozen[0].candidate_count == 1


def test_missing_route_item_cannot_drop_a_full_document_clause() -> None:
    clauses = _request().clauses
    routed = _routed_clauses(
        clauses,
        ClauseRoutingResult(
            regulation_topics=(),
            topic_schema_version="1.0.0",
            relation_schema_version="1.0.0",
            items=(),
            config_valid=False,
        ),
    )

    assert [item.clause.clause_id for item in routed] == [
        clause.clause_id for clause in clauses
    ]
    assert all(item.submitted for item in routed)
    assert all(item.relation.value == "unknown" for item in routed)


def test_missing_auditor_result_is_explicitly_incomplete() -> None:
    result = run_audit_pipeline(
        _request(),
        retriever=_retriever,
        package_auditor=lambda packages, concurrency, deadline, callback: (),
    )

    assert result.summary.audit_status is AuditStatus.INCOMPLETE
    assert result.summary.compliance_conclusion is ComplianceConclusion.UNDETERMINED
    assert result.records[0].decision.error_code == "missing_audit_decision"


def test_retrieval_degradation_prevents_green_conclusion() -> None:
    def degraded_retriever(*args) -> RegulationRetrievalOutcome:
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_unit(),),
            degraded=True,
            warnings=("语义检索失败",),
            coverage=RegulationRetrievalCoverage(
                rag_available=True,
                catalog_available=True,
                semantic_available=False,
                registered_available=True,
                category_resolution="provided",
                complete_candidate_freeze=True,
            ),
            candidate_count=1,
        )

    result = run_audit_pipeline(
        _request(),
        retriever=degraded_retriever,
        package_auditor=_compliant_auditor,
    )

    assert result.summary.audit_status is AuditStatus.DEGRADED
    assert result.summary.compliance_conclusion is ComplianceConclusion.UNDETERMINED


def test_informational_parse_warning_is_reported_without_forcing_degradation() -> None:
    request = replace(
        _request(),
        parse_warnings=("旧版 .doc 已临时转换为 .docx 后解析",),
    )

    result = run_audit_pipeline(
        request,
        retriever=_retriever,
        package_auditor=_compliant_auditor,
    )

    assert result.summary.audit_status is AuditStatus.COMPLETED
    assert result.summary.compliance_conclusion is ComplianceConclusion.NO_VIOLATION_FOUND
    assert result.summary.warnings == request.parse_warnings


def test_retrieval_time_consumes_deadline_and_skips_auditor() -> None:
    auditor_called = False

    def slow_retriever(*args) -> RegulationRetrievalOutcome:
        time.sleep(0.02)
        return _retriever(*args)

    def auditor(*args):
        nonlocal auditor_called
        auditor_called = True
        return ()

    result = run_audit_pipeline(
        _request(),
        retriever=slow_retriever,
        package_auditor=auditor,
        deadline_seconds=0.001,
    )

    assert not auditor_called
    assert result.summary.audit_status is AuditStatus.INCOMPLETE
    assert result.summary.compliance_conclusion is ComplianceConclusion.UNDETERMINED
    assert result.records[0].decision.error_code == "audit_deadline_exceeded"


def test_retrieval_timeout_with_zero_units_cannot_be_green() -> None:
    def slow_empty_retriever(*args) -> RegulationRetrievalOutcome:
        time.sleep(0.02)
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(),
            candidate_count=0,
        )

    result = run_audit_pipeline(
        _request(),
        retriever=slow_empty_retriever,
        package_auditor=lambda *args: (),
        deadline_seconds=0.001,
    )

    assert result.records == ()
    assert result.summary.audit_status is AuditStatus.INCOMPLETE
    assert result.summary.compliance_conclusion is ComplianceConclusion.UNDETERMINED
    assert result.summary.failed_count == 1
