import time
from dataclasses import replace

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    AuditStatus,
    ComplianceConclusion,
    FactTruth,
    ProductFactEvidence,
    ProofStrategy,
    RegulationAuditDecision,
    RegulationDecisionStatus,
    RegulationTriggerSpec,
    TriggerFactName,
    TriggerOperator,
    TriggerStatus,
)
from lib.common.product_tags import ProductLine, ProductTags
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    _routed_clauses,
    build_regulation_audit_packages,
    run_audit_pipeline,
)
from lib.compliance.clause_routing import ClauseRoutingResult
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalCoverage,
    RegulationRetrievalOutcome,
)
from lib.compliance.regulation_units import RegulationChunk, RegulationUnit
from lib.llm.product_fact_resolution import FactResolutionResult


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


def _policy_loan_unit() -> RegulationUnit:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.HAS_POLICY_LOAN,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("policy.loan",),
        proof_strategy=ProofStrategy.EXPLICIT_PRESENCE,
        search_any_terms=("保单贷款", "保单借款", "保险单贷款"),
    )
    chunk = RegulationChunk(
        chunk_id="chunk-loan",
        law_name="保单贷款规则",
        article_number="第二条",
        section_path="第二条",
        source_file="loan.md",
        chunk_index=0,
        content="保单贷款比例不得超过现金价值的百分之八十。",
        regulation_topics=("policy.loan",),
        trigger_specs=(spec,),
    )
    return RegulationUnit(
        unit_id="unit-loan",
        kb_version="v5",
        source_file="loan.md",
        locator="第二条",
        locator_type="article_number",
        law_name="保单贷款规则",
        article_number="第二条",
        section_path="第二条",
        chunks=(chunk,),
        applicability_status="applicable",
        regulation_topics=("policy.loan",),
        trigger_specs=(spec,),
    )


def _closed_mention_unit() -> RegulationUnit:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("coverage.medical",),
        proof_strategy=ProofStrategy.CLOSED_PHRASE_SCAN,
        search_any_terms=("院外购药", "药店"),
        exclusion_approved=True,
    )
    chunk = RegulationChunk(
        chunk_id="chunk-drug",
        law_name="院外购药规则",
        article_number="第三条",
        section_path="第三条",
        source_file="drug.md",
        chunk_index=0,
        content="涉及院外购药责任时应符合本条要求。",
        regulation_topics=("coverage.medical",),
        trigger_specs=(spec,),
    )
    return RegulationUnit(
        unit_id="unit-drug",
        kb_version="v5",
        source_file="drug.md",
        locator="第三条",
        locator_type="article_number",
        law_name="院外购药规则",
        article_number="第三条",
        section_path="第三条",
        chunks=(chunk,),
        applicability_status="applicable",
        regulation_topics=("coverage.medical",),
        trigger_specs=(spec,),
    )


def _semantic_policy_loan_unit() -> RegulationUnit:
    unit = _policy_loan_unit()
    spec = replace(
        unit.trigger_specs[0],
        target_topics=("policy.cash_value",),
        search_all_terms=(),
        search_any_terms=(),
        proof_strategy=ProofStrategy.SEMANTIC_FACT,
    )
    return replace(
        unit,
        chunks=(replace(unit.chunks[0], trigger_specs=(spec,)),),
        trigger_specs=(spec,),
    )


def _request_with_cash_value_clause() -> AuditPipelineRequest:
    request = _request()
    return replace(request, clauses=(*request.clauses, AuditClauseSnapshot(
        clause_id="clause-cash",
        number="2.4",
        title="现金价值",
        text="本合同具有现金价值。",
        block_type="clause",
        topics=("policy.cash_value",),
    )))


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


def test_complete_document_attestation_reaches_audit_package() -> None:
    request = replace(_request(), coverage_attested=True)

    packages, _, _ = build_regulation_audit_packages(request, (_unit(),))

    assert packages[0].complete_document is True


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
    selection = result.records[0].evidence_selection
    assert selection is not None
    assert "clause-waiting" in selection.selected_clause_ids
    assert all(item.submitted for item in package.clauses)


def test_safe_trigger_false_stays_shadow_before_cutover() -> None:
    auditor_called = False

    def retriever(*args) -> RegulationRetrievalOutcome:
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_closed_mention_unit(),),
            candidate_count=1,
            excluded_count=2,
        )

    def auditor(*args):
        nonlocal auditor_called
        auditor_called = True
        return _compliant_auditor(*args)

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=retriever,
        package_auditor=auditor,
    )

    assert auditor_called
    assert len(result.records) == 1
    assert result.trigger_records[0].evaluation.status is TriggerStatus.NOT_TRIGGERED
    assert result.trigger_records[0].exclusion_approved is True
    assert result.trigger_records[0].exclusion_applied is False
    assert result.summary.excluded_count == 2
    assert result.trigger_exclusion_mode == "shadow"


