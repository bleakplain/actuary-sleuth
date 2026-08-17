"""逐法规条款单元的结构化 LLM 审核。"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterable, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.common.compliance_audit import (
    BatchAuditAttemptTrace,
    ProductClauseEvidence,
    ProductEvidenceStrength,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    RegulationEvidence,
    RegulationObligationAssessment,
    RegulationObligationStatus,
    RoutedClause,
)
from lib.common.constants import ComplianceConstants
from lib.llm.base import BaseLLMClient
from lib.llm.call_budget import CallBudgetExceededError
from lib.llm.factory import LLMClientFactory
from lib.config import get_audit_llm_config

logger = logging.getLogger(__name__)
_PROMPT_SAFETY_MARGIN = 10_000
_MIN_EVIDENCE_CHARACTERS = 6
_MIN_AUTOMATED_DECISION_CONFIDENCE = 0.7
_MAX_CONTEXT_REQUEST_NUMBERS = 5
_MAX_REPAIR_PRODUCT_SOURCES = 24
_MAX_SELECTED_EVIDENCE_IDS = 8
_EVIDENCE_PROTOCOL_VERSION = "task-scoped-evidence-id-v1"
_PROHIBITION_PATTERN = re.compile(
    r"(?:不得|严禁|禁止)"
    r"(?![^。；\n]{0,8}(?:超过|低于|少于|高于|短于|长于|早于|晚于|过高|过低))"
)
_ABSENCE_FINDING_PATTERN = re.compile(
    r"(?:未发现|没有发现|未检出|不存在|不包含|不含|"
    r"未(?:包含|出现|使用|采用|约定|通过|混淆|提供|设置|设计|自定义))"
)
_EVIDENCE_REQUIRED_PATTERN = re.compile(
    r"(?:应当|必须|应|须|需|至少|至多|不超过|不低于|不少于|"
    r"不高于|不短于|不长于|不早于|不晚于)"
)
_GLOBAL_AUDIT_SLOTS = threading.BoundedSemaphore(
    ComplianceConstants.AUDIT_MAX_CONCURRENCY
)


class _ObligationAssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligation_id: str
    status: RegulationObligationStatus
    reasoning: str = Field(min_length=1)
    regulation_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )
    product_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )


class _DecisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    regulation_unit_id: str
    status: RegulationDecisionStatus
    reasoning: str = Field(min_length=1)
    suggestion: str = ""
    regulation_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )
    product_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )
    applicability_dispute: bool = False
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    needs_more_context: bool = False
    requested_outline_refs: Tuple[str, ...] = ()
    obligation_assessments: Tuple[_ObligationAssessmentOutput, ...] = ()


class _EvidenceRepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    regulation_unit_id: str
    regulation_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )
    product_evidence_ids: Tuple[str, ...] = Field(
        default=(), max_length=_MAX_SELECTED_EVIDENCE_IDS,
    )


@dataclass(frozen=True)
class _BatchAttemptResult:
    decisions: Dict[str, RegulationAuditDecision]
    draft_statuses: Dict[str, RegulationDecisionStatus]
    raw_items: Dict[str, Dict[str, object]]
    trace: BatchAuditAttemptTrace
    repair_feedback: Tuple[str, ...] = ()


@dataclass(frozen=True)
class _EvidenceRepairTask:
    package: RegulationAuditPackage
    draft: _DecisionOutput
    raw_item: Mapping[str, object]
    feedback: Tuple[str, ...]


def _controlled_validation_feedback(
    error: ValidationError | ValueError,
) -> str:
    """Describe invalid output without echoing model-controlled input values."""
    if isinstance(error, ValidationError):
        details = []
        for item in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:8]:
            location = ".".join(str(part) for part in item.get("loc", ()))
            code = str(item.get("type") or "validation_error")
            details.append(f"field={location or '$'} code={code}")
        return "structured_output_invalid " + "; ".join(details)
    message = str(error)
    field = (
        "regulation_evidence"
        if "法规证据" in message
        else "product_evidence"
        if "产品证据" in message
        else "status"
        if "status" in message
        else "task_identity"
        if "task_id" in message or "regulation_unit_id" in message
        else "decision"
    )
    return f"decision_validation_failed field={field} code=value_error"


def _regulation_evidence_refs(
    package: RegulationAuditPackage,
) -> Dict[str, RegulationChunkSnapshot]:
    scope = _task_evidence_scope(package)
    return {
        f"{scope}-R{index:03d}": chunk
        for index, chunk in enumerate(package.regulation.chunks, start=1)
    }


def _product_evidence_refs(
    package: RegulationAuditPackage,
) -> Dict[str, RoutedClause]:
    scope = _task_evidence_scope(package)
    strong_clause_ids = {
        candidate.clause_id
        for candidate in package.product_evidence_candidates
        if candidate.strength is ProductEvidenceStrength.STRONG
    }
    return {
        f"{scope}-P{index:03d}": routed
        for index, routed in enumerate(package.clauses, start=1)
        if (
            routed.clause.clause_id in strong_clause_ids
            and routed.submitted
            and _has_clause_body(routed)
        )
    }


def _product_context_refs(package: RegulationAuditPackage) -> Dict[str, RoutedClause]:
    return {
        f"C{index:03d}": routed
        for index, routed in enumerate(package.clauses, start=1)
        if routed.submitted and _has_clause_body(routed)
    }


def _product_evidence_catalog(
    package: RegulationAuditPackage,
) -> List[Dict[str, object]]:
    context_ref_by_clause_id = {
        routed.clause.clause_id: context_ref
        for context_ref, routed in _product_context_refs(package).items()
    }
    strong_candidate_by_clause_id = {
        candidate.clause_id: candidate
        for candidate in package.product_evidence_candidates
        if candidate.strength is ProductEvidenceStrength.STRONG
    }
    return [
        {
            "evidence_id": evidence_id,
            "context_ref": context_ref_by_clause_id[routed.clause.clause_id],
            "clause_id": routed.clause.clause_id,
            "strength": strong_candidate_by_clause_id[
                routed.clause.clause_id
            ].strength.value,
            "source_layers": list(
                strong_candidate_by_clause_id[routed.clause.clause_id].source_layers
            ),
        }
        for evidence_id, routed in _product_evidence_refs(package).items()
    ]


def _task_evidence_scope(package: RegulationAuditPackage) -> str:
    if package.input_index < 0:
        raise ValueError("input_index 不能为负数")
    return f"U{package.input_index + 1:04d}"


def _product_name_evidence_id(package: RegulationAuditPackage) -> Optional[str]:
    name_is_in_scope = (
        "contract.name" in package.regulation.topics
        or any(
            "contract.name" in spec.target_topics
            for spec in package.regulation.trigger_specs
        )
    )
    if (
        not name_is_in_scope
        or not package.product_name.strip()
    ):
        return None
    return f"{_task_evidence_scope(package)}-PNAME"


def _has_clause_body(routed: RoutedClause) -> bool:
    return not routed.clause.container_only and bool(routed.clause.text.strip())


def _outline_refs(package: RegulationAuditPackage) -> Dict[str, RoutedClause]:
    return {
        f"O{index:03d}": routed
        for index, routed in enumerate(package.clauses, start=1)
    }


def _has_complete_submitted_document(package: RegulationAuditPackage) -> bool:
    body_clauses = tuple(
        routed for routed in package.clauses if _has_clause_body(routed)
    )
    return (
        package.complete_document
        and bool(body_clauses)
        and all(routed.submitted for routed in body_clauses)
    )


_EvidenceDomain = Literal["regulation", "product"]
_EvidenceCandidate = Tuple[str, str, str]


def _evidence_candidates(
    package: RegulationAuditPackage,
    domain: _EvidenceDomain,
) -> Tuple[_EvidenceCandidate, ...]:
    if domain == "regulation":
        return tuple(
            (evidence_ref, chunk.chunk_id, chunk.content)
            for evidence_ref, chunk in _regulation_evidence_refs(package).items()
        )
    candidates = tuple(
        (evidence_ref, routed.clause.clause_id, routed.clause.text)
        for evidence_ref, routed in _product_evidence_refs(package).items()
    )
    product_name_evidence_id = _product_name_evidence_id(package)
    if product_name_evidence_id is not None:
        candidates += ((
            product_name_evidence_id,
            "product-name",
            package.product_name,
        ),)
    return candidates


def _normalize_legacy_evidence_items(
    package: RegulationAuditPackage,
    domain: _EvidenceDomain,
    raw_items: object,
) -> List[str]:
    if not isinstance(raw_items, (list, tuple)):
        raise ValueError("旧版证据字段必须是数组")
    candidates = {
        evidence_id: content
        for evidence_id, _, content in _evidence_candidates(package, domain)
    }
    normalized_ids: List[str] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise ValueError("旧版证据项必须是对象")
        unexpected = set(item).difference({"evidence_id", "evidence_ref", "quote"})
        if unexpected:
            raise ValueError("旧版证据项包含未知字段")
        evidence_id = item.get("evidence_id")
        evidence_ref = item.get("evidence_ref")
        if evidence_id is not None and evidence_ref is not None:
            if evidence_id != evidence_ref:
                raise ValueError("证据同时返回冲突的 evidence_id 与 evidence_ref")
        selected_id = evidence_id if evidence_id is not None else evidence_ref
        if not isinstance(selected_id, str) or selected_id not in candidates:
            raise ValueError("旧版证据项未使用当前任务同域的精确证据ID")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("旧版证据项缺少逐字摘录")
        if quote not in candidates[selected_id]:
            raise ValueError("旧版证据摘录与所选精确证据ID不同源")
        normalized_ids.append(selected_id)
    return normalized_ids


def _normalize_decision_payload(
    package: RegulationAuditPackage,
    payload: object,
) -> Dict[str, object]:
    """兼容同源旧字段，但不根据摘录反查或纠正证据 ID。"""
    if not isinstance(payload, Mapping):
        raise ValueError("审核结果必须是JSON对象")
    normalized = dict(payload)
    evidence_fields: Tuple[Tuple[str, str, _EvidenceDomain], ...] = (
        ("regulation_evidence_ids", "regulation_evidence", "regulation"),
        ("product_evidence_ids", "product_evidence", "product"),
    )
    for id_field, legacy_field, domain in evidence_fields:
        if id_field in normalized and legacy_field in normalized:
            raise ValueError(f"不得同时返回{id_field}与{legacy_field}")
        if legacy_field not in normalized:
            continue
        normalized[id_field] = _normalize_legacy_evidence_items(
            package,
            domain,
            normalized.pop(legacy_field),
        )
    return normalized


def _product_fact_payload(
    package: RegulationAuditPackage,
) -> List[Dict[str, object]]:
    return [
        {
            "name": fact.name.value,
            "truth": fact.truth.value,
            "value": fact.value,
            "unit": fact.unit,
            "method": fact.method,
            "confidence": fact.confidence,
            "evidence": [
                {
                    "clause_id": evidence.clause_id,
                    "quote": evidence.quote,
                }
                for evidence in fact.evidence
            ],
            "reason": fact.reason,
            "safe_for_exclusion": fact.safe_for_exclusion,
        }
        for fact in package.product_facts
    ]


def _batch_payload(
    packages: Tuple[RegulationAuditPackage, ...],
) -> Dict[str, object]:
    first = _package_payload(packages[0])
    product = first.get("product")
    if not isinstance(product, Mapping):
        raise ValueError("审核包缺少结构化产品上下文")
    shared_product: Dict[str, object] = dict(product)
    raw_clauses = shared_product.get("clauses")
    if not isinstance(raw_clauses, list):
        raise ValueError("审核包产品条款必须是结构化列表")
    structured_clauses = tuple(
        clause for clause in raw_clauses if isinstance(clause, Mapping)
    )
    if len(structured_clauses) != len(raw_clauses):
        raise ValueError("审核包产品条款必须是结构化列表")
    shared_product.pop("product_facts", None)
    shared_product.pop("name_evidence_id", None)
    shared_product.pop("product_evidence_catalog", None)
    shared_product["clauses"] = [
        {
            key: value
            for key, value in clause.items()
            if key not in {"relation", "routing_reasons"}
        }
        for clause in structured_clauses
    ]
    return {
        "evidence_protocol_version": _EVIDENCE_PROTOCOL_VERSION,
        "batch_id": f"{packages[0].regulation.source_file}:{packages[0].input_index}",
        "required_unit_ids": [
            package.regulation.regulation_unit_id for package in packages
        ],
        "product": shared_product,
        "regulation_tasks": [
            {
                "task_id": package.task_id,
                "regulation_unit": _package_payload(package)["regulation_unit"],
                "product_facts": _product_fact_payload(package),
                "product_name_evidence_id": _product_name_evidence_id(package),
                "product_evidence_catalog": _product_evidence_catalog(package),
                "priority_product_clauses": [
                    {
                        "evidence_id": evidence_id,
                        "context_ref": next(
                            context_ref
                            for context_ref, context_routed in _product_context_refs(
                                package,
                            ).items()
                            if context_routed.clause.clause_id == routed.clause.clause_id
                        ),
                        "clause_id": routed.clause.clause_id,
                        "number": routed.clause.number,
                        "title": routed.clause.title,
                        "text": routed.clause.text,
                        "relation": routed.relation.value,
                    }
                    for evidence_id, routed in _product_evidence_refs(package).items()
                    if routed.submitted and routed.relation.value in {"direct", "related"}
                ],
            }
            for package in packages
        ],
    }


def build_batch_audit_messages(
    packages: Tuple[RegulationAuditPackage, ...],
    repair_feedback: Tuple[str, ...] = (),
) -> List[Dict[str, str]]:
    """同一法规文件共享一次产品全文，但每个法规单元必须独立回答。"""
    if not packages:
        raise ValueError("批量审核至少需要一个法规单元")
    source_files = {package.regulation.source_file for package in packages}
    if len(source_files) != 1:
        raise ValueError("一个审核批次只能包含同一法规文件的法规单元")
    _validate_batch_product_context(packages)
    payload = json.dumps(_batch_payload(packages), ensure_ascii=False)
    system = (
        "你是保险产品条款合规审核员。只能使用审核包提供的法规和产品原文。"
        "必须逐一回答 required_unit_ids 中的每个法规单元，不得省略、合并或新增ID。"
        "产品事实和触发结果只是可审计trace，不得用它们改写法规适用性。"
        "每个regulation_task的product_facts仅属于该法规单元，不得跨任务引用。"
    )
    instruction = """输出一个 JSON 对象，不得输出 Markdown：
{"results": [{
  "task_id": "<对应task_id>",
  "regulation_unit_id": "<对应regulation_unit_id>",
  "status": "compliant|non_compliant|insufficient_information|manual_review",
  "reasoning": "<理由>", "suggestion": "<建议>",
  "regulation_evidence_ids": ["<当前任务的Uxxxx-R001等ID>"],
  "product_evidence_ids": ["<当前任务的Uxxxx-P001或Uxxxx-PNAME等ID>"],
  "obligation_assessments": [{
    "obligation_id": "<原obligation_id>",
    "status": "satisfied|violated|insufficient_information",
    "reasoning": "<该项义务的独立判断理由>",
    "regulation_evidence_ids": ["<本任务法规证据ID>"],
    "product_evidence_ids": ["<本任务产品证据ID>"]
  }],
  "applicability_dispute": false, "confidence": 0.95
}]}

