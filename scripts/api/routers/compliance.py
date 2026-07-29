"""合规检查路由 — 流式条款审查 + 文档解析。"""

import os
import uuid
import asyncio
from dataclasses import replace
import json
import logging
import tempfile
import threading
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sse_starlette.sse import EventSourceResponse

from api.database import get_connection, list_compliance_reports, get_compliance_report, save_compliance_report
from api.schemas.compliance import (
    DocumentCheckRequest, ComplianceReportResponse,
    ParsedDocumentResponse, ParsedClause, ParsedDataTable, ParsedSection,
    ParsedAuditBlock, RichTextParseRequest,
)
from lib.common.constants import ComplianceConstants
from lib.common.html_converter import html_to_docx
from lib.common.product_tags import ProductTags
from lib.compliance.checker import (
    AuditResultItem,
    streaming_compliance_check,
    streaming_negative_check,
    identify_category,
    infer_category_from_product_tags,
    build_regulation_retrieval_query,
    retrieve_audit_regulations_with_status,
    normalize_clause_number,
    extract_section_numbers,
)
from lib.compliance.rule_engine import RuleViolation, ProductMetadata
from lib.doc_parser import parse_product_document, DocumentParseError
from lib.doc_parser.models import (
    AuditBlockType,
    AuditDocument,
)
from lib.doc_parser.pd.product_name_recognizer import recognize_product_name
from lib.doc_parser.pd.clause_tagger import tag_clause_topics
from lib.doc_parser.pd.product_tagging import build_product_tags
from lib.auth.permissions import require_permission
from lib.auth.parse_attestation import issue_parse_attestation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])


def _report_owner_scope(user: Dict[str, Any]) -> Optional[str]:
    """管理员可治理全部报告，其他角色只能访问自己的报告。"""
    if user.get("role_id") == "admin":
        return None
    user_id = str(user.get("user_id", "")).strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="当前用户身份缺少 user_id")
    return user_id


def _apply_requested_product_name(
    audit_doc: AuditDocument, product_name: str, document_content: str,
) -> AuditDocument:
    """让用户明确提交的产品名称成为名称字段和标签的共同事实来源。"""
    recognition = recognize_product_name([product_name])
    return replace(
        audit_doc,
        product_name=product_name,
        product_name_source="user_input",
        product_tags=build_product_tags(
            product_name,
            document_content,
            product_name_source="user_input",
            complete_document=audit_doc.coverage_attested,
        ),
        is_rider=recognition.is_rider,
        group_or_individual=recognition.group_or_individual,
        duration_type=recognition.duration_type,
        design_type=recognition.design_type,
        naming_warnings=recognition.warnings,
    )


def _resolve_retrieval_context(
    category: Optional[str],
    product_tags: ProductTags,
) -> Tuple[Optional[str], List[str]]:
    """恢复法规分类并生成需要向用户展示的降级原因。"""
    warnings: List[str] = []
    if not category:
        category = infer_category_from_product_tags(product_tags)
        if category:
            warnings.append(f"常规险种识别失败，已依据产品标签按“{category}”检索法规")
        else:
            warnings.append("无法确定险种，已保守检索所有险种法规")
    return category, warnings


