"""候选版法规单元审核 API；不依赖旧规则引擎。"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
)

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.database import save_compliance_report
from api.schemas.compliance import DocumentCheckRequest
from lib.auth.permissions import require_permission
from lib.common.compliance_audit import (
    AuditStatus,
    ComplianceConclusion,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)
from lib.common.constants import ComplianceConstants
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    AuditPipelineResult,
    RegulationAuditRecord,
    run_audit_pipeline,
)
from lib.compliance.pipeline_request import (
    InvalidPipelineRequestError,
    ParsedAuditBlockInput,
    PipelineRequestConflictError,
    PipelineRequestInput,
    build_audit_pipeline_request,
)
from lib.compliance.regulation_retrieval import (
    AuditRegulationItem,
    RegulationRetrievalOutcome,
    infer_category_from_product_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查候选主链"])
AUDIT_TOTAL_DEADLINE_SECONDS = (
    ComplianceConstants.AUDIT_TOTAL_DEADLINE_SECONDS
)
AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS = (
    ComplianceConstants.AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS
)
AUDIT_MAX_CONCURRENCY = ComplianceConstants.AUDIT_MAX_CONCURRENCY
_AUDIT_WATCHDOG_MESSAGE = "审核主链超过端到端时间预算"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _decision_core(decision: RegulationAuditDecision) -> Dict[str, Any]:
    return _jsonable(asdict(decision))


def _record_data(record: RegulationAuditRecord) -> Dict[str, Any]:
    result = _decision_core(record.decision)
    routed_by_id = {
        routed.clause.clause_id: routed for routed in record.package.clauses
    }
    result["routed_clauses"] = [
        {
            "clause_id": item.clause_id,
            "number": routed_by_id[item.clause_id].clause.number,
            "title": routed_by_id[item.clause_id].clause.title,
            "topics": list(item.clause_topics),
            "relation": item.route.value,
            "reasons": [
                item.reason,
                *(f"受控排除 fixture: {fixture}" for fixture in item.fixture_ids),
            ],
            "submitted": item.selected,
        }
        for item in record.routing.items
    ]
    result["facts"] = [_jsonable(asdict(fact)) for fact in record.package.facts]
    return result


def _legacy_items(result: AuditPipelineResult) -> List[Dict[str, Any]]:
    clause_by_id = {
        clause.clause_id: clause for clause in result.request.clauses
    }
    items: List[Dict[str, Any]] = []
    for record in result.records:
        decision = record.decision
        if decision.status is RegulationDecisionStatus.COMPLIANT:
            continue
        product_ids = tuple(
            evidence.clause_id for evidence in decision.product_evidence
        )
        first_clause = clause_by_id.get(product_ids[0]) if product_ids else None
        items.append({
            "clause_number": first_clause.number if first_clause else "未知",
            "check_type": "regulation_unit",
            "clause_content": "\n".join(
                evidence.quote for evidence in decision.product_evidence
            ),
            "status": (
                "non_compliant"
                if decision.status is RegulationDecisionStatus.NON_COMPLIANT
                else "attention"
            ),
            "chunk_id": (
                decision.regulation_evidence[0].chunk_id
                if decision.regulation_evidence
                else None
            ),
            "source_ref": decision.regulation_unit_id,
            "suggestion": decision.suggestion,
            "conclusion": decision.status.value,
            "regulation_unit_id": decision.regulation_unit_id,
            "regulation_chunk_ids": [
                chunk.chunk_id for chunk in record.package.regulation.chunks
            ],
            "product_clause_ids": list(product_ids),
            "reasoning": decision.reasoning,
            "confidence": decision.confidence,
            "applicability_dispute": decision.applicability_dispute,
            "incomplete": decision.incomplete,
            "error_code": decision.error_code,
        })
    return items


def _is_negative_record(record: RegulationAuditRecord) -> bool:
    regulation = record.package.regulation
    identity = f"{regulation.law_name} {regulation.source_file}"
    return regulation.category == "负面清单检查" or "负面清单" in identity


def _negative_list_status(records: Iterable[RegulationAuditRecord]) -> str:
    negative = tuple(record for record in records if _is_negative_record(record))
    if not negative:
        return "skipped"
    if any(
        record.decision.status is RegulationDecisionStatus.NON_COMPLIANT
        for record in negative
    ):
        return "violated"
    if all(
        record.decision.status is RegulationDecisionStatus.COMPLIANT
        and not record.decision.incomplete
        for record in negative
    ):
        return "passed"
    return "skipped"


def _regulation_sources(
    regulations: Iterable[AuditRegulationItem],
) -> Dict[str, List[str]]:
    labels = {
        "category": "险种专属",
        "general": "通用法规",
        "semantic": "语义检索",
        "catalog": "全库候选",
        "negative_list": "负面清单",
    }
    sources: Dict[str, List[str]] = {}
    for regulation in regulations:
        label = (
            "负面清单"
            if (
                regulation.category == "负面清单检查"
                or "负面清单" in f"{regulation.law_name} {regulation.source_file}"
            )
            else labels.get(regulation.source_type, regulation.source_type or "标签检索")
        )
        sources.setdefault(label, []).append(regulation.law_name)
    return {
        label: sorted(set(names))
        for label, names in sources.items()
    }


def _clause_coverage(result: AuditPipelineResult) -> Dict[str, Any]:
    all_ids = {clause.clause_id for clause in result.request.clauses}
    checked_ids = {
        routed.clause.clause_id
        for record in result.records
        for routed in record.package.clauses
        if routed.submitted
    }
    clause_by_id = {
        clause.clause_id: clause for clause in result.request.clauses
    }
    unchecked = [
        clause_by_id[clause_id].number or clause_id
        for clause_id in sorted(all_ids - checked_ids)
    ]
    block_types = {clause.block_type for clause in result.request.clauses}
    return {
        "total": len(all_ids),
        "checked": len(checked_ids),
        "unchecked": unchecked,
        "all_total": len(all_ids),
        "has_notices": "notice" in block_types,
        "has_health": "health_disclosure" in block_types,
        "has_exclusions": "exclusion" in block_types,
        "has_tables": "table" in block_types,
    }


def build_report_data(result: AuditPipelineResult) -> Dict[str, Any]:
    decisions = [_record_data(record) for record in result.records]
    summary = {
        "compliant": sum(
            record.decision.status is RegulationDecisionStatus.COMPLIANT
            for record in result.records
        ),
        "non_compliant": sum(
            record.decision.status is RegulationDecisionStatus.NON_COMPLIANT
            for record in result.records
        ),
        "attention": sum(
            record.decision.status in {
                RegulationDecisionStatus.INSUFFICIENT_INFORMATION,
                RegulationDecisionStatus.MANUAL_REVIEW,
            }
            for record in result.records
        ),
    }
    kb_versions = tuple(dict.fromkeys(
        unit.kb_version
        for unit in result.retrieval.regulation_units
        if unit.kb_version
    ))
    failure_reasons = tuple(dict.fromkeys((
        *result.warnings,
        *(
            f"{record.decision.regulation_unit_id}: {record.decision.error_code}"
            for record in result.records
            if record.decision.incomplete
        ),
    )))
    return {
        "summary": summary,
        "items": _legacy_items(result),
        "regulations": [
            _jsonable(asdict(regulation))
            for regulation in result.retrieval.regulations
        ],
        "excluded_regulations": [
            _jsonable(asdict(regulation))
            for regulation in result.retrieval.excluded_regulation_units
        ],
        "decisions": decisions,
        "product_tags": result.request.product_tags.to_dict(),
        "document_fingerprint": result.request.document_fingerprint,
        "audit_input_fingerprint": result.request.audit_input_fingerprint,
        "product_name_source": result.request.product_name_source,
        "parse_warnings": list(result.request.parse_warnings),
        "regulation_sources": _regulation_sources(result.retrieval.regulations),
        "category": (
            result.request.category
            or infer_category_from_product_tags(result.request.product_tags)
            or ""
        ),
        "negative_list_result": _negative_list_status(result.records),
        "retrieval_degraded": result.retrieval.degraded,
        "retrieval_warnings": list(result.retrieval.warnings),
        "clause_coverage": _clause_coverage(result),
        "audit_status": result.summary.audit_status.value,
        "compliance_conclusion": result.summary.compliance_conclusion.value,
        "kb_version": ",".join(kb_versions),
        "topic_taxonomy_version": result.topic_taxonomy_version,
        "topic_relations_version": result.topic_relations_version,
        "evaluation_dataset_version": ComplianceConstants.EVALUATION_DATASET_VERSION,
        "evaluation_dataset_status": ComplianceConstants.EVALUATION_DATASET_STATUS,
        "cutover_gate_status": ComplianceConstants.CUTOVER_GATE_STATUS,
        "candidate_count": result.summary.candidate_count,
        "excluded_count": result.summary.excluded_count,
        "completed_count": result.summary.completed_count,
        "failed_count": result.summary.failed_count,
        "failure_reasons": list(failure_reasons),
    }


def _incomplete_report(
    category: str,
    message: str,
    request: Optional[AuditPipelineRequest] = None,
) -> Dict[str, Any]:
    return {
        "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
        "items": [],
        "regulations": [],
        "excluded_regulations": [],
        "decisions": [],
        "product_tags": (
            request.product_tags.to_dict() if request is not None else {}
        ),
        "document_fingerprint": (
            request.document_fingerprint if request is not None else ""
        ),
        "audit_input_fingerprint": (
            request.audit_input_fingerprint if request is not None else ""
        ),
        "product_name_source": (
            request.product_name_source if request is not None else "unknown"
        ),
        "parse_warnings": (
            list(request.parse_warnings) if request is not None else []
        ),
        "regulation_sources": {},
        "category": category,
        "negative_list_result": "skipped",
        "retrieval_degraded": True,
        "retrieval_warnings": [message],
        "clause_coverage": None,
        "audit_status": AuditStatus.INCOMPLETE.value,
        "compliance_conclusion": ComplianceConclusion.UNDETERMINED.value,
        "kb_version": "",
        "topic_taxonomy_version": "unavailable",
        "topic_relations_version": "unavailable",
        "evaluation_dataset_version": ComplianceConstants.EVALUATION_DATASET_VERSION,
        "evaluation_dataset_status": ComplianceConstants.EVALUATION_DATASET_STATUS,
        "cutover_gate_status": ComplianceConstants.CUTOVER_GATE_STATUS,
        "candidate_count": 0,
        "excluded_count": 0,
        "completed_count": 0,
        "failed_count": 1,
        "failure_reasons": [message],
    }


def _pipeline_request(
    req: DocumentCheckRequest,
    user_subject: str = "",
) -> AuditPipelineRequest:
    try:
        return build_audit_pipeline_request(
            PipelineRequestInput(
                document_content=req.document_content,
                parse_id=req.parse_id,
                parse_attestation=req.parse_attestation,
                document_fingerprint=req.document_fingerprint,
                audit_input_fingerprint=req.audit_input_fingerprint,
                product_name=req.product_name,
                product_name_source=req.product_name_source,
                coverage_attested=req.coverage_attested,
                parse_warnings=tuple(req.parse_warnings),
                category=req.category,
                audit_blocks=tuple(
                    ParsedAuditBlockInput(
                        clause_id=block.clause_id,
                        block_type=block.block_type,
                        source_index=block.source_index,
                        number=block.number,
                        title=block.title,
                        content=block.content,
                        hierarchy_level=block.hierarchy_level,
                        parent_number=block.parent_number,
                        ancestor_numbers=tuple(block.ancestor_numbers),
                        hierarchy_path=block.hierarchy_path,
                        container_only=block.container_only,
                    )
                    for block in req.audit_blocks
                ),
                product_tags=req.product_tags,
            ),
            user_subject,
        )
    except InvalidPipelineRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PipelineRequestConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/check/document/v2/stream")
async def check_document_v2_stream(
    req: DocumentCheckRequest,
    user: Dict[str, Any] = Depends(require_permission("compliance")),
) -> EventSourceResponse:
    """执行候选新主链；精算验收完成前不替换现有默认入口。"""
    pipeline_request = _pipeline_request(req, str(user.get("user_id", "")))

    async def event_stream() -> AsyncIterator[Dict[str, str]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        holder: Dict[str, Any] = {}
        total_budget = max(0.0, AUDIT_TOTAL_DEADLINE_SECONDS)
        persistence_reserve = min(
            max(0.0, AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS),
            total_budget,
        )
        overall_deadline = time.monotonic() + total_budget
        producer_deadline = overall_deadline - persistence_reserve

        def enqueue_from_thread(event: Optional[Dict[str, Any]]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                logger.warning("审核事件循环已关闭，丢弃后台线程事件")

        def on_decision(
            decision: RegulationAuditDecision,
            completed: int,
            total: int,
        ) -> None:
            enqueue_from_thread({
                "type": "regulation_decision",
                "data": {
                    **_decision_core(decision),
                    "completed": completed,
                    "total": total,
                },
            })

        def on_candidates_frozen(outcome: RegulationRetrievalOutcome) -> None:
            coverage = (
                _jsonable(asdict(outcome.coverage))
                if outcome.coverage is not None
                else None
            )
            enqueue_from_thread({
                "type": "candidate_freeze",
                "data": {
                    "candidate_count": outcome.candidate_count,
                    "excluded_count": outcome.excluded_count,
                    "degraded": outcome.degraded,
                    "warnings": list(outcome.warnings),
                    "coverage": coverage,
                },
            })

        def producer() -> None:
            try:
                holder["result"] = run_audit_pipeline(
                    pipeline_request,
                    max_concurrency=AUDIT_MAX_CONCURRENCY,
                    deadline_seconds=max(
                        0.0,
                        producer_deadline - time.monotonic(),
                    ),
                    on_decision=on_decision,
                    on_candidates_frozen=on_candidates_frozen,
                )
            except Exception as exc:
                logger.exception("候选审核主链失败")
                holder["error"] = str(exc)
            finally:
                enqueue_from_thread(None)

        yield {
            "event": "message",
            "data": json.dumps({
                "type": "progress",
                "data": "正在冻结法规候选并执行适用性过滤…",
            }, ensure_ascii=False),
        }
        producer_thread = threading.Thread(
            target=producer,
            daemon=True,
            name="compliance-v2-audit",
        )
        try:
            producer_thread.start()
        except RuntimeError as exc:
            logger.exception("候选审核后台线程启动失败")
            holder["error"] = f"审核主链无法启动：{exc}"

        watchdog_timed_out = False
        while producer_thread.ident is not None:
            remaining = producer_deadline - time.monotonic()
            if remaining <= 0:
                watchdog_timed_out = True
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                watchdog_timed_out = True
                break
            if event is None:
                break
            yield {
                "event": "message",
                "data": json.dumps(event, ensure_ascii=False),
            }
        if watchdog_timed_out:
            holder["error"] = _AUDIT_WATCHDOG_MESSAGE

        report_id = f"cr_{uuid.uuid4().hex}"
        try:
            pipeline_result = holder.get("result")
            if (
                not watchdog_timed_out
                and isinstance(pipeline_result, AuditPipelineResult)
            ):
                report_data = build_report_data(pipeline_result)
            else:
                report_data = _incomplete_report(
                    pipeline_request.category or "",
                    f"审核主链异常：{holder.get('error', '未知错误')}",
                    pipeline_request,
                )
            persistence_timeout = overall_deadline - time.monotonic()
            if persistence_timeout <= 0:
                raise asyncio.TimeoutError("审核报告持久化预算已耗尽")
            # SQLite 工作已进入线程后无法安全取消；等待事务明确结束，避免
            # 客户端先收到 error、后台随后提交而形成不可见的孤儿报告。
            await asyncio.to_thread(
                save_compliance_report,
                report_id,
                pipeline_request.product_name,
                pipeline_request.category or "",
                "document",
                report_data,
                str(user.get("user_id", "")),
            )
        except Exception:
            logger.exception("候选审核报告生成或持久化失败: %s", report_id)
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",
                        "data": "报告生成或保存失败，审核结果未形成可信终态",
                    },
                    ensure_ascii=False,
                ),
            }
            return
        done_data = {
            "report_id": report_id,
            "product_name": pipeline_request.product_name,
            **report_data,
        }
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "done", "data": done_data},
                ensure_ascii=False,
            ),
        }

    return EventSourceResponse(event_stream())
