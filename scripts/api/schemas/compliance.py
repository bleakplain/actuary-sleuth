from typing import Optional, Dict
from pydantic import BaseModel, Field


class ProductCheckRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="产品名称")
    category: str = Field(..., min_length=1, description="险种类型")
    params: Dict[str, object] = Field(..., description="产品参数键值对")


class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")


class ComplianceItem(BaseModel):
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
