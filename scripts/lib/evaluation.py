#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估计算模块

从 AuditData 计算 EvaluationResult 的纯函数模块

设计原则：
- 所有函数都是纯函数，无副作用
- 输入输出明确，易于测试
- 不依赖外部状态
"""
from typing import Dict, List, Any

from lib.audit_data import AuditData, EvaluationResult
from lib.reporting.model import _InsuranceProduct

__all__ = ['calculate_evaluation', 'calculate_score', 'calculate_grade',
           'calculate_summary', 'group_violations']


def calculate_evaluation(data: AuditData) -> EvaluationResult:
    """
    从 AuditData 计算评估结果

    这是主入口函数，协调所有计算步骤

    Args:
        data: 审核原始数据

    Returns:
        EvaluationResult: 评估计算结果
    """
    # 构建产品对象
    product = _InsuranceProduct(
        name=data.product_info.get('product_name', '未知产品'),
        type=data.product_info.get('product_type', ''),
        company=data.product_info.get('insurance_company', ''),
        version=data.product_info.get('version', ''),
        document_url=data.product_info.get('document_url', '')
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
        violations=data.violations,
        pricing_analysis=data.pricing_analysis,
        product=product,
        score=score,
        grade=grade,
        summary=summary,
        high_violations=high_violations,
        medium_violations=medium_violations,
        low_violations=low_violations
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
    SCORE_BASE = 100
    SEVERITY_PENALTY = {
        'high': 20,
        'medium': 10,
        'low': 5
    }
    PRICING_ISSUE_PENALTY = 10

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
    GRADE_THRESHOLDS = [
        (90, '优秀'),
        (75, '良好'),
        (60, '合格')
    ]
    GRADE_DEFAULT = '不合格'

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
    # 统计各严重程度数量
    severity_counts = {
        'high': len([v for v in violations if v.get('severity') == 'high']),
        'medium': len([v for v in violations if v.get('severity') == 'medium']),
        'low': len([v for v in violations if v.get('severity') == 'low'])
    }

    # 统计定价问题
    pricing_issues = _count_pricing_issues(pricing_analysis)

    # 判断是否有严重问题
    has_critical_issues = severity_counts['high'] > 0 or pricing_issues > 1

    # 使用扁平结构 (与 docx_generator 兼容)
    return {
        'high': severity_counts['high'],
        'medium': severity_counts['medium'],
        'low': severity_counts['low'],
        'total_violations': len(violations),
        'pricing_issues': pricing_issues,
        'has_issues': len(violations) > 0 or pricing_issues > 0,
        'has_critical_issues': has_critical_issues,
        # 保留嵌套格式用于向后兼容
        'violation_severity': severity_counts
    }


def group_violations(violations: List[Dict[str, Any]]) -> tuple:
    """
    按严重程度分组违规项

    Args:
        violations: 违规项列表

    Returns:
        tuple: (high_violations, medium_violations, low_violations)
    """
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']
    low_violations = [v for v in violations if v.get('severity') == 'low']

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
