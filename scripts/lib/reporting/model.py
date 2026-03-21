#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估数据模型

定义用于评估过程的数据载体，在模板编排的各步骤之间传递数据

统一数据模型：使用新的审核模型 (lib.common.audit.EvaluationResult)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from lib.common.models import Product, ProductCategory

__all__ = ['EvaluationContext']


@dataclass
class EvaluationContext:
    """
    评估上下文

    承载审核评估过程中的所有数据，在模板编排的各步骤之间传递

    统一数据模型设计：
    - 直接使用新审核模型的各个字段
    - 不再依赖 lib.audit.AuditResult
    """
    # 产品信息
    product: Product = field(default_factory=lambda: Product(
        name="",
        company="",
        category=ProductCategory.OTHER,
        period=""
    ))

    # 审核数据
    violations: List[Dict[str, Any]] = field(default_factory=list)
    clauses: List[Dict[str, Any]] = field(default_factory=list)
    pricing_analysis: Dict[str, Any] = field(default_factory=dict)

    # 评估结果
    score: int = 0
    grade: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None

    # 分组后的违规列表（便于报告生成）
    high_violations: List[Dict[str, Any]] = field(default_factory=list)
    medium_violations: List[Dict[str, Any]] = field(default_factory=list)
    low_violations: List[Dict[str, Any]] = field(default_factory=list)

    # 法规依据
    regulation_basis: List[str] = field(default_factory=list)

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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
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
            'summary': self.summary or {},
        }

    @classmethod
    def from_evaluation_result(
        cls,
        result: 'EvaluationResult',
        regulation_basis: List[str] = None
    ) -> 'EvaluationContext':
        """
        从新的 EvaluationResult 创建 EvaluationContext

        Args:
            result: lib.common.audit.EvaluationResult 实例
            regulation_basis: 法规依据列表（可选）

        Returns:
            EvaluationContext 实例
        """
        from lib.common.audit import (
            get_violations,
            get_product,
            get_clauses,
            get_pricing_analysis
        )

        violations = get_violations(result)
        product = get_product(result)
        clauses = get_clauses(result)
        pricing_analysis = get_pricing_analysis(result)

        # 分组违规
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']
        low_violations = [v for v in violations if v.get('severity') == 'low']

        return cls(
            product=product,
            violations=violations,
            clauses=clauses,
            pricing_analysis=pricing_analysis,
            score=result.score,
            grade=result.grade,
            summary=result.summary,
            high_violations=high_violations,
            medium_violations=medium_violations,
            low_violations=low_violations,
            regulation_basis=regulation_basis or []
        )

    @classmethod
    def from_product(cls, product: Product) -> 'EvaluationContext':
        """从产品创建上下文"""
        return cls(product=product)