def test_approved_safe_trigger_excludes_only_after_global_cutover(monkeypatch) -> None:
    from lib.common.constants import ComplianceConstants

    monkeypatch.setattr(
        ComplianceConstants,
        "REGULATION_TRIGGER_EXCLUSION_MODE",
        "active",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "EVALUATION_DATASET_STATUS",
        "approved",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "CUTOVER_GATE_STATUS",
        "passed",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_SOURCE_SHA256",
        "approved-source-sha",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_CATALOG_SHA256",
        "approved-catalog-sha",
    )
    auditor_called = False

    def auditor(*args):
        nonlocal auditor_called
        auditor_called = True
        return ()

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_closed_mention_unit(),),
            candidate_count=1,
            excluded_count=2,
            kb_trigger_schema_version="1.0.0",
            kb_source_sha256="approved-source-sha",
            kb_catalog_sha256="approved-catalog-sha",
            coverage=RegulationRetrievalCoverage(
                rag_available=True,
                catalog_available=True,
                semantic_available=True,
                registered_available=True,
                category_resolution="explicit",
                complete_candidate_freeze=True,
            ),
        ),
        package_auditor=auditor,
    )

    assert not auditor_called
    assert result.records == ()
    assert result.trigger_records[0].exclusion_applied is True
    assert result.summary.excluded_count == 3
    assert result.summary.compliance_conclusion is (
        ComplianceConclusion.NO_APPLICABLE_REGULATIONS
    )


def test_changed_regulation_source_cannot_reuse_prior_trigger_approval(
    monkeypatch,
) -> None:
    from lib.common.constants import ComplianceConstants

    monkeypatch.setattr(
        ComplianceConstants,
        "REGULATION_TRIGGER_EXCLUSION_MODE",
        "active",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "EVALUATION_DATASET_STATUS",
        "approved",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "CUTOVER_GATE_STATUS",
        "passed",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_SOURCE_SHA256",
        "approved-source-sha",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_CATALOG_SHA256",
        "approved-catalog-sha",
    )

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_closed_mention_unit(),),
            candidate_count=1,
            kb_trigger_schema_version="1.0.0",
            kb_source_sha256="changed-source-sha",
            kb_catalog_sha256="approved-catalog-sha",
            coverage=RegulationRetrievalCoverage(
                rag_available=True,
                catalog_available=True,
                semantic_available=True,
                registered_available=True,
                category_resolution="explicit",
                complete_candidate_freeze=True,
            ),
        ),
        package_auditor=_compliant_auditor,
    )

    assert len(result.records) == 1
    assert result.trigger_records[0].exclusion_applied is False
    assert "当前法规源文件指纹与精算验收版本不一致" in (
        result.trigger_exclusion_blockers
    )


def test_changed_regulation_catalog_cannot_reuse_prior_trigger_approval(
    monkeypatch,
) -> None:
    from lib.common.constants import ComplianceConstants

    monkeypatch.setattr(
        ComplianceConstants,
        "REGULATION_TRIGGER_EXCLUSION_MODE",
        "active",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "EVALUATION_DATASET_STATUS",
        "approved",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "CUTOVER_GATE_STATUS",
        "passed",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_SOURCE_SHA256",
        "approved-source-sha",
    )
    monkeypatch.setattr(
        ComplianceConstants,
        "APPROVED_REGULATION_TRIGGER_CATALOG_SHA256",
        "approved-catalog-sha",
    )

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_closed_mention_unit(),),
            candidate_count=1,
            kb_trigger_schema_version="1.0.0",
            kb_source_sha256="approved-source-sha",
            kb_catalog_sha256="changed-catalog-sha",
            coverage=RegulationRetrievalCoverage(
                rag_available=True,
                catalog_available=True,
                semantic_available=True,
                registered_available=True,
                category_resolution="explicit",
                complete_candidate_freeze=True,
            ),
        ),
        package_auditor=_compliant_auditor,
    )

    assert len(result.records) == 1
    assert result.trigger_records[0].exclusion_applied is False
    assert "当前法规目录指纹与精算验收版本不一致" in (
        result.trigger_exclusion_blockers
    )


def test_active_mode_cannot_bypass_blocked_cutover_gate(monkeypatch) -> None:
    from lib.common.constants import ComplianceConstants

    monkeypatch.setattr(
        ComplianceConstants,
        "REGULATION_TRIGGER_EXCLUSION_MODE",
        "active",
    )
    auditor_called = False

    def auditor(*args):
        nonlocal auditor_called
        auditor_called = True
        return _compliant_auditor(*args)

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_closed_mention_unit(),),
            candidate_count=1,
        ),
        package_auditor=auditor,
    )

    assert auditor_called
    assert result.trigger_records[0].exclusion_applied is False
    assert result.trigger_exclusion_ready is False
    assert "生产切换门禁尚未通过" in result.trigger_exclusion_blockers


