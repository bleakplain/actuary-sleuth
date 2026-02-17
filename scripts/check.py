#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
负面清单检查脚本
"""
import re
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib import db
from lib.config import get_config


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Negative List Check Script')
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


def execute(params):
    """执行负面清单检查

    Args:
        params: 包含 'clauses' 键的字典，值为产品条款数组

    Returns:
        dict: 包含违规信息的字典
    """
    # 验证输入参数
    if 'clauses' not in params:
        raise ValueError("Missing required parameter: 'clauses'")

    clauses = params['clauses']

    if not isinstance(clauses, list):
        raise TypeError("'clauses' must be a list")

    # 获取负面清单规则
    rules = db.get_negative_list()

    if not rules:
        return {
            'success': True,
            'violations': [],
            'count': 0,
            'summary': {'high': 0, 'medium': 0, 'low': 0},
            'message': 'No negative list rules found in database'
        }

    # 执行检查
    violations = []
    for idx, clause in enumerate(clauses):
        # 兼容新旧格式：字符串或字典
        if isinstance(clause, str):
            clause_text = clause
            clause_reference = f"条款{idx+1}"
        elif isinstance(clause, dict):
            clause_text = clause.get('text', '')
            clause_reference = clause.get('reference', f"条款{idx+1}")
        else:
            continue

        for rule in rules:
            if match_rule(clause_text, rule):
                # 截断过长的条款文本用于显示
                clause_preview = clause_text[:100] + '...' if len(clause_text) > 100 else clause_text

                violations.append({
                    'clause_index': idx,
                    'clause_text': clause_preview,
                    'clause_reference': clause_reference,  # 新增：保存条款引用
                    'rule': rule['rule_number'],
                    'description': rule['description'],
                    'severity': rule['severity'],
                    'category': rule.get('category', ''),
                    'remediation': rule.get('remediation', '')
                })

    return {
        'success': True,
        'violations': violations,
        'count': len(violations),
        'summary': group_by_severity(violations)
    }


def match_rule(clause, rule):
    """规则匹配逻辑

    Args:
        clause: 产品条款文本
        rule: 负面清单规则字典

    Returns:
        bool: 如果匹配则返回True
    """
    # 关键词匹配
    keywords = _parse_json_field(rule.get('keywords', '[]'))
    if keywords:
        for keyword in keywords:
            if isinstance(keyword, str) and keyword in clause:
                return True

    # 正则表达式匹配
    patterns = _parse_json_field(rule.get('patterns', '[]'))
    if patterns:
        for pattern in patterns:
            if isinstance(pattern, str):
                try:
                    if re.search(pattern, clause):
                        return True
                except re.error:
                    # 忽略无效的正则表达式
                    continue

    return False


def _parse_json_field(field_value):
    """安全解析JSON字段

    Args:
        field_value: 可能是JSON字符串或已解析的对象

    Returns:
        list: 解析后的列表，解析失败时返回空列表
    """
    if isinstance(field_value, list):
        return field_value

    if isinstance(field_value, str):
        try:
            return json.loads(field_value)
        except (json.JSONDecodeError, TypeError):
            return []

    return []


def group_by_severity(violations):
    """按严重程度分组

    Args:
        violations: 违规记录列表

    Returns:
        dict: 包含各严重程度计数的字典
    """
    summary = {
        'high': 0,
        'medium': 0,
        'low': 0
    }

    for violation in violations:
        severity = violation.get('severity', 'low').lower()
        if severity in summary:
            summary[severity] += 1

    return summary


if __name__ == '__main__':
    sys.exit(main())
