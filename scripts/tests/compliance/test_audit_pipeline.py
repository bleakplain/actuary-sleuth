import time
from dataclasses import replace

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    AuditStatus,
    ComplianceConclusion,
    FactTruth,
    ProductEvidenceStrength,
    ProductFactEvidence,
    ProofStrategy,
    RegulationAuditDecision,
    RegulationAuditPackage,
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
from lib.compliance.clause_evidence import (
    ClauseEvidenceMatch,
    ClauseEvidenceSelection,
    EvidenceSourceLayer,
)
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


def _semantic_renewal_unit() -> RegulationUnit:
    spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.HAS_RENEWAL,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("renewal.reapplication",),
        proof_strategy=ProofStrategy.SEMANTIC_FACT,
    )
    chunk = RegulationChunk(
        chunk_id="chunk-renewal",
        law_name="重新投保规则",
        article_number="第三条",
        section_path="第三条",
        source_file="renewal.md",
        chunk_index=0,
        content="重新投保安排应符合本条规定。",
        regulation_topics=("renewal.reapplication",),
        trigger_specs=(spec,),
    )
    return RegulationUnit(
        unit_id="unit-renewal",
        kb_version="v5",
        source_file="renewal.md",
        locator="第三条",
        locator_type="article_number",
        law_name="重新投保规则",
        article_number="第三条",
        section_path="第三条",
        chunks=(chunk,),
        applicability_status="applicable",
        regulation_topics=("renewal.reapplication",),
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


def _request_with_policy_loan_clause() -> AuditPipelineRequest:
    request = _request_with_cash_value_clause()
    return replace(request, clauses=(*request.clauses, AuditClauseSnapshot(
        clause_id="clause-loan",
        number="2.5",
        title="保单贷款",
        text="投保人可以申请保单贷款，贷款金额不得超过现金价值的80%。",
        block_type="clause",
        topics=("policy.loan",),
    )))


def _request_with_reapplication_clause() -> AuditPipelineRequest:
    request = _request()
    return replace(request, clauses=(*request.clauses, AuditClauseSnapshot(
        clause_id="clause-reapplication",
        number="2.6",
        title="重新投保",
        text="保险期间届满后，投保人可以重新投保本产品。",
        block_type="clause",
        topics=("renewal.reapplication",),
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


def _selection(
    matches: tuple[ClauseEvidenceMatch, ...],
    *,
    config_valid: bool = True,
) -> ClauseEvidenceSelection:
    selected = frozenset(match.clause_id for match in matches)
    return ClauseEvidenceSelection(
        regulation_topics=("coverage.waiting_period",),
        selected_clause_ids=tuple(
            clause_id
            for clause_id in (
                "clause-waiting",
                "clause-weak",
                "clause-trigger-bm25",
                "clause-trigger-only",
                "clause-cover",
                "clause-short",
                "clause-container",
            )
            if clause_id in selected
        ),
        matches=matches,
        full_outline=(),
        relation_schema_version="1.0.0",
        rule_schema_version="1.0.0",
        config_valid=config_valid,
    )


def _match(
    clause_id: str,
    layer: EvidenceSourceLayer,
) -> ClauseEvidenceMatch:
    return ClauseEvidenceMatch(
        clause_id=clause_id,
        source_layer=layer,
        selection_reason=f"test:{layer.value}",
        score=1.0,
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
    assert max_concurrency == 2
    assert 0 < deadline_seconds <= 900.0
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


def test_product_evidence_catalog_is_task_specific_and_strength_aware() -> None:
    base = _request()
    request = replace(base, clauses=(*base.clauses,
        AuditClauseSnapshot(
            "clause-weak", "3.1", "其他约定",
            "本合同包含与法规文本相似的其他完整约定。", "clause",
        ),
        AuditClauseSnapshot(
            "clause-trigger-bm25", "3.2", "事实约定",
            "本合同明确记录触发事实及其审核内容。", "clause",
        ),
        AuditClauseSnapshot(
            "clause-trigger-only", "3.3", "事实约定",
            "本合同仅记录触发事实，不足以作为结论证据。", "clause",
        ),
        AuditClauseSnapshot(
            "clause-cover", "", "", "测试医疗保险条款", "unclassified",
        ),
        AuditClauseSnapshot(
            "clause-short", "", "附表", "保障表", "unclassified",
        ),
        AuditClauseSnapshot(
            "clause-container", "4", "等待期", "本章约定等待期。", "clause",
            container_only=True,
        ),
    ))
    selection = _selection((
        _match("clause-waiting", EvidenceSourceLayer.EXACT_TOPIC),
        _match("clause-weak", EvidenceSourceLayer.BM25),
        _match("clause-trigger-bm25", EvidenceSourceLayer.TRIGGER_FACT),
        _match("clause-trigger-bm25", EvidenceSourceLayer.BM25),
        _match("clause-trigger-only", EvidenceSourceLayer.TRIGGER_FACT),
        _match("clause-cover", EvidenceSourceLayer.TRIGGER_FACT),
        _match("clause-cover", EvidenceSourceLayer.BM25),
        _match("clause-short", EvidenceSourceLayer.BM25),
        _match("clause-container", EvidenceSourceLayer.EXACT_TOPIC),
    ))

    packages, _, _ = build_regulation_audit_packages(
        request,
        (_unit(),),
        evidence_selections={"unit-1": selection},
    )

    candidates = {
        candidate.clause_id: candidate
        for candidate in packages[0].product_evidence_candidates
    }
    assert tuple(candidates) == (
        "clause-waiting",
        "clause-weak",
        "clause-trigger-bm25",
    )
    assert candidates["clause-waiting"].strength is (
        ProductEvidenceStrength.STRONG
    )
    assert candidates["clause-weak"].strength is ProductEvidenceStrength.WEAK
    assert candidates["clause-trigger-bm25"].strength is (
        ProductEvidenceStrength.WEAK
    )
    assert candidates["clause-trigger-bm25"].source_layers == (
        "trigger_fact",
        "bm25",
    )


def test_product_evidence_catalog_does_not_leak_between_units() -> None:
    base = _request()
    request = replace(base, clauses=(*base.clauses, AuditClauseSnapshot(
        "clause-weak", "3.1", "其他约定",
        "本合同包含与第二条法规相关的完整约定。", "clause",
    )))
    second = replace(
        _unit(),
        unit_id="unit-2",
        locator="第二条",
        article_number="第二条",
        section_path="第二条",
    )
    packages, _, _ = build_regulation_audit_packages(
        request,
        (_unit(), second),
        evidence_selections={
            "unit-1": _selection((
                _match("clause-waiting", EvidenceSourceLayer.EXACT_TOPIC),
            )),
            "unit-2": _selection((
                _match("clause-weak", EvidenceSourceLayer.BM25),
            )),
        },
    )

    candidates_by_unit = {
        package.regulation.regulation_unit_id: tuple(
            candidate.clause_id
            for candidate in package.product_evidence_candidates
        )
        for package in packages
    }
    assert candidates_by_unit == {
        "unit-1": ("clause-waiting",),
        "unit-2": ("clause-weak",),
    }


def test_invalid_or_empty_selection_never_fails_open_to_full_document() -> None:
    second = replace(
        _unit(),
        unit_id="unit-2",
        locator="第二条",
        article_number="第二条",
        section_path="第二条",
    )
    packages, _, _ = build_regulation_audit_packages(
        _request(),
        (_unit(), second),
        evidence_selections={
            "unit-1": _selection((
                _match("clause-waiting", EvidenceSourceLayer.EXACT_TOPIC),
            ), config_valid=False),
            "unit-2": _selection(()),
        },
    )

    assert all(not package.product_evidence_candidates for package in packages)
    assert all(
        len(tuple(item for item in package.clauses if item.submitted)) == 3
        for package in packages
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
    selection = result.records[0].evidence_selection
    assert selection is not None
    assert "clause-waiting" in selection.selected_clause_ids
    assert tuple(
        candidate.clause_id for candidate in package.product_evidence_candidates
    ) == ("clause-waiting",)
    assert package.product_evidence_candidates[0].strength is (
        ProductEvidenceStrength.STRONG
    )
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


def test_packages_only_receive_product_facts_referenced_by_their_unit() -> None:
    captured_packages: tuple[RegulationAuditPackage, ...] = ()
    loan_unit = _policy_loan_unit()
    loan_spec = replace(
        loan_unit.trigger_specs[0],
        required_facts=(TriggerFactName.HAS_CASH_VALUE,),
    )
    loan_unit = replace(
        loan_unit,
        chunks=(replace(loan_unit.chunks[0], trigger_specs=(loan_spec,)),),
        trigger_specs=(loan_spec,),
    )

    def auditor(packages, *args):
        nonlocal captured_packages
        captured_packages = tuple(packages)
        return tuple(
            RegulationAuditDecision(
                task_id=package.task_id,
                regulation_unit_id=package.regulation.regulation_unit_id,
                status=RegulationDecisionStatus.COMPLIANT,
                reasoning="未发现违反本条的内容。",
                suggestion="",
                regulation_evidence=(),
                product_evidence=(),
            )
            for package in captured_packages
        )

    result = run_audit_pipeline(
        replace(_request(), coverage_attested=True),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(
                loan_unit,
                _closed_mention_unit(),
                _unit(),
            ),
            candidate_count=3,
        ),
        package_auditor=auditor,
    )

    full_ledger_names = {fact.name for fact in result.product_facts}
    assert full_ledger_names == {
        TriggerFactName.HAS_POLICY_LOAN,
        TriggerFactName.HAS_CASH_VALUE,
        TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG,
    }
    packages_by_unit: dict[str, RegulationAuditPackage] = {
        package.regulation.regulation_unit_id: package
        for package in captured_packages
    }
    assert {
        fact.name for fact in packages_by_unit["unit-loan"].product_facts
    } == {
        TriggerFactName.HAS_POLICY_LOAN,
        TriggerFactName.HAS_CASH_VALUE,
    }
    assert {
        fact.name for fact in packages_by_unit["unit-drug"].product_facts
    } == {TriggerFactName.MENTIONS_OUT_OF_HOSPITAL_DRUG}
    assert packages_by_unit["unit-1"].product_facts == ()


def test_policy_loan_evidence_keeps_cash_value_as_trace_only() -> None:
    unit = _policy_loan_unit()
    spec = replace(
        unit.trigger_specs[0],
        target_topics=("policy.loan", "policy.cash_value"),
        required_facts=(TriggerFactName.HAS_CASH_VALUE,),
    )
    unit = replace(
        unit,
        chunks=(replace(unit.chunks[0], trigger_specs=(spec,)),),
        trigger_specs=(spec,),
    )

    result = run_audit_pipeline(
        _request_with_policy_loan_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(unit,),
            candidate_count=1,
        ),
        package_auditor=_compliant_auditor,
    )

    record = result.records[0]
    assert record.evidence_selection is not None
    assert record.evidence_selection.selected_clause_ids == ("clause-loan",)
    assert {
        fact.name for fact in record.package.product_facts
    } == {
        TriggerFactName.HAS_POLICY_LOAN,
        TriggerFactName.HAS_CASH_VALUE,
    }
    cash_value = next(
        fact
        for fact in record.package.product_facts
        if fact.name is TriggerFactName.HAS_CASH_VALUE
    )
    assert cash_value.evidence[0].clause_id == "clause-cash"


def test_policy_loan_evidence_does_not_expand_cash_value_only_clause() -> None:
    unit = _policy_loan_unit()
    spec = replace(
        unit.trigger_specs[0],
        target_topics=("policy.loan", "policy.cash_value"),
        required_facts=(TriggerFactName.HAS_CASH_VALUE,),
    )
    unit = replace(
        unit,
        chunks=(replace(unit.chunks[0], trigger_specs=(spec,)),),
        trigger_specs=(spec,),
    )

    result = run_audit_pipeline(
        _request_with_cash_value_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(unit,),
            candidate_count=1,
        ),
        package_auditor=_compliant_auditor,
    )

    record = result.records[0]
    assert record.evidence_selection is not None
    assert record.evidence_selection.selected_clause_ids == ()
    assert any(
        fact.name is TriggerFactName.HAS_CASH_VALUE and fact.evidence
        for fact in record.package.product_facts
    )


def test_policy_loan_required_cash_value_uses_separate_fact_resolution_scope(
) -> None:
    unit = _policy_loan_unit()
    spec = replace(
        unit.trigger_specs[0],
        target_topics=("policy.loan", "policy.cash_value"),
        required_facts=(TriggerFactName.HAS_CASH_VALUE,),
        proof_strategy=ProofStrategy.SEMANTIC_FACT,
    )
    unit = replace(
        unit,
        chunks=(replace(unit.chunks[0], trigger_specs=(spec,)),),
        trigger_specs=(spec,),
    )
    base_request = _request()
    request = replace(base_request, clauses=(*base_request.clauses,
        AuditClauseSnapshot(
            clause_id="clause-cash-conflict",
            number="2.7",
            title="现金价值",
            text="本合同没有现金价值，但另一项约定称本合同具有现金价值。",
            block_type="clause",
            topics=("policy.cash_value",),
        ),
    ))
    calls = 0

    def resolver(facts, clauses, candidates, timeout_seconds):
        nonlocal calls
        calls += 1
        assert tuple(clause.clause_id for clause in clauses) == (
            "clause-cash-conflict",
        )
        assert candidates == {
            TriggerFactName.HAS_CASH_VALUE: ("clause-cash-conflict",),
        }
        assert timeout_seconds > 0
        resolved = tuple(
            replace(
                fact,
                truth=FactTruth.TRUE,
                value=True,
                method="semantic_fact",
                confidence=0.9,
                proof_strategy=ProofStrategy.SEMANTIC_FACT,
            )
            if fact.name is TriggerFactName.HAS_CASH_VALUE
            else fact
            for fact in facts
        )
        return FactResolutionResult(
            facts=resolved,
            requested_fact_names=(TriggerFactName.HAS_CASH_VALUE,),
            resolved_fact_names=(TriggerFactName.HAS_CASH_VALUE,),
            validation_errors=(),
            attempted=True,
        )

    result = run_audit_pipeline(
        request,
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(unit,),
            candidate_count=1,
        ),
        package_auditor=_compliant_auditor,
        fact_resolver=resolver,
    )

    assert calls == 1
    selection = result.records[0].evidence_selection
    assert selection is not None
    assert selection.selected_clause_ids == ()
    assert result.fact_resolution is not None
    assert result.fact_resolution.resolved_fact_names == (
        TriggerFactName.HAS_CASH_VALUE,
    )


def test_fact_resolver_runs_once_per_product_and_updates_trigger_trace() -> None:
    calls = 0

    def resolver(facts, clauses, candidates, timeout_seconds):
        nonlocal calls
        calls += 1
        assert tuple(clause.clause_id for clause in clauses) == (
            "clause-reapplication",
        )
        assert candidates == {
            TriggerFactName.HAS_RENEWAL: ("clause-reapplication",),
        }
        assert 0 < timeout_seconds <= 45.0
        resolved = tuple(
            replace(
                fact,
                truth=FactTruth.TRUE,
                value=True,
                confidence=0.9,
                evidence=(ProductFactEvidence(
                    "clause-reapplication", "投保人可以重新投保本产品。",
                ),),
                method="semantic_fact",
                proof_strategy=ProofStrategy.SEMANTIC_FACT,
            )
            for fact in facts
        )
        return FactResolutionResult(
            facts=resolved,
            requested_fact_names=(TriggerFactName.HAS_RENEWAL,),
            resolved_fact_names=(TriggerFactName.HAS_RENEWAL,),
            validation_errors=(),
            attempted=True,
        )

    result = run_audit_pipeline(
        _request_with_reapplication_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(
                _semantic_renewal_unit(),
                replace(_semantic_renewal_unit(), unit_id="unit-renewal-2"),
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
        TriggerFactName.HAS_RENEWAL,
    )


def test_fact_resolver_failure_keeps_unknown_without_degrading_formal_audit() -> None:
    def failing_resolver(*args):
        raise RuntimeError("offline fixture failure")

    result = run_audit_pipeline(
        _request_with_reapplication_clause(),
        retriever=lambda *args: RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_semantic_renewal_unit(),),
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
