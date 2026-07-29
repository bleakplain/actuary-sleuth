"""逐法规条款单元的结构化 LLM 审核。"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.common.compliance_audit import (
    ProductClauseEvidence,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    RegulationEvidence,
    RoutedClause,
)
from lib.common.constants import ComplianceConstants
from lib.llm.base import BaseLLMClient
from lib.llm.factory import LLMClientFactory
from lib.config import get_audit_llm_config

logger = logging.getLogger(__name__)
_PROMPT_SAFETY_MARGIN = 10_000
_MIN_EVIDENCE_CHARACTERS = 6
_MIN_AUTOMATED_DECISION_CONFIDENCE = 0.7
_GLOBAL_AUDIT_SLOTS = threading.BoundedSemaphore(
    ComplianceConstants.AUDIT_MAX_CONCURRENCY
)


class _EvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    regulation_unit_id: str
    status: RegulationDecisionStatus
    reasoning: str = Field(min_length=1)
    suggestion: str = ""
    regulation_evidence: Tuple[_EvidenceOutput, ...] = ()
    product_evidence: Tuple[_EvidenceOutput, ...] = ()
    applicability_dispute: bool = False
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


def _package_payload(package: RegulationAuditPackage) -> Dict[str, object]:
    return {
        "task_id": package.task_id,
        "regulation_unit": {
            "regulation_unit_id": package.regulation.regulation_unit_id,
            "kb_version": package.regulation.kb_version,
            "law_name": package.regulation.law_name,
            "source_file": package.regulation.source_file,
            "article_number": package.regulation.article_number,
            "section_path": package.regulation.section_path,
            "applicability_status": package.regulation.applicability_status,
            "applicability_reasons": list(package.regulation.applicability_reasons),
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                }
                for chunk in package.regulation.chunks
            ],
        },
        "product": {
            "name": package.product_name,
            "tags": package.product_tags.to_dict(),
            "clauses": [
                {
                    "clause_id": routed.clause.clause_id,
                    "number": routed.clause.number,
                    "title": routed.clause.title,
                    "text": routed.clause.text,
                    "topics": list(routed.clause.topics),
                    "hierarchy_level": routed.clause.hierarchy_level,
                    "parent_number": routed.clause.parent_number,
                    "ancestor_numbers": list(
                        routed.clause.ancestor_numbers
                    ),
                    "hierarchy_path": routed.clause.hierarchy_path,
                    "container_only": routed.clause.container_only,
                    "relation": routed.relation.value,
                    "routing_reasons": list(routed.reasons),
                }
                for routed in package.clauses
                if routed.submitted
            ],
            "facts": [
                {
                    "kind": fact.kind.value,
                    "value": fact.value,
                    "unit": fact.unit,
                    "clause_id": fact.clause_id,
                    "evidence": fact.evidence,
                    "confidence": fact.confidence,
                }
                for fact in package.facts
            ],
        },
    }


def build_audit_messages(
    package: RegulationAuditPackage,
) -> List[Dict[str, str]]:
    payload = json.dumps(_package_payload(package), ensure_ascii=False)
    system = (
        "你是保险产品条款合规审核员。只能使用用户消息中的法规原文、产品标签、"
        "产品条款和确定性事实。一次只判断一个 regulation_unit。"
        "不得使用外部法规，不得把适用性改为 not_applicable。"
    )
    instruction = """请输出一个 JSON 对象，且不得输出 Markdown：
{
  "task_id": "<原 task_id>",
  "regulation_unit_id": "<原 regulation_unit_id>",
  "status": "compliant|non_compliant|insufficient_information|manual_review",
  "reasoning": "<依据法规和产品原文的理由>",
  "suggestion": "<必要时的修改建议>",
  "regulation_evidence": [{"evidence_id": "<chunk_id>", "quote": "<逐字摘录>"}],
  "product_evidence": [{"evidence_id": "<clause_id；仅名称类法规可用 product-name>", "quote": "<逐字摘录>"}],
  "applicability_dispute": false,
  "confidence": 0.0
}

