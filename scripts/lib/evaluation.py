#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估计算模块

从 AuditData 计算 EvaluationResult 的纯函数模块

设计原则：
- 所有函数都是纯函数，无副作用
- 输入输出明确，易于测试
- 不依赖外部状态
- 不依赖上层模块（如 reporting），保持单向依赖
"""
from typing import Dict, List, Any, Tuple

from lib.audit_data import AuditData, EvaluationResult
from lib.common.models import Product, ProductCategory, ProductInfo
from lib.common.product_type import get_category

__all__ = ['calculate_evaluation', 'calculate_score', 'calculate_grade',
           'calculate_summary', 'group_violations']

# 模块级常量 - 避免每次函数调用时重建
SCORE_BASE = 100
SEVERITY_PENALTY = {
    'high': 20,
    'medium': 10,
    'low': 5
}
PRICING_ISSUE_PENALTY = 10

GRADE_THRESHOLDS = [
    (90, '优秀'),
    (75, '良好'),
    (60, '合格')
]
GRADE_DEFAULT = '不合格'


def calculate_evaluation(data: AuditData) -> EvaluationResult:
    """
    从 AuditData 计算评估结果

    这是主入口函数，协调所有计算步骤。

    此函数将 AuditData 转换为 EvaluationResult，后者是审核流程的完整输出，
    包含所有导出和 API 响应需要的数据。

    Args:
        data: 审核原始数据

    Returns:
        EvaluationResult: 评估计算结果（包含所有导出数据）
    """
    # 构建产品对象
    product_type_str = data.product_info.get('product_type', '')
    category = get_category(product_type_str)

    common_product = Product(
        name=data.product_info.get('product_name', '未知产品'),
        company=data.product_info.get('insurance_company', ''),
        category=category,
        period=data.product_info.get('insurance_period', '')
    )

    # 包装为 ProductInfo（供报告层使用）
    product = ProductInfo.from_product(
        common_product,
        document_url=data.document_url,
        version=data.product_info.get('version', '')
    )

    # 分组违规项
    high_violations, medium_violations, low_violations = group_violations(data.violations)

    # 计算分数
    score = calculate_score(data.violations, data.pricing_analysis)

    # 计算评级
    grade = calculate_grade(score)

    # 计算摘要
    summary = calculate_summary(data.violations, data.pricing_analysis, score)

    return EvaluationResult(
        # === 计算结果 ===
        score=score,
        grade=grade,
        summary=summary,

        # === 违规数据 ===
        violations=data.violations,
        high_violations=high_violations,
        medium_violations=medium_violations,
        low_violations=low_violations,
        pricing_analysis=data.pricing_analysis,

        # === 条款数据 ===
        clauses=data.clauses,

        # === 产品信息 ===
        product=product,
        product_info=data.product_info,

        # === 元数据 ===
        audit_id=data.audit_id,
        document_url=data.document_url,
        timestamp=data.timestamp
    )


def calculate_score(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> int:
    """
    计算综合评分

    Args:
        violations: 违规项列表
        pricing_analysis: 定价分析结果

    Returns:
        int: 综合评分 (0-100)
    """
    score = SCORE_BASE

    # 根据违规严重程度扣分
    for violation in violations:
        severity = violation.get('severity', 'low')
        score -= SEVERITY_PENALTY.get(severity, 0)

    # 根据定价分析扣分
    pricing_issues = _count_pricing_issues(pricing_analysis)
    score -= pricing_issues * PRICING_ISSUE_PENALTY

    return max(0, min(100, score))


def calculate_grade(score: int) -> str:
    """
    计算评级

    Args:
        score: 综合评分

    Returns:
        str: 评级
    """
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return GRADE_DEFAULT


def calculate_summary(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    score: int
) -> Dict[str, Any]:
    """
    计算违规摘要

    Args:
        violations: 违规项列表
        pricing_analysis: 定价分析结果
        score: 综合评分

    Returns:
        dict: 违规摘要
    """
    # 统计各严重程度数量（单次遍历）
    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    for v in violations:
        severity = v.get('severity', 'low')
        if severity in severity_counts:
            severity_counts[severity] += 1

    # 统计定价问题
    pricing_issues = _count_pricing_issues(pricing_analysis)

    # 判断是否有严重问题
    has_critical_issues = severity_counts['high'] > 0 or pricing_issues > 1

    return {
        'high': severity_counts['high'],
        'medium': severity_counts['medium'],
        'low': severity_counts['low'],
        'total_violations': len(violations),
        'pricing_issues': pricing_issues,
        'has_issues': len(violations) > 0 or pricing_issues > 0,
        'has_critical_issues': has_critical_issues,
        'violation_severity': severity_counts
    }


def group_violations(violations: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    按严重程度分组违规项（单次遍历）

    Args:
        violations: 违规项列表

    Returns:
        tuple: (high_violations, medium_violations, low_violations)
    """
    high_violations = []
    medium_violations = []
    low_violations = []

    for v in violations:
        severity = v.get('severity', 'low')
        if severity == 'high':
            high_violations.append(v)
        elif severity == 'medium':
            medium_violations.append(v)
        else:
            low_violations.append(v)

    return high_violations, medium_violations, low_violations


def _count_pricing_issues(pricing_analysis: Dict[str, Any]) -> int:
    """
    统计定价问题数量

    Args:
        pricing_analysis: 定价分析结果

    Returns:
        int: 问题数量
    """
    if not pricing_analysis:
        return 0

    pricing = pricing_analysis.get('pricing', {})
    issues = 0

    # 检查各项定价参数
    for category in ['interest', 'expense', 'mortality']:
        value = pricing.get(category)
        if isinstance(value, dict) and not value.get('reasonable', True):
            issues += 1

    return issues