@router.post("/check/document/stream")
async def check_document_stream(req: DocumentCheckRequest, user: dict = Depends(require_permission("compliance"))):
    """流式合规检查，通过 SSE 实时推送违规条款。"""
    category: Optional[str] = req.category
    if not category:
        category, _ = await _identify_category_async(req.document_content, req.product_name or "")

    product_tags = build_product_tags(req.product_name or None, req.document_content)
    category, retrieval_warnings = _resolve_retrieval_context(
        category, product_tags,
    )
    clause_topics = tuple(req.clause_topics) or tag_clause_topics("", req.document_content)
    retrieval_query = build_regulation_retrieval_query(
        req.product_name, req.document_content, product_tags,
    )
    retrieval_outcome = await asyncio.to_thread(
        retrieve_audit_regulations_with_status,
        retrieval_query,
        category,
        product_tags,
        clause_topics,
    )
    regulations = list(retrieval_outcome.regulations)
    retrieval_warnings = list(dict.fromkeys(
        [*retrieval_warnings, *retrieval_outcome.warnings],
    ))
    retrieval_degraded = bool(retrieval_warnings) or retrieval_outcome.degraded

    regulation_sources: Dict[str, List[str]] = {
        "险种专属": sorted(set(r.law_name for r in regulations if r.source_type == "category")),
        "通用法规": sorted(set(r.law_name for r in regulations if r.source_type == "general")),
        "标签检索": sorted(set(r.law_name for r in regulations if r.source_type == "semantic")),
    }

    async def event_stream() -> AsyncIterator[Dict[str, str]]:
        all_items: List[Union[AuditResultItem, RuleViolation]] = []
        all_regulations = list(regulations)
        negative_list_result = "skipped"
        failure_reasons: List[str] = []
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

        for warning in retrieval_warnings:
            yield {"event": "message", "data": json.dumps(
                {"type": "progress", "data": f"检索降级：{warning}"}, ensure_ascii=False,
            )}

        product_meta = ProductMetadata(
            category=category,
            product_form=(
                "团体" if product_tags.customer_scope.value == "group"
                else "个人" if product_tags.customer_scope.value == "individual"
                else None
            ),
            insurance_term=(
                "长期" if product_tags.term_class.value == "long_term"
                else "短期" if product_tags.term_class.value == "short_term"
                else None
            ),
            policy_type=(
                "主险" if product_tags.contract_role.value == "main"
                else "附加险" if product_tags.contract_role.value == "rider"
                else None
            ),
        )

        def _producer() -> None:
            try:
                for event in streaming_compliance_check(req.document_content, regulations, category, product_meta):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
                for event in streaming_negative_check(req.document_content):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "data": f"审核流异常：{e}"},
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=_producer, daemon=True)
        thread.start()

        while True:
            event = await queue.get()
            if event is None:
                break
            event_type = event.get("type")
            if event_type == "error":
                failure_reasons.append(str(event.get("data") or "审核流发生未知异常"))
                continue
            if event_type == "violation":
                all_items.append(event["data"])
                yield {"event": "message", "data": json.dumps(
                    {"type": "violation", "data": event["data"].__dict__}, ensure_ascii=False
                )}
                continue
            if event_type == "negative_list_result":
                negative_list_result = event["data"]
                neg_regs = event.get("regulations", [])
                if neg_regs:
                    all_regulations.extend(neg_regs)
                    regulation_sources["负面清单"] = sorted(set(
                        r.get("law_name", "") for r in neg_regs if r.get("law_name")
                    ))
                continue
            if (
                event_type == "progress"
                and isinstance(event.get("data"), str)
                and event["data"].lstrip().startswith("⚠")
                and "失败" in event["data"]
            ):
                failure_reasons.append(event["data"])
            yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

        # done: compute summary, coverage, save report
        report_id = f"cr_{uuid.uuid4().hex}"
        product_name = req.product_name or "未命名产品"
        summary = {"non_compliant": len(all_items), "compliant": 0, "attention": 0}

        section_info = extract_section_numbers(req.document_content)
        doc_clause_set = set(section_info["clauses"])
        flagged_clause_set = set()
        for item in all_items:
            cn = item.clause_number
            if cn != "未知":
                normalized = normalize_clause_number(cn)
                if normalized:
                    flagged_clause_set.add(normalized)

        definition_chapter = section_info.get("definition_chapter")
        checked_clauses = doc_clause_set
        if definition_chapter:
            checked_clauses = {c for c in doc_clause_set if not c.startswith(definition_chapter + ".")}

        failure_reasons = list(dict.fromkeys(failure_reasons))
        audit_status = (
            "incomplete"
            if failure_reasons
            else "degraded"
            if retrieval_degraded
            else "completed"
        )
        compliance_conclusion = (
            "undetermined"
            if failure_reasons or (retrieval_degraded and not all_items)
            else "non_compliant"
            if all_items
            else "no_violation_found"
        )
        done_data = {
            "report_id": report_id,
            "product_name": product_name,
            "category": category or "",
            "summary": summary,
            "negative_list_result": negative_list_result,
            "regulation_sources": regulation_sources,
            "regulations": [r.__dict__ if hasattr(r, '__dict__') else r for r in all_regulations],
            "retrieval_degraded": retrieval_degraded,
            "retrieval_warnings": retrieval_warnings,
            "audit_status": audit_status,
            "compliance_conclusion": compliance_conclusion,
            "candidate_count": len(all_regulations),
            "excluded_count": 0,
            "completed_count": 0 if failure_reasons else len(all_regulations),
            "failed_count": len(failure_reasons),
            "failure_reasons": failure_reasons,
            "clause_coverage": {
                "total": len(checked_clauses),
                "checked": len(checked_clauses),
                "flagged": len(flagged_clause_set & doc_clause_set),
                "unchecked": [],
                "all_total": len(section_info.get("all_clauses", doc_clause_set)),
                "definition_chapter": definition_chapter,
                "has_notices": section_info["has_notices"],
                "has_health": section_info["has_health"],
                "has_exclusions": section_info["has_exclusions"],
                "has_tables": section_info["has_tables"],
            },
        }

        result_for_db = {
            "summary": summary,
            "items": [item.__dict__ for item in all_items],
            "regulations": [r.__dict__ if hasattr(r, '__dict__') else r for r in all_regulations],
            "regulation_sources": regulation_sources,
            "category": category or "",
            "negative_list_result": negative_list_result,
            "retrieval_degraded": retrieval_degraded,
            "retrieval_warnings": retrieval_warnings,
            "audit_status": audit_status,
            "compliance_conclusion": compliance_conclusion,
            "candidate_count": len(all_regulations),
            "excluded_count": 0,
            "completed_count": 0 if failure_reasons else len(all_regulations),
            "failed_count": len(failure_reasons),
            "failure_reasons": failure_reasons,
            "clause_coverage": done_data["clause_coverage"],
        }
        try:
            save_compliance_report(
                report_id,
                product_name,
                category or "",
                "document",
                result_for_db,
                str(user.get("user_id", "")),
            )
        except Exception:
            logger.exception("旧合规审核报告持久化失败: %s", report_id)
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",
                        "data": "报告保存失败，审核结果未持久化",
                    },
                    ensure_ascii=False,
                ),
            }
            return

        yield {"event": "message", "data": json.dumps({"type": "done", "data": done_data}, ensure_ascii=False)}

    return EventSourceResponse(event_stream())


