#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理脚本
解析保险产品文档，提取结构化信息
"""
import json
import argparse
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib.config import get_config


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Document Preprocessing Script')
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
    执行文档预处理

    Args:
        params: 包含文档内容的字典
            - documentContent: 文档内容（Markdown 或纯文本）
            - documentUrl: 文档 URL（可选）
            - documentType: 文档类型（可选）

    Returns:
        dict: 包含预处理结果的字典
    """
    # 验证输入参数
    if 'documentContent' not in params:
        raise ValueError("Missing required parameter: 'documentContent'")

    document_content = params['documentContent']
    document_url = params.get('documentUrl', '')
    document_type = params.get('documentType', 'unknown')

    # 解析文档结构
    parsed_data = parse_document(document_content)

    # 提取产品信息
    product_info = extract_product_info(document_content)

    # 提取条款列表
    clauses = extract_clauses(document_content)

    # 提取定价参数
    pricing_params = extract_pricing_params(document_content)

    # 构建结果
    result = {
        'success': True,
        'preprocess_id': f"PRE-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        'metadata': {
            'document_url': document_url,
            'document_type': document_type,
            'timestamp': datetime.now().isoformat(),
            'content_length': len(document_content)
        },
        'product_info': product_info,
        'structure': parsed_data,
        'clauses': clauses,
        'pricing_params': pricing_params
    }

    return result


def parse_document(content: str) -> Dict[str, Any]:
    """
    解析文档结构

    Args:
        content: 文档内容

    Returns:
        dict: 文档结构信息
    """
    lines = content.split('\n')

    structure = {
        'total_lines': len(lines),
        'sections': [],
        'has_table_of_contents': False,
        'formatting_markers': []
    }

    # 识别章节
    current_section = None
    for i, line in enumerate(lines):
        # 检测标题（Markdown 格式）
        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            title = line.lstrip('#').strip()
            section = {
                'line_number': i + 1,
                'level': level,
                'title': title
            }
            structure['sections'].append(section)
            current_section = title

        # 检测目录
        if '目录' in line or '目　录' in line:
            structure['has_table_of_contents'] = True

        # 检测格式标记
        if '**' in line:
            structure['formatting_markers'].append('bold')
        if '*' in line and '**' not in line:
            structure['formatting_markers'].append('italic')

    return structure


def extract_product_info(content: str) -> Dict[str, Any]:
    """
    提取产品基本信息

    Args:
        content: 文档内容

    Returns:
        dict: 产品信息
    """
    product_info = {
        'product_name': '',
        'insurance_company': '',
        'product_type': '',
        'insurance_period': '',
        'payment_method': '',
        'age_range': '',
        'occupation_class': ''
    }

    # 产品名称模式
    patterns = {
        'product_name': [
            r'^#\s*(.+?)(?:\s|条款|保险|产品|\n)',  # Markdown一级标题
            r'产品名称[：:]\s*(.+?)(?:\n|$)',
            r'保险产品名称[：:]\s*(.+?)(?:\n|$)',
            r'###\s*第[一二三四五六七八九十\d]+\s*条\s*产品名称\s*\n(.+?)(?:\n|$)',
            r'第[一二三四五六七八九十\d]+\s*条\s*产品名称[：:]\s*(.+?)(?:\n|$)',
            r'^(.+?)保险条款'
        ],
        'insurance_company': [
            r'(.+?)人寿保险股份有限公司',
            r'(.+?)保险有限公司',
            r'保险公司[：:]\s*(.+?)(?:\n|$)',
            r'承保公司[：:]\s*(.+?)(?:\n|$)'
        ],
        'product_type': [
            r'###\s*##\s*(.+?)险',
            r'产品类型[：:]\s*(.+?)(?:\n|$)',
            r'险种[：:]\s*(.+?)(?:\n|$)'
        ],
        'insurance_period': [
            r'保险期间[：:]\s*(.+?)(?:\n|$)',
            r'保险期限[：:]\s*(.+?)(?:\n|$)',
            r'###\s*第[一二三四五六七八九十\d]+\s*条\s*保险期间\s*\n(.+?)(?:\n|$)',
            r'第[一二三四五六七八九十\d]+\s*条\s*保险期间[：:]\s*(.+?)(?:\n|$)'
        ],
        'payment_method': [
            r'缴费方式[：:]\s*(.+?)(?:\n|$)',
            r'交费方式[：:]\s*(.+?)(?:\n|$)',
            r'###\s*第[一二三四五六七八九十\d]+\s*条\s*保险费\s*\n(.+?)(?:\n|$)'
        ],
        'age_range': [
            r'投保年龄[：:]\s*(.+?)(?:\n|$)',
            r'年龄限制[：:]\s*(.+?)(?:\n|$)',
            r'凡出生满(.+?)周岁',
            r'(\d+周岁至\d+周岁)'
        ],
        'occupation_class': [
            r'职业类别[：:]\s*(.+?)(?:\n|$)',
            r'职业等级[：:]\s*(.+?)(?:\n|$)'
        ]
    }

    # 尝试匹配每个字段
    for field, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
            if match:
                product_info[field] = match.group(1).strip()
                break

    return product_info