每个 required_unit_id 必须且只能出现一次。证据、状态和引用规则与单条审核一致；
不能证明符合时必须输出 insufficient_information，不能直接省略。
每个 regulation_task 的 product_facts 只可用于本任务，不得引用同批次其他任务的
product_facts 形成判断或证据。
confidence 必须根据本条证据充分程度独立评估，不得机械复制示例值；能够由法规和
产品原文直接证明的结论应给出与证据强度一致的置信度。
证据ID必须逐字复制当前regulation_task目录中完整、带任务前缀的ID；法规只能写入
regulation_evidence_ids，产品只能写入product_evidence_ids。不得输出quote，不得使用
其他任务的ID、内部chunk_id/clause_id或占位名称。若状态为 insufficient_information，
可以返回空证据数组，但仍必须给出该法规单元的明确回答。
共享product.clauses中的context_ref只用于阅读全文，不是可引用证据ID；产品证据只能从
当前regulation_task.product_evidence_catalog或其product_name_evidence_id中选择。
每个法规单元应先检查其 priority_product_clauses，再检查完整产品条款；重点条款
只是证据定位提示，不限制使用其他真实条款。
若regulation_unit.obligations非空，必须按目录顺序逐项返回obligation_assessments，
不得漏项、新增或合并。每项satisfied/violated必须同时引用本任务的法规和产品证据；
证据不足时返回insufficient_information。此模式下顶层两类evidence_ids必须留空，程序
将从逐项结果汇总证据；全部satisfied时总体status才可为compliant，任一violated时总体
status必须为non_compliant，其他情况总体status必须为insufficient_information。

