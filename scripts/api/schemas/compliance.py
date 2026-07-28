"""合规检查相关 schema"""
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


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
    applicability_status: str = ""
    matched_dimensions: List[str] = Field(default_factory=list)
    matched_topics: List[str] = Field(default_factory=list)
    fallback_layer: str = ""
    retrieval_sources: List[str] = Field(default_factory=list)


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
    retrieval_degraded: bool = False
    retrieval_warnings: List[str] = Field(default_factory=list)
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
    clause_topics: List[str] = Field(default_factory=list)


class ParsedClause(BaseModel):
    number: str
    title: str
    text: str
    topics: List[str] = Field(default_factory=list)


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
    # 产品名识别结果（从文档正文提取，区别于 file_name）
    product_name: Optional[str] = None
    is_rider: bool = False
    # 结构化标签维度（供前端展示与后续标签化法规筛选）
    group_or_individual: Optional[str] = None
    duration_type: Optional[str] = None
    design_type: Optional[str] = None
    naming_warnings: List[str] = []
    product_tags: Dict = Field(default_factory=dict)


class RichTextParseRequest(BaseModel):
    html_content: str
    product_name: str = ""
