#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成脚本
生成结构化的审核报告
"""
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib import db


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Report Generation Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    parser.add_argument('--config', default='./config/settings.json', help='Config file')
    args = parser.parse_args()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 执行业务逻辑
    try:
        result = execute(params)
        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        # 错误输出
        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        return 1


def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成审核报告

    Args:
        params: 包含审核数据的字典
            - violations: 违规记录列表
            - pricing_analysis: 定价分析结果
            - product_info: 产品信息
            - score: 总分（可选）

    Returns:
        dict: 包含报告内容的字典
    """
    # 验证输入参数
    if 'violations' not in params:
        raise ValueError("Missing required parameter: 'violations'")

    violations = params['violations']
    pricing_analysis = params.get('pricing_analysis', {})
    product_info = params.get('product_info', {})
    score = params.get('score')

    # 如果没有提供分数，则计算分数
    if score is None:
        score = calculate_score(violations, pricing_analysis)

    # 生成评级
    grade = calculate_grade(score)

    # 生成报告摘要
    summary = generate_summary(violations, pricing_analysis)

    # 生成报告内容
    report_content = generate_report_content(
        violations,
        pricing_analysis,
        product_info,
        score,
        grade,
        summary
    )

    # 构建结果
    result = {
        'success': True,
        'report_id': f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        'score': score,
        'grade': grade,
        'summary': summary,
        'content': report_content,
        'metadata': {
            'product_name': product_info.get('product_name', '未知产品'),
            'timestamp': datetime.now().isoformat()
        }
    }

    return result


def calculate_score(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> int:
    """
    计算综合评分

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果

    Returns:
        int: 评分（0-100）
    """
    # 基础分
    score = 100

    # 根据违规严重程度扣分
    for violation in violations:
        severity = violation.get('severity', 'low').lower()
        if severity == 'high':
            score -= 20
        elif severity == 'medium':
            score -= 10
        elif severity == 'low':
            score -= 5

    # 根据定价分析扣分
    if pricing_analysis:
        pricing = pricing_analysis.get('pricing', {})
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category, {})
            if analysis.get('reasonable') is False:
                score -= 10

    # 确保分数在0-100范围内
    return max(0, min(100, score))


def calculate_grade(score: int) -> str:
    """
    计算评级

    Args:
        score: 分数

    Returns:
        str: 评级
    """
    if score >= 90:
        return '优秀'
    elif score >= 75:
        return '良好'
    elif score >= 60:
        return '合格'
    else:
        return '不合格'


def generate_summary(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成报告摘要

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果

    Returns:
        dict: 摘要信息
    """
    # 统计违规数量
    violation_summary = {
        'high': 0,
        'medium': 0,
        'low': 0
    }

    for violation in violations:
        severity = violation.get('severity', 'low').lower()
        if severity in violation_summary:
            violation_summary[severity] += 1

    # 统计定价问题
    pricing_issues = 0
    if pricing_analysis:
        pricing = pricing_analysis.get('pricing', {})
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category, {})
            if analysis.get('reasonable') is False:
                pricing_issues += 1

    return {
        'total_violations': len(violations),
        'violation_severity': violation_summary,
        'pricing_issues': pricing_issues,
        'has_critical_issues': violation_summary['high'] > 0 or pricing_issues > 1
    }


def generate_report_content(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    score: int,
    grade: str,
    summary: Dict[str, Any]
) -> str:
    """
    生成报告文本内容

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果
        product_info: 产品信息
        score: 分数
        grade: 评级
        summary: 摘要信息

    Returns:
        str: 报告内容（Markdown格式）
    """
    lines = []

    # 报告标题
    lines.append("# 保险产品合规性审核报告\n")

    # 基本信息
    lines.append("## 一、基本信息\n")
    lines.append(f"- **产品名称**: {product_info.get('product_name', '未知产品')}")
    lines.append(f"- **保险公司**: {product_info.get('insurance_company', '未知')}")
    lines.append(f"- **产品类型**: {product_info.get('product_type', '未知')}")
    lines.append(f"- **审核时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 审核结果
    lines.append("## 二、审核结果\n")
    lines.append(f"- **综合评分**: {score}分")
    lines.append(f"- **评级**: {grade}")
    lines.append(f"- **违规总数**: {summary['total_violations']}项")
    lines.append(f"- **严重违规**: {summary['violation_severity']['high']}项")
    lines.append(f"- **中等违规**: {summary['violation_severity']['medium']}项")
    lines.append(f"- **轻微违规**: {summary['violation_severity']['low']}项")
    lines.append(f"- **定价问题**: {summary['pricing_issues']}项\n")

    # 违规详情
    if violations:
        lines.append("## 三、违规详情\n")

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']
        low_violations = [v for v in violations if v.get('severity') == 'low']

        if high_violations:
            lines.append("### 3.1 严重违规\n")
            for i, violation in enumerate(high_violations, 1):
                lines.append(f"#### {i}. {violation.get('description', '未知违规')}")
                lines.append(f"- **规则编号**: {violation.get('rule', 'N/A')}")
                lines.append(f"- **条款索引**: {violation.get('clause_index', 'N/A')}")
                lines.append(f"- **整改建议**: {violation.get('remediation', '无')}")
                lines.append(f"- **条款内容**: \n```\n{violation.get('clause_text', '')}\n```\n")

        if medium_violations:
            lines.append("### 3.2 中等违规\n")
            for i, violation in enumerate(medium_violations, 1):
                lines.append(f"#### {i}. {violation.get('description', '未知违规')}")
                lines.append(f"- **规则编号**: {violation.get('rule', 'N/A')}")
                lines.append(f"- **整改建议**: {violation.get('remediation', '无')}\n")

        if low_violations:
            lines.append("### 3.3 轻微违规\n")
            for i, violation in enumerate(low_violations, 1):
                lines.append(f"{i}. {violation.get('description', '未知违规')} - {violation.get('remediation', '无')}")

    # 定价分析
    if pricing_analysis:
        lines.append("\n## 四、定价合理性分析\n")

        pricing = pricing_analysis.get('pricing', {})
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category)
            if analysis:
                category_name = {
                    'mortality': '死亡率/发生率',
                    'interest': '预定利率',
                    'expense': '费用率'
                }.get(category, category)

                lines.append(f"### {category_name}")
                lines.append(f"- **当前值**: {analysis.get('value', 'N/A')}")
                lines.append(f"- **基准值**: {analysis.get('benchmark', 'N/A')}")
                lines.append(f"- **偏差**: {analysis.get('deviation', 'N/A')}%")
                lines.append(f"- **合理性**: {'合理' if analysis.get('reasonable') else '不合理'}")
                lines.append(f"- **说明**: {analysis.get('note', '')}\n")

        # 建议
        recommendations = pricing_analysis.get('recommendations', [])
        if recommendations:
            lines.append("### 改进建议\n")
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec}")

    # 结论
    lines.append("\n## 五、审核结论\n")

    if summary['has_critical_issues']:
        lines.append("**该产品存在严重合规问题，建议进行重大修改后再提交审核。**")
    elif score >= 75:
        lines.append("**该产品整体合规性良好，建议对指出的问题进行修改后可以推向市场。**")
    elif score >= 60:
        lines.append("**该产品基本合规，但存在一些需要改进的问题，建议修改后再推向市场。**")
    else:
        lines.append("**该产品合规性不足，需要进行全面修改。**")

    lines.append("\n---\n")
    lines.append("*本报告由 Actuary Sleuth 自动生成，仅供参考，最终决策应以监管部门官方解释为准。*")

    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main())