def test_unknown_trigger_is_retained_and_exposes_fact_trace() -> None:
    def retriever(*args) -> RegulationRetrievalOutcome:
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_policy_loan_unit(),),
            candidate_count=1,
        )

    result = run_audit_pipeline(
        _request(),
        retriever=retriever,
        package_auditor=_compliant_auditor,
    )

    assert len(result.records) == 1
    trigger = result.trigger_records[0].evaluation
    assert trigger.status is TriggerStatus.INDETERMINATE
    assert result.product_facts[0].name is TriggerFactName.HAS_POLICY_LOAN
    assert result.records[0].package.product_facts == result.product_facts


def test_fact_resolver_runs_once_per_product_and_updates_trigger_trace() -> None:
    calls = 0

    def resolver(facts, clauses, candidates, timeout_seconds):
        nonlocal calls
        calls += 1
        assert tuple(clause.clause_id for clause in clauses) == ("clause-cash",)
        assert candidates == {
            TriggerFactName.HAS_POLICY_LOAN: ("clause-cash",),
        }
        assert 0 < timeout_seconds <= 45.0
        resolved = tuple(
            replace(
                fact,
                truth=FactTruth.TRUE,
                value=True,
                confidence=0.9,
                evidence=(ProductFactEvidence(
                    "clause-cash", "本合同具有现金价值。",
                ),),
                method="semantic_fact",
                proof_strategy=ProofStrategy.SEMANTIC_FACT,
            )
            for fact in facts
        )
        return FactResolutionResult(
            facts=resolved,
            requested_fact_names=(TriggerFactName.HAS_POLICY_LOAN,),
            resolved_fact_names=(TriggerFactName.HAS_POLICY_LOAN,),
            validation_errors=(),
            attempted=True,
        )

    result = run_audit_pipeline(
        _request_with_cash_value_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(
                _semantic_policy_loan_unit(),
                replace(_semantic_policy_loan_unit(), unit_id="unit-loan-2"),
            ),
            candidate_count=2,
        ),
        package_auditor=lambda packages, *args: tuple(
            replace(
                _compliant_auditor((package,), *args)[0],
                task_id=package.task_id,
                regulation_unit_id=package.regulation.regulation_unit_id,
            )
            for package in packages
        ),
        fact_resolver=resolver,
    )

    assert calls == 1
    assert all(
        record.evaluation.status is TriggerStatus.TRIGGERED
        for record in result.trigger_records
    )
    assert result.fact_resolution is not None
    assert result.fact_resolution.resolved_fact_names == (
        TriggerFactName.HAS_POLICY_LOAN,
    )


def test_fact_resolver_failure_keeps_unknown_without_degrading_formal_audit() -> None:
    def failing_resolver(*args):
        raise RuntimeError("offline fixture failure")

    result = run_audit_pipeline(
        _request_with_cash_value_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_semantic_policy_loan_unit(),),
            candidate_count=1,
        ),
        package_auditor=_compliant_auditor,
        fact_resolver=failing_resolver,
    )

    assert result.trigger_records[0].evaluation.status is (
        TriggerStatus.INDETERMINATE
    )
    assert result.summary.audit_status is AuditStatus.COMPLETED
    assert any("事实补充编排失败" in item for item in result.shadow_warnings)


def test_shared_audit_facts_are_extracted_once_for_multiple_units(monkeypatch) -> None:
    from lib.compliance import audit_pipeline

    calls = 0
    original = audit_pipeline.extract_audit_facts

    def counted(blocks, product_tags):
        nonlocal calls
        calls += 1
        return original(blocks, product_tags)

    monkeypatch.setattr(audit_pipeline, "extract_audit_facts", counted)

    result = run_audit_pipeline(
        _request(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_unit(), replace(
                _unit(),
                unit_id="unit-2",
                locator="第二条",
                article_number="第二条",
                section_path="第二条",
            )),
            candidate_count=2,
        ),
        package_auditor=lambda packages, *args: tuple(
            RegulationAuditDecision(
                task_id=package.task_id,
                regulation_unit_id=package.regulation.regulation_unit_id,
                status=RegulationDecisionStatus.COMPLIANT,
                reasoning="未发现违反本条的内容。",
                suggestion="",
                regulation_evidence=(),
                product_evidence=(),
            )
            for package in packages
        ),
    )

    assert len(result.records) == 2
    assert calls == 1
    assert result.records[0].package.facts is result.records[1].package.facts


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
