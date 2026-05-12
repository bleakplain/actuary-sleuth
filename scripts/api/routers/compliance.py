"""合规检查路由 — 条款文档审查 + 文档解析。"""

import os
import uuid
import asyncio
import logging
import tempfile
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, UploadFile, File

from api.database import get_connection, list_compliance_reports, get_compliance_report, save_compliance_report
from api.schemas.compliance import (
    DocumentCheckRequest, ComplianceReportResponse,
    ParsedDocumentResponse, ParsedClause, ParsedDataTable, ParsedSection,
    RichTextParseRequest,
)
from lib.common.constants import ComplianceConstants
from lib.common.html_converter import html_to_docx
from lib.compliance.checker import (
    check_negative_list,
    identify_category,
    load_audit_regulations,
    batch_compliance_check,
    extract_section_numbers,
)
from lib.doc_parser import parse_product_document, DocumentParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])


@router.post("/check/document", response_model=ComplianceReportResponse)
async def check_document(req: DocumentCheckRequest):
    category: Optional[str] = req.category
    if not category:
        category, _ = await _identify_category_async(req.document_content, req.product_name or "")

    regulations = await asyncio.to_thread(load_audit_regulations, category)

    regulation_sources: Dict[str, List[str]] = {
        "险种专属": [r.law_name for r in regulations if r.source_type == "category"],
        "通用法规": [r.law_name for r in regulations if r.source_type == "general"],
    }

    try:
        result = await asyncio.to_thread(
            batch_compliance_check, req.document_content, regulations
        )
    except Exception as e:
        logger.error(f"Document check failed: {e}")
        raise HTTPException(status_code=500, detail=f"条款审查失败: {e}")

    if "error" in result:
        logger.error(f"Compliance check returned error: {result['error']}")
        raise HTTPException(status_code=500, detail="审查结果解析失败，请重试")

    try:
        negative_items, negative_list_result, negative_regulations = await asyncio.to_thread(
            check_negative_list, req.document_content
        )
    except Exception as e:
        logger.error(f"Negative list check failed: {e}")
        negative_items, negative_list_result, negative_regulations = [], "skipped", []

    all_regulations = regulations + negative_regulations
    result["regulations"] = [r.__dict__ for r in all_regulations]
    result["regulation_sources"] = regulation_sources
    result["category"] = category

    if negative_items:
        result["items"].extend([item.__dict__ for item in negative_items])
    if negative_regulations:
        result["regulation_sources"]["负面清单"] = [r.law_name for r in negative_regulations]

    result["summary"] = {
        "compliant": sum(1 for i in result.get("items", []) if i.get("status") == "compliant"),
        "non_compliant": sum(1 for i in result.get("items", []) if i.get("status") == "non_compliant"),
        "attention": sum(1 for i in result.get("items", []) if i.get("status") == "attention"),
    }

    result["negative_list_result"] = negative_list_result

    section_info = extract_section_numbers(req.document_content)
    doc_clause_set = set(section_info["clauses"])
    checked_clause_set = {
        c for item in result.get("items", [])
        if (c := item.get("clause_number", "")) != "未知"
    }
    result["clause_coverage"] = {
        "total": len(doc_clause_set),
        "checked": len(checked_clause_set & doc_clause_set),
        "unchecked": list(doc_clause_set - checked_clause_set),
        "has_notices": section_info["has_notices"],
        "has_health": section_info["has_health"],
        "has_exclusions": section_info["has_exclusions"],
        "has_tables": section_info["has_tables"],
    }

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    product_name = req.product_name or "未命名产品"
    save_compliance_report(report_id, product_name, category or "", "document", result)

    return ComplianceReportResponse(
        id=report_id,
        product_name=product_name,
        category=category or "",
        mode="document",
        result=result,
        created_at="",
    )


@router.get("/categories")
async def get_categories():
    """获取有效的险种类型列表"""
    return {"categories": ComplianceConstants.VALID_CATEGORIES}


@router.get("/reports", response_model=list[ComplianceReportResponse])
async def list_reports():
    return list_compliance_reports()