def extract_clauses(content: str) -> List[Dict[str, Any]]:
    """
    提取条款列表（包含章节信息）

    Args:
        content: 文档内容

    Returns:
        list: 条款字典列表，每个包含 text 和 reference
    """
    clauses = []

    # 按章节分割
    lines = content.split('\n')
    current_clause = []
    current_reference = ""
    in_clause = False

    for i, line in enumerate(lines):
        # 检测条款开始（常见条款标题，支持中文数字）
        match = re.match(r'^(第[一二三四五六七八九十百千万\d]+[条章节])(.+)', line)
        if match:
            if current_clause:
                clause_text = '\n'.join(current_clause).strip()
                if len(clause_text) > 10:  # 过滤太短的条款
                    clauses.append({
                        'text': clause_text,
                        'reference': current_reference
                    })
            current_reference = match.group(1)  # 保存条款编号，如"第一条"
            current_clause = [line]
            in_clause = True
        elif in_clause:
            current_clause.append(line)

    # 添加最后一个条款
    if current_clause:
        clause_text = '\n'.join(current_clause).strip()
        if len(clause_text) > 10:
            clauses.append({
                'text': clause_text,
                'reference': current_reference
            })

    # 如果没有找到明确的条款，则按段落分割
    if not clauses:
        paragraphs = content.split('\n\n')
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) > 20:  # 只保留有意义的段落
                clauses.append({
                    'text': para,
                    'reference': f"段落{i+1}"
                })

    return clauses


def extract_pricing_params(content: str) -> Dict[str, Any]:
    """
    提取定价参数

    Args:
        content: 文档内容

    Returns:
        dict: 定价参数
    """
    pricing_params = {
        'mortality_rate': None,
        'interest_rate': None,
        'expense_rate': None,
        'premium_rate': None,
        'cash_value': None,
        'dividend': None
    }

    # 死亡率/发生率
    mortality_patterns = [
        r'死亡率[：:]\s*([\d.]+)',
        r'发生率[：:]\s*([\d.]+)',
        r'生命表[：:]\s*(.+?)(?:\n|$)'
    ]

    # 利率
    interest_patterns = [
        r'预定利率[：:]\s*([\d.]+)(?:%|％)?',
        r'年利率[：:]\s*([\d.]+)(?:%|％)?',
        r'利率[：:]\s*([\d.]+)(?:%|％)?',
        r'预定利率为([\d.]+)(?:%|％)?',
        r'###\s*第[一二三四五六七八九十\d]+\s*条\s*预定利率\s*\n本产品的预定利率为([\d.]+)(?:%|％)?'
    ]

    # 费用率
    expense_patterns = [
        r'费用率[：:]\s*([\d.]+)(?:%|％)?',
        r'附加费用率[：:]\s*([\d.]+)(?:%|％)?',
        r'手续费[：:]\s*([\d.]+)(?:%|％)?',
        r'费用率为([\d.]+)(?:%|％)?',
        r'###\s*第[一二三四五六七八九十\d]+\s*条\s*费用率\s*\n本产品的费用率为([\d.]+)(?:%|％)?'
    ]

    # 提取数值
    for pattern in mortality_patterns:
        match = re.search(pattern, content)
        if match:
            try:
                pricing_params['mortality_rate'] = float(match.group(1))
                break
            except ValueError:
                pricing_params['mortality_rate'] = match.group(1)

    for pattern in interest_patterns:
        match = re.search(pattern, content)
        if match:
            try:
                pricing_params['interest_rate'] = float(match.group(1))
                break
            except ValueError:
                pricing_params['interest_rate'] = match.group(1)

    for pattern in expense_patterns:
        match = re.search(pattern, content)
        if match:
            try:
                pricing_params['expense_rate'] = float(match.group(1))
                break
            except ValueError:
                pricing_params['expense_rate'] = match.group(1)

    # 检查是否有现金价值
    pricing_params['cash_value'] = '现金价值' in content or '退保金' in content

    # 检查是否有分红
    pricing_params['dividend'] = '分红' in content or '红利' in content

    return pricing_params


if __name__ == '__main__':
    sys.exit(main())
