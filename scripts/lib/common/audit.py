#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审核数据模型 (阶段式处理)

设计原则：
1. 每个阶段对应一个结果类
2. 通过组合体现数据流：PreprocessedResult → CheckedResult → AnalyzedResult → EvaluationResult
3. 不可变数据：使用 frozen dataclass
4. 职责清晰：每个类只包含对应阶段的输出
"""
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime

from lib.common.models import Product, ProductCategory

__all__ = [
    'PreprocessedResult',
    'CheckedResult',
    'AnalyzedResult',
    'EvaluationResult',
    'to_api_dict',
    'to_export_dict',
    'create_preprocessed_result'
]


@dataclass(frozen=True)
class PreprocessedResult:
    """
    预处理结果

    预处理步骤的输出，包含解析出的产品和条款信息。
    """
    # 元数据
    audit_id: str
    document_url: str
    timestamp: datetime

    # 预处理输出
    product: Product
    clauses: List[Dict[str, Any]]
    pricing_params: Dict[str, Any]


@dataclass(frozen=True)
class CheckedResult:
    """
    负面清单检查结果

    检查步骤的输出，在预处理基础上增加了违规信息。
    """
    preprocessed: PreprocessedResult
    violations: List[Dict[str, Any]]


@dataclass(frozen=True)
class AnalyzedResult:
    """
    定价分析结果

    分析步骤的输出，在检查基础上增加了定价分析。
    """
    checked: CheckedResult
    pricing_analysis: Dict[str, Any]


@dataclass(frozen=True)
class EvaluationResult:
    analyzed: AnalyzedResult
    score: int
    grade: str
    summary: Dict[str, Any]

    def get_violations(self) -> List[Dict[str, Any]]:
        return self.analyzed.checked.violations

    def get_violation_count(self) -> int:
        return len(self.analyzed.checked.violations)

    def get_violation_summary(self) -> Dict[str, int]:
        violations = self.analyzed.checked.violations
        return {
            'high': sum(1 for v in violations if v.get('severity') == 'high'),
            'medium': sum(1 for v in violations if v.get('severity') == 'medium'),
            'low': sum(1 for v in violations if v.get('severity') == 'low'),
        }

    def to_dict(self) -> Dict[str, Any]:
        preprocessed = self.analyzed.checked.preprocessed
        checked = self.analyzed.checked
        analyzed = self.analyzed

        return {
            'success': True,
            'audit_id': preprocessed.audit_id,
            'violations': checked.violations,
            'violation_count': self.get_violation_count(),
            'violation_summary': self.get_violation_summary(),
            'pricing': analyzed.pricing_analysis,
            'score': self.score,
            'grade': self.grade,
            'summary': self.summary,
        }


# ==================== 工厂函数 ====================

def create_preprocessed_result(audit_id: str, document_url: str) -> PreprocessedResult:
    """创建空的 PreprocessedResult 对象"""
    return PreprocessedResult(
        audit_id=audit_id,
        document_url=document_url,
        timestamp=datetime.now(),
        product=Product(
            name="",
            company="",
            category=ProductCategory.OTHER,
            period=""
        ),
        clauses=[],
        pricing_params={}
    )


# ==================== 便捷访问属性 ====================

def get_violations(result: EvaluationResult) -> List[Dict[str, Any]]:
    """获取违规列表"""
    return result.analyzed.checked.violations

def get_product(result: EvaluationResult) -> Product:
    """获取产品信息"""
    return result.analyzed.checked.preprocessed.product

def get_clauses(result: EvaluationResult) -> List[Dict[str, Any]]:
    """获取条款列表"""
    return result.analyzed.checked.preprocessed.clauses

def get_pricing_analysis(result: EvaluationResult) -> Dict[str, Any]:
    """获取定价分析"""
    return result.analyzed.pricing_analysis

def get_audit_id(result: EvaluationResult) -> str:
    """获取审核ID"""
    return result.analyzed.checked.preprocessed.audit_id

def get_document_url(result: EvaluationResult) -> str:
    """获取文档URL"""
    return result.analyzed.checked.preprocessed.document_url

def get_timestamp(result: EvaluationResult) -> datetime:
    """获取时间戳"""
    return result.analyzed.checked.preprocessed.timestamp

def get_preprocess_id(result: EvaluationResult) -> str:
    """获取预处理ID"""
    return f"PRE-{result.analyzed.checked.preprocessed.audit_id.split('-')[1]}"


# ==================== 转换函数 ====================

def to_api_dict(result: EvaluationResult) -> Dict[str, Any]:
    """
    转换为 API 响应格式

    Args:
        result: 评估结果

    Returns:
        API 响应字典
    """
    preprocessed = result.analyzed.checked.preprocessed
    checked = result.analyzed.checked
    analyzed = result.analyzed

    violations = checked.violations
    total_violations = len(violations)

    return {
        'success': True,
        'audit_id': preprocessed.audit_id,
        'violations': violations,
        'violation_count': total_violations,
        'violation_summary': {
            'high': sum(1 for v in violations if v.get('severity') == 'high'),
            'medium': sum(1 for v in violations if v.get('severity') == 'medium'),
            'low': sum(1 for v in violations if v.get('severity') == 'low'),
        },
        'pricing': analyzed.pricing_analysis,
        'score': result.score,
        'grade': result.grade,
        'summary': result.summary,
        'report': '',
        'metadata': {
            'audit_type': 'full',
            'document_url': preprocessed.document_url,
            'timestamp': preprocessed.timestamp.isoformat(),
        },
        'details': {
            'preprocess_id': get_preprocess_id(result),
            'product_name': preprocessed.product.name,
            'product_type': preprocessed.product.type,
            'insurance_company': preprocessed.product.company,
            'clauses': preprocessed.clauses,
            'document_url': preprocessed.document_url
        },
    }


def to_export_dict(result: EvaluationResult) -> Dict[str, Any]:
    """
    转换为导出格式

    Args:
        result: 评估结果

    Returns:
        导出格式字典
    """
    preprocessed = result.analyzed.checked.preprocessed
    checked = result.analyzed.checked
    analyzed = result.analyzed

    violations = checked.violations

    return {
        'violations': violations,
        'high_violations': [v for v in violations if v.get('severity') == 'high'],
        'medium_violations': [v for v in violations if v.get('severity') == 'medium'],
        'low_violations': [v for v in violations if v.get('severity') == 'low'],
        'pricing_analysis': analyzed.pricing_analysis,
        'clauses': preprocessed.clauses,
        'product': preprocessed.product,
        'score': result.score,
        'grade': result.grade,
        'summary': result.summary,
    }
