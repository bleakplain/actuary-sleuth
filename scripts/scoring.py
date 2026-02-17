#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定价合理性分析脚本
分析产品定价参数的合理性
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


# 配置文件路径（相对于脚本目录）
CONFIG_PATH = Path(__file__).parent / 'config' / 'settings.json'


def load_config() -> Dict[str, Any]:
    """
    加载配置文件

    Returns:
        dict: 配置字典，如果文件不存在则返回空字典
    """
    config = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load config file: {e}", file=sys.stderr)
    return config


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Pricing Analysis Script')
    parser.add_argument('--input', required=True, help='JSON input file')
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
    执行定价合理性分析

    Args:
        params: 包含定价参数的字典
            - pricing_params: 定价参数字典
            - product_type: 产品类型（可选）

    Returns:
        dict: 包含分析结果的字典
    """
    # 验证输入参数
    if 'pricing_params' not in params:
        raise ValueError("Missing required parameter: 'pricing_params'")

    pricing_params = params['pricing_params']
    product_type = params.get('product_type', 'unknown')

    # 执行定价分析
    mortality_analysis = analyze_mortality(pricing_params.get('mortality_rate'), product_type)
    interest_analysis = analyze_interest(pricing_params.get('interest_rate'), product_type)
    expense_analysis = analyze_expense(pricing_params.get('expense_rate'), product_type)

    # 计算综合评分
    overall_score = calculate_overall_score(
        mortality_analysis,
        interest_analysis,
        expense_analysis
    )

    # 生成建议
    recommendations = generate_recommendations(
        mortality_analysis,
        interest_analysis,
        expense_analysis
    )

    # 构建结果
    result = {
        'success': True,
        'analysis_id': f"ANA-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        'pricing': {
            'mortality': mortality_analysis,
            'interest': interest_analysis,
            'expense': expense_analysis
        },
        'overall_score': overall_score,
        'is_reasonable': overall_score >= 60,
        'recommendations': recommendations,
        'metadata': {
            'product_type': product_type,
            'timestamp': datetime.now().isoformat()
        }
    }

    return result


def analyze_mortality(mortality_rate: Any, product_type: str) -> Dict[str, Any]:
    """
    分析死亡率/发生率

    Args:
        mortality_rate: 死亡率/发生率
        product_type: 产品类型

    Returns:
        dict: 分析结果
    """
    # 基准死亡率（根据中国生命表2025）
    benchmarks = {
        'life': 0.0005,      # 寿险
        'health': 0.002,     # 健康险
        'accident': 0.001,   # 意外险
        'default': 0.001
    }

    # 获取基准值
    benchmark = benchmarks.get(product_type, benchmarks['default'])

    # 解析输入值
    value = None
    if isinstance(mortality_rate, (int, float)):
        value = mortality_rate
    elif isinstance(mortality_rate, str):
        try:
            value = float(mortality_rate)
        except ValueError:
            pass

    # 如果值大于1，可能是百分比形式，需要转换
    if value is not None and value > 1:
        value = value / 100

    if value is None:
        return {
            'value': mortality_rate,
            'benchmark': benchmark,
            'deviation': None,
            'reasonable': None,
            'note': '无法解析死亡率数值'
        }

    # 计算偏差
    deviation = ((value - benchmark) / benchmark) * 100 if benchmark != 0 else 0

    # 判断合理性（偏差在±20%内为合理）
    is_reasonable = abs(deviation) <= 20

    return {
        'value': value,
        'benchmark': benchmark,
        'deviation': round(deviation, 2),
        'reasonable': is_reasonable,
        'note': '死亡率/发生率符合行业标准' if is_reasonable else '死亡率/发生率偏离行业标准'
    }


def analyze_interest(interest_rate: Any, product_type: str) -> Dict[str, Any]:
    """
    分析利率

    Args:
        interest_rate: 利率
        product_type: 产品类型

    Returns:
        dict: 分析结果
    """
    # 基准利率（根据监管规定）
    benchmarks = {
        'life': 0.035,       # 寿险预定利率上限
        'health': 0.035,     # 健康险预定利率上限
        'accident': 0.035,   # 意外险预定利率上限
        'default': 0.030
    }

    # 获取基准值
    benchmark = benchmarks.get(product_type, benchmarks['default'])

    # 解析输入值
    value = None
    if isinstance(interest_rate, (int, float)):
        value = interest_rate
    elif isinstance(interest_rate, str):
        try:
            value = float(interest_rate)
        except ValueError:
            pass

    # 如果值大于1，可能是百分比形式，需要转换
    if value is not None and value > 1:
        value = value / 100

    if value is None:
        return {
            'value': interest_rate,
            'benchmark': benchmark,
            'deviation': None,
            'reasonable': None,
            'note': '无法解析利率数值'
        }

    # 计算偏差
    deviation = ((value - benchmark) / benchmark) * 100 if benchmark != 0 else 0

    # 判断合理性（不超过基准利率且偏差在±10%内为合理）
    is_reasonable = value <= benchmark and abs(deviation) <= 10

    note = '预定利率符合监管规定'
    if value > benchmark:
        note = '预定利率超过监管上限'
    elif abs(deviation) > 10:
        note = '预定利率偏离行业标准'

    return {
        'value': value,
        'benchmark': benchmark,
        'deviation': round(deviation, 2),
        'reasonable': is_reasonable,
        'note': note
    }


def analyze_expense(expense_rate: Any, product_type: str) -> Dict[str, Any]:
    """
    分析费用率

    Args:
        expense_rate: 费用率
        product_type: 产品类型

    Returns:
        dict: 分析结果
    """
    # 基准费用率（根据条款费率管理办法）
    benchmarks = {
        'life': 0.12,        # 寿险费用率上限
        'health': 0.35,      # 健康险费用率上限
        'accident': 0.25,    # 意外险费用率上限
        'default': 0.20
    }

    # 获取基准值
    benchmark = benchmarks.get(product_type, benchmarks['default'])

    # 解析输入值
    value = None
    if isinstance(expense_rate, (int, float)):
        value = expense_rate
    elif isinstance(expense_rate, str):
        try:
            value = float(expense_rate)
        except ValueError:
            pass

    # 如果值大于1，可能是百分比形式，需要转换
    if value is not None and value > 1:
        value = value / 100

    if value is None:
        return {
            'value': expense_rate,
            'benchmark': benchmark,
            'deviation': None,
            'reasonable': None,
            'note': '无法解析费用率数值'
        }

    # 计算偏差
    deviation = ((value - benchmark) / benchmark) * 100 if benchmark != 0 else 0

    # 判断合理性（不超过基准费用率且偏差在±15%内为合理）
    is_reasonable = value <= benchmark and abs(deviation) <= 15

    note = '费用率符合监管规定'
    if value > benchmark:
        note = '费用率超过监管上限'
    elif abs(deviation) > 15:
        note = '费用率偏离行业标准'

    return {
        'value': value,
        'benchmark': benchmark,
        'deviation': round(deviation, 2),
        'reasonable': is_reasonable,
        'note': note
    }


def calculate_overall_score(
    mortality_analysis: Dict[str, Any],
    interest_analysis: Dict[str, Any],
    expense_analysis: Dict[str, Any]
) -> int:
    """
    计算综合评分

    Args:
        mortality_analysis: 死亡率分析结果
        interest_analysis: 利率分析结果
        expense_analysis: 费用率分析结果

    Returns:
        int: 综合评分（0-100）
    """
    scores = []

    # 对每个维度评分
    for analysis in [mortality_analysis, interest_analysis, expense_analysis]:
        if analysis.get('reasonable') is True:
            scores.append(100)
        elif analysis.get('reasonable') is False:
            # 根据偏差程度扣分
            deviation = abs(analysis.get('deviation', 0))
            if deviation <= 10:
                scores.append(80)
            elif deviation <= 20:
                scores.append(60)
            elif deviation <= 30:
                scores.append(40)
            else:
                scores.append(20)
        else:
            scores.append(50)  # 无法判断时给中性分数

    # 计算平均分
    if scores:
        return int(sum(scores) / len(scores))
    return 50


def generate_recommendations(
    mortality_analysis: Dict[str, Any],
    interest_analysis: Dict[str, Any],
    expense_analysis: Dict[str, Any]
) -> List[str]:
    """
    生成改进建议

    Args:
        mortality_analysis: 死亡率分析结果
        interest_analysis: 利率分析结果
        expense_analysis: 费用率分析结果

    Returns:
        list: 建议列表
    """
    recommendations = []

    # 死亡率建议
    if mortality_analysis.get('reasonable') is False:
        deviation = mortality_analysis.get('deviation', 0)
        if deviation > 0:
            recommendations.append('死亡率/发生率高于行业基准，建议核实定价假设')
        else:
            recommendations.append('死亡率/发生率低于行业基准，注意风险评估')

    # 利率建议
    if interest_analysis.get('reasonable') is False:
        if interest_analysis.get('value', 0) > interest_analysis.get('benchmark', 0):
            recommendations.append('预定利率超过监管上限，需调整至符合规定')
        else:
            recommendations.append('预定利率偏离行业标准，建议与市场水平保持一致')

    # 费用率建议
    if expense_analysis.get('reasonable') is False:
        if expense_analysis.get('value', 0) > expense_analysis.get('benchmark', 0):
            recommendations.append('费用率超过监管上限，需优化费用结构')
        else:
            recommendations.append('费用率偏低，需确认是否覆盖实际运营成本')

    # 如果都合理，给予肯定
    if all([
        mortality_analysis.get('reasonable'),
        interest_analysis.get('reasonable'),
        expense_analysis.get('reasonable')
    ]):
        recommendations.append('定价参数合理，符合监管要求和行业标准')

    return recommendations


if __name__ == '__main__':
    sys.exit(main())
