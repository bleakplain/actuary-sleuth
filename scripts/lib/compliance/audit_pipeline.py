"""产品标签驱动的单一法规审核编排链。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping, Optional, Tuple

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    AuditRunSummary,
    ExtractedFact,
    FactTruth,
    ProductFact,
    RegulationTriggerSpec,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    TriggerEvaluation,
    TriggerFactName,
    TriggerStatus,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
)
from lib.common.constants import ComplianceConstants
from lib.common.product_tags import ProductTags
from lib.compliance.audit_reporting import summarize_audit_run
from lib.compliance.auditor import audit_regulation_packages
from lib.compliance.clause_routing import (
    ClauseRoute,
    ClauseRoutingResult,
    route_product_clauses,
)
from lib.compliance.clause_evidence import (
    ClauseEvidenceSelection,
    FactEvidenceReference,
    select_clause_evidence,
)
from lib.compliance.fact_extraction import (
    build_product_fact_ledger,
    extract_audit_facts,
)
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalOutcome,
    build_regulation_retrieval_query,
    retrieve_regulation_candidates,
)
from lib.compliance.regulation_units import RegulationUnit
from lib.compliance.regulation_triggers import evaluate_regulation_triggers
from lib.llm.product_fact_resolution import FactResolutionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditPipelineRequest:
    product_name: str
    document_content: str
    product_tags: ProductTags
    clauses: Tuple[AuditClauseSnapshot, ...]
    category: Optional[str] = None
    document_fingerprint: str = ""
    audit_input_fingerprint: str = ""
    product_name_source: str = "unknown"
    parse_warnings: Tuple[str, ...] = ()
    coverage_attested: bool = False
    coverage_attested_facts: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RegulationAuditRecord:
    package: RegulationAuditPackage
    routing: ClauseRoutingResult
    decision: RegulationAuditDecision
    evidence_selection: Optional[ClauseEvidenceSelection] = None


@dataclass(frozen=True)
class RegulationTriggerRecord:
    regulation_unit_id: str
    kb_version: str
    source_file: str
    section_path: str
    chunk_ids: Tuple[str, ...]
    law_name: str
    article_number: str
    trigger_specs: Tuple[RegulationTriggerSpec, ...]
    evaluation: TriggerEvaluation
    exclusion_approved: bool
    exclusion_applied: bool


@dataclass(frozen=True)
class AuditPipelineResult:
    request: AuditPipelineRequest
    retrieval: RegulationRetrievalOutcome
    records: Tuple[RegulationAuditRecord, ...]
    summary: AuditRunSummary
    topic_taxonomy_version: str
    topic_relations_version: str
    warnings: Tuple[str, ...] = ()
    product_facts: Tuple[ProductFact, ...] = ()
    trigger_records: Tuple[RegulationTriggerRecord, ...] = ()
    shadow_warnings: Tuple[str, ...] = ()
    trigger_exclusion_mode: str = "shadow"
    trigger_exclusion_ready: bool = False
    trigger_exclusion_blockers: Tuple[str, ...] = ()
    fact_resolution: Optional[FactResolutionResult] = None


@dataclass(frozen=True)
class _PreparedAuditContext:
    units: Tuple[RegulationUnit, ...]
    audit_facts: Tuple[ExtractedFact, ...]
    product_facts: Tuple[ProductFact, ...]
    trigger_records: Tuple[RegulationTriggerRecord, ...]
    warnings: Tuple[str, ...] = ()
    shadow_warnings: Tuple[str, ...] = ()
    fact_resolution: Optional[FactResolutionResult] = None


RegulationRetriever = Callable[
    [str, Optional[str], ProductTags, Tuple[str, ...], int],
    RegulationRetrievalOutcome,
]
PackageAuditor = Callable[
    [
        Iterable[RegulationAuditPackage],
        int,
        float,
        Optional[Callable[[RegulationAuditDecision, int, int], None]],
    ],
    Tuple[RegulationAuditDecision, ...],
]
CandidateFreezeCallback = Callable[[RegulationRetrievalOutcome], None]
FactResolver = Callable[
    [
        Tuple[ProductFact, ...],
        Tuple[AuditClauseSnapshot, ...],
        Mapping[TriggerFactName, Tuple[str, ...]],
        float,
    ],
    FactResolutionResult,
]
_AUDIT_DEADLINE_ERROR_CODE = "audit_deadline_exceeded"
_AUDIT_DEADLINE_REASON = "整份审核已超过时间预算。"


def _default_retriever(
    query: str,
    category: Optional[str],
    product_tags: ProductTags,
    clause_topics: Tuple[str, ...],
    semantic_top_k: int,
) -> RegulationRetrievalOutcome:
    return retrieve_regulation_candidates(
        query,
        category,
        product_tags,
        clause_topics,
        semantic_top_k,
    )


def _default_auditor(
    packages: Iterable[RegulationAuditPackage],
    max_concurrency: int,
    deadline_seconds: float,
    on_decision: Optional[
        Callable[[RegulationAuditDecision, int, int], None]
    ],
) -> Tuple[RegulationAuditDecision, ...]:
    return audit_regulation_packages(
        packages,
        max_concurrency=max_concurrency,
        deadline_seconds=deadline_seconds,
        on_decision=on_decision,
    )


def _unit_snapshot(unit: RegulationUnit) -> RegulationUnitSnapshot:
    return RegulationUnitSnapshot(
        regulation_unit_id=unit.unit_id,
        kb_version=unit.kb_version,
        law_name=unit.law_name,
        source_file=unit.source_file,
        article_number=unit.article_number,
        section_path=unit.section_path,
        topics=unit.regulation_topics,
        chunks=tuple(
            RegulationChunkSnapshot(
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                chunk_index=(
                    chunk.chunk_index
                    if chunk.chunk_index is not None
                    else index
                ),
            )
            for index, chunk in enumerate(unit.chunks)
        ),
        applicability_status=unit.applicability_status,
        applicability_reasons=unit.applicability_reasons,
        category=unit.category,
        trigger_specs=unit.trigger_specs,
    )


def _required_fact_names(
    units: Iterable[RegulationUnit],
) -> Tuple[TriggerFactName, ...]:
    return tuple(dict.fromkeys(
        fact_name
        for unit in units
        for spec in unit.trigger_specs
        for fact_name in (spec.fact_name, *spec.required_facts)
    ))


def _prepare_audit_context(
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
    *,
    fact_resolver: Optional[FactResolver] = None,
    fact_resolution_timeout_seconds: float = 0.0,
    allow_trigger_exclusion: bool = False,
) -> _PreparedAuditContext:
    warnings: list[str] = []
    shadow_warnings: list[str] = []
    specs = tuple(spec for unit in units for spec in unit.trigger_specs)
    required_fact_names = _required_fact_names(units)
    try:
        audit_facts = extract_audit_facts(request.clauses, request.product_tags)
    except Exception as exc:
        logger.warning("产品共享确定性事实提取失败: %s", exc)
        audit_facts = ()
        warnings.append("产品共享确定性事实提取失败")
    try:
        product_facts = build_product_fact_ledger(
            request.clauses,
            request.product_tags,
            required_fact_names,
            complete_document=request.coverage_attested,
            coverage_attested_facts=request.coverage_attested_facts,
            trigger_specs=specs,
            extracted_facts=audit_facts,
        )
    except Exception as exc:
        logger.warning("产品触发事实账本构建失败: %s", exc)
        product_facts = tuple(
            ProductFact(
                name=fact_name,
                truth=FactTruth.UNKNOWN,
                confidence=0.0,
                method="fact_ledger_failure",
                reason="事实账本构建失败，保守保留法规",
            )
            for fact_name in required_fact_names
        )
        warnings.append("产品触发事实账本构建失败，所有触发条件保守保留")
    fact_resolution = FactResolutionResult(
        facts=product_facts,
        requested_fact_names=(),
        resolved_fact_names=(),
        validation_errors=(),
        attempted=False,
    )
    if fact_resolver is not None and product_facts:
        candidate_clauses, candidate_ids_by_fact, candidate_warnings = (
            _fact_resolution_candidates(request, units, product_facts)
        )
        shadow_warnings.extend(candidate_warnings)
        if candidate_clauses and candidate_ids_by_fact:
            try:
                fact_resolution = fact_resolver(
                    product_facts,
                    candidate_clauses,
                    candidate_ids_by_fact,
                    max(0.0, fact_resolution_timeout_seconds),
                )
                product_facts = fact_resolution.facts
                shadow_warnings.extend(fact_resolution.validation_errors)
            except Exception as exc:
                logger.warning("产品未决事实补充编排失败: %s", exc)
                fact_resolution = FactResolutionResult(
                    facts=product_facts,
                    requested_fact_names=tuple(candidate_ids_by_fact),
                    resolved_fact_names=(),
                    validation_errors=(
                        f"事实补充编排失败: {type(exc).__name__}",
                    ),
                    attempted=True,
                )
                shadow_warnings.extend(fact_resolution.validation_errors)
    fact_by_name = {fact.name: fact for fact in product_facts}
    trigger_records: list[RegulationTriggerRecord] = []
    retained_units: list[RegulationUnit] = []
    for unit in units:
        try:
            evaluation = evaluate_regulation_triggers(
                unit.trigger_specs,
                fact_by_name,
            )
        except Exception as exc:
            logger.warning("法规触发条件求值失败: unit=%s error=%s", unit.unit_id, exc)
            evaluation = TriggerEvaluation(
                status=TriggerStatus.INDETERMINATE,
                fact_names=tuple(spec.fact_name for spec in unit.trigger_specs),
                reasons=("触发求值失败，保守保留法规",),
                evidence_clause_ids=(),
            )
            warnings.append(f"{unit.unit_id}: 触发条件求值失败，保守保留")
        exclusion_approved = bool(unit.trigger_specs) and all(
            spec.exclusion_approved for spec in unit.trigger_specs
        )
        exclusion_applied = (
            evaluation.status is TriggerStatus.NOT_TRIGGERED
            and exclusion_approved
            and allow_trigger_exclusion
        )
        trigger_records.append(RegulationTriggerRecord(
            regulation_unit_id=unit.unit_id,
            kb_version=unit.kb_version,
            source_file=unit.source_file,
            section_path=unit.section_path,
            chunk_ids=unit.chunk_ids,
            law_name=unit.law_name,
            article_number=unit.article_number,
            trigger_specs=tuple(unit.trigger_specs),
            evaluation=evaluation,
            exclusion_approved=exclusion_approved,
            exclusion_applied=exclusion_applied,
        ))
        if not exclusion_applied:
            retained_units.append(unit)
    return _PreparedAuditContext(
        units=tuple(retained_units),
        audit_facts=audit_facts,
        product_facts=product_facts,
        trigger_records=tuple(trigger_records),
        warnings=tuple(warnings),
        shadow_warnings=tuple(dict.fromkeys(shadow_warnings)),
        fact_resolution=fact_resolution,
    )


def _routed_clauses(
    clauses: Tuple[AuditClauseSnapshot, ...],
    routing: ClauseRoutingResult,
) -> Tuple[RoutedClause, ...]:
    route_by_id = {item.clause_id: item for item in routing.items}
    relation_by_route = {
        ClauseRoute.DIRECT: RoutedClauseRelation.DIRECT,
        ClauseRoute.RELATED: RoutedClauseRelation.RELATED,
        ClauseRoute.UNKNOWN: RoutedClauseRelation.UNKNOWN,
        ClauseRoute.NOT_RELEVANT: RoutedClauseRelation.NOT_RELEVANT,
    }
    routed_clauses: list[RoutedClause] = []
    for clause in clauses:
        item = route_by_id.get(clause.clause_id)
        if item is None:
            routed_clauses.append(RoutedClause(
                clause=clause,
                relation=RoutedClauseRelation.UNKNOWN,
                reasons=("路由结果缺失，完整条款基线保守提交",),
                submitted=True,
            ))
            continue
        routed_clauses.append(
            RoutedClause(
                clause=clause,
                relation=relation_by_route[item.route],
                reasons=(
                    item.reason,
                    *(
                        f"受控排除 fixture: {fixture}"
                        for fixture in item.fixture_ids
                    ),
                    *(
                        ("完整条款基线：路由分类不删除 LLM 上下文",)
                        if item.route is ClauseRoute.NOT_RELEVANT
                        else ()
                    ),
                ),
                submitted=True,
            )
        )
    return tuple(routed_clauses)


def build_regulation_audit_packages(
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
    *,
    audit_facts: Optional[Tuple[ExtractedFact, ...]] = None,
    product_facts: Optional[Tuple[ProductFact, ...]] = None,
    trigger_evaluations: Optional[Mapping[str, TriggerEvaluation]] = None,
) -> Tuple[
    Tuple[RegulationAuditPackage, ...],
    Tuple[ClauseRoutingResult, ...],
    Tuple[str, ...],
]:
    packages: list[RegulationAuditPackage] = []
    routing_results: list[ClauseRoutingResult] = []
    warnings: list[str] = []
    if (
        audit_facts is None
        or product_facts is None
        or trigger_evaluations is None
    ):
        prepared = _prepare_audit_context(request, units)
        units = prepared.units
        audit_facts = prepared.audit_facts
        product_facts = prepared.product_facts
        trigger_evaluations = {
            record.regulation_unit_id: record.evaluation
            for record in prepared.trigger_records
        }
        warnings.extend(prepared.warnings)
    for index, unit in enumerate(units):
        routing = route_product_clauses(unit.regulation_topics, request.clauses)
        routed = _routed_clauses(request.clauses, routing)
        if routing.warnings:
            warnings.extend(
                f"{unit.unit_id}: {warning}" for warning in routing.warnings
            )
        packages.append(RegulationAuditPackage(
            task_id=f"audit:{unit.unit_id}",
            input_index=index,
            product_name=request.product_name,
            product_tags=request.product_tags,
            regulation=_unit_snapshot(unit),
            clauses=routed,
            facts=audit_facts,
            complete_document=request.coverage_attested,
            product_facts=product_facts,
            trigger_evaluation=trigger_evaluations.get(unit.unit_id),
        ))
        routing_results.append(routing)
    return tuple(packages), tuple(routing_results), tuple(warnings)


def _evidence_selection_for_spec(
    request: AuditPipelineRequest,
    unit: RegulationUnit,
    product_facts: Tuple[ProductFact, ...],
    spec: Optional[RegulationTriggerSpec],
) -> ClauseEvidenceSelection:
    known_clause_ids = {clause.clause_id for clause in request.clauses}
    relevant_fact_names = (
        frozenset((spec.fact_name, *spec.required_facts))
        if spec is not None
        else frozenset()
    )
    fact_evidence = tuple(
        FactEvidenceReference(fact.name.value, evidence.clause_id)
        for fact in product_facts
        if fact.name in relevant_fact_names
        for evidence in fact.evidence
        if evidence.clause_id in known_clause_ids
    )
    return select_clause_evidence(
        (
            spec.target_topics or unit.regulation_topics
            if spec is not None
            else unit.regulation_topics
        ),
        unit.content,
        request.clauses,
        fact_evidence=fact_evidence,
        search_all_terms=spec.search_all_terms if spec is not None else (),
        search_any_terms=spec.search_any_terms if spec is not None else (),
    )


def _evidence_selection_for_unit(
    request: AuditPipelineRequest,
    unit: RegulationUnit,
    product_facts: Tuple[ProductFact, ...],
) -> ClauseEvidenceSelection:
    spec_groups: Tuple[Optional[RegulationTriggerSpec], ...] = (
        tuple(unit.trigger_specs) if unit.trigger_specs else (None,)
    )
    selections = [
        _evidence_selection_for_spec(request, unit, product_facts, spec)
        for spec in spec_groups
    ]
    if len(selections) == 1:
        return selections[0]
    selected_set = {
        clause_id
        for selection in selections
        for clause_id in selection.selected_clause_ids
    }
    matches = tuple(dict.fromkeys(
        match for selection in selections for match in selection.matches
    ))
    return ClauseEvidenceSelection(
        regulation_topics=tuple(dict.fromkeys(
            topic for selection in selections for topic in selection.regulation_topics
        )),
        selected_clause_ids=tuple(
            clause.clause_id
            for clause in request.clauses
            if clause.clause_id in selected_set
        ),
        matches=matches,
        full_outline=selections[0].full_outline,
        relation_schema_version=",".join(dict.fromkeys(
            selection.relation_schema_version for selection in selections
        )),
        rule_schema_version=",".join(dict.fromkeys(
            selection.rule_schema_version for selection in selections
        )),
        config_valid=all(selection.config_valid for selection in selections),
        warnings=tuple(dict.fromkeys(
            warning for selection in selections for warning in selection.warnings
        )),
    )


def _fact_resolution_candidates(
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
    product_facts: Tuple[ProductFact, ...],
) -> Tuple[
    Tuple[AuditClauseSnapshot, ...],
    Mapping[TriggerFactName, Tuple[str, ...]],
    Tuple[str, ...],
]:
    unresolved = frozenset(
        fact.name for fact in product_facts if fact.truth is FactTruth.UNKNOWN
    )
    candidate_ids: dict[TriggerFactName, list[str]] = {}
    warnings: list[str] = []
    for unit in units:
        for spec in unit.trigger_specs:
            fact_names = tuple(
                name
                for name in (spec.fact_name, *spec.required_facts)
                if name in unresolved
            )
            if not fact_names:
                continue
            try:
                selection = _evidence_selection_for_spec(
                    request,
                    unit,
                    product_facts,
                    spec,
                )
            except Exception as exc:
                logger.warning(
                    "产品事实候选条款选择失败: unit=%s error=%s",
                    unit.unit_id,
                    exc,
                )
                warnings.append(f"{unit.unit_id}: 产品事实候选条款选择失败")
                continue
            warnings.extend(
                f"{unit.unit_id}: {warning}" for warning in selection.warnings
            )
            for fact_name in fact_names:
                candidate_ids.setdefault(fact_name, []).extend(
                    selection.selected_clause_ids
                )
    normalized_ids = {
        fact_name: tuple(dict.fromkeys(clause_ids))
        for fact_name, clause_ids in candidate_ids.items()
        if clause_ids
    }
    selected_ids = frozenset(
        clause_id
        for clause_ids in normalized_ids.values()
        for clause_id in clause_ids
    )
    clauses = tuple(
        clause for clause in request.clauses if clause.clause_id in selected_ids
    )
    return clauses, normalized_ids, tuple(dict.fromkeys(warnings))


def _build_shadow_evidence_selections(
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
    product_facts: Tuple[ProductFact, ...],
) -> Tuple[Mapping[str, ClauseEvidenceSelection], Tuple[str, ...]]:
    selections: dict[str, ClauseEvidenceSelection] = {}
    warnings: list[str] = []
    for unit in units:
        try:
            selection = _evidence_selection_for_unit(
                request,
                unit,
                product_facts,
            )
        except Exception as exc:
            logger.warning(
                "动态条款证据影子选择失败: unit=%s error=%s",
                unit.unit_id,
                exc,
            )
            warnings.append(f"{unit.unit_id}: 动态条款证据影子选择失败")
            continue
        selections[unit.unit_id] = selection
        warnings.extend(
            f"{unit.unit_id}: {warning}" for warning in selection.warnings
        )
    return selections, tuple(dict.fromkeys(warnings))


def _deadline_decision(
    package: RegulationAuditPackage,
) -> RegulationAuditDecision:
    return RegulationAuditDecision(
        task_id=package.task_id,
        regulation_unit_id=package.regulation.regulation_unit_id,
        status=RegulationDecisionStatus.MANUAL_REVIEW,
        reasoning=_AUDIT_DEADLINE_REASON,
        suggestion="请人工复核该法规条款单元。",
        regulation_evidence=(),
        product_evidence=(),
        incomplete=True,
        error_code=_AUDIT_DEADLINE_ERROR_CODE,
    )


def _notify_deadline_decisions(
    decisions: Tuple[RegulationAuditDecision, ...],
    callback: Optional[
        Callable[[RegulationAuditDecision, int, int], None]
    ],
) -> None:
    if callback is None:
        return
    total = len(decisions)
    for completed, decision in enumerate(decisions, start=1):
        try:
            callback(decision, completed, total)
        except Exception as exc:
            logger.warning("审核进度回调失败: %s", exc)


def _trigger_exclusion_gate(
    retrieval: RegulationRetrievalOutcome,
) -> Tuple[bool, Tuple[str, ...]]:
    blockers = []
    if ComplianceConstants.REGULATION_TRIGGER_EXCLUSION_MODE != "active":
        blockers.append("触发排除尚处于影子模式")
    if ComplianceConstants.EVALUATION_DATASET_STATUS != "approved":
        blockers.append("精算验收集尚未批准")
    if ComplianceConstants.CUTOVER_GATE_STATUS != "passed":
        blockers.append("生产切换门禁尚未通过")
    if retrieval.kb_trigger_schema_version != (
        ComplianceConstants.REGULATION_TRIGGER_SCHEMA_VERSION
    ):
        blockers.append("知识库触发 schema 与运行时不一致")
    approved_source_sha256 = (
        ComplianceConstants.APPROVED_REGULATION_TRIGGER_SOURCE_SHA256
    )
    if not approved_source_sha256:
        blockers.append("尚未绑定经精算验收的法规源文件指纹")
    elif retrieval.kb_source_sha256 != approved_source_sha256:
        blockers.append("当前法规源文件指纹与精算验收版本不一致")
    approved_catalog_sha256 = (
        ComplianceConstants.APPROVED_REGULATION_TRIGGER_CATALOG_SHA256
    )
    if not approved_catalog_sha256:
        blockers.append("尚未绑定经精算验收的法规目录指纹")
    elif retrieval.kb_catalog_sha256 != approved_catalog_sha256:
        blockers.append("当前法规目录指纹与精算验收版本不一致")
    if (
        retrieval.coverage is None
        or not retrieval.coverage.complete_candidate_freeze
    ):
        blockers.append("法规候选冻结不完整")
    if retrieval.degraded:
        blockers.append("法规检索已降级")
    return not blockers, tuple(blockers)


def run_audit_pipeline(
    request: AuditPipelineRequest,
    *,
    retriever: RegulationRetriever = _default_retriever,
    package_auditor: PackageAuditor = _default_auditor,
    semantic_top_k: int = 12,
    max_concurrency: int = ComplianceConstants.AUDIT_MAX_CONCURRENCY,
    deadline_seconds: float = ComplianceConstants.AUDIT_TOTAL_DEADLINE_SECONDS,
    on_decision: Optional[
        Callable[[RegulationAuditDecision, int, int], None]
    ] = None,
    on_candidates_frozen: Optional[CandidateFreezeCallback] = None,
    fact_resolver: Optional[FactResolver] = None,
) -> AuditPipelineResult:
    """执行候选冻结、逐法规路由、事实提取和法规级判断。"""
    deadline = time.monotonic() + max(0.0, deadline_seconds)
    clause_topics = tuple(dict.fromkeys(
        topic
        for clause in request.clauses
        for topic in clause.topics
        if topic
    ))
    query = build_regulation_retrieval_query(
        request.product_name,
        request.document_content,
        request.product_tags,
    )
    retrieval = retriever(
        query,
        request.category,
        request.product_tags,
        clause_topics,
        semantic_top_k,
    )
    trigger_exclusion_ready, trigger_exclusion_blockers = (
        _trigger_exclusion_gate(retrieval)
    )
    fact_resolution_timeout = min(
        max(0.0, deadline - time.monotonic()),
        ComplianceConstants.AUDIT_FACT_RESOLUTION_MAX_SECONDS,
    )
    prepared = _prepare_audit_context(
        request,
        retrieval.regulation_units,
        fact_resolver=fact_resolver,
        fact_resolution_timeout_seconds=fact_resolution_timeout,
        allow_trigger_exclusion=trigger_exclusion_ready,
    )
    trigger_excluded_count = sum(
        record.exclusion_applied for record in prepared.trigger_records
    )
    if on_candidates_frozen is not None:
        try:
            on_candidates_frozen(replace(
                retrieval,
                regulation_units=prepared.units,
                candidate_count=len(prepared.units),
                excluded_count=retrieval.excluded_count + trigger_excluded_count,
            ))
        except Exception as exc:
            logger.warning("法规候选冻结进度回调失败: %s", exc)
    trigger_evaluations = {
        record.regulation_unit_id: record.evaluation
        for record in prepared.trigger_records
    }
    evidence_selections, evidence_shadow_warnings = _build_shadow_evidence_selections(
        request,
        prepared.units,
        prepared.product_facts,
    )
    packages, routing_results, package_warnings = build_regulation_audit_packages(
        request,
        prepared.units,
        audit_facts=prepared.audit_facts,
        product_facts=prepared.product_facts,
        trigger_evaluations=trigger_evaluations,
    )
    processing_warnings = tuple((*prepared.warnings, *package_warnings))
    degrading_warnings = tuple(
        dict.fromkeys((
            *request.product_tags.warnings,
            *processing_warnings,
        ))
    )
    reported_warnings = tuple(
        dict.fromkeys((
            *request.parse_warnings,
            *degrading_warnings,
        ))
    )
    remaining_seconds = deadline - time.monotonic()
    deadline_exceeded = remaining_seconds <= 0
    if deadline_exceeded:
        decisions = tuple(_deadline_decision(package) for package in packages)
        _notify_deadline_decisions(decisions, on_decision)
        degrading_warnings = tuple(dict.fromkeys((
            *degrading_warnings,
            _AUDIT_DEADLINE_REASON,
        )))
        reported_warnings = tuple(dict.fromkeys((
            *reported_warnings,
            _AUDIT_DEADLINE_REASON,
        )))
    elif not packages:
        decisions = ()
    else:
        decisions = package_auditor(
            packages,
            max_concurrency,
            remaining_seconds,
            on_decision,
        )
        if time.monotonic() >= deadline:
            deadline_exceeded = True
            degrading_warnings = tuple(dict.fromkeys((
                *degrading_warnings,
                _AUDIT_DEADLINE_REASON,
            )))
            reported_warnings = tuple(dict.fromkeys((
                *reported_warnings,
                _AUDIT_DEADLINE_REASON,
            )))
    decision_by_task = {decision.task_id: decision for decision in decisions}
    for package in packages:
        if package.task_id in decision_by_task:
            continue
        decision_by_task[package.task_id] = RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.MANUAL_REVIEW,
            reasoning="法规审核任务没有返回结果。",
            suggestion="请人工复核该法规条款单元。",
            regulation_evidence=(),
            product_evidence=(),
            incomplete=True,
            error_code="missing_audit_decision",
        )
    records = tuple(
        RegulationAuditRecord(
            package=package,
            routing=routing,
            decision=decision_by_task[package.task_id],
            evidence_selection=evidence_selections.get(
                package.regulation.regulation_unit_id
            ),
        )
        for package, routing in zip(packages, routing_results)
    )
    missing_decisions = sum(
        record.decision.error_code == "missing_audit_decision"
        for record in records
    )
    if missing_decisions:
        missing_warning = f"{missing_decisions} 个法规审核任务没有返回结果"
        degrading_warnings = (
            *degrading_warnings,
            missing_warning,
        )
        reported_warnings = (
            *reported_warnings,
            missing_warning,
        )
    routing_degraded = any(not result.config_valid for result in routing_results)
    retrieval_complete = (
        retrieval.coverage.complete_candidate_freeze
        if retrieval.coverage is not None
        else not retrieval.degraded
    ) and not deadline_exceeded
    summary = summarize_audit_run(
        (record.decision for record in records),
        candidate_count=len(packages),
        excluded_count=retrieval.excluded_count + trigger_excluded_count,
        retrieval_degraded=(
            retrieval.degraded
            or routing_degraded
            or bool(degrading_warnings)
            or bool(missing_decisions)
        ),
        retrieval_complete=retrieval_complete,
        warnings=tuple(dict.fromkeys(
            (*retrieval.warnings, *reported_warnings)
        )),
    )
    taxonomy_versions = tuple(dict.fromkeys(
        result.topic_schema_version for result in routing_results
    ))
    relation_versions = tuple(dict.fromkeys(
        result.relation_schema_version for result in routing_results
    ))
    return AuditPipelineResult(
        request=request,
        retrieval=retrieval,
        records=records,
        summary=summary,
        topic_taxonomy_version=",".join(taxonomy_versions) or "unavailable",
        topic_relations_version=",".join(relation_versions) or "unavailable",
        warnings=summary.warnings,
        product_facts=prepared.product_facts,
        trigger_records=prepared.trigger_records,
        shadow_warnings=tuple(dict.fromkeys((
            *prepared.shadow_warnings,
            *evidence_shadow_warnings,
        ))),
        trigger_exclusion_mode=(
            ComplianceConstants.REGULATION_TRIGGER_EXCLUSION_MODE
        ),
        trigger_exclusion_ready=trigger_exclusion_ready,
        trigger_exclusion_blockers=trigger_exclusion_blockers,
        fact_resolution=prepared.fact_resolution,
    )
