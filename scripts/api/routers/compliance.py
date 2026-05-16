"""合规检查路由 — 流式条款审查 + 文档解析。"""

import os
import uuid
import asyncio
import json
import logging
import tempfile
import threading
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sse_starlette.sse import EventSourceResponse

from api.database import get_connection, list_compliance_reports, get_compliance_report, save_compliance_report
from api.schemas.compliance import (
    DocumentCheckRequest, ComplianceReportResponse,
    ParsedDocumentResponse, ParsedClause, ParsedDataTable, ParsedSection,
    RichTextParseRequest,
)
from lib.common.constants import ComplianceConstants
from lib.common.html_converter import html_to_docx
from lib.compliance.checker import (
    streaming_compliance_check,
    streaming_negative_check,
    identify_category,
    load_audit_regulations,
    normalize_clause_number,
    extract_section_numbers,
)
from lib.doc_parser import parse_product_document, DocumentParseError
from lib.auth.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])


@router.post("/check/document/stream")
async def check_document_stream(req: DocumentCheckRequest, user: dict = Depends(require_permission("compliance"))):
    """流式合规检查，通过 SSE 实时推送违规条款。"""
    category: Optional[str] = req.category
    if not category:
        category, _ = await _identify_category_async(req.document_content, req.product_name or "")

    regulations = await asyncio.to_thread(load_audit_regulations, category)

    regulation_sources: Dict[str, List[str]] = {
        "险种专属": sorted(set(r.law_name for r in regulations if r.source_type == "category")),
        "通用法规": sorted(set(r.law_name for r in regulations if r.source_type == "general")),
    }

    async def event_stream():
        all_items: List[Dict] = []
        all_regulations = list(regulations)
        negative_list_result = "skipped"
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _producer():
            try:
                for event in streaming_compliance_check(req.document_content, regulations):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
                for event in streaming_negative_check(req.document_content):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "data": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=_producer, daemon=True)
        thread.start()

        while True:
            event = await queue.get()
            if event is None:
                break
            if event["type"] == "violation":
                all_items.append(event["data"])
            elif event["type"] == "negative_list_result":
                negative_list_result = event["data"]
                neg_regs = event.get("regulations", [])
                if neg_regs:
                    all_regulations.extend(neg_regs)
                    regulation_sources["负面清单"] = sorted(set(
                        r.get("law_name", "") for r in neg_regs if r.get("law_name")
                    ))
                continue
            yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

        # done: compute summary, coverage, save report
        report_id = f"cr_{uuid.uuid4().hex[:8]}"
        product_name = req.product_name or "未命名产品"
        summary = {"non_compliant": len(all_items), "compliant": 0, "attention": 0}

        section_info = extract_section_numbers(req.document_content)
        doc_clause_set = set(section_info["clauses"])
        flagged_clause_set = set()
        for item in all_items:
            cn = item.get("clause_number", "")
            if cn != "未知":
                normalized = normalize_clause_number(cn)
                if normalized:
                    flagged_clause_set.add(normalized)

        definition_chapter = section_info.get("definition_chapter")
        checked_clauses = doc_clause_set
        if definition_chapter:
            checked_clauses = {c for c in doc_clause_set if not c.startswith(definition_chapter + ".")}

        done_data = {
            "report_id": report_id,
            "product_name": product_name,
            "category": category or "",
            "summary": summary,
            "negative_list_result": negative_list_result,
            "regulation_sources": regulation_sources,
            "regulations": [r.__dict__ if hasattr(r, '__dict__') else r for r in all_regulations],
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
            "items": all_items,
            "regulations": [r.__dict__ if hasattr(r, '__dict__') else r for r in all_regulations],
            "regulation_sources": regulation_sources,
            "category": category or "",
            "negative_list_result": negative_list_result,
            "clause_coverage": done_data["clause_coverage"],
        }
        save_compliance_report(report_id, product_name, category or "", "document", result_for_db)

        yield {"event": "message", "data": json.dumps({"type": "done", "data": done_data}, ensure_ascii=False)}

    return EventSourceResponse(event_stream())


@router.get("/categories")
async def get_categories(user: dict = Depends(require_permission("compliance"))):
    return {"categories": ComplianceConstants.VALID_CATEGORIES}


