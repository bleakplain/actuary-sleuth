"""构建与解析结果绑定的候选审核请求。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Mapping, Optional, Tuple

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
    calculate_clause_hierarchy,
    calculate_clause_ids,
    calculate_document_fingerprint,
    render_audit_document_text,
)
from lib.doc_parser.pd.clause_tagger import tag_clause_topics
from lib.doc_parser.pd.product_tagging import build_product_tags

logger = logging.getLogger(__name__)

# TODO(T046/rollout-complete): 所有解析方已签发新字段后删除此缺失字段豁免。
_ROLLING_ADDITIVE_PRODUCT_TAG_FIELDS = frozenset({
    "is_specific_disease_product",
    "mentions_out_of_hospital_drug",
    "is_cancer_specific_product",
    "mentions_critical_illness_definition_term",
    "is_increasing_sum_assured_product",
})


class PipelineRequestError(ValueError):
    """候选审核请求无法由受信解析结果构建。"""


class InvalidPipelineRequestError(PipelineRequestError):
    """请求缺少必要结构或包含重复标识。"""


class PipelineRequestConflictError(PipelineRequestError):
    """请求内容与解析凭证或绑定原文不一致。"""


def _list_product_tag_mismatches(
    submitted: ProductTags,
    recomputed: ProductTags,
    ignored_fields: frozenset[str] = frozenset(),
) -> Tuple[str, ...]:
    """列出标签值差异，不把证据文本或完整标签内容写入日志。"""
    ignored = {"evidence", "warnings", *ignored_fields}
    return tuple(
        field.name
        for field in fields(ProductTags)
        if field.name not in ignored
        and getattr(submitted, field.name) != getattr(recomputed, field.name)
    )


@dataclass(frozen=True)
class ParsedAuditBlockInput:
    clause_id: str
    block_type: str
    source_index: int
    number: str
    title: str
    content: str
    hierarchy_level: int = 0
    parent_number: Optional[str] = None
    ancestor_numbers: Tuple[str, ...] = ()
    hierarchy_path: str = ""
    container_only: bool = False


@dataclass(frozen=True)
class PipelineRequestInput:
    document_content: str
    parse_id: str
    parse_attestation: str
    document_fingerprint: str
    audit_input_fingerprint: str
    product_name: str
    product_name_source: str
    coverage_attested: bool
    parse_warnings: Tuple[str, ...]
    category: str
    audit_blocks: Tuple[ParsedAuditBlockInput, ...]
    product_tags: Mapping[str, object]


def _validate_bound_hierarchy(
    blocks: Tuple[ParsedAuditBlockInput, ...],
) -> None:
    """重算编号层级，拒绝客户端篡改派生路由事实。

    层级不另行加入内容指纹：它完全由已绑定的 block_type、number、
    content 和同类型编号集合决定。这样既保留证据 ID 的版面独立性，
    又让下游只能消费服务端可重验的层级。
    """
    hierarchical_types = {"clause", "rider"}
    numbers_by_type = {
        block_type: tuple(
            block.number
            for block in blocks
            if block.block_type == block_type and block.number
        )
        for block_type in hierarchical_types
    }
    for block in blocks:
        if block.block_type in hierarchical_types:
            (
                expected_level,
                expected_parent,
                expected_ancestors,
                expected_path,
            ) = calculate_clause_hierarchy(block.number)
            expected_container = bool(
                not block.content.strip()
                and block.number
                and any(
                    number.startswith(f"{block.number}.")
                    for number in numbers_by_type[block.block_type]
                )
            )
        else:
            expected_level, expected_parent = 0, None
            expected_ancestors, expected_path = (), ""
            expected_container = False
        submitted = (
            block.hierarchy_level,
            block.parent_number,
            block.ancestor_numbers,
            block.hierarchy_path,
            block.container_only,
        )
        expected = (
            expected_level,
            expected_parent,
            expected_ancestors,
            expected_path,
            expected_container,
        )
        if submitted != expected:
            raise PipelineRequestConflictError(
                f"审核块 {block.clause_id} 的编号层级与绑定原文不一致，请重新解析"
            )


def build_audit_pipeline_request(
    source: PipelineRequestInput,
    user_subject: str = "",
) -> AuditPipelineRequest:
    """只接受与服务端解析凭证绑定的完整文档事实。"""
    try:
        verified_attestation = verify_parse_attestation(
            source.parse_attestation,
            source.parse_id,
            source.document_fingerprint,
            source.audit_input_fingerprint,
            source.product_name_source,
            source.parse_warnings,
            user_subject,
            coverage_attested=source.coverage_attested,
        )
    except ParseAttestationError as exc:
        raise PipelineRequestConflictError(str(exc)) from exc
    if verified_attestation.version == 1:
        logger.warning(
            "接受兼容窗口内的 v1 解析凭证；全文覆盖证明已降级为 False"
        )
    if not source.audit_blocks:
        raise InvalidPipelineRequestError(
            "候选审核主链需要先调用文档解析接口并提交 audit_blocks"
        )
    ids = [block.clause_id for block in source.audit_blocks]
    if len(ids) != len(set(ids)):
        raise InvalidPipelineRequestError("audit_blocks 包含重复 clause_id")
    _validate_bound_hierarchy(source.audit_blocks)
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
        complete_document=verified_attestation.coverage_attested,
    )
    submitted_tags = ProductTags.from_dict(source.product_tags)
    missing_additive_fields = frozenset(
        field_name
        for field_name in _ROLLING_ADDITIVE_PRODUCT_TAG_FIELDS
        if field_name not in source.product_tags
    )
    if verified_attestation.version == 2 and missing_additive_fields:
        logger.warning(
            "兼容滚动发布期间缺失的新增产品风险事实已由服务端重算；"
            "missing_fields=%s",
            ",".join(sorted(missing_additive_fields)),
        )
    tag_mismatches = _list_product_tag_mismatches(
        submitted_tags,
        product_tags,
        missing_additive_fields,
    )
    if tag_mismatches:
        if verified_attestation.version == 2:
            raise PipelineRequestConflictError(
                "产品标签与绑定的产品名称及条款原文不一致，请重新解析"
            )
        logger.warning(
            "v1 凭证下提交的产品标签已由服务端重算结果覆盖；"
            "mismatched_fields=%s",
            ",".join(tag_mismatches),
        )
    clauses = tuple(
        AuditClauseSnapshot(
            clause_id=block.clause_id,
            number=block.number,
            title=block.title,
            text=block.content,
            block_type=block.block_type,
            topics=tag_clause_topics(block.title, block.content),
            hierarchy_level=block.hierarchy_level,
            parent_number=block.parent_number,
            ancestor_numbers=block.ancestor_numbers,
            hierarchy_path=block.hierarchy_path,
            container_only=block.container_only,
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
        coverage_attested=verified_attestation.coverage_attested,
    )
