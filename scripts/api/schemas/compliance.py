from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
    category: Optional[str] = Field(None, description="险种类型（可选，LLM自动识别或用户选择）")


class ComplianceReportOut(BaseModel):
    id: str
    product_name: str
    category: str
    mode: str
    result: Dict[str, object]
    created_at: str


class ParsedClause(BaseModel):
    number: str = ""
    title: str = ""
    text: str = ""


class ParsedPremiumTable(BaseModel):
    table_type: str = "unknown"  # premium, appendix, coverage, drug_list, gene_test, hospital, other
    remark: str = ""
    raw_text: str = ""
    data: List[List[str]] = []


class ParsedSection(BaseModel):
    title: str = ""
    content: str = ""


class ParsedDocumentResponse(BaseModel):
    parse_id: str
    file_name: str = ""
    file_type: str = ""
    clauses: List[ParsedClause] = []
    premium_tables: List[ParsedPremiumTable] = []
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
    html_content: str = Field(..., min_length=1, description="富文本 HTML 内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
