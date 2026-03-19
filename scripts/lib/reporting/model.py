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

from lib.common.models import Product as CommonProduct, ProductCategory

__all__ = ['EvaluationContext', 'ProductInfo']


@dataclass
class ProductInfo:
    """
    产品信息（用于报告生成）

    包装 common.Product，添加报告需要的额外字段
    """
    product: CommonProduct
    document_url: str = ""
    version: str = ""

    @property
    def name(self) -> str:
        return self.product.name

    @property
    def company(self) -> str:
        return self.product.company

    @property
    def type(self) -> str:
        """产品类型（从 category enum 转换为字符串）"""
        category_map = {
            'critical_illness': '重大疾病保险',
            'medical_insurance': '医疗保险',
            'life_insurance': '人寿保险',
            'participating_life': '分红型人寿保险',
            'universal_life': '万能险',
            'annuity': '年金保险',
            'accident': '意外伤害保险',
            'health': '健康保险',
            'pension': '养老保险',
            'other': '其他保险',
        }
        category_value = self.product.category.value if self.product.category else 'other'
        return category_map.get(category_value, category_value)

    @classmethod
    def from_common_product(
        cls,
        product: CommonProduct,
        document_url: str = "",
        version: str = ""
    ) -> 'ProductInfo':
        """从 common.Product 创建 ProductInfo"""
        return cls(
            product=product,
            document_url=document_url,
            version=version
        )

    @classmethod
    def from_dict(cls, product_info: Dict[str, Any]) -> 'ProductInfo':
        """从字典创建 ProductInfo（向后兼容）"""
        category_map = {
            '重大疾病保险': ProductCategory.CRITICAL_ILLNESS,
            '医疗保险': ProductCategory.MEDICAL_INSURANCE,
            '人寿保险': ProductCategory.LIFE_INSURANCE,
            '终身寿险': ProductCategory.LIFE_INSURANCE,
            '重疾险': ProductCategory.CRITICAL_ILLNESS,
            '意外险': ProductCategory.ACCIDENT,
            '意外伤害保险': ProductCategory.ACCIDENT,
        }

        # 确定产品类型
        type_str = product_info.get('product_type', '')
        category = ProductCategory.OTHER
        for key, cat in category_map.items():
            if key in type_str:
                category = cat
                break

        product = CommonProduct(
            name=product_info.get('product_name', ''),
            company=product_info.get('insurance_company', ''),
            category=category,
            period=product_info.get('insurance_period', ''),
            waiting_period=None,
            age_min=None,
            age_max=None
        )

        return cls(
            product=product,
            document_url=product_info.get('document_url', ''),
            version=product_info.get('version', '')
        )


# 向后兼容的别名
_InsuranceProduct = ProductInfo


@dataclass
class EvaluationContext:
    """
    评估上下文

    承载审核评估过程中的所有数据，
    在模板编排的各个步骤之间传递

    统一数据模型设计：
    - 使用 AuditResult 作为单一数据源（audit 模块输出）
    - 消除数据转换，直接使用 audit 的结论
    - violations 从 audit_result.issues 转换而来

    职责：
    - 存储 AuditResult（来自 audit 模块）
    - 存储产品信息和定价分析
    - 提供便捷方法访问 violations（从 AuditResult.issues 转换）
    - 存储计算结果（grade，score 来自 AuditResult）

    设计原则：
    - 纯数据载体，不包含业务逻辑
    - 可变对象，在各步骤中被填充
    - 向后兼容，提供 to_dict() 方法
    """
    # ========== 核心：审核结果（单一数据源） ==========

    audit_result: Optional['AuditResult'] = None

    # ========== 产品信息 ==========

    product: ProductInfo = field(default_factory=lambda: ProductInfo(
        product=CommonProduct(
            name="",
            company="",
            category=ProductCategory.OTHER,
            period=""
        )
    ))

    # ========== 定价分析（可选） ==========

    pricing_analysis: Dict[str, Any] = field(default_factory=dict)

    # ========== 条款内容（可选） ==========

    clauses: List[Dict[str, Any]] = field(default_factory=list)

    # ========== 计算结果（从 audit_result 衍生） ==========

    grade: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None

    # ========== 分组后的违规项（从 audit_result.issues 转换） ==========

    high_violations: List[Dict[str, Any]] = field(default_factory=list)
    medium_violations: List[Dict[str, Any]] = field(default_factory=list)
    low_violations: List[Dict[str, Any]] = field(default_factory=list)

    # ========== 审核依据（从 audit_result.regulations_used） ==========

    regulation_basis: List[str] = field(default_factory=list)

    # ========== 缓存 ==========

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

        将 AuditIssue 转换为 reporting 需要的格式

        缓存策略：当 audit_result 变化时清除缓存
        """
        if not self.audit_result:
            return []

        # 检查缓存
        if self._violations_cache is not None:
            return self._violations_cache

        # 构建并缓存
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
        """获取审核结论（从 audit_result）"""
        if self.audit_result:
            return self.audit_result.overall_assessment
        return "不通过"

    @property
    def assessment_reason(self) -> str:
        """获取审核依据说明（从 audit_result）"""
        if self.audit_result:
            return self.audit_result.assessment_reason
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        用于向后兼容，保持与现有接口的一致性
        """
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