@router.get("/reports", response_model=list[ComplianceReportResponse])
async def list_reports(user: dict = Depends(require_permission("compliance"))):
    return list_compliance_reports()


@router.get("/reports/{report_id}", response_model=ComplianceReportResponse)
async def get_report(report_id: str, user: dict = Depends(require_permission("compliance"))):
    report = get_compliance_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.delete("/reports/{report_id}")
async def delete_compliance_report(report_id: str, user: dict = Depends(require_permission("compliance"))):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM compliance_reports WHERE id = ?", (report_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="报告不存在")
    return {"status": "deleted"}


# --- Document parsing ---


def _build_combined_text(
    clauses: List[ParsedClause],
    data_tables: List[ParsedDataTable],
    notices: List[ParsedSection],
    health_disclosures: List[ParsedSection],
    exclusions: List[ParsedSection],
    rider_clauses: List[ParsedClause],
) -> str:
    parts = []
    for c in clauses:
        parts.append(f"【条款 {c.number}】{c.title}\n{c.text}")
    for i, t in enumerate(data_tables, 1):
        parts.append(f"【数据表 {i}】\n{t.raw_text}")
    for s in notices:
        parts.append(f"【投保须知】{s.title}\n{s.content}")
    for s in health_disclosures:
        parts.append(f"【健康告知】{s.title}\n{s.content}")
    for s in exclusions:
        parts.append(f"【责任免除】{s.title}\n{s.content}")
    for c in rider_clauses:
        parts.append(f"【附加险条款 {c.number}】{c.title}\n{c.text}")
    return "\n\n".join(parts)


def _audit_doc_to_response(audit_doc, file_type: str,
                           identified_category: Optional[str] = None,
                           category_confidence: float = 0.0,
                           combined_text: Optional[str] = None) -> ParsedDocumentResponse:
    clauses = [ParsedClause(number=c.number, title=c.title, text=c.text) for c in audit_doc.clauses]
    tables = [ParsedDataTable(
        table_type=t.table_type.value if hasattr(t.table_type, 'value') else str(t.table_type),
        remark=t.remark or "", raw_text=t.raw_text, data=[list(row) for row in t.data],
    ) for t in audit_doc.tables]
    notices = [ParsedSection(title=s.title, content=s.content) for s in audit_doc.notices]
    health = [ParsedSection(title=s.title, content=s.content) for s in audit_doc.health_disclosures]
    exclusions = [ParsedSection(title=s.title, content=s.content) for s in audit_doc.exclusions]
    riders = [ParsedClause(number=c.number, title=c.title, text=c.text) for c in audit_doc.rider_clauses]

    if combined_text is None:
        combined_text = _build_combined_text(clauses, tables, notices, health, exclusions, riders)

    return ParsedDocumentResponse(
        parse_id=f"pd_{uuid.uuid4().hex[:8]}",
        file_name=audit_doc.file_name,
        file_type=file_type,
        clauses=clauses, data_tables=tables, notices=notices,
        health_disclosures=health, exclusions=exclusions, rider_clauses=riders,
        warnings=list(audit_doc.warnings),
        combined_text=combined_text,
        parse_time=audit_doc.parse_time.isoformat(),
        identified_category=identified_category,
        category_confidence=category_confidence,
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
        raise HTTPException(status_code=400, detail=f"仅支持 PDF 和 DOCX 格式，当前: {ext}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        audit_doc = parse_product_document(tmp_path)
        combined_text = _build_combined_text(
            audit_doc.clauses, audit_doc.tables, audit_doc.notices,
            audit_doc.health_disclosures, audit_doc.exclusions, audit_doc.rider_clauses,
        )
        category, confidence = await _identify_category_async(combined_text, audit_doc.file_name)
        return _audit_doc_to_response(audit_doc, ext, category, confidence, combined_text)
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

    tmp_path = None
    try:
        tmp_path = html_to_docx(req.html_content)
        audit_doc = parse_product_document(tmp_path)
        combined_text = _build_combined_text(
            audit_doc.clauses, audit_doc.tables, audit_doc.notices,
            audit_doc.health_disclosures, audit_doc.exclusions, audit_doc.rider_clauses,
        )
        category, confidence = await _identify_category_async(combined_text, req.product_name or "")
        response = _audit_doc_to_response(audit_doc, ".html", category, confidence, combined_text)
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