约束：
1. non_compliant 必须同时引用至少一条法规证据和一条产品条款证据。
2. compliant 必须同时有法规证据和产品条款证据；若无法用产品原文证明已满足要求，
   输出 insufficient_information。
3. 法规适用性存在争议时输出 manual_review，并将 applicability_dispute 设为 true。
4. quote 必须是对应 evidence_id 原文中的连续逐字摘录。
5. 不得引用未提供的 evidence_id。
6. 产品条款证据必须摘录条款正文，不得只引用条款标题；摘录至少包含一个完整事实或要求。
7. 只有法规条款主题包含 contract.name 时，才可以把 product-name 作为产品证据。

审核包：
""" + payload
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline < 0:
        return text
    text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _failure_decision(
    package: RegulationAuditPackage,
    error_code: str,
    reasoning: str,
) -> RegulationAuditDecision:
    return RegulationAuditDecision(
        task_id=package.task_id,
        regulation_unit_id=package.regulation.regulation_unit_id,
        status=RegulationDecisionStatus.MANUAL_REVIEW,
        reasoning=reasoning,
        suggestion="请人工复核该法规条款单元。",
        regulation_evidence=(),
        product_evidence=(),
        incomplete=True,
        error_code=error_code,
    )


def _validate_evidence(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
) -> RegulationAuditDecision:
    if not output.reasoning.strip():
        raise ValueError("reasoning 不能为空")
    regulation_content = {
        chunk.chunk_id: chunk.content for chunk in package.regulation.chunks
    }
    product_content = {
        routed.clause.clause_id: routed.clause.text
        for routed in package.clauses
        if routed.submitted
    }

    def require_substantive_quote(quote: str, evidence_type: str) -> str:
        normalized = re.sub(r"[\W_]+", "", quote, flags=re.UNICODE)
        if len(normalized) < _MIN_EVIDENCE_CHARACTERS:
            raise ValueError(
                f"{evidence_type}摘录过短，不能证明完整事实或要求"
            )
        return quote.strip()

    regulation_evidence: List[RegulationEvidence] = []
    for evidence in output.regulation_evidence:
        if not evidence.evidence_id.strip() or not evidence.quote.strip():
            raise ValueError("法规证据 ID 和摘录不能为空")
        content = regulation_content.get(evidence.evidence_id)
        if content is None or evidence.quote not in content:
            raise ValueError(f"无效法规证据: {evidence.evidence_id}")
        regulation_evidence.append(RegulationEvidence(
            chunk_id=evidence.evidence_id,
            quote=require_substantive_quote(evidence.quote, "法规证据"),
        ))
    product_evidence: List[ProductClauseEvidence] = []
    for evidence in output.product_evidence:
        if not evidence.evidence_id.strip() or not evidence.quote.strip():
            raise ValueError("产品证据 ID 和摘录不能为空")
        source_kind = "clause_body"
        content = product_content.get(evidence.evidence_id)
        if evidence.evidence_id == "product-name":
            if "contract.name" not in package.regulation.topics:
                raise ValueError("当前法规主题不允许使用 product-name 作为结论证据")
            source_kind = "product_name"
            content = package.product_name
        if content is None or evidence.quote not in content:
            raise ValueError(f"无效产品条款证据: {evidence.evidence_id}")
        product_evidence.append(ProductClauseEvidence(
            clause_id=evidence.evidence_id,
            quote=require_substantive_quote(evidence.quote, "产品证据"),
            source_kind=source_kind,
        ))

    status = output.status
    incomplete = False
    error_code = ""
    reasoning = output.reasoning
    if output.task_id != package.task_id:
        raise ValueError("task_id 与审核包不一致")
    if output.regulation_unit_id != package.regulation.regulation_unit_id:
        raise ValueError("regulation_unit_id 与审核包不一致")
    if output.applicability_dispute:
        status = RegulationDecisionStatus.MANUAL_REVIEW
    if (
        status in {
            RegulationDecisionStatus.COMPLIANT,
            RegulationDecisionStatus.NON_COMPLIANT,
        }
        and (
            output.confidence is None
            or output.confidence < _MIN_AUTOMATED_DECISION_CONFIDENCE
        )
    ):
        status = RegulationDecisionStatus.MANUAL_REVIEW
        error_code = "low_model_confidence"
        reasoning = (
            f"{reasoning}；模型置信度不足，不能形成自动合规或不合规结论。"
        )
    if status is RegulationDecisionStatus.NON_COMPLIANT and (
        not regulation_evidence or not product_evidence
    ):
        status = RegulationDecisionStatus.MANUAL_REVIEW
        incomplete = True
        error_code = "missing_non_compliance_evidence"
        reasoning = f"{reasoning}；模型未提供完整的法规与产品条款证据。"
    if status is RegulationDecisionStatus.COMPLIANT and (
        not regulation_evidence or not product_evidence
    ):
        status = RegulationDecisionStatus.MANUAL_REVIEW
        incomplete = True
        error_code = "missing_compliance_evidence"
        reasoning = f"{reasoning}；模型未提供完整的法规与产品条款证据。"
    return RegulationAuditDecision(
        task_id=package.task_id,
        regulation_unit_id=package.regulation.regulation_unit_id,
        status=status,
        reasoning=reasoning,
        suggestion=output.suggestion,
        regulation_evidence=tuple(regulation_evidence),
        product_evidence=tuple(product_evidence),
        applicability_dispute=output.applicability_dispute,
        confidence=output.confidence,
        incomplete=incomplete,
        error_code=error_code,
    )


def _audit_atomic_package(
    package: RegulationAuditPackage,
    llm: BaseLLMClient,
    timeout_seconds: float,
) -> RegulationAuditDecision:
    try:
        request_timeout = max(1.0, min(45.0, timeout_seconds / 3))
        raw = llm.chat(
            build_audit_messages(package),
            temperature=0.0,
            max_tokens=4096,
            timeout=request_timeout,
            _retry_deadline=time.monotonic() + max(0.001, timeout_seconds),
        )
        output = _DecisionOutput.model_validate_json(_strip_code_fence(raw))
        return _validate_evidence(package, output)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return _failure_decision(
            package, "invalid_structured_output", f"模型输出无法验证：{exc}",
        )
    except Exception as exc:
        logger.warning(
            "法规条款单元审核失败: unit=%s error=%s",
            package.regulation.regulation_unit_id,
            exc,
        )
        return _failure_decision(package, "llm_call_failed", f"模型调用失败：{exc}")


def _package_length(package: RegulationAuditPackage) -> int:
    return sum(len(message["content"]) for message in build_audit_messages(package))


def _segment_package(
    package: RegulationAuditPackage,
    chunks: Tuple[RegulationChunkSnapshot, ...],
    clauses: Tuple[RoutedClause, ...],
    segment_index: int,
) -> RegulationAuditPackage:
    clause_ids = {
        routed.clause.clause_id for routed in clauses if routed.submitted
    }
    facts = tuple(
        fact
        for fact in package.facts
        if fact.clause_id == "product-name" or fact.clause_id in clause_ids
    )
    return replace(
        package,
        task_id=f"{package.task_id}:segment:{segment_index}",
        regulation=replace(package.regulation, chunks=chunks),
        clauses=clauses,
        facts=facts,
    )


def split_audit_package(
    package: RegulationAuditPackage,
    max_prompt_length: int = BaseLLMClient.MAX_PROMPT_LENGTH,
) -> Tuple[RegulationAuditPackage, ...]:
    """仅在超长时按法规 chunk 与产品条款边界分段，不截断证据原文。"""
    if _package_length(package) <= max_prompt_length:
        return (package,)
    target = max(1, max_prompt_length - min(_PROMPT_SAFETY_MARGIN, max_prompt_length // 10))
    chunks = package.regulation.chunks
    chunk_groups: List[Tuple[RegulationChunkSnapshot, ...]] = []
    current_chunks: List[RegulationChunkSnapshot] = []
    for chunk in chunks:
        candidate = (*current_chunks, chunk)
        probe = _segment_package(package, tuple(candidate), (), 0)
        if current_chunks and _package_length(probe) > target:
            chunk_groups.append(tuple(current_chunks))
            current_chunks = [chunk]
        else:
            current_chunks.append(chunk)
    if current_chunks:
        chunk_groups.append(tuple(current_chunks))

    submitted = tuple(item for item in package.clauses if item.submitted)
    unsubmitted = tuple(item for item in package.clauses if not item.submitted)
    segments: List[RegulationAuditPackage] = []
    segment_index = 0
    for chunk_group in chunk_groups:
        if not submitted:
            segments.append(_segment_package(
                package,
                chunk_group,
                unsubmitted,
                segment_index,
            ))
            segment_index += 1
            continue
        clause_groups: List[Tuple[RoutedClause, ...]] = []
        current_clauses: List[RoutedClause] = []
        for clause in submitted:
            candidate_clauses = (*current_clauses, clause)
            probe = _segment_package(
                package,
                chunk_group,
                tuple(candidate_clauses),
                segment_index,
            )
            if current_clauses and _package_length(probe) > target:
                clause_groups.append(tuple(current_clauses))
                current_clauses = [clause]
            else:
                current_clauses.append(clause)
        if current_clauses:
            clause_groups.append(tuple(current_clauses))
        for clause_group in clause_groups:
            segments.append(_segment_package(
                package,
                chunk_group,
                (*clause_group, *unsubmitted),
                segment_index,
            ))
            segment_index += 1
    return tuple(segments) or (package,)


def _merge_segment_decisions(
    package: RegulationAuditPackage,
    decisions: Tuple[RegulationAuditDecision, ...],
) -> RegulationAuditDecision:
    priority = {
        RegulationDecisionStatus.NON_COMPLIANT: 0,
        RegulationDecisionStatus.MANUAL_REVIEW: 1,
        RegulationDecisionStatus.INSUFFICIENT_INFORMATION: 2,
        RegulationDecisionStatus.COMPLIANT: 3,
    }
    applicability_dispute = any(
        item.applicability_dispute for item in decisions
    )
    status = (
        RegulationDecisionStatus.MANUAL_REVIEW
        if applicability_dispute
        else min((item.status for item in decisions), key=priority.__getitem__)
    )
    regulation_evidence = tuple({
        (item.chunk_id, item.quote): item
        for decision in decisions
        for item in decision.regulation_evidence
    }.values())
    product_evidence = tuple({
        (item.clause_id, item.quote): item
        for decision in decisions
        for item in decision.product_evidence
    }.values())
    confidences = tuple(
        item.confidence for item in decisions if item.confidence is not None
    )
    error_codes = tuple(dict.fromkeys(
        item.error_code for item in decisions if item.error_code
    ))
    return RegulationAuditDecision(
        task_id=package.task_id,
        regulation_unit_id=package.regulation.regulation_unit_id,
        status=status,
        reasoning="\n".join(
            f"分段{index + 1}：{item.reasoning}"
            for index, item in enumerate(decisions)
        ),
        suggestion="\n".join(dict.fromkeys(
            item.suggestion for item in decisions if item.suggestion
        )),
        regulation_evidence=regulation_evidence,
        product_evidence=product_evidence,
        applicability_dispute=applicability_dispute,
        confidence=min(confidences) if confidences else None,
        incomplete=any(item.incomplete for item in decisions),
        error_code=",".join(error_codes),
    )


def audit_regulation_package(
    package: RegulationAuditPackage,
    llm: BaseLLMClient,
    timeout_seconds: float,
) -> RegulationAuditDecision:
    segments = split_audit_package(package)
    if len(segments) == 1 and segments[0] is package:
        return _audit_atomic_package(package, llm, timeout_seconds)
    deadline = time.monotonic() + max(0.001, timeout_seconds)
    decisions: List[RegulationAuditDecision] = []
    for segment in segments:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            decisions.append(_failure_decision(
                segment,
                "audit_deadline_exceeded",
                "法规条款单元分段未在时间预算内完成。",
            ))
            continue
        decisions.append(_audit_atomic_package(segment, llm, remaining))
    return _merge_segment_decisions(package, tuple(decisions))


def _create_audit_client() -> BaseLLMClient:
    return LLMClientFactory.create_client(get_audit_llm_config())


def audit_regulation_packages(
    packages: Iterable[RegulationAuditPackage],
    client_factory: Callable[[], BaseLLMClient] = _create_audit_client,
    max_concurrency: int = ComplianceConstants.AUDIT_MAX_CONCURRENCY,
    deadline_seconds: float = ComplianceConstants.AUDIT_TOTAL_DEADLINE_SECONDS,
    on_decision: Optional[
        Callable[[RegulationAuditDecision, int, int], None]
    ] = None,
) -> Tuple[RegulationAuditDecision, ...]:
    ordered = tuple(sorted(packages, key=lambda item: item.input_index))
    if not ordered:
        return ()
    concurrency = max(
        1,
        min(max_concurrency, ComplianceConstants.AUDIT_MAX_CONCURRENCY),
    )
    deadline = time.monotonic() + max(0.001, deadline_seconds)

    def run(package: RegulationAuditPackage) -> RegulationAuditDecision:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failure_decision(
                package, "audit_deadline_exceeded", "整份审核已超过时间预算。",
            )
        if not _GLOBAL_AUDIT_SLOTS.acquire(timeout=remaining):
            return _failure_decision(
                package,
                "audit_deadline_exceeded",
                "法规审核未能在时间预算内取得全局模型调用配额。",
            )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _failure_decision(
                    package,
                    "audit_deadline_exceeded",
                    "整份审核已超过时间预算。",
                )
            client: Optional[BaseLLMClient] = None
            try:
                client = client_factory()
            except Exception as exc:
                logger.warning(
                    "法规审核客户端初始化失败: unit=%s error=%s",
                    package.regulation.regulation_unit_id,
                    exc,
                )
                return _failure_decision(
                    package,
                    "llm_client_initialization_failed",
                    f"模型客户端初始化失败：{exc}",
                )
            try:
                return audit_regulation_package(package, client, remaining)
            except Exception as exc:
                logger.exception(
                    "法规审核工作执行异常: unit=%s",
                    package.regulation.regulation_unit_id,
                )
                return _failure_decision(
                    package,
                    "audit_worker_failed",
                    f"法规审核工作执行异常：{exc}",
                )
            finally:
                try:
                    client.close()
                except Exception as exc:
                    logger.warning(
                        "法规审核客户端关闭失败: unit=%s error=%s",
                        package.regulation.regulation_unit_id,
                        exc,
                    )
        finally:
            _GLOBAL_AUDIT_SLOTS.release()

    executor = ThreadPoolExecutor(
        max_workers=concurrency,
        thread_name_prefix="regulation-audit",
    )
    future_map: Dict[Future[RegulationAuditDecision], RegulationAuditPackage] = {
        executor.submit(run, package): package for package in ordered
    }
    pending = set(future_map)
    decisions: List[RegulationAuditDecision] = []
    completed = 0
    total = len(ordered)
    while pending:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            break
        done, pending = wait(
            pending,
            timeout=remaining,
            return_when=FIRST_COMPLETED,
        )
        if not done:
            break
        for future in done:
            package = future_map[future]
            try:
                decision = future.result()
            except Exception as exc:
                logger.exception(
                    "法规审核工作线程异常: unit=%s",
                    package.regulation.regulation_unit_id,
                )
                decision = _failure_decision(
                    package,
                    "audit_worker_failed",
                    f"法规审核工作线程异常：{exc}",
                )
            decisions.append(decision)
            completed += 1
            if on_decision is not None:
                try:
                    on_decision(decision, completed, total)
                except Exception as exc:
                    logger.warning("审核进度回调失败: %s", exc)
    for future in pending:
        package = future_map[future]
        future.cancel()
        decision = _failure_decision(
            package, "audit_deadline_exceeded", "法规条款单元未在时间预算内完成。",
        )
        decisions.append(decision)
        completed += 1
        if on_decision is not None:
            try:
                on_decision(decision, completed, total)
            except Exception as exc:
                logger.warning("审核进度回调失败: %s", exc)
    executor.shutdown(wait=False, cancel_futures=True)
    order = {package.task_id: package.input_index for package in ordered}
    return tuple(sorted(decisions, key=lambda item: order[item.task_id]))