@router.get("/reports/{report_id}", response_model=ComplianceReportResponse)
async def get_report(report_id: str):
    report = get_compliance_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.delete("/reports/{report_id}")
async def delete_compliance_report(report_id: str):
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM compliance_reports WHERE id = ?", (report_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="报告不存在")
    return {"status": "deleted"}


def _build_combined_text(
    clauses: List[ParsedClause],
    data_tables: List[ParsedDataTable],
    notices: List[ParsedSection],
    health_disclosures: List[ParsedSection],
    exclusions: List[ParsedSection],
    rider_clauses: List[ParsedClause],
) -> str:
    """将解析结果合并为文本，用于合规检查"""
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
    """将 AuditDocument 转换为 ParsedDocumentResponse

    combined_text: 如已预计算则传入避免重复构建
    """
    clauses = [
        ParsedClause(number=c.number, title=c.title, text=c.text)
        for c in audit_doc.clauses
    ]
    tables = [
        ParsedDataTable(
            table_type=t.table_type.value if hasattr(t.table_type, 'value') else str(t.table_type),
            remark=t.remark or "",
            raw_text=t.raw_text,
            data=[list(row) for row in t.data]
        )
        for t in audit_doc.tables
    ]
    notices = [
        ParsedSection(title=s.title, content=s.content)
        for s in audit_doc.notices
    ]
    health_disclosures = [
        ParsedSection(title=s.title, content=s.content)
        for s in audit_doc.health_disclosures
    ]
    exclusions = [
        ParsedSection(title=s.title, content=s.content)
        for s in audit_doc.exclusions
    ]
    rider_clauses = [
        ParsedClause(number=c.number, title=c.title, text=c.text)
        for c in audit_doc.rider_clauses
    ]

    if combined_text is None:
        combined_text = _build_combined_text(
            clauses, tables, notices, health_disclosures, exclusions, rider_clauses
        )

    return ParsedDocumentResponse(
        parse_id=f"pd_{uuid.uuid4().hex[:8]}",
        file_name=audit_doc.file_name,
        file_type=file_type,
        clauses=clauses,
        data_tables=tables,
        notices=notices,
        health_disclosures=health_disclosures,
        exclusions=exclusions,
        rider_clauses=rider_clauses,
        warnings=list(audit_doc.warnings),
        combined_text=combined_text,
        parse_time=audit_doc.parse_time.isoformat(),
        identified_category=identified_category,
        category_confidence=category_confidence,
    )


async def _identify_category_async(combined_text: str, product_name: str) -> Tuple[Optional[str], float]:
    """异步执行险种识别，失败时返回 None"""
    try:
        cr = await asyncio.to_thread(
            identify_category, combined_text, product_name
        )
        return cr.category, cr.confidence
    except Exception as e:
        logger.warning(f"险种识别失败: {e}")
        return None, 0.0


@router.post("/parse-file", response_model=ParsedDocumentResponse)
async def parse_file(file: UploadFile = File(...)):
    """上传并解析保险产品文档（PDF/DOCX）"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ComplianceConstants.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"仅支持 PDF 和 DOCX 格式，当前: {ext}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        audit_doc = parse_product_document(tmp_path)
        combined_text = _build_combined_text(
            audit_doc.clauses, audit_doc.tables, audit_doc.notices,
            audit_doc.health_disclosures, audit_doc.exclusions, audit_doc.rider_clauses
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
async def parse_rich_text(req: RichTextParseRequest):
    """解析富文本内容（HTML）"""
    if not req.html_content or not req.html_content.strip():
        raise HTTPException(status_code=400, detail="HTML 内容不能为空")

    tmp_path = None
    try:
        tmp_path = html_to_docx(req.html_content)
        audit_doc = parse_product_document(tmp_path)
        combined_text = _build_combined_text(
            audit_doc.clauses, audit_doc.tables, audit_doc.notices,
            audit_doc.health_disclosures, audit_doc.exclusions, audit_doc.rider_clauses
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
