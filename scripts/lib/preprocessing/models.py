#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型

文档预处理系统的核心数据结构。

包含两类模型：
1. 产品文档预处理：DocumentProfile, ExtractResult 等
2. 法规文档预处理：RegulationRecord, RegulationStatus 等
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional


@dataclass
class DocumentProfile:
    """文档画像：用于路由决策的文档特征"""
    is_structured: bool          # 有章节结构（章节数≥5）
    has_clause_numbers: bool     # 有条款编号（第X条）
    has_premium_table: bool      # 包含费率表特征


@dataclass
class StructureMarkers:
    """结构标记"""
    clause_positions: List[int] = field(default_factory=list)
    table_positions: List[int] = field(default_factory=list)
    section_positions: List[int] = field(default_factory=list)


@dataclass
class NormalizedDocument:
    """规范化文档"""
    content: str
    profile: DocumentProfile
    structure_markers: StructureMarkers
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractResult:
    """提取结果"""
    data: Dict[str, Any]
    confidence: Dict[str, float]
    provenance: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_field(self, key: str, default=None):
        """获取字段值"""
        return self.data.get(key, default)

    def get_provenance(self, key: str) -> str:
        """获取字段来源"""
        return self.provenance.get(key, 'unknown')


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: int = 0  # 0-100


@dataclass
class ProductType:
    """产品类型定义"""
    code: str
    name: str
    patterns: List[str]
    features: Dict[str, float]
    required_fields: List[str]

    def match_score(self, document: str) -> float:
        """计算匹配分数"""
        import re
        score = 0.0

        # 关键词匹配
        for pattern in self.patterns:
            if re.search(pattern, document):
                score += 1.0 / len(self.patterns)

        # 特征匹配
        for feature, weight in self.features.items():
            if self._has_feature(document, feature):
                score += weight

        return min(score, 1.0)

    def _has_feature(self, document: str, feature: str) -> bool:
        """检测特征"""
        import re
        feature_map = {
            'diseases_list': r'(恶性肿瘤|急性心肌梗死|脑中风后遗症|重疾)',
            'grading': r'(轻症|中症|重症)',
            'waiting_period': r'等待期.*?\d+.*?[天日]',
            'account': r'(保单账户|结算利率|追加保费)',
            'deductible': r'(免赔额|起付线)',
            'payout_ratio': r'(赔付比例|给付比例)',
            'insurance_period': r'(保险期间|保障期限)',
            'cash_value': r'(现金价值|退保金)',
        }

        pattern = feature_map.get(feature, feature)
        return bool(re.search(pattern, document))


@dataclass
class ExtractionRequest:
    """提取请求"""
    document: str
    source_type: str = 'text'
    required_fields: Optional[List[str]] = None


@dataclass
class ExtractionResponse:
    """提取响应"""
    result: Dict[str, Any]
    metadata: Dict[str, Any]


# ==================== 法规文档预处理模型 ====================

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
class RegulationProcessingOutcome:
    """法规处理结果"""
    success: bool
    regulation_id: str
    record: RegulationRecord
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processed_at: datetime = field(default_factory=datetime.now)
    processor: str = ""  # 处理器标识，如 "regulation_cleaner" 或 "regulation_extractor"


@dataclass
class RegulationDocument:
    """法规文档"""
    content: str
    source_file: str
    record: RegulationRecord

