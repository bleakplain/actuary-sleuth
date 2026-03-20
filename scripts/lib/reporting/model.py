#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估数据模型

定义用于评估过程的数据载体，在模板编排的各步骤之间传递数据

统一数据模型：使用 AuditResult 作为单一数据源，使用 common.Product
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.audit import AuditResult, AuditIssue

from lib.common.models import Product as CommonProduct, ProductCategory, Product
from lib.common.product_type import get_category, get_name

__all__ = ['EvaluationContext', 'Product']

# 向后兼容：Product 别名
Product = Product


@dataclass
class EvaluationContext:
    """
    评估上下文

    承载审核评估过程中的所有数据，在模板编排的各步骤之间传递

    统一数据模型设计：
    - 使用 AuditResult 作为单一数据源（audit 模块输出）
    - violations 从 audit_result.issues 转换而来
    """
    audit_result: Optional['AuditResult'] = None
    product: Product = field(default_factory=lambda: Product(
        name="",
        company="",
        category=ProductCategory.OTHER,
        period=""
    ))
    pricing_analysis: Dict[str, Any] = field(default_factory=dict)
    clauses: List[Dict[str, Any]] = field(default_factory=list)
    grade: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    high_violations: List[Dict[str, Any]] = field(default_factory=list)
    medium_violations: List[Dict[str, Any]] = field(default_factory=list)
    low_violations: List[Dict[str, Any]] = field(default_factory=list)
    regulation_basis: List[str] = field(default_factory=list)
    _violations_cache: Optional[List[Dict[str, Any]]] = None

    @property
    def score(self) -> int:
        """获取评分（从 audit_result）"""
        if self.audit_result:
            return self.audit_result.score
        return 0

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """
        获取违规列表（从 audit_result.issues 转换，带缓存）
        """
        if not self.audit_result:
            return []

        if self._violations_cache is not None:
            return self._violations_cache

        self._violations_cache = [
            {
                'clause_reference': issue.clause,
                'clause_text': issue.clause,
                'description': issue.description,
                'category': issue.dimension,
                'severity': issue.severity,
                'remediation': issue.suggestion,
                'regulation_citation': issue.regulation,
            }
            for issue in self.audit_result.issues
        ]
        return self._violations_cache

    def clear_cache(self) -> None:
        """清除缓存（当 audit_result 变化时调用）"""
        self._violations_cache = None

    @property
    def overall_assessment(self) -> str:
        """获取审核结论"""
        if self.audit_result:
            return self.audit_result.overall_assessment
        return "不通过"

    @property
    def assessment_reason(self) -> str:
        """获取审核依据说明"""
        if self.audit_result:
            return self.audit_result.assessment_reason
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'audit_result': {
                'overall_assessment': self.overall_assessment,
                'assessment_reason': self.assessment_reason,
                'score': self.score,
                'summary': self.audit_result.summary if self.audit_result else '',
                'regulations_used': self.audit_result.regulations_used if self.audit_result else [],
            },
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