@router.get("/categories")
async def get_categories(user: dict = Depends(require_permission("compliance"))):
    return {"categories": ComplianceConstants.VALID_CATEGORIES}


@router.get("/reports", response_model=list[ComplianceReportResponse])
async def list_reports(user: dict = Depends(require_permission("compliance"))):
    return list_compliance_reports(_report_owner_scope(user))


@router.get("/reports/{report_id}", response_model=ComplianceReportResponse)
async def get_report(report_id: str, user: dict = Depends(require_permission("compliance"))):
    report = get_compliance_report(report_id, _report_owner_scope(user))
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.delete("/reports/{report_id}")
async def delete_compliance_report(report_id: str, user: dict = Depends(require_permission("compliance"))):
    owner_user_id = _report_owner_scope(user)
    with get_connection() as conn:
        if owner_user_id is None:
            cur = conn.execute(
                "DELETE FROM compliance_reports WHERE id = ?",
                (report_id,),
            )
        else:
            cur = conn.execute(
                "DELETE FROM compliance_reports "
                "WHERE id = ? AND owner_user_id = ?",
                (report_id, owner_user_id),
            )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="报告不存在")
    return {"status": "deleted"}


# --- Document parsing ---


def _audit_doc_to_response(audit_doc, file_type: str,
                           identified_category: Optional[str] = None,
                           category_confidence: float = 0.0,
                           user_subject: str = "") -> ParsedDocumentResponse:
    block_by_source = {
        (block.block_type, block.source_index): block
        for block in audit_doc.audit_blocks
    }
    clauses = [
        ParsedClause(
            clause_id=block_by_source[(AuditBlockType.CLAUSE, index)].clause_id,
            number=clause.number,
            title=clause.title,
            text=clause.text,
            topics=list(clause.topics),
            hierarchy_level=block_by_source[
                (AuditBlockType.CLAUSE, index)
            ].hierarchy_level,
            parent_number=block_by_source[
                (AuditBlockType.CLAUSE, index)
            ].parent_number,
            ancestor_numbers=list(block_by_source[
                (AuditBlockType.CLAUSE, index)
            ].ancestor_numbers),
            hierarchy_path=block_by_source[
                (AuditBlockType.CLAUSE, index)
            ].hierarchy_path,
            container_only=block_by_source[
                (AuditBlockType.CLAUSE, index)
            ].container_only,
        )
        for index, clause in enumerate(audit_doc.clauses)
    ]
    tables = [
        ParsedDataTable(
            clause_id=block_by_source[(AuditBlockType.TABLE, index)].clause_id,
            table_type=(
                t.table_type.value
                if hasattr(t.table_type, "value")
                else str(t.table_type)
            ),
            remark=t.remark or "",
            raw_text=block_by_source[
                (AuditBlockType.TABLE, index)
            ].content,
            data=[list(row) for row in t.data],
        )
        for index, t in enumerate(audit_doc.tables)
    ]
    unclassified = [
        ParsedSection(
            clause_id=block_by_source[
                (AuditBlockType.UNCLASSIFIED, index)
            ].clause_id,
            title=section.title,
            content=section.content,
        )
        for index, section in enumerate(audit_doc.unclassified_sections)
    ]
    notices = [
        ParsedSection(
            clause_id=block_by_source[(AuditBlockType.NOTICE, index)].clause_id,
            title=section.title,
            content=section.content,
        )
        for index, section in enumerate(audit_doc.notices)
    ]
    health = [
        ParsedSection(
            clause_id=block_by_source[(AuditBlockType.HEALTH_DISCLOSURE, index)].clause_id,
            title=section.title,
            content=section.content,
        )
        for index, section in enumerate(audit_doc.health_disclosures)
    ]
    exclusions = [
        ParsedSection(
            clause_id=block_by_source[(AuditBlockType.EXCLUSION, index)].clause_id,
            title=section.title,
            content=section.content,
        )
        for index, section in enumerate(audit_doc.exclusions)
    ]
    riders = [
        ParsedClause(
            clause_id=block_by_source[(AuditBlockType.RIDER, index)].clause_id,
            number=clause.number,
            title=clause.title,
            text=clause.text,
            topics=list(clause.topics),
            hierarchy_level=block_by_source[
                (AuditBlockType.RIDER, index)
            ].hierarchy_level,
            parent_number=block_by_source[
                (AuditBlockType.RIDER, index)
            ].parent_number,
            ancestor_numbers=list(block_by_source[
                (AuditBlockType.RIDER, index)
            ].ancestor_numbers),
            hierarchy_path=block_by_source[
                (AuditBlockType.RIDER, index)
            ].hierarchy_path,
            container_only=block_by_source[
                (AuditBlockType.RIDER, index)
            ].container_only,
        )
        for index, clause in enumerate(audit_doc.rider_clauses)
    ]
    audit_blocks = [
        ParsedAuditBlock(
            clause_id=block.clause_id,
            block_type=block.block_type.value,
            source_index=block.source_index,
            number=block.number,
            title=block.title,
            content=block.content,
            topics=list(block.topics),
            hierarchy_level=block.hierarchy_level,
            parent_number=block.parent_number,
            ancestor_numbers=list(block.ancestor_numbers),
            hierarchy_path=block.hierarchy_path,
            container_only=block.container_only,
        )
        for block in audit_doc.audit_blocks
    ]

    combined_text = audit_doc.canonical_text
    parse_id = f"pd_{uuid.uuid4().hex}"
    attestation = issue_parse_attestation(
        parse_id,
        audit_doc.document_fingerprint,
        audit_doc.audit_input_fingerprint,
        audit_doc.product_name_source,
        tuple(audit_doc.warnings),
        user_subject,
        coverage_attested=audit_doc.coverage_attested,
    )

    return ParsedDocumentResponse(
        parse_id=parse_id,
        parse_attestation=attestation.token,
        parse_attestation_expires_at=attestation.expires_at,
        file_name=audit_doc.file_name,
        file_type=file_type,
        clauses=clauses, data_tables=tables,
        unclassified_sections=unclassified, notices=notices,
        health_disclosures=health, exclusions=exclusions, rider_clauses=riders,
        audit_blocks=audit_blocks,
        document_fingerprint=audit_doc.document_fingerprint,
        audit_input_fingerprint=audit_doc.audit_input_fingerprint,
        warnings=list(audit_doc.warnings),
        combined_text=combined_text,
        parse_time=audit_doc.parse_time.isoformat(),
        identified_category=identified_category,
        category_confidence=category_confidence,
        product_name=audit_doc.product_name,
        product_name_source=audit_doc.product_name_source,
        coverage_attested=audit_doc.coverage_attested,
        is_rider=audit_doc.is_rider,
        group_or_individual=audit_doc.group_or_individual,
        duration_type=audit_doc.duration_type,
        design_type=audit_doc.design_type,
        naming_warnings=list(audit_doc.naming_warnings),
        product_tags=audit_doc.product_tags.to_dict(),
    )


