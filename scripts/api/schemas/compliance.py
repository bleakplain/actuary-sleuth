"""合规检查相关 schema"""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class AuditSourceOut(BaseModel):
    model_config = ConfigDict(extra='ignore')
    source_id: int = 0
    law_name: str = ""
    article_number: str = ""
    content: str = ""
    source_type: str = ""
    doc_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    effective_date: Optional[str] = None


class AuditItemOut(BaseModel):
    clause_number: str = ""
    check_type: str = ""
    param: str
    value: str = ""
    requirement: str = ""
    status: str
    source_id: Optional[int] = None
    source_type: str = ""
    source_excerpt: str = ""
    suggestion: str = ""


class ComplianceResultOut(BaseModel):
    model_config = ConfigDict(extra='ignore')
    summary: Dict[str, int] = {}
    items: List[AuditItemOut] = []
    sources: List[AuditSourceOut] = []
    regulation_sources: Dict[str, List[str]] = {}
    category: Optional[str] = ""
    negative_list_result: Optional[str] = ""


class ComplianceReportOut(BaseModel):
    id: str
    product_name: str
    category: str
    mode: str
    result: ComplianceResultOut
    created_at: str


class DocumentCheckRequest(BaseModel):
    document_content: str
    product_name: str = ""
    category: str = ""


class ParsedClause(BaseModel):
    number: str
    title: str
    text: str


class ParsedDataTable(BaseModel):
    table_type: str
    remark: str = ""
    raw_text: str = ""
    data: List[List[str]] = []


class ParsedSection(BaseModel):
    title: str
    content: str


class ParsedDocumentResponse(BaseModel):
    parse_id: str
    file_name: str
    file_type: str
    clauses: List[ParsedClause] = []
    data_tables: List[ParsedDataTable] = []
    notices: List[ParsedSection] = []
    health_disclosures: List[ParsedSection] = []
    exclusions: List[ParsedSection] = []
    rider_clauses: List[ParsedClause] = []
    warnings: List[str] = []
    combined_text: str = ""
    parse_time: str = ""
    identified_category: Optional[str] = None
    category_confidence: float = 0.0


class RichTextParseRequest(BaseModel):
    html_content: str
    product_name: str = ""
