"""逐法规条款单元的结构化 LLM 审核。"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.common.compliance_audit import (
    BatchAuditAttemptTrace,
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
_MAX_CONTEXT_REQUEST_NUMBERS = 5
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
    needs_more_context: bool = False
    requested_outline_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class _BatchAttemptResult:
    decisions: Dict[str, RegulationAuditDecision]
    draft_statuses: Dict[str, RegulationDecisionStatus]
    trace: BatchAuditAttemptTrace


def _regulation_evidence_refs(
    package: RegulationAuditPackage,
) -> Dict[str, RegulationChunkSnapshot]:
    return {
        f"R{index:03d}": chunk
        for index, chunk in enumerate(package.regulation.chunks, start=1)
    }


def _product_evidence_refs(
    package: RegulationAuditPackage,
) -> Dict[str, RoutedClause]:
    submitted = (
        item
        for item in package.clauses
        if item.submitted and _has_clause_body(item)
    )
    return {
        f"P{index:03d}": routed
        for index, routed in enumerate(submitted, start=1)
    }


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
    shared_product["clauses"] = [
        {
            key: value
            for key, value in clause.items()
            if key not in {"relation", "routing_reasons"}
        }
        for clause in structured_clauses
    ]
    return {
        "batch_id": f"{packages[0].regulation.source_file}:{packages[0].input_index}",
        "required_unit_ids": [
            package.regulation.regulation_unit_id for package in packages
        ],
        "product": shared_product,
        "regulation_tasks": [
            {
                "task_id": package.task_id,
                "regulation_unit": _package_payload(package)["regulation_unit"],
                "priority_product_clauses": [
                    {
                        "evidence_ref": evidence_ref,
                        "clause_id": routed.clause.clause_id,
                        "number": routed.clause.number,
                        "title": routed.clause.title,
                        "text": routed.clause.text,
                        "relation": routed.relation.value,
                    }
                    for evidence_ref, routed in _product_evidence_refs(package).items()
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
    )
    instruction = """输出一个 JSON 对象，不得输出 Markdown：
{"results": [{
  "task_id": "<对应task_id>",
  "regulation_unit_id": "<对应regulation_unit_id>",
  "status": "compliant|non_compliant|insufficient_information|manual_review",
  "reasoning": "<理由>", "suggestion": "<建议>",
  "regulation_evidence": [{"evidence_id": "<R001等evidence_ref>", "quote": "<逐字摘录>"}],
  "product_evidence": [{"evidence_id": "<P001等evidence_ref或PNAME>", "quote": "<逐字摘录>"}],
  "applicability_dispute": false, "confidence": 0.95
}]}

每个 required_unit_id 必须且只能出现一次。证据、状态和引用规则与单条审核一致；
不能证明符合时必须输出 insufficient_information，不能直接省略。
confidence 必须根据本条证据充分程度独立评估，不得机械复制示例值；能够由法规和
产品逐字证据直接证明的结论应给出与证据强度一致的置信度。
evidence_id 必须逐字复制审核包中短 evidence_ref（法规R001…；产品P001…；产品名称
PNAME），不得复制内部哈希或使用product_clause等占位名称。若状态为 insufficient_information，
可以返回空证据数组，但仍必须给出该法规单元的明确回答。
每个法规单元应先检查其 priority_product_clauses，再检查完整产品条款；重点条款
只是证据定位提示，不限制使用其他真实条款。

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