async def _identify_category_async(combined_text: str, product_name: str) -> Tuple[Optional[str], float]:
    try:
        cr = await asyncio.to_thread(identify_category, combined_text, product_name)
        return cr.category, cr.confidence
    except Exception as e:
        logger.warning(f"险种识别失败: {e}")
        return None, 0.0


@router.post("/parse-file", response_model=ParsedDocumentResponse)
async def parse_file(file: UploadFile = File(...), user: dict = Depends(require_permission("compliance"))):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ComplianceConstants.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"仅支持 PDF、DOC 和 DOCX 格式，当前: {ext}")

    payload = await file.read(ComplianceConstants.MAX_PRODUCT_DOCUMENT_BYTES + 1)
    if len(payload) > ComplianceConstants.MAX_PRODUCT_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="产品条款文件超过25 MB上限")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        audit_doc = await asyncio.to_thread(
            parse_product_document,
            tmp_path,
            original_file_name=file.filename,
        )
        combined_text = audit_doc.canonical_text
        # 识别出的产品名优先，识别失败回退到文件名
        category_name = audit_doc.product_name or audit_doc.file_name
        category, confidence = await _identify_category_async(combined_text, category_name)
        return _audit_doc_to_response(
            audit_doc,
            ext,
            category,
            confidence,
            str(user.get("user_id", "")),
        )
    except DocumentParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Document parse failed: {e}")
        raise HTTPException(status_code=500, detail=f"文档解析失败: {e}")
    finally:
        os.unlink(tmp_path)