"""
    if repair_feedback:
        instruction += (
            "\n\n上一轮回答未通过程序校验。只修复本批次中的以下问题，仍须完整回答"
            " required_unit_ids：\n- " + "\n- ".join(repair_feedback)
        )
    instruction += "\n\n审核包：\n" + payload
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def _evidence_repair_product_sources(
    package: RegulationAuditPackage,
    _raw_item: Mapping[str, object],
) -> List[Dict[str, object]]:
    """Expose every task-local strong source without resending weak context."""
    product_refs = _product_evidence_refs(package)
    selected = tuple(product_refs)[:_MAX_REPAIR_PRODUCT_SOURCES]
    return [
        {
            "evidence_id": reference,
            "clause_id": product_refs[reference].clause.clause_id,
            "number": product_refs[reference].clause.number,
            "title": product_refs[reference].clause.title,
            "text": product_refs[reference].clause.text,
        }
        for reference in selected
    ]


def _repair_draft_payload(raw_item: Mapping[str, object]) -> Dict[str, object]:
    """Keep the locked decision core without re-exposing rejected citations."""
    result: Dict[str, object] = {}
    for field_name, limit in (("reasoning", 2000), ("suggestion", 1000)):
        value = raw_item.get(field_name)
        if isinstance(value, str):
            result[field_name] = value[:limit]
    for field_name in ("status", "applicability_dispute", "confidence"):
        if field_name in raw_item:
            result[field_name] = raw_item[field_name]
    return result


def _build_evidence_repair_messages(
    tasks: Tuple[_EvidenceRepairTask, ...],
) -> List[Dict[str, str]]:
    """Build a compact task-isolated repair batch without resending full text."""
    if not tasks:
        raise ValueError("紧凑证据修复至少需要一个任务")
    payload = {
        "evidence_protocol_version": _EVIDENCE_PROTOCOL_VERSION,
        "required_unit_ids": [
            task.package.regulation.regulation_unit_id for task in tasks
        ],
        "tasks": [
            {
                "task_id": task.package.task_id,
                "regulation_unit_id": task.package.regulation.regulation_unit_id,
                "required_status": task.draft.status.value,
                "original_result": _repair_draft_payload(task.raw_item),
                "validation_errors": list(task.feedback),
                "regulation_evidence_catalog": [
                    {
                        "evidence_id": reference,
                        "chunk_id": chunk.chunk_id,
                        "content": chunk.content,
                    }
                    for reference, chunk in _regulation_evidence_refs(
                        task.package,
                    ).items()
                ],
                "product_name_evidence": (
                    {
                        "evidence_id": _product_name_evidence_id(task.package),
                        "text": task.package.product_name,
                    }
                    if _product_name_evidence_id(task.package) is not None
                    else None
                ),
                "product_evidence_catalog": _evidence_repair_product_sources(
                    task.package, task.raw_item,
                ),
            }
            for task in tasks
        ],
    }
    instruction = """上一轮已完成合规判断，但证据引用未通过程序校验。本轮只修复证据，
不得重新审核，也不得使用目录外内容。只复制catalog中的完整evidence_id；法规证据只能来自regulation_evidence_catalog，产品证据只能来自
product_evidence_catalog或允许时的PNAME。若required_status为non_compliant，必须同时给出
法规和产品证据；若为compliant，通常也必须同时给出两类证据。只有原判断确属全文禁止性
零命中、且original_result.reasoning已经明确说明“已检查完整产品条款，未发现……”时，
才允许product_evidence_ids为空。

required_unit_ids中的每个任务必须且只能返回一次；不同任务的catalog相互隔离，严禁跨任务引用。
输出一个JSON对象，不得输出Markdown：
{"results":[{"task_id":"<原task_id>","regulation_unit_id":"<原unit_id>",
"regulation_evidence_ids":["<本任务Uxxxx-R001等ID>"],
"product_evidence_ids":["<本任务Uxxxx-P001或Uxxxx-PNAME等ID>"]
}]}

证据修复包：
""" + json.dumps(payload, ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "你只负责修复保险条款审核结果中的证据ID。"
                "不得输出或改变既有结论、理由、适用性争议或置信度，不得补充外部知识。"
            ),
        },
        {"role": "user", "content": instruction},
    ]


def _package_payload(package: RegulationAuditPackage) -> Dict[str, object]:
    regulation_refs = _regulation_evidence_refs(package)
    product_context_refs = _product_context_refs(package)
    outline_refs = _outline_refs(package)
    return {
        "evidence_protocol_version": _EVIDENCE_PROTOCOL_VERSION,
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
            "obligations": [
                {
                    "obligation_id": item.obligation_id,
                    "requirement": item.requirement,
                    "automated_decision_allowed": item.automated_decision_allowed,
                    "insufficient_reason": item.insufficient_reason,
                }
                for item in package.obligations
            ],
            "chunks": [
                {
                    "evidence_id": evidence_ref,
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                }
                for evidence_ref, chunk in regulation_refs.items()
            ],
            "trigger_evaluation": (
                {
                    "status": package.trigger_evaluation.status.value,
                    "fact_names": [
                        name.value
                        for name in package.trigger_evaluation.fact_names
                    ],
                    "reasons": list(package.trigger_evaluation.reasons),
                    "evidence_clause_ids": list(
                        package.trigger_evaluation.evidence_clause_ids
                    ),
                }
                if package.trigger_evaluation is not None
                else None
            ),
        },
        "product": {
            "name": package.product_name,
            "name_evidence_id": _product_name_evidence_id(package),
            "product_evidence_catalog": _product_evidence_catalog(package),
            "complete_document": _has_complete_submitted_document(package),
            "tags": package.product_tags.to_dict(),
            "clauses": [
                {
                    "context_ref": context_ref,
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
                for context_ref, routed in product_context_refs.items()
            ],
            "clause_outline": [
                {
                    "outline_ref": outline_ref,
                    "number": routed.clause.number,
                    "title": routed.clause.title,
                    "hierarchy_level": routed.clause.hierarchy_level,
                    "parent_number": routed.clause.parent_number,
                    "ancestor_numbers": list(routed.clause.ancestor_numbers),
                    "hierarchy_path": routed.clause.hierarchy_path,
                    "body_submitted": routed.submitted,
                    "body_available": _has_clause_body(routed),
                    "container_only": routed.clause.container_only,
                }
                for outline_ref, routed in outline_refs.items()
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
            "product_facts": _product_fact_payload(package),
        },
    }


def build_audit_messages(
    package: RegulationAuditPackage,
    *,
    allow_context_request: bool = True,
) -> List[Dict[str, str]]:
    payload = json.dumps(_package_payload(package), ensure_ascii=False)
    system = (
        "你是保险产品条款合规审核员。只能使用用户消息中的法规原文、产品标签、"
        "产品条款和确定性事实。一次只判断一个 regulation_unit。"
        "不得使用外部法规，不得把适用性改为 not_applicable。"
        "风险触发标签只表示该法规必须进入审核，不表示产品已经满足检查目标。"
        "产品事实和触发结果只是可审计trace，不得用它们改写法规适用性。"
    )
    instruction = """请输出一个 JSON 对象，且不得输出 Markdown：
{
  "task_id": "<原 task_id>",
  "regulation_unit_id": "<原 regulation_unit_id>",
  "status": "compliant|non_compliant|insufficient_information|manual_review",
  "reasoning": "<依据法规和产品原文的理由>",
  "suggestion": "<必要时的修改建议>",
  "regulation_evidence_ids": ["<当前任务的Uxxxx-R001等ID>"],
  "product_evidence_ids": ["<当前任务的Uxxxx-P001或Uxxxx-PNAME等ID>"],
  "obligation_assessments": [{
    "obligation_id": "<原obligation_id>",
    "status": "satisfied|violated|insufficient_information",
    "reasoning": "<该项义务的独立判断理由>",
    "regulation_evidence_ids": ["<本任务法规证据ID>"],
    "product_evidence_ids": ["<本任务产品证据ID>"]
  }],
  "applicability_dispute": false,
  "confidence": 0.95,
  "needs_more_context": false,
  "requested_outline_refs": []
}

