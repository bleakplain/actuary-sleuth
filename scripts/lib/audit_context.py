#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审核上下文 (AuditContext)

定义审核流程中的数据载体，在整个审核流程中传递数据。
整合了预处理数据、检查结果、分析结果、评估结果和导出结果。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime

from lib.reporting.model import EvaluationContext

__all__ = ['AuditContext']


@dataclass
class AuditContext:
    """
    审核上下文

    承载整个审核流程中的所有数据，作为各步骤之间传递数据的单一容器。

    职责：
    - 存储元数据（审核ID、文档URL、时间戳）
    - 存储预处理数据（产品信息、条款、定价参数）
    - 存储检查结果（违规项列表）
    - 存储分析结果（定价分析）
    - 存储评估结果（使用 EvaluationContext）
    - 存储导出结果

    设计原则：
    - 纯数据载体，不包含业务逻辑
    - 可变对象，在各步骤中被填充
    - 提供便捷的访问方法和转换方法

    使用示例：
    >>> context = AuditContext()
    >>> context.audit_id = "AUD-123"
    >>> context.document_url = "https://..."
    >>> _preprocess(context)  # 填充 product_info, clauses 等
    >>> _check_violations(context)  # 填充 violations
    >>> _generate_report(context)  # 填充 evaluation
    >>> return context.to_result()
    """

    # ========== 元数据 ==========

    audit_id: str = ""
    document_url: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # ========== 预处理数据 ==========

    product_info: Dict[str, Any] = field(default_factory=dict)
    clauses: List[Dict[str, Any]] = field(default_factory=list)
    pricing_params: Dict[str, Any] = field(default_factory=dict)

    # ========== 检查结果 ==========

    violations: List[Dict[str, Any]] = field(default_factory=list)

    # ========== 分析结果 ==========

    pricing_analysis: Dict[str, Any] = field(default_factory=dict)

    # ========== 评估结果 ==========
    # 使用现有的 EvaluationContext 来存储评估相关数据

    evaluation: EvaluationContext = field(default_factory=EvaluationContext)

    # ========== 导出结果 ==========

    export_result: Optional[Dict[str, Any]] = None

    def to_result(self) -> Dict[str, Any]:
        """
        转换为最终结果字典格式

        兼容现有的 _build_audit_result 输出格式

        Returns:
            dict: 完整的审核结果字典
        """
        return {
            'success': True,
            'audit_id': self.audit_id,
            'violations': self.violations,
            'violation_count': len(self.violations),
            'violation_summary': {
                'high': len([v for v in self.violations if v.get('severity') == 'high']),
                'medium': len([v for v in self.violations if v.get('severity') == 'medium']),
                'low': len([v for v in self.violations if v.get('severity') == 'low'])
            },
            'pricing': self.pricing_analysis.get('pricing', {}),
            'score': self.evaluation.score or 0,
            'grade': self.evaluation.grade or '',
            'summary': self.evaluation.summary or {},
            'report': self.evaluation.to_dict().get('content', ''),
            'metadata': {
                'audit_type': 'full',
                'document_url': self.document_url,
                'timestamp': self.timestamp.isoformat(),
                'product_info': self.product_info
            },
            'details': {
                'preprocess_id': f"PRE-{self.audit_id.split('-')[1]}",
                'product_info': self.product_info,
                'document_url': self.document_url
            },
            'report_export': self.export_result or {}
        }

    @property
    def has_issues(self) -> bool:
        """是否有违规问题"""
        return len(self.violations) > 0

    @property
    def has_critical_issues(self) -> bool:
        """是否有严重问题"""
        return any(v.get('severity') == 'high' for v in self.violations)

    @property
    def total_violations(self) -> int:
        """违规总数"""
        return len(self.violations)

    @property
    def high_violations_count(self) -> int:
        """严重违规数量"""
        return len([v for v in self.violations if v.get('severity') == 'high'])

    @property
    def medium_violations_count(self) -> int:
        """中等违规数量"""
        return len([v for v in self.violations if v.get('severity') == 'medium'])

    @property
    def low_violations_count(self) -> int:
        """轻微违规数量"""
        return len([v for v in self.violations if v.get('severity') == 'low'])
