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
    product_info: Dict[str, Any]
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
            product_info={},
            clauses=[],
            pricing_params={},
            violations=[],
            pricing_analysis={}
        )


@dataclass(frozen=True)
class EvaluationResult:
    """
    评估计算结果 (Immutable)

    存储从 AuditData 计算得出的所有结果。

    职责：
    - 存储计算结果（分数、评级、摘要）
    - 存储结构化数据（产品对象、分组违规项）
    - 作为导出模块的数据源

    设计原则：
    - frozen=True 确保创建后不可修改
    - 从 AuditData 计算得出，计算逻辑在 calculate_evaluation()
    - 包含所有导出需要的数据，避免后续再计算
    """
    # 输入数据引用 (用于验证和追溯)
    violations: List[Dict[str, Any]]
    pricing_analysis: Dict[str, Any]

    # 计算结果
    score: int
    grade: str
    summary: Dict[str, Any]

    # 结构化数据
    product: '_InsuranceProduct'

    # 衍生数据 (预分组，避免重复计算)
    high_violations: List[Dict[str, Any]]
    medium_violations: List[Dict[str, Any]]
    low_violations: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于向后兼容）"""
        return {
            'violations': self.violations,
            'pricing_analysis': self.pricing_analysis,
            'product_info': {
                'product_name': self.product.name,
                'product_type': self.product.type,
                'insurance_company': self.product.company,
                'version': self.product.version,
                'document_url': self.product.document_url
            },
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


# 导入 _InsuranceProduct (避免循环导入)
from lib.reporting.model import _InsuranceProduct