约束：
1. non_compliant 必须同时引用至少一条法规证据和一条产品条款证据。
2. compliant 必须同时有法规证据和产品条款证据；只有第8项允许产品证据为空。
3. 法规适用性存在争议时输出 manual_review，并将 applicability_dispute 设为 true。
4. 只返回证据ID，不得返回quote；程序会按ID回填完整、未截断的法规chunk或产品条款正文。
5. 证据ID只能逐字复制当前任务目录提供的完整任务域ID。法规ID只能写入regulation_evidence_ids，
   产品ID只能写入product_evidence_ids；不得使用其他任务ID、内部chunk_id/clause_id或别名。
6. 每个证据数组最多返回8个ID，且不得重复。ID合法只证明来源可追溯，不等于证据在语义上充分；
   仍须选择真正支撑reasoning与status的原文atom。
7. 产品名称确实能够证明产品身份或名称明示属性时，才会提供Uxxxx-PNAME；不得用产品名称证明条款正文必须包含的表述。
8. 若法规明确禁止特定表述、责任或设计，且product.complete_document为true，逐块检查完整
   产品条款后未发现禁止事项，可以将product_evidence_ids留空，但reasoning必须明确写明“已检查
   完整产品条款，未发现……”；数值上下限和“应当/必须”义务不得使用此例外。
9. 若regulation_unit.obligations非空，必须按目录顺序逐项返回obligation_assessments，
   不得漏项、新增或合并。每项satisfied/violated必须同时引用该任务的法规和产品证据；
   证据不足时返回insufficient_information。此模式下顶层两类evidence_ids必须留空，程序
   将从逐项结果汇总证据；全部satisfied时总体status才可为compliant，任一violated时总体
   status必须为non_compliant，其他情况总体status必须为insufficient_information。

product.clause_outline 是完整条款目录，只用于定位可能需要补充的正文，不是结论证据。
product.clauses中的context_ref只用于阅读全文，不是可引用证据ID；产品证据只能从
product.product_evidence_catalog或允许时的product.name_evidence_id中选择。
"""
    if allow_context_request:
        instruction += """
10. 只有当已提交正文不足以判断、且目录中存在明确值得补充的条款时，才可设置
   needs_more_context=true。此时status必须为insufficient_information，不得同时形成
   compliant/non_compliant结论，regulation_evidence_ids和product_evidence_ids必须为空。
11. requested_outline_refs只能填写clause_outline中真实、正文可用且尚未提交的O001等
    outline_ref，必须去重，最多5个；不得填写number或编造ref。
"""
    else:
        instruction += """
10. 本轮已是唯一一次上下文扩展后的最终判断。不得再请求补充条款；
   needs_more_context必须为false，requested_outline_refs必须为空。若仍不足以
   判断，直接输出status=insufficient_information。
