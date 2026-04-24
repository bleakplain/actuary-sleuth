"""合规检查路由 — 条款文档审查 + 文档解析。"""

import os
import uuid
import asyncio
import logging
import tempfile
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File

from api.database import get_connection, list_compliance_reports, get_compliance_report, save_compliance_report
from api.schemas.compliance import (
    DocumentCheckRequest, ComplianceReportOut,
    ParsedDocumentResponse, ParsedClause, ParsedPremiumTable, ParsedSection,
    RichTextParseRequest, CategoryIdentifyRequest, CategoryIdentifyResponse,
)
from lib.common.constants import ComplianceConstants
from lib.compliance.checker import (
    check_negative_list,
    identify_category,
    build_enhanced_context,
    run_compliance_check,
)
from lib.compliance.prompts import COMPLIANCE_PROMPT_DOCUMENT
from lib.doc_parser import parse_product_document, DocumentParseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])


@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    # 险种识别（如果未提供）
    category = req.category
    if not category:
        category, _, _ = identify_category(req.document_content, req.product_name or "")

    # 构建增强的法规上下文（两层检索）
    context, sources_info = build_enhanced_context(category=category)

    prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
        document_content=req.document_content[:3000],
        context=context[:8000],
    )

    try:
        result = await asyncio.to_thread(run_compliance_check, prompt)
    except Exception as e:
        logger.error(f"Document check failed: {e}")
        raise HTTPException(status_code=500, detail=f"条款审查失败: {e}")

    # 执行负面清单检查
    negative_items = check_negative_list(req.document_content)

    # 合并结果
    result["regulation_sources"] = sources_info
    result["category"] = category

    if negative_items:
        result["items"].extend(negative_items)
        result["summary"]["non_compliant"] = result["summary"].get("non_compliant", 0) + len(negative_items)
        result["regulation_sources"]["负面清单"] = [item["param"] for item in negative_items]

    result["negative_list_checked"] = True

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    product_name = req.product_name or "未命名产品"
    save_compliance_report(report_id, product_name, category or "", "document", result)

    return ComplianceReportOut(
        id=report_id,
        product_name=product_name,
        category=category or "",
        mode="document",
        result=result,
        created_at="",
    )


@router.post("/identify-category", response_model=CategoryIdentifyResponse)
async def identify_category_endpoint(req: CategoryIdentifyRequest):
    """识别险种类型"""
    category, confidence, method = identify_category(
        req.document_content,
        req.product_name or "",
    )

    suggested = []
    if category:
        suggested.append(category)
    suggested.extend(ComplianceConstants.VALID_CATEGORIES[:5])
    suggested = list(dict.fromkeys(suggested))[:5]

    return CategoryIdentifyResponse(
        category=category,
        confidence=confidence,
        method=method,
        suggested_categories=suggested,
    )


@router.get("/reports", response_model=list[ComplianceReportOut])
async def list_reports():
    return list_compliance_reports()


@router.get("/reports/{report_id}", response_model=ComplianceReportOut)
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
    premium_tables: List[ParsedPremiumTable],
    notices: List[ParsedSection],
    health_disclosures: List[ParsedSection],
    exclusions: List[ParsedSection],
    rider_clauses: List[ParsedClause],
) -> str:
    """将解析结果合并为文本，用于合规检查"""
    parts = []
    for c in clauses:
        parts.append(f"【条款 {c.number}】{c.title}\n{c.text}")
    for i, t in enumerate(premium_tables, 1):
        parts.append(f"【费率表 {i}】\n{t.raw_text}")
    for s in notices:
        parts.append(f"【投保须知】{s.title}\n{s.content}")
    for s in health_disclosures:
        parts.append(f"【健康告知】{s.title}\n{s.content}")
    for s in exclusions:
        parts.append(f"【责任免除】{s.title}\n{s.content}")
    for c in rider_clauses:
        parts.append(f"【附加险条款 {c.number}】{c.title}\n{c.text}")
    return "\n\n".join(parts)