@router.post("/parse-rich-text", response_model=ParsedDocumentResponse)
async def parse_rich_text(req: RichTextParseRequest, user: dict = Depends(require_permission("compliance"))):
    if not req.html_content or not req.html_content.strip():
        raise HTTPException(status_code=400, detail="HTML 内容不能为空")
    if len(req.html_content) > ComplianceConstants.MAX_RICH_TEXT_CHARACTERS:
        raise HTTPException(status_code=413, detail="富文本产品条款超过字符上限")

    tmp_path = None
    try:
        tmp_path = await asyncio.to_thread(html_to_docx, req.html_content)
        audit_doc = await asyncio.to_thread(
            parse_product_document,
            tmp_path,
            original_file_name="rich-text.docx",
            user_product_name=req.product_name or None,
        )
        combined_text = audit_doc.canonical_text
        # 用户明确提交的名称优先；未提交时使用文档识别结果，最后回退到文件名。
        category_name = audit_doc.product_name or audit_doc.file_name
        category, confidence = await _identify_category_async(combined_text, category_name)
        response = _audit_doc_to_response(
            audit_doc,
            ".html",
            category,
            confidence,
            str(user.get("user_id", "")),
        )
        if req.product_name:
            response.file_name = req.product_name
        return response
    except DocumentParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Rich text parse failed: {e}")
        raise HTTPException(status_code=500, detail=f"富文本解析失败: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