"""
    instruction += "\n审核包：\n" + payload
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


def _budget_exhausted_decision(
    package: RegulationAuditPackage,
    error: Optional[CallBudgetExceededError] = None,
) -> RegulationAuditDecision:
    reason = f"（{error.reason.value}）" if error is not None else ""
    accounting = (
        f"请求预留{error.requested_tokens} tokens，"
        f"当时剩余{error.snapshot.remaining_tokens} tokens；"
        if error is not None else ""
    )
    return _failure_decision(
        package,
        "audit_budget_exhausted",
        f"模型调用预算已耗尽{reason}，{accounting}未继续发送审核请求。",
    )


def _insufficient_context_decision(
    package: RegulationAuditPackage,
    reasoning: str,
) -> RegulationAuditDecision:
    return RegulationAuditDecision(
        task_id=package.task_id,
        regulation_unit_id=package.regulation.regulation_unit_id,
        status=RegulationDecisionStatus.INSUFFICIENT_INFORMATION,
        reasoning=reasoning,
        suggestion="请人工核对完整产品条款或补充必要材料。",
        regulation_evidence=(),
        product_evidence=(),
        incomplete=False,
        error_code="context_expansion_exhausted",
    )


def _validate_output_identity(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
) -> None:
    if output.task_id != package.task_id:
        raise ValueError("task_id 与审核包不一致")
    if output.regulation_unit_id != package.regulation.regulation_unit_id:
        raise ValueError("regulation_unit_id 与审核包不一致")


def _repairable_draft_output(
    package: RegulationAuditPackage,
    raw_item: Mapping[str, object],
) -> _DecisionOutput:
    """Validate every non-evidence field before allowing evidence-only repair."""
    if package.obligations:
        raise ValueError("逐项义务结果不得进入仅证据修复")
    core = dict(raw_item)
    core.pop("regulation_evidence", None)
    core.pop("product_evidence", None)
    core["regulation_evidence_ids"] = []
    core["product_evidence_ids"] = []
    output = _DecisionOutput.model_validate(core)
    _validate_output_identity(package, output)
    if output.needs_more_context or output.requested_outline_refs:
        raise ValueError("上下文请求不能进入证据修复")
    return output


def _validate_context_request(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
) -> Tuple[str, ...]:
    _validate_output_identity(package, output)
    requested = tuple(ref.strip() for ref in output.requested_outline_refs)
    if not output.needs_more_context:
        if requested:
            raise ValueError(
                "needs_more_context=false时不得请求补充条款"
            )
        return ()
    if output.status is not RegulationDecisionStatus.INSUFFICIENT_INFORMATION:
        raise ValueError(
            "请求补充上下文时status必须为insufficient_information"
        )
    if output.applicability_dispute:
        raise ValueError("请求补充上下文时不得同时提出适用性争议")
    if output.regulation_evidence_ids or output.product_evidence_ids:
        raise ValueError("请求补充上下文时不得同时形成证据结论")
    if output.obligation_assessments:
        raise ValueError("请求补充上下文时不得同时形成逐项义务结论")
    if not requested or any(not number for number in requested):
        raise ValueError("请求补充上下文时必须提供非空条款编号")
    if len(requested) > _MAX_CONTEXT_REQUEST_NUMBERS:
        raise ValueError(
            f"一次最多请求{_MAX_CONTEXT_REQUEST_NUMBERS}个条款编号"
        )
    if len(set(requested)) != len(requested):
        raise ValueError("请求的条款编号必须去重")
    available = {
        outline_ref
        for outline_ref, routed in _outline_refs(package).items()
        if not routed.submitted and _has_clause_body(routed)
    }
    invalid = tuple(number for number in requested if number not in available)
    if invalid:
        raise ValueError(
            "请求了不存在、无正文或已提交的条款目录ref: " + ", ".join(invalid)
        )
    return requested


def _expand_context_by_outline_refs(
    package: RegulationAuditPackage,
    requested_refs: Tuple[str, ...],
) -> RegulationAuditPackage:
    requested_clause_ids = {
        routed.clause.clause_id
        for outline_ref, routed in _outline_refs(package).items()
        if outline_ref in set(requested_refs)
    }
    return replace(
        package,
        clauses=tuple(
            replace(
                routed,
                submitted=True,
                reasons=(*routed.reasons, "模型按目录编号请求补充上下文"),
            )
            if (
                not routed.submitted
                and routed.clause.clause_id in requested_clause_ids
            )
            else routed
            for routed in package.clauses
        ),
    )


def _validate_obligation_assessments(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
    regulation_refs: Mapping[str, RegulationChunkSnapshot],
    product_refs: Mapping[str, RoutedClause],
) -> Tuple[_DecisionOutput, Tuple[RegulationObligationAssessment, ...]]:
    if not package.obligations:
        if output.obligation_assessments:
            raise ValueError("当前法规未配置逐项义务，不得返回义务评估")
        return output, ()
    expected_ids = tuple(item.obligation_id for item in package.obligations)
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError("法规义务ID配置重复")
    returned_ids = tuple(
        item.obligation_id for item in output.obligation_assessments
    )
    if returned_ids != expected_ids:
        raise ValueError("逐项义务必须按目录顺序完整返回且不得新增或合并")
    product_name_evidence_id = _product_name_evidence_id(package)
    flattened_regulation_ids: List[str] = []
    flattened_product_ids: List[str] = []
    assessments: List[RegulationObligationAssessment] = []
    obligation_by_id = {
        item.obligation_id: item for item in package.obligations
    }
    for item in output.obligation_assessments:
        obligation = obligation_by_id[item.obligation_id]
        if not obligation.automated_decision_allowed:
            assessments.append(RegulationObligationAssessment(
                obligation_id=item.obligation_id,
                requirement=obligation.requirement,
                status=RegulationObligationStatus.INSUFFICIENT_INFORMATION,
                reasoning=obligation.insufficient_reason,
            ))
            continue
        if len(set(item.regulation_evidence_ids)) != len(
            item.regulation_evidence_ids
        ):
            raise ValueError(f"{item.obligation_id}: 法规证据ID不得重复")
        if len(set(item.product_evidence_ids)) != len(item.product_evidence_ids):
            raise ValueError(f"{item.obligation_id}: 产品证据ID不得重复")
        invalid_regulation_ids = tuple(
            evidence_id for evidence_id in item.regulation_evidence_ids
            if evidence_id not in regulation_refs
        )
        invalid_product_ids = tuple(
            evidence_id for evidence_id in item.product_evidence_ids
            if evidence_id not in product_refs
            and evidence_id != product_name_evidence_id
        )
        if invalid_regulation_ids or invalid_product_ids:
            raise ValueError(
                f"{item.obligation_id}: 证据ID不属于当前任务: "
                + ", ".join((*invalid_regulation_ids, *invalid_product_ids))
            )
        if item.status in {
            RegulationObligationStatus.SATISFIED,
            RegulationObligationStatus.VIOLATED,
        } and (not item.regulation_evidence_ids or not item.product_evidence_ids):
            raise ValueError(
                f"{item.obligation_id}: 明确逐项结论必须同时提供法规与产品证据"
            )
        flattened_regulation_ids.extend(item.regulation_evidence_ids)
        flattened_product_ids.extend(item.product_evidence_ids)
        assessments.append(RegulationObligationAssessment(
            obligation_id=item.obligation_id,
            requirement=obligation.requirement,
            status=item.status,
            reasoning=item.reasoning,
            regulation_chunk_ids=tuple(
                regulation_refs[evidence_id].chunk_id
                for evidence_id in item.regulation_evidence_ids
            ),
            product_clause_ids=tuple(
                "product-name"
                if evidence_id == product_name_evidence_id
                else product_refs[evidence_id].clause.clause_id
                for evidence_id in item.product_evidence_ids
            ),
        ))
    statuses = tuple(item.status for item in assessments)
    derived_status = (
        RegulationDecisionStatus.NON_COMPLIANT
        if RegulationObligationStatus.VIOLATED in statuses
        else RegulationDecisionStatus.INSUFFICIENT_INFORMATION
        if RegulationObligationStatus.INSUFFICIENT_INFORMATION in statuses
        else RegulationDecisionStatus.COMPLIANT
    )
    expected_status = (
        RegulationDecisionStatus.MANUAL_REVIEW
        if output.applicability_dispute else derived_status
    )
    has_deterministic_override = any(
        not item.automated_decision_allowed for item in package.obligations
    )
    deterministic_insufficient_override = (
        has_deterministic_override
        and expected_status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    )
    if (
        output.status is not expected_status
        and not deterministic_insufficient_override
    ):
        raise ValueError(
            "总体status与逐项义务结果不一致: "
            f"expected={expected_status.value} actual={output.status.value}"
        )
    blocked_reasons = tuple(
        item.insufficient_reason
        for item in package.obligations
        if not item.automated_decision_allowed
    )
    reasoning = output.reasoning
    if deterministic_insufficient_override:
        reasoning = (
            "存在未通过自动证据充分性验收的义务："
            + "；".join(blocked_reasons)
        )
    return output.model_copy(update={
        "status": expected_status,
        "reasoning": reasoning,
        "confidence": (
            None if deterministic_insufficient_override else output.confidence
        ),
        "regulation_evidence_ids": tuple(dict.fromkeys(
            flattened_regulation_ids
        )),
        "product_evidence_ids": tuple(dict.fromkeys(flattened_product_ids)),
    }), tuple(assessments)


def _validate_evidence(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
) -> RegulationAuditDecision:
    if _validate_context_request(package, output):
        raise ValueError("上下文请求必须由单条审核编排流程处理")
    if not output.reasoning.strip():
        raise ValueError("reasoning 不能为空")
    regulation_refs = _regulation_evidence_refs(package)
    regulation_content = {
        evidence_ref: chunk.content
        for evidence_ref, chunk in regulation_refs.items()
    }
    regulation_ids = {
        evidence_ref: chunk.chunk_id
        for evidence_ref, chunk in regulation_refs.items()
    }
    product_refs = _product_evidence_refs(package)
    output, obligation_assessments = _validate_obligation_assessments(
        package,
        output,
        regulation_refs,
        product_refs,
    )
    product_content = {
        evidence_ref: routed.clause.text
        for evidence_ref, routed in product_refs.items()
    }
    product_ids = {
        evidence_ref: routed.clause.clause_id
        for evidence_ref, routed in product_refs.items()
    }

    def require_substantive_quote(quote: str, evidence_type: str) -> str:
        normalized = re.sub(r"[\W_]+", "", quote, flags=re.UNICODE)
        if len(normalized) < _MIN_EVIDENCE_CHARACTERS:
            raise ValueError(
                f"{evidence_type}摘录过短，不能证明完整事实或要求"
            )
        return quote

    if len(set(output.regulation_evidence_ids)) != len(
        output.regulation_evidence_ids
    ):
        raise ValueError("法规证据ID不得重复")
    if len(set(output.product_evidence_ids)) != len(output.product_evidence_ids):
        raise ValueError("产品证据ID不得重复")
    regulation_evidence: List[RegulationEvidence] = []
    for evidence_id in output.regulation_evidence_ids:
        content = regulation_content.get(evidence_id)
        if content is None:
            if evidence_id in product_content or evidence_id == (
                _product_name_evidence_id(package)
            ):
                raise ValueError("法规证据不得引用产品证据ID")
            raise ValueError(f"无效法规证据ID: {evidence_id}")
        regulation_evidence.append(RegulationEvidence(
            chunk_id=regulation_ids[evidence_id],
            quote=require_substantive_quote(content, "法规证据"),
        ))
    product_evidence: List[ProductClauseEvidence] = []
    product_name_evidence_id = _product_name_evidence_id(package)
    for evidence_id in output.product_evidence_ids:
        source_kind = "clause_body"
        content = product_content.get(evidence_id)
        if evidence_id == product_name_evidence_id:
            source_kind = "product_name"
            content = package.product_name
        if content is None:
            if evidence_id in regulation_content:
                raise ValueError("产品证据不得引用法规证据ID")
            if evidence_id.endswith("-PNAME"):
                raise ValueError("当前法规主题不允许使用产品名称作为结论证据")
            raise ValueError(f"无效产品证据ID: {evidence_id}")
        product_evidence.append(ProductClauseEvidence(
            clause_id=(
                "product-name"
                if source_kind == "product_name"
                else product_ids[evidence_id]
            ),
            quote=require_substantive_quote(content, "产品证据"),
            source_kind=source_kind,
        ))

    status = output.status
    incomplete = False
    error_code = ""
    reasoning = output.reasoning
    _validate_output_identity(package, output)
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
    regulation_text = "\n".join(
        chunk.content for chunk in package.regulation.chunks
    )
    absence_compliance = (
        status is RegulationDecisionStatus.COMPLIANT
        and _has_complete_submitted_document(package)
        and bool(regulation_evidence)
        and not product_evidence
        and _PROHIBITION_PATTERN.search(regulation_text) is not None
        and _EVIDENCE_REQUIRED_PATTERN.search(regulation_text) is None
        and _ABSENCE_FINDING_PATTERN.search(reasoning) is not None
    )
    if status is RegulationDecisionStatus.COMPLIANT and (
        not regulation_evidence or (not product_evidence and not absence_compliance)
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
        obligation_assessments=obligation_assessments,
    )


def _audit_atomic_package(
    package: RegulationAuditPackage,
    llm: BaseLLMClient,
    timeout_seconds: float,
    *,
    allow_context_expansion: bool = True,
    request_timeout_cap_seconds: float = (
        ComplianceConstants.AUDIT_REQUEST_TIMEOUT_CAP_SECONDS
    ),
) -> RegulationAuditDecision:
    deadline = time.monotonic() + max(0.001, timeout_seconds)

    def request_output(
        current_package: RegulationAuditPackage,
        *,
        allow_context_request: bool,
    ) -> _DecisionOutput:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("法规条款单元审核已超过时间预算")
        request_timeout = max(1.0, min(request_timeout_cap_seconds, remaining))
        raw = llm.chat(
            build_audit_messages(
                current_package,
                allow_context_request=allow_context_request,
            ),
            temperature=0.0,
            max_tokens=4096,
            response_format={"type": "json_object"},
            timeout=request_timeout,
            _retry_deadline=time.monotonic() + max(0.001, remaining),
        )
        parsed = json.loads(_strip_code_fence(raw))
        return _DecisionOutput.model_validate(
            _normalize_decision_payload(current_package, parsed)
        )

    try:
        output = request_output(
            package,
            allow_context_request=allow_context_expansion,
        )
        requested = _validate_context_request(package, output)
        if not requested:
            return _validate_evidence(package, output)
        if not allow_context_expansion:
            return _insufficient_context_decision(
                package,
                "本次受控测试未启用上下文扩展，模型请求的补充条款未再次发送。",
            )
        expanded = _expand_context_by_outline_refs(package, requested)
        second_output = request_output(expanded, allow_context_request=False)
        if second_output.needs_more_context:
            # 第二轮只校验请求是否属于原始可用目录；第一轮已
            # 展开的 ref 在 expanded 中会变成 submitted，不应因重复请求
            # 被误报为结构化输出非法。
            _validate_context_request(package, second_output)
            return _insufficient_context_decision(
                package,
                "已按目录编号执行唯一一次上下文扩展，模型仍请求补充信息。",
            )
        decision = _validate_evidence(expanded, second_output)
        if decision.error_code in {
            "missing_compliance_evidence",
            "missing_non_compliance_evidence",
        }:
            return _insufficient_context_decision(
                package,
                f"已按目录编号执行唯一一次上下文扩展，仍缺少形成结论所需的证据；{decision.reasoning}",
            )
        return replace(decision, task_id=package.task_id)
    except CallBudgetExceededError as exc:
        logger.warning(
            "法规条款单元审核预算已耗尽: unit=%s reason=%s",
            package.regulation.regulation_unit_id,
            exc.reason.value,
        )
        return _budget_exhausted_decision(package, exc)
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


def _request_batch_decisions(
    packages: Tuple[RegulationAuditPackage, ...],
    llm: BaseLLMClient,
    timeout_seconds: float,
    *,
    attempt: int,
    repair_feedback: Tuple[str, ...] = (),
    required_statuses: Optional[Dict[str, RegulationDecisionStatus]] = None,
    request_timeout_cap_seconds: float = (
        ComplianceConstants.AUDIT_REQUEST_TIMEOUT_CAP_SECONDS
    ),
) -> _BatchAttemptResult:
    request_timeout = max(
        1.0,
        min(
            request_timeout_cap_seconds,
            timeout_seconds,
        ),
    )
    raw = llm.chat(
        build_batch_audit_messages(packages, repair_feedback),
        temperature=0.0,
        max_tokens=min(16_384, max(4096, len(packages) * 2048)),
        response_format={"type": "json_object"},
        timeout=request_timeout,
        _retry_deadline=time.monotonic() + max(0.001, timeout_seconds),
    )
    requested_ids = tuple(
        package.regulation.regulation_unit_id for package in packages
    )
    errors: List[str] = []
    controlled_feedback: List[str] = []
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        return _BatchAttemptResult({}, {}, {}, BatchAuditAttemptTrace(
            attempt, requested_ids, (), (f"JSON解析失败: {exc}",), raw,
        ))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        return _BatchAttemptResult({}, {}, {}, BatchAuditAttemptTrace(
            attempt, requested_ids, (), ("顶层必须是包含results数组的对象",), raw,
        ))
    by_unit = {
        package.regulation.regulation_unit_id: package for package in packages
    }
    raw_by_unit: Dict[str, List[Mapping[str, object]]] = {}
    for item in parsed["results"]:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("regulation_unit_id")
        if isinstance(unit_id, str) and unit_id in by_unit:
            raw_by_unit.setdefault(unit_id, []).append(item)
        elif isinstance(unit_id, str):
            errors.append(f"返回未知regulation_unit_id: {unit_id}")
            controlled_feedback.append("batch: unexpected_regulation_unit_id")
    decisions: Dict[str, RegulationAuditDecision] = {}
    draft_statuses: Dict[str, RegulationDecisionStatus] = {}
    raw_items: Dict[str, Dict[str, object]] = {}
    for unit_id, items in raw_by_unit.items():
        if len(items) != 1:
            errors.append(f"{unit_id}: 重复返回{len(items)}次")
            controlled_feedback.append(
                f"{unit_id}: result_count_invalid code=duplicate_result"
            )
            continue
        raw_item = dict(items[0])
        raw_items[unit_id] = raw_item
        try:
            draft_statuses[unit_id] = _repairable_draft_output(
                by_unit[unit_id], raw_item,
            ).status
        except (ValidationError, ValueError):
            pass
        try:
            output = _DecisionOutput.model_validate(
                _normalize_decision_payload(by_unit[unit_id], raw_item)
            )
            draft_statuses[unit_id] = output.status
            required_status = (required_statuses or {}).get(unit_id)
            if required_status is not None and output.status is not required_status:
                raise ValueError(
                    f"证据修复不得把status从{required_status.value}改为{output.status.value}"
                )
            decisions[unit_id] = _validate_evidence(by_unit[unit_id], output)
        except (ValidationError, ValueError) as exc:
            errors.append(f"{unit_id}: {exc}")
            controlled_feedback.append(
                f"{unit_id}: {_controlled_validation_feedback(exc)}"
            )
            continue
    missing = tuple(unit_id for unit_id in requested_ids if unit_id not in decisions)
    errors.extend(f"{unit_id}: 缺失或未通过校验" for unit_id in missing)
    controlled_feedback.extend(
        f"{unit_id}: result_missing_or_invalid" for unit_id in missing
    )
    return _BatchAttemptResult(decisions, draft_statuses, raw_items, BatchAuditAttemptTrace(
        attempt=attempt,
        requested_unit_ids=requested_ids,
        returned_unit_ids=tuple(raw_by_unit),
        validation_errors=tuple(errors),
        raw_response=raw,
    ), tuple(controlled_feedback))


def _request_evidence_repair_decisions(
    tasks: Tuple[_EvidenceRepairTask, ...],
    llm: BaseLLMClient,
    timeout_seconds: float,
) -> _BatchAttemptResult:
    """Repair citations in one compact batch with a whitelist per task."""
    if not tasks:
        raise ValueError("紧凑证据修复至少需要一个任务")
    messages = _build_evidence_repair_messages(tasks)
    request_timeout = max(1.0, min(45.0, timeout_seconds / 3))
    raw = llm.chat(
        messages,
        temperature=0.0,
        max_tokens=min(4096, max(2048, len(tasks) * 1024)),
        response_format={"type": "json_object"},
        timeout=request_timeout,
        _retry_deadline=time.monotonic() + max(0.001, timeout_seconds),
    )
    by_unit = {
        task.package.regulation.regulation_unit_id: task for task in tasks
    }
    requested_ids = tuple(by_unit)
    returned_ids: List[str] = []
    errors: List[str] = []
    decisions: Dict[str, RegulationAuditDecision] = {}
    try:
        parsed = json.loads(_strip_code_fence(raw))
        if not isinstance(parsed, Mapping) or not isinstance(
            parsed.get("results"), list,
        ):
            raise ValueError("顶层必须是包含results数组的对象")
        raw_by_unit: Dict[str, List[Mapping[str, object]]] = {}
        for item in parsed["results"]:
            if not isinstance(item, Mapping):
                continue
            unit_id = item.get("regulation_unit_id")
            if isinstance(unit_id, str) and unit_id in by_unit:
                raw_by_unit.setdefault(unit_id, []).append(item)
                returned_ids.append(unit_id)
            elif isinstance(unit_id, str):
                errors.append(f"返回未知regulation_unit_id: {unit_id}")
        for unit_id, task in by_unit.items():
            items = raw_by_unit.get(unit_id, [])
            if len(items) != 1:
                errors.append(f"{unit_id}: 紧凑证据修复返回{len(items)}次")
                continue
            try:
                repair = _EvidenceRepairOutput.model_validate(
                    _normalize_decision_payload(task.package, items[0])
                )
                if repair.task_id != task.package.task_id:
                    raise ValueError("task_id 与审核包不一致")
                allowed_regulation_refs = frozenset(
                    _regulation_evidence_refs(task.package)
                )
                allowed_product_refs = {
                    str(source["evidence_id"])
                    for source in _evidence_repair_product_sources(
                        task.package, task.raw_item,
                    )
                }
                product_name_evidence_id = _product_name_evidence_id(task.package)
                if product_name_evidence_id is not None:
                    allowed_product_refs.add(product_name_evidence_id)
                invalid_regulation_refs = tuple(
                    evidence_id
                    for evidence_id in repair.regulation_evidence_ids
                    if evidence_id not in allowed_regulation_refs
                )
                invalid_product_refs = tuple(
                    evidence_id
                    for evidence_id in repair.product_evidence_ids
                    if evidence_id not in allowed_product_refs
                )
                if invalid_regulation_refs or invalid_product_refs:
                    raise ValueError(
                        "证据修复返回了紧凑目录外ID: "
                        + ", ".join((
                            *invalid_regulation_refs,
                            *invalid_product_refs,
                        ))
                    )
                repaired = task.draft.model_copy(update={
                    "regulation_evidence_ids": repair.regulation_evidence_ids,
                    "product_evidence_ids": repair.product_evidence_ids,
                })
                decisions[unit_id] = _validate_evidence(
                    task.package, repaired,
                )
            except (ValidationError, ValueError) as exc:
                errors.append(
                    f"{unit_id}: 紧凑证据修复未通过校验: {exc}"
                )
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"紧凑证据修复响应无效: {exc}")
    trace = BatchAuditAttemptTrace(
        attempt=2,
        requested_unit_ids=requested_ids,
        returned_unit_ids=tuple(returned_ids),
        validation_errors=tuple(errors),
        raw_response=raw,
        stage="model_evidence_recovery",
    )
    return _BatchAttemptResult(
        decisions,
        {unit_id: task.draft.status for unit_id, task in by_unit.items()},
        {},
        trace,
    )


def audit_regulation_package_batch(
    packages: Iterable[RegulationAuditPackage],
    llm: BaseLLMClient,
    timeout_seconds: float,
    *,
    max_batch_size: int = 8,
    on_attempt: Optional[Callable[[BatchAuditAttemptTrace], None]] = None,
    allow_full_repair: bool = True,
    allow_evidence_repair: bool = True,
    request_timeout_cap_seconds: float = (
        ComplianceConstants.AUDIT_REQUEST_TIMEOUT_CAP_SECONDS
    ),
) -> Tuple[RegulationAuditDecision, ...]:
    """批量审核同一产品与法规；首轮完整判断，次轮紧凑修复证据。"""
    ordered = tuple(sorted(packages, key=lambda item: item.input_index))
    if not ordered:
        return ()
    if len(ordered) > max_batch_size:
        raise ValueError(f"批量审核最多允许 {max_batch_size} 个法规单元")
    source_files = {package.regulation.source_file for package in ordered}
    if len(source_files) != 1:
        raise ValueError("一个审核批次只能包含同一法规文件的法规单元")
    _validate_batch_product_context(ordered)
    deadline = time.monotonic() + max(0.001, timeout_seconds)
    accepted: Dict[str, RegulationAuditDecision] = {}
    batch_response_received = False
    initial_result: Optional[_BatchAttemptResult] = None
    initial_attempt = 0
    initial_attempts = (1, 2) if allow_full_repair else (1,)
    for attempt in initial_attempts:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or initial_result is not None or accepted:
            break
        try:
            initial_result = _request_batch_decisions(
                ordered,
                llm,
                remaining,
                attempt=attempt,
                request_timeout_cap_seconds=request_timeout_cap_seconds,
            )
            initial_attempt = attempt
            batch_response_received = True
            accepted.update(initial_result.decisions)
            if on_attempt is not None:
                on_attempt(initial_result.trace)
        except CallBudgetExceededError as exc:
            logger.warning(
                "法规批量审核预算已耗尽: source=%s reason=%s",
                ordered[0].regulation.source_file,
                exc.reason.value,
            )
            for package in ordered:
                accepted[package.regulation.regulation_unit_id] = (
                    _budget_exhausted_decision(package, exc)
                )
            break
        except Exception as exc:
            logger.warning(
                "法规批量审核失败: source=%s error=%s",
                ordered[0].regulation.source_file,
                exc,
            )
    pending = tuple(
        package for package in ordered
        if package.regulation.regulation_unit_id not in accepted
    )
    if (
        allow_evidence_repair
        and initial_result is not None
        and initial_attempt == 1
        and pending
    ):
        requested_ids = tuple(
            package.regulation.regulation_unit_id for package in ordered
        )
        error_prefixes = tuple(f"{unit_id}:" for unit_id in requested_ids)
        compact_tasks: List[_EvidenceRepairTask] = []
        for package in pending:
            unit_id = package.regulation.regulation_unit_id
            raw_item = initial_result.raw_items.get(unit_id)
            if raw_item is None:
                continue
            try:
                draft = _repairable_draft_output(package, raw_item)
            except (ValidationError, ValueError):
                continue
            feedback = tuple(
                error for error in initial_result.repair_feedback
                if error.startswith(f"{unit_id}:")
                or not error.startswith(error_prefixes)
            )
            compact_tasks.append(_EvidenceRepairTask(
                package=package,
                draft=draft,
                raw_item=raw_item,
                feedback=feedback,
            ))
        if compact_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                for task in compact_tasks:
                    accepted[task.package.regulation.regulation_unit_id] = (
                        _failure_decision(
                            task.package,
                            "batch_audit_incomplete",
                            "紧凑证据修复未能在时间预算内执行。",
                        )
                    )
            else:
                try:
                    repair_result = _request_evidence_repair_decisions(
                        tuple(compact_tasks), llm, remaining,
                    )
                    accepted.update(repair_result.decisions)
                    if on_attempt is not None:
                        on_attempt(repair_result.trace)
                    for task in compact_tasks:
                        unit_id = task.package.regulation.regulation_unit_id
                        if unit_id not in repair_result.decisions:
                            accepted[unit_id] = _failure_decision(
                                task.package,
                                "model_evidence_recovery_failed",
                                "模型首轮结论的证据未通过校验，紧凑证据修复仍未形成"
                                "可验证引用；为避免重复发送完整产品条款，未继续全文补问。",
                            )
                except CallBudgetExceededError as exc:
                    logger.warning(
                        "法规紧凑证据修复预算已耗尽: source=%s reason=%s",
                        ordered[0].regulation.source_file,
                        exc.reason.value,
                    )
                    for unresolved in ordered:
                        unresolved_id = unresolved.regulation.regulation_unit_id
                        if unresolved_id not in accepted:
                            accepted[unresolved_id] = _budget_exhausted_decision(
                                unresolved, exc,
                            )
                except Exception as exc:
                    logger.warning(
                        "法规紧凑证据修复失败: source=%s error=%s",
                        ordered[0].regulation.source_file,
                        exc,
                    )
                    for task in compact_tasks:
                        accepted[task.package.regulation.regulation_unit_id] = (
                            _failure_decision(
                                task.package,
                                "model_evidence_recovery_failed",
                                "紧凑证据修复调用失败；为避免重复发送完整产品条款，"
                                "未继续全文补问。",
                            )
                        )
        pending = tuple(
            package for package in ordered
            if package.regulation.regulation_unit_id not in accepted
        )
        if pending and not allow_full_repair:
            for package in pending:
                accepted[package.regulation.regulation_unit_id] = (
                    _failure_decision(
                        package,
                        "full_repair_disabled",
                        "首轮回答存在非证据型结构问题；本次受控测试不允许重新发送"
                        "完整产品条款，已转人工复核。",
                    )
                )
            pending = ()
        for package in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            unit_id = package.regulation.regulation_unit_id
            repair_feedback = tuple(
                error for error in initial_result.repair_feedback
                if error.startswith(f"{unit_id}:")
                or not error.startswith(error_prefixes)
            )
            required_status = initial_result.draft_statuses.get(unit_id)
            try:
                result = _request_batch_decisions(
                    (package,),
                    llm,
                    remaining,
                    attempt=2,
                    repair_feedback=repair_feedback,
                    required_statuses=(
                        {unit_id: required_status}
                        if required_status is not None else None
                    ),
                    request_timeout_cap_seconds=request_timeout_cap_seconds,
                )
                accepted.update(result.decisions)
                if on_attempt is not None:
                    on_attempt(result.trace)
            except CallBudgetExceededError as exc:
                logger.warning(
                    "法规单元结构修复预算已耗尽: unit=%s reason=%s",
                    unit_id,
                    exc.reason.value,
                )
                for unresolved in ordered:
                    unresolved_id = unresolved.regulation.regulation_unit_id
                    if unresolved_id not in accepted:
                        accepted[unresolved_id] = _budget_exhausted_decision(
                            unresolved, exc,
                        )
                break
            except Exception as exc:
                logger.warning(
                    "法规单元结构修复失败: unit=%s error=%s", unit_id, exc,
                )
        pending = tuple(
            package for package in ordered
            if package.regulation.regulation_unit_id not in accepted
        )
    if pending and not batch_response_received:
        for package in pending:
            accepted[package.regulation.regulation_unit_id] = _failure_decision(
                package,
                "batch_llm_call_failed",
                "批量模型调用未收到有效响应；为避免供应商故障引发逐条请求风暴，未继续单条补问。",
            )
        pending = ()
    if pending and not allow_full_repair:
        for package in pending:
            accepted[package.regulation.regulation_unit_id] = _failure_decision(
                package,
                "full_repair_disabled",
                "批量回答仍有未完成单元；本次受控测试不允许重新发送完整产品条款，"
                "已转人工复核。",
            )
        pending = ()
    for index, package in enumerate(pending):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            decision = _failure_decision(
                package,
                "batch_audit_incomplete",
                "批量审核漏答且未能在时间预算内完成单条补问。",
            )
        else:
            decision = audit_regulation_package(package, llm, remaining)
        accepted[package.regulation.regulation_unit_id] = decision
        if "audit_budget_exhausted" in decision.error_code.split(","):
            for unresolved in pending[index + 1:]:
                accepted[unresolved.regulation.regulation_unit_id] = (
                    _budget_exhausted_decision(unresolved)
                )
            break
    return tuple(
        accepted[package.regulation.regulation_unit_id] for package in ordered
    )


def _validate_batch_product_context(
    packages: Tuple[RegulationAuditPackage, ...],
) -> None:
    """共享产品全文只在产品事实和条款序列完全一致时才安全。"""
    if len({package.input_index for package in packages}) != len(packages):
        raise ValueError("一个审核批次的任务证据域必须唯一")
    if len({package.task_id for package in packages}) != len(packages):
        raise ValueError("一个审核批次不得包含重复task_id")
    if len({
        package.regulation.regulation_unit_id for package in packages
    }) != len(packages):
        raise ValueError("一个审核批次不得包含重复regulation_unit_id")
    first = packages[0]
    first_clauses = tuple(
        (
            routed.clause.clause_id,
            routed.clause.number,
            routed.clause.title,
            routed.clause.text,
            routed.clause.topics,
            routed.clause.hierarchy_path,
            routed.clause.container_only,
        )
        for routed in first.clauses
        if routed.submitted and _has_clause_body(routed)
    )
    for package in packages[1:]:
        clauses = tuple(
            (
                routed.clause.clause_id,
                routed.clause.number,
                routed.clause.title,
                routed.clause.text,
                routed.clause.topics,
                routed.clause.hierarchy_path,
                routed.clause.container_only,
            )
            for routed in package.clauses
            if routed.submitted and _has_clause_body(routed)
        )
        if (
            package.product_name != first.product_name
            or package.product_tags != first.product_tags
            or package.complete_document != first.complete_document
            or clauses != first_clauses
            or package.facts != first.facts
        ):
            raise ValueError("一个审核批次只能共享同一份产品基础上下文和产品条款")


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
        complete_document=False,
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
    execution_orders: Optional[Tuple[int, ...]] = None,
) -> RegulationAuditDecision:
    orders = (
        execution_orders
        if execution_orders is not None
        else tuple(range(1, len(decisions) + 1))
    )
    if len(orders) != len(decisions):
        raise ValueError("分段执行顺序数量必须与分段结论数量一致")
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
            f"源分段{index + 1}（执行顺序{orders[index]}）：{item.reasoning}"
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
    *,
    max_prompt_length: int = BaseLLMClient.MAX_PROMPT_LENGTH,
    allow_context_expansion: bool = True,
    request_timeout_cap_seconds: float = (
        ComplianceConstants.AUDIT_REQUEST_TIMEOUT_CAP_SECONDS
    ),
) -> RegulationAuditDecision:
    if request_timeout_cap_seconds <= 0:
        raise ValueError("HTTP timeout cap必须为正数")
    segments = split_audit_package(package, max_prompt_length=max_prompt_length)
    if package.obligations and len(segments) > 1:
        return _failure_decision(
            package,
            "obligation_segmentation_unsupported",
            "逐项义务审核包超过单次上下文，当前不能在分段间安全合并逐项结论。",
        )
    if len(segments) == 1 and segments[0] is package:
        return _audit_atomic_package(
            package,
            llm,
            timeout_seconds,
            allow_context_expansion=allow_context_expansion,
            request_timeout_cap_seconds=request_timeout_cap_seconds,
        )
    deadline = time.monotonic() + max(0.001, timeout_seconds)
    execution_order = tuple(sorted(
        enumerate(segments),
        key=lambda item: sum(
            len(message["content"].encode("utf-8"))
            for message in build_audit_messages(item[1])
        ),
        reverse=True,
    ))
    execution_ranks = {
        source_segment_index: execution_index
        for execution_index, (source_segment_index, _segment) in enumerate(
            execution_order,
            start=1,
        )
    }
    decisions: Dict[int, RegulationAuditDecision] = {}
    for execution_index, (segment_index, segment) in enumerate(execution_order):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            decisions[segment_index] = _failure_decision(
                segment,
                "audit_deadline_exceeded",
                "法规条款单元分段未在时间预算内完成。",
            )
            continue
        decision = _audit_atomic_package(
            segment,
            llm,
            remaining,
            allow_context_expansion=allow_context_expansion,
            request_timeout_cap_seconds=request_timeout_cap_seconds,
        )
        decisions[segment_index] = decision
        if "audit_budget_exhausted" in decision.error_code.split(","):
            for remaining_index, remaining_segment in execution_order[
                execution_index + 1:
            ]:
                decisions[remaining_index] = _budget_exhausted_decision(
                    remaining_segment,
                )
            break
    return _merge_segment_decisions(
        package,
        tuple(decisions[index] for index in range(len(segments))),
        tuple(execution_ranks[index] for index in range(len(segments))),
    )


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
