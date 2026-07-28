"""构建与解析结果绑定的候选审核请求。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Tuple

from lib.auth.parse_attestation import (
    ParseAttestationError,
    verify_parse_attestation,
)
from lib.common.compliance_audit import AuditClauseSnapshot
from lib.common.product_tags import ProductTags
from lib.compliance.audit_pipeline import AuditPipelineRequest
from lib.compliance.regulation_retrieval import infer_category_from_product_tags
from lib.doc_parser.models import (
    calculate_audit_input_fingerprint,
    calculate_clause_ids,
    calculate_document_fingerprint,
    render_audit_document_text,
)
from lib.doc_parser.pd.clause_tagger import tag_clause_topics
from lib.doc_parser.pd.product_tagging import build_product_tags


class PipelineRequestError(ValueError):
    """候选审核请求无法由受信解析结果构建。"""


class InvalidPipelineRequestError(PipelineRequestError):
    """请求缺少必要结构或包含重复标识。"""


class PipelineRequestConflictError(PipelineRequestError):
    """请求内容与解析凭证或绑定原文不一致。"""


@dataclass(frozen=True)
class ParsedAuditBlockInput:
    clause_id: str
    block_type: str
    source_index: int
    number: str
    title: str
    content: str


@dataclass(frozen=True)
class PipelineRequestInput:
    document_content: str
    parse_id: str
    parse_attestation: str
    document_fingerprint: str
    audit_input_fingerprint: str
    product_name: str
    product_name_source: str
    parse_warnings: Tuple[str, ...]
    category: str
    audit_blocks: Tuple[ParsedAuditBlockInput, ...]
    product_tags: Mapping[str, object]


def build_audit_pipeline_request(
    source: PipelineRequestInput,
    user_subject: str = "",
) -> AuditPipelineRequest:
    """只接受与服务端解析凭证绑定的完整文档事实。"""
    try:
        verify_parse_attestation(
            source.parse_attestation,
            source.parse_id,
            source.document_fingerprint,
            source.audit_input_fingerprint,
            source.product_name_source,
            source.parse_warnings,
            user_subject,
        )
    except ParseAttestationError as exc:
        raise PipelineRequestConflictError(str(exc)) from exc
    if not source.audit_blocks:
        raise InvalidPipelineRequestError(
            "候选审核主链需要先调用文档解析接口并提交 audit_blocks"
        )
    ids = [block.clause_id for block in source.audit_blocks]
    if len(ids) != len(set(ids)):
        raise InvalidPipelineRequestError("audit_blocks 包含重复 clause_id")
    if not source.document_fingerprint:
        raise InvalidPipelineRequestError("缺少 document_fingerprint")
    block_identities = tuple(
        (block.block_type, block.number, block.title, block.content)
        for block in source.audit_blocks
    )
    calculated_fingerprint = calculate_document_fingerprint(block_identities)
    if calculated_fingerprint != source.document_fingerprint:
        raise PipelineRequestConflictError(
            "audit_blocks 与解析时的 document_fingerprint 不一致，请重新解析"
        )
    expected_input_fingerprint = calculate_audit_input_fingerprint(
        calculated_fingerprint,
        source.product_name,
    )
    if source.audit_input_fingerprint != expected_input_fingerprint:
        raise PipelineRequestConflictError(
            "产品名称与解析时的审核输入指纹不一致，请重新解析"
        )
    if tuple(ids) != calculate_clause_ids(block_identities):
        raise PipelineRequestConflictError(
            "clause_id 与审核块原文不一致，请重新解析"
        )
    rendered_document = render_audit_document_text(
        (
            block.block_type,
            block.source_index,
            block.number,
            block.title,
            block.content,
        )
        for block in source.audit_blocks
    )
    if rendered_document != source.document_content:
        raise PipelineRequestConflictError(
            "document_content 与完整审核块集合不一致，请重新解析"
        )
    product_tags = build_product_tags(
        source.product_name or None,
        source.document_content,
        product_name_source=source.product_name_source,
        complete_document=True,
    )
    submitted_tags = ProductTags.from_dict(source.product_tags)
    if replace(submitted_tags, evidence=(), warnings=()) != replace(
        product_tags,
        evidence=(),
        warnings=(),
    ):
        raise PipelineRequestConflictError(
            "产品标签与绑定的产品名称及条款原文不一致，请重新解析"
        )
    clauses = tuple(
        AuditClauseSnapshot(
            clause_id=block.clause_id,
            number=block.number,
            title=block.title,
            text=block.content,
            block_type=block.block_type,
            topics=tag_clause_topics(block.title, block.content),
        )
        for block in source.audit_blocks
    )
    return AuditPipelineRequest(
        product_name=source.product_name or "未命名产品",
        document_content=source.document_content,
        product_tags=product_tags,
        clauses=clauses,
        category=source.category or infer_category_from_product_tags(product_tags),
        document_fingerprint=source.document_fingerprint,
        audit_input_fingerprint=source.audit_input_fingerprint,
        product_name_source=source.product_name_source,
        parse_warnings=source.parse_warnings,
    )
