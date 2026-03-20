#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审核数据模型 (解耦版本)

设计原则：
1. 单向数据流：AuditData → EvaluationResult → Export
2. 不可变数据：使用 frozen dataclass 确保数据不被修改
3. 职责分离：原始数据、计算结果、导出准备各司其职
4. 显式依赖：通过函数参数明确数据来源
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime

from lib.common.models import Product, ProductCategory

__all__ = ['AuditData', 'EvaluationResult']


@dataclass(frozen=True)
class AuditData:
    """
    审核原始数据 (Immutable)

    存储审核流程中收集的原始数据，不做任何计算或转换。

    职责：
    - 存储从外部获取的原始信息（产品信息、条款、定价参数）
    - 存储检查和分析结果（违规项、定价分析）
    - 作为不可变数据源，供后续计算使用

    设计原则：
    - frozen=True 确保创建后不可修改
    - 所有字段都是简单的数据结构
    - 不包含任何计算结果
    """
    # 元数据
    audit_id: str
    document_url: str
    timestamp: datetime

    # 预处理数据
    product: Product
    clauses: List[Dict[str, Any]]
    pricing_params: Dict[str, Any]

    # 检查结果
    violations: List[Dict[str, Any]]

    # 分析结果
    pricing_analysis: Dict[str, Any]

    @classmethod
    def create(cls, audit_id: str, document_url: str) -> 'AuditData':
        """创建空的 AuditData 对象"""
        return cls(
            audit_id=audit_id,
            document_url=document_url,
            timestamp=datetime.now(),
            product=Product(name="", company="", category=ProductCategory.OTHER, period=""),
            clauses=[],
            pricing_params={},
            violations=[],
            pricing_analysis={}
        )


@dataclass(frozen=True)
class EvaluationResult:
    """
    评估计算结果 (Immutable)

    存储从 AuditData 计算得出的所有结果，是审核流程的完整输出。

    职责：
    - 存储计算结果（分数、评级、摘要）
    - 存储结构化数据（产品对象、分组违规项）
    - 存储所有导出需要的数据（clauses、product、metadata）
    - 作为唯一的导出数据源，API 响应和报告生成都应从此获取数据

    设计原则：
    - frozen=True 确保创建后不可修改
    - 从 AuditData 计算得出，计算逻辑在 calculate_evaluation()
    - 包含所有导出需要的数据，实现真正的单向数据流
    - 不应再依赖 AuditData 获取任何信息

    数据流：AuditData → EvaluationResult → Export/API
    """
    # === 计算结果 ===
    score: int
    grade: str
    summary: Dict[str, Any]

    # === 违规数据 ===
    violations: List[Dict[str, Any]]
    high_violations: List[Dict[str, Any]]
    medium_violations: List[Dict[str, Any]]
    low_violations: List[Dict[str, Any]]
    pricing_analysis: Dict[str, Any]

    # === 条款数据 ===
    clauses: List[Dict[str, Any]]

    # === 产品信息 ===
    product: Product

    # === 元数据 ===
    audit_id: str
    document_url: str
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为 API 响应格式

        这是构建 API 响应的唯一数据源，不应再从 AuditData 获取任何数据。
        """
        return {
            'violations': self.violations,
            'violation_count': len(self.violations),
            'violation_summary': {
                'high': len(self.high_violations),
                'medium': len(self.medium_violations),
                'low': len(self.low_violations)
            },
            'pricing_analysis': self.pricing_analysis,
            'score': self.score,
            'grade': self.grade,
            'summary': self.summary,
            'clauses': self.clauses,
            'product_info': {
                'product_name': self.product.name,
                'product_type': self.product.type,
                'insurance_company': self.product.company,
                'document_url': self.product.document_url,
                'version': self.product.version,
            },
            'audit_id': self.audit_id,
            'document_url': self.document_url,
            'timestamp': self.timestamp.isoformat(),
        }

    def to_export_dict(self) -> Dict[str, Any]:
        """
        转换为导出格式

        包含报告生成所需的所有数据。
        """
        return {
            'violations': self.violations,
            'high_violations': self.high_violations,
            'medium_violations': self.medium_violations,
            'low_violations': self.low_violations,
            'pricing_analysis': self.pricing_analysis,
            'clauses': self.clauses,
            'product': self.product,
            'score': self.score,
            'grade': self.grade,
            'summary': self.summary,
        }

    @property
    def has_issues(self) -> bool:
        """是否有违规问题"""
        return len(self.violations) > 0

    @property
    def has_critical_issues(self) -> bool:
        """是否有严重问题"""
        return len(self.high_violations) > 0

    @property
    def total_violations(self) -> int:
        """违规总数"""
        return len(self.violations)

    @property
    def preprocess_id(self) -> str:
        """预处理 ID"""
        return f"PRE-{self.audit_id.split('-')[1]}"
