"""产品标签驱动的单一法规审核编排链。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    AuditRunSummary,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
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
from lib.compliance.fact_extraction import extract_audit_facts
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalOutcome,
    build_regulation_retrieval_query,
    retrieve_regulation_candidates,
)
from lib.compliance.regulation_units import RegulationUnit

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


@dataclass(frozen=True)
class RegulationAuditRecord:
    package: RegulationAuditPackage
    routing: ClauseRoutingResult
    decision: RegulationAuditDecision


@dataclass(frozen=True)
class AuditPipelineResult:
    request: AuditPipelineRequest
    retrieval: RegulationRetrievalOutcome
    records: Tuple[RegulationAuditRecord, ...]
    summary: AuditRunSummary
    topic_taxonomy_version: str
    topic_relations_version: str
    warnings: Tuple[str, ...] = ()


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


def _build_packages(
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
) -> Tuple[
    Tuple[RegulationAuditPackage, ...],
    Tuple[ClauseRoutingResult, ...],
    Tuple[str, ...],
]:
    packages = []
    routing_results = []
    warnings = []
    for index, unit in enumerate(units):
        routing = route_product_clauses(unit.regulation_topics, request.clauses)
        routed = _routed_clauses(request.clauses, routing)
        selected = tuple(item.clause for item in routed if item.submitted)
        try:
            facts = extract_audit_facts(selected, request.product_tags)
        except Exception as exc:
            logger.warning("法规单元事实提取失败: unit=%s error=%s", unit.unit_id, exc)
            facts = ()
            warnings.append(f"{unit.unit_id}: 事实提取失败")
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
            facts=facts,
        ))
        routing_results.append(routing)
    return tuple(packages), tuple(routing_results), tuple(warnings)


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
    if on_candidates_frozen is not None:
        try:
            on_candidates_frozen(retrieval)
        except Exception as exc:
            logger.warning("法规候选冻结进度回调失败: %s", exc)
    packages, routing_results, processing_warnings = _build_packages(
        request,
        retrieval.regulation_units,
    )
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
        excluded_count=retrieval.excluded_count,
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
    )
