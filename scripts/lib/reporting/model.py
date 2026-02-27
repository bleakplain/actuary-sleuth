#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估数据模型

定义用于评估过程的数据载体，在模板编排的各步骤之间传递数据
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

__all__ = ['EvaluationContext']


@dataclass
class _InsuranceProduct:
    """
    保险产品信息

    被审核的保险产品的基本信息
    """
    name: str                           # 产品名称
    type: str = ""                      # 产品类型（终身寿险、重疾险等）
    company: str = ""                   # 保险公司
    document_url: str = ""              # 文档链接
    version: str = ""                   # 版本号


@dataclass
class EvaluationContext:
    """
    评估上下文

    承载审核评估过程中的所有数据，
    在模板编排的各个步骤之间传递

    职责：
    - 存储输入数据（violations, pricing_analysis, product）
    - 存储计算结果（score, grade, summary）
    - 存储分组后的违规项（避免重复计算）
    - 存储审核依据

    设计原则：
    - 纯数据载体，不包含业务逻辑
    - 可变对象，在各步骤中被填充
    - 向后兼容，提供 to_dict() 方法
    """
    # ========== 输入数据 ==========

    violations: List[Dict[str, Any]] = field(default_factory=list)
    pricing_analysis: Dict[str, Any] = field(default_factory=dict)
    product: _InsuranceProduct = field(default_factory=lambda: _InsuranceProduct(name=""))

    # ========== 计算结果 ==========

    score: Optional[int] = None
    grade: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None

    # ========== 分组后的违规项 ==========
    # 预先分组，避免在各步骤中重复过滤

    high_violations: List[Dict[str, Any]] = field(default_factory=list)
    medium_violations: List[Dict[str, Any]] = field(default_factory=list)
    low_violations: List[Dict[str, Any]] = field(default_factory=list)

    # ========== 审核依据 ==========

    regulation_basis: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        用于向后兼容，保持与现有接口的一致性
        """
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
