# scripts/lib/common/models.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class RegulationStatus(str, Enum):
    """法规处理状态"""
    RAW = "raw"                      # 原始文档
    CLEANED = "cleaned"              # 已清洗
    EXTRACTED = "extracted"          # 已提取结构化信息
    AUDITED = "audited"              # 已审核
    FAILED = "failed"                # 处理失败


class RegulationLevel(str, Enum):
    """法规层级"""
    LAW = "law"                                  # 法律
    DEPARTMENT_RULE = "department_rule"          # 部门规章
    NORMATIVE = "normative"                      # 规范性文件
    OTHER = "other"                              # 其他


@dataclass
class RegulationRecord:
    """法规基本信息记录"""
    law_name: str
    article_number: str
    category: str
    effective_date: Optional[str] = None
    hierarchy_level: Optional[RegulationLevel] = None
    issuing_authority: Optional[str] = None
    status: RegulationStatus = RegulationStatus.RAW
    quality_score: Optional[float] = None


@dataclass
class ProcessingOutcome:
    """处理结果"""
    success: bool
    regulation_id: str
    record: RegulationRecord
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processed_at: datetime = field(default_factory=datetime.now)
    processor: str = ""  # 处理器标识，如 "preprocessing" 或 "audit"


@dataclass
class RegulationDocument:
    """法规文档"""
    content: str
    source_file: str
    record: RegulationRecord
