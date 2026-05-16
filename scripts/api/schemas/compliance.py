"""合规检查相关 schema"""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class AuditRegulationItemResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    chunk_id: str = ""
    law_name: str = ""
    article_number: str = ""
    content: str = ""
    source_type: str = ""
    doc_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    effective_date: Optional[str] = None


class AuditResultItemResponse(BaseModel):
    clause_number: str = ""
    check_type: str = ""
    clause_content: str = ""
    status: str
    chunk_id: Optional[str] = None
    suggestion: str = ""
    conclusion: str = ""


class ComplianceReportDataResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    summary: Dict[str, int] = {}
    items: List[AuditResultItemResponse] = []
    regulations: List[AuditRegulationItemResponse] = []
    regulation_sources: Dict[str, List[str]] = {}
    category: Optional[str] = ""
    negative_list_result: Optional[str] = ""
    clause_coverage: Optional[Dict] = None


class ComplianceReportResponse(BaseModel):
    id: str
    product_name: str
    category: str
    mode: str
    result: ComplianceReportDataResponse
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