def _audit_doc_to_response(audit_doc, file_type: str) -> ParsedDocumentResponse:
    """将 AuditDocument 转换为 ParsedDocumentResponse"""
    clauses = [
        ParsedClause(number=c.number, title=c.title, text=c.text)
        for c in audit_doc.clauses
    ]
    premium_tables = [
        ParsedPremiumTable(raw_text=t.raw_text, data=[list(row) for row in t.data])
        for t in audit_doc.premium_tables
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

    combined_text = _build_combined_text(
        clauses, premium_tables, notices, health_disclosures, exclusions, rider_clauses
    )

    return ParsedDocumentResponse(
        parse_id=f"pd_{uuid.uuid4().hex[:8]}",
        file_name=audit_doc.file_name,
        file_type=file_type,
        clauses=clauses,
        premium_tables=premium_tables,
        notices=notices,
        health_disclosures=health_disclosures,
        exclusions=exclusions,
        rider_clauses=rider_clauses,
        warnings=list(audit_doc.warnings),
        combined_text=combined_text,
        parse_time=audit_doc.parse_time.isoformat(),
    )


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
        return _audit_doc_to_response(audit_doc, ext)
    except DocumentParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Document parse failed: {e}")
        raise HTTPException(status_code=500, detail=f"文档解析失败: {e}")
    finally:
        os.unlink(tmp_path)


def _html_to_docx(html_content: str) -> str:
    """将 HTML 转换为临时 DOCX 文件，返回文件路径"""
    from docx import Document
    from html.parser import HTMLParser

    class SimpleHTMLParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.paragraphs = []
            self.tables = []
            self.current_table = []
            self.current_row = []
            self.current_cell = ""
            self.in_table = False
            self.in_row = False
            self.in_cell = False
            self.current_text = ""
            self.in_p = False

        def handle_starttag(self, tag, attrs):
            if tag == 'p':
                self.in_p = True
                self.current_text = ""
            elif tag == 'table':
                self.in_table = True
                self.current_table = []
            elif tag == 'tr':
                self.in_row = True
                self.current_row = []
            elif tag in ['td', 'th']:
                self.in_cell = True
                self.current_cell = ""
            elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                self.in_p = True
                self.current_text = ""

        def handle_endtag(self, tag):
            if tag == 'p' and self.in_p:
                self.in_p = False
                text = self.current_text.strip()
                if text:
                    self.paragraphs.append(text)
            elif tag == 'table':
                self.in_table = False
                if self.current_table:
                    self.tables.append(self.current_table)
                self.current_table = []
            elif tag == 'tr':
                self.in_row = False
                if self.current_row:
                    self.current_table.append(self.current_row)
                self.current_row = []
            elif tag in ['td', 'th']:
                self.in_cell = False
                self.current_row.append(self.current_cell.strip())
            elif tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                self.in_p = False
                text = self.current_text.strip()
                if text:
                    self.paragraphs.append(text)

        def handle_data(self, data):
            if self.in_p:
                self.current_text += data
            elif self.in_cell:
                self.current_cell += data

    parser = SimpleHTMLParser()
    parser.feed(html_content)

    doc = Document()

    for p in parser.paragraphs:
        doc.add_paragraph(p)

    for table_data in parser.tables:
        if not table_data or not table_data[0]:
            continue
        num_cols = max(len(row) for row in table_data)
        table = doc.add_table(rows=len(table_data), cols=num_cols)
        table.style = 'Table Grid'
        for i, row in enumerate(table_data):
            for j, cell in enumerate(row):
                if j < num_cols:
                    table.rows[i].cells[j].text = cell

    # 使用安全的临时文件创建
    fd, tmp_path = tempfile.mkstemp(suffix='.docx')
    os.close(fd)  # 关闭文件描述符，让 doc.save 使用路径
    doc.save(tmp_path)
    return tmp_path


@router.post("/parse-rich-text", response_model=ParsedDocumentResponse)
async def parse_rich_text(req: RichTextParseRequest):
    """解析富文本内容（HTML）"""
    if not req.html_content or not req.html_content.strip():
        raise HTTPException(status_code=400, detail="HTML 内容不能为空")

    tmp_path = None
    try:
        tmp_path = _html_to_docx(req.html_content)
        audit_doc = parse_product_document(tmp_path)
        response = _audit_doc_to_response(audit_doc, ".html")
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
