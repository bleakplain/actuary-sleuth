from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class ProductCheckRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="产品名称")
    category: str = Field(..., min_length=1, description="险种类型")
    params: Dict[str, object] = Field(..., description="产品参数键值对")


class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
    parse_id: Optional[str] = Field(None, description="解析结果ID，用于遗漏检测")


class ComplianceItem(BaseModel):
    clause_number: str = ""
    param: str
    value: Optional[object] = None
    requirement: str = ""
    status: str = Field(..., pattern="^(compliant|non_compliant|attention)$")
    source: Optional[str] = None
    source_excerpt: Optional[str] = None
    suggestion: Optional[str] = None


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


class RichTextParseRequest(BaseModel):
    html_content: str = Field(..., min_length=1, description="富文本 HTML 内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")
