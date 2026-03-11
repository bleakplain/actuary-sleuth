#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型

文档预处理系统的核心数据结构。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class FormatInfo:
    """格式信息"""
    is_table_dense: bool
    is_structured: bool
    has_clause_numbers: bool
    has_premium_table: bool
    table_density: float
    section_count: int


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
    format_info: FormatInfo
    structure_markers: StructureMarkers
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionRoute:
    """提取路由决策"""
    mode: str  # 'fast' | 'structured'
    product_type: str
    confidence: float
    is_hybrid: bool
    reason: str


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
class StructureInfo:
    """结构信息"""
    has_premium_table: bool
    has_clauses: bool
    sections: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict) -> 'StructureInfo':
        """从字典创建"""
        return cls(
            has_premium_table=data.get('has_premium_table', False),
            has_clauses=data.get('has_clauses', False),
            sections=data.get('sections', [])
        )


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
