#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估计算模块

从 AnalyzedResult 计算 EvaluationResult
"""
from typing import Dict, List, Any

from lib.common.audit import (
    AnalyzedResult,
    EvaluationResult
)

__all__ = ['calculate_result']

# 模块级常量
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


def calculate_result(analyzed: AnalyzedResult) -> EvaluationResult:
    """
    从 AnalyzedResult 计算最终评估结果

    Args:
        analyzed: 定价分析结果

    Returns:
        EvaluationResult: 最终评估结果
    """
    violations = analyzed.checked.violations
    pricing_analysis = analyzed.pricing_analysis

    # 计算分数
    score = calculate_score(violations, pricing_analysis)

    # 计算评级
    grade = calculate_grade(score)

    # 计算摘要
    summary = calculate_summary(violations, pricing_analysis, score)

    return EvaluationResult(
        analyzed=analyzed,
        score=score,
        grade=grade,
        summary=summary
    )


def calculate_score(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> int:
    """计算综合评分"""
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
    """计算评级"""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return GRADE_DEFAULT


def calculate_summary(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    score: int
) -> Dict[str, Any]:
    """计算违规摘要"""
    # 统计各严重程度数量
    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    for v in violations:
        severity = v.get('severity', 'low')
        if severity in severity_counts:
            severity_counts[severity] += 1

    # 统计定价问题
    pricing_issues = _count_pricing_issues(pricing_analysis)

    return {
        'high': severity_counts['high'],
        'medium': severity_counts['medium'],
        'low': severity_counts['low'],
        'total_violations': len(violations),
        'pricing_issues': pricing_issues,
        'has_issues': len(violations) > 0 or pricing_issues > 0,
        'has_critical_issues': severity_counts['high'] > 0 or pricing_issues > 1,
    }


def _count_pricing_issues(pricing_analysis: Dict[str, Any]) -> int:
    """统计定价问题数量"""
    if not pricing_analysis:
        return 0

    # pricing_analysis 已经是从 scoring.result['pricing'] 提取的数据
    # 直接包含 {mortality, interest, expense} 键，不需要再嵌套 'pricing'
    issues = 0

    for category in ['mortality', 'interest', 'expense']:
        value = pricing_analysis.get(category)
        if isinstance(value, dict) and not value.get('reasonable', True):
            issues += 1

    return issues