def _package_payload(package: RegulationAuditPackage) -> Dict[str, object]:
    regulation_refs = _regulation_evidence_refs(package)
    product_refs = _product_evidence_refs(package)
    outline_refs = _outline_refs(package)
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
                    "evidence_ref": evidence_ref,
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
            "name_evidence_ref": "PNAME",
            "complete_document": _has_complete_submitted_document(package),
            "tags": package.product_tags.to_dict(),
            "clauses": [
                {
                    "evidence_ref": evidence_ref,
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
                for evidence_ref, routed in product_refs.items()
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
            "product_facts": [
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
            ],
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
  "regulation_evidence": [{"evidence_id": "<R001等evidence_ref>", "quote": "<逐字摘录>"}],
  "product_evidence": [{"evidence_id": "<P001等evidence_ref或PNAME>", "quote": "<逐字摘录>"}],
  "applicability_dispute": false,
  "confidence": 0.95,
  "needs_more_context": false,
  "requested_outline_refs": []
}

约束：
1. non_compliant 必须同时引用至少一条法规证据和一条产品条款证据。
2. compliant 必须同时有法规证据和产品条款证据；只有第8项允许产品证据为空。
3. 法规适用性存在争议时输出 manual_review，并将 applicability_dispute 设为 true。
4. quote 必须是对应 evidence_id 原文中的连续逐字摘录。
5. evidence_id 只能使用审核包提供的短 evidence_ref：法规使用R001…，产品条款使用P001…，产品名称使用PNAME。
6. 产品条款证据必须摘录条款正文，不得只引用条款标题；摘录至少包含一个完整事实或要求。
7. 产品名称确实能够证明产品身份或名称明示属性时，可以使用PNAME；不得用产品名称证明条款正文必须包含的表述。
8. 若法规明确禁止特定表述、责任或设计，且product.complete_document为true，逐块检查完整
   产品条款后未发现禁止事项，可以将product_evidence留空，但reasoning必须明确写明“已检查
   完整产品条款，未发现……”；数值上下限和“应当/必须”义务不得使用此例外。

product.clause_outline 是完整条款目录，只用于定位可能需要补充的正文，不是结论证据。
"""
    if allow_context_request:
        instruction += """
9. 只有当已提交正文不足以判断、且目录中存在明确值得补充的条款时，才可设置
   needs_more_context=true。此时status必须为insufficient_information，不得同时形成
   compliant/non_compliant结论，regulation_evidence和product_evidence必须为空。
10. requested_outline_refs只能填写clause_outline中真实、正文可用且尚未提交的O001等
    outline_ref，必须去重，最多5个；不得填写number或编造ref。
"""
    else:
        instruction += """
9. 本轮已是唯一一次上下文扩展后的最终判断。不得再请求补充条款；
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
    if output.regulation_evidence or output.product_evidence:
        raise ValueError("请求补充上下文时不得同时形成证据结论")
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


def _validate_evidence(
    package: RegulationAuditPackage,
    output: _DecisionOutput,
) -> RegulationAuditDecision:
    if _validate_context_request(package, output):
        raise ValueError("上下文请求必须由单条审核编排流程处理")
    if not output.reasoning.strip():
        raise ValueError("reasoning 不能为空")
    regulation_content = {
        chunk.chunk_id: chunk.content for chunk in package.regulation.chunks
    }
    regulation_refs = _regulation_evidence_refs(package)
    regulation_content.update({
        evidence_ref: chunk.content
        for evidence_ref, chunk in regulation_refs.items()
    })
    regulation_ids = {
        evidence_ref: chunk.chunk_id
        for evidence_ref, chunk in regulation_refs.items()
    }
    product_content = {
        routed.clause.clause_id: routed.clause.text
        for routed in package.clauses
        if routed.submitted
    }
    product_refs = _product_evidence_refs(package)
    product_content.update({
        evidence_ref: routed.clause.text
        for evidence_ref, routed in product_refs.items()
    })
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
        return quote.strip()

    regulation_evidence: List[RegulationEvidence] = []
    for evidence in output.regulation_evidence:
        if not evidence.evidence_id.strip() or not evidence.quote.strip():
            raise ValueError("法规证据 ID 和摘录不能为空")
        content = regulation_content.get(evidence.evidence_id)
        if content is None or evidence.quote not in content:
            raise ValueError(f"无效法规证据: {evidence.evidence_id}")
        regulation_evidence.append(RegulationEvidence(
            chunk_id=regulation_ids.get(evidence.evidence_id, evidence.evidence_id),
            quote=require_substantive_quote(evidence.quote, "法规证据"),
        ))
    product_evidence: List[ProductClauseEvidence] = []
    for evidence in output.product_evidence:
        if not evidence.evidence_id.strip() or not evidence.quote.strip():
            raise ValueError("产品证据 ID 和摘录不能为空")
        source_kind = "clause_body"
        content = product_content.get(evidence.evidence_id)
        if evidence.evidence_id in {"product-name", "PNAME"}:
            if "contract.name" not in package.regulation.topics:
                raise ValueError("当前法规主题不允许使用产品名称作为结论证据")
            source_kind = "product_name"
            content = package.product_name
        if content is None or evidence.quote not in content:
            raise ValueError(f"无效产品条款证据: {evidence.evidence_id}")
        product_evidence.append(ProductClauseEvidence(
            clause_id=(
                "product-name"
                if source_kind == "product_name"
                else product_ids.get(evidence.evidence_id, evidence.evidence_id)
            ),
            quote=require_substantive_quote(evidence.quote, "产品证据"),
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
    )


def _audit_atomic_package(
    package: RegulationAuditPackage,
    llm: BaseLLMClient,
    timeout_seconds: float,
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
        request_timeout = max(1.0, min(45.0, remaining / 3))
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
        return _DecisionOutput.model_validate_json(_strip_code_fence(raw))

    try:
        output = request_output(package, allow_context_request=True)
        requested = _validate_context_request(package, output)
        if not requested:
            return _validate_evidence(package, output)
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
) -> _BatchAttemptResult:
    request_timeout = max(1.0, min(45.0, timeout_seconds / 3))
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
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        return _BatchAttemptResult({}, {}, BatchAuditAttemptTrace(
            attempt, requested_ids, (), (f"JSON解析失败: {exc}",), raw,
        ))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        return _BatchAttemptResult({}, {}, BatchAuditAttemptTrace(
            attempt, requested_ids, (), ("顶层必须是包含results数组的对象",), raw,
        ))
    by_unit = {
        package.regulation.regulation_unit_id: package for package in packages
    }
    raw_by_unit: Dict[str, List[object]] = {}
    for item in parsed["results"]:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("regulation_unit_id")
        if isinstance(unit_id, str) and unit_id in by_unit:
            raw_by_unit.setdefault(unit_id, []).append(item)
        elif isinstance(unit_id, str):
            errors.append(f"返回未知regulation_unit_id: {unit_id}")
    decisions: Dict[str, RegulationAuditDecision] = {}
    draft_statuses: Dict[str, RegulationDecisionStatus] = {}
    for unit_id, items in raw_by_unit.items():
        if len(items) != 1:
            errors.append(f"{unit_id}: 重复返回{len(items)}次")
            continue
        try:
            output = _DecisionOutput.model_validate(items[0])
            draft_statuses[unit_id] = output.status
            required_status = (required_statuses or {}).get(unit_id)
            if required_status is not None and output.status is not required_status:
                raise ValueError(
                    f"证据修复不得把status从{required_status.value}改为{output.status.value}"
                )
            decisions[unit_id] = _validate_evidence(by_unit[unit_id], output)
        except (ValidationError, ValueError) as exc:
            errors.append(f"{unit_id}: {exc}")
            continue
    missing = tuple(unit_id for unit_id in requested_ids if unit_id not in decisions)
    errors.extend(f"{unit_id}: 缺失或未通过校验" for unit_id in missing)
    return _BatchAttemptResult(decisions, draft_statuses, BatchAuditAttemptTrace(
        attempt=attempt,
        requested_unit_ids=requested_ids,
        returned_unit_ids=tuple(raw_by_unit),
        validation_errors=tuple(errors),
        raw_response=raw,
    ))


def audit_regulation_package_batch(
    packages: Iterable[RegulationAuditPackage],
    llm: BaseLLMClient,
    timeout_seconds: float,
    *,
    max_batch_size: int = 8,
    on_attempt: Optional[Callable[[BatchAuditAttemptTrace], None]] = None,
) -> Tuple[RegulationAuditDecision, ...]:
    """批量审核同一产品与法规；有响应时补问漏答，无响应时停止扇出。"""
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
    pending = ordered
    batch_response_received = False
    repair_feedback: Tuple[str, ...] = ()
    required_statuses: Dict[str, RegulationDecisionStatus] = {}
    for attempt in range(1, 3):
        remaining = deadline - time.monotonic()
        if not pending or remaining <= 0:
            break
        try:
            result = _request_batch_decisions(
                pending,
                llm,
                remaining,
                attempt=attempt,
                repair_feedback=(
                    *repair_feedback,
                    *(
                        f"{unit_id}: 本轮仅修复证据，status必须保持{status.value}"
                        for unit_id, status in required_statuses.items()
                    ),
                ),
                required_statuses=required_statuses,
            )
            batch_response_received = True
            accepted.update(result.decisions)
            repair_feedback = result.trace.validation_errors
            required_statuses.update(result.draft_statuses)
            if on_attempt is not None:
                on_attempt(result.trace)
        except Exception as exc:
            logger.warning("法规批量审核失败: source=%s error=%s", ordered[0].regulation.source_file, exc)
        pending = tuple(
            package for package in pending
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
    for package in pending:
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
    return tuple(
        accepted[package.regulation.regulation_unit_id] for package in ordered
    )


def _validate_batch_product_context(
    packages: Tuple[RegulationAuditPackage, ...],
) -> None:
    """共享产品全文只在产品事实和条款序列完全一致时才安全。"""
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
            or package.product_facts != first.product_facts
        ):
            raise ValueError("一个审核批次只能共享同一份产品事实和产品条款")


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
