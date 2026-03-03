#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理脚本
解析保险产品文档，提取结构化信息
支持规则+LLM混合提取架构
"""
import json
import argparse
import sys
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

from lib.config import get_config
from lib.id_generator import IDGenerator
from lib.hybrid_extractor import HybridExtractor, extract_document

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def display_structured_content(product_info: Dict[str, Any], clauses: List[Dict[str, Any]], pricing_params: Dict[str, Any]) -> None:
    """
    显示结构化保险产品内容供确认

    Args:
        product_info: 产品信息
        clauses: 条款列表
        pricing_params: 定价参数
    """
    print("\n" + "="*60, file=sys.stderr)
    print("预处理完成 - 结构化保险产品内容确认", file=sys.stderr)
    print("="*60, file=sys.stderr)

    # 产品信息
    print("\n【产品信息】", file=sys.stderr)
    for key, value in product_info.items():
        if value:
            print(f"  {key}: {value}", file=sys.stderr)

    # 条款摘要
    print(f"\n【条款内容】", file=sys.stderr)
    print(f"  提取条款数: {len(clauses)}", file=sys.stderr)
    if clauses:
        print(f"  条款预览 (前3条):", file=sys.stderr)
        for i, clause in enumerate(clauses[:3], 1):
            text = clause.get('text', '')
            reference = clause.get('reference', '未知')
            preview = text[:80] + '...' if len(text) > 80 else text
            print(f"    {i}. [{reference}] {preview}", file=sys.stderr)
        if len(clauses) > 3:
            print(f"    ... (还有 {len(clauses) - 3} 条)", file=sys.stderr)

    # 定价参数
    print(f"\n【定价参数】", file=sys.stderr)
    pricing_found = False
    for key, value in pricing_params.items():
        if value:
            print(f"  {key}: {value}", file=sys.stderr)
            pricing_found = True
    if not pricing_found:
        print(f"  未提取到定价参数", file=sys.stderr)

    print("\n" + "="*60, file=sys.stderr)
    print("请确认上述信息是否准确，然后进入正式审核阶段", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)


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
    执行文档预处理（使用混合提取架构）

    Args:
        params: 包含文档内容的字典
            - documentContent: 文档内容（Markdown 或纯文本）
            - documentUrl: 文档 URL（可选）
            - documentType: 文档类型（可选）
            - use_hybrid: 是否使用混合提取（默认true）

    Returns:
        dict: 包含预处理结果的字典
    """
    # 验证输入参数
    if 'documentContent' not in params:
        raise ValueError("Missing required parameter: 'documentContent'")

    document_content = params['documentContent']
    document_url = params.get('documentUrl', '')
    document_type = params.get('documentType', 'unknown')
    use_hybrid = params.get('use_hybrid', True)

    # 生成预处理ID
    preprocess_id = IDGenerator.generate_preprocess()

    if use_hybrid:
        # 使用混合提取架构
        logger.info("使用混合提取架构进行预处理")

        try:
            # 执行混合提取
            extract_result = extract_document(document_content)

            # 解析文档结构
            parsed_data = parse_document(document_content)

            # 从混合提取结果中提取结构化信息
            product_info = _extract_product_info_from_result(extract_result)
            clauses = _extract_clauses_from_result(extract_result)
            pricing_params = _extract_pricing_from_result(extract_result)

            # 显示结构化内容供确认
            display_structured_content(product_info, clauses, pricing_params)

            # 构建结果
            result = {
                'success': True,
                'preprocess_id': preprocess_id,
                'metadata': {
                    'document_url': document_url,
                    'document_type': document_type,
                    'timestamp': datetime.now().isoformat(),
                    'content_length': len(document_content),
                    'extraction_method': 'hybrid',
                    'extraction_sources': extract_result.get_source_summary()
                },
                'product_info': product_info,
                'structure': parsed_data,
                'clauses': clauses,
                'pricing_params': pricing_params,
                'extraction_debug': {
                    'confidence': extract_result.confidence,
                    'provenance': extract_result.provenance,
                    'low_confidence_fields': extract_result.get_low_confidence_fields()
                }
            }

            return result

        except Exception as e:
            logger.warning(f"混合提取失败，回退到规则提取: {e}")
            # 回退到规则提取
            pass

    # 规则提取（原有逻辑）
    logger.info("使用规则提取进行预处理")

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
        'preprocess_id': preprocess_id,
        'metadata': {
            'document_url': document_url,
            'document_type': document_type,
            'timestamp': datetime.now().isoformat(),
            'content_length': len(document_content),
            'extraction_method': 'rule'
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


def clean_html_tables(text: str) -> str:
    """
    清理HTML表格内容，将其转换为可读文本

    Args:
        text: 包含HTML表格的文本

    Returns:
        str: 清理后的文本
    """
    # 移除HTML表格标签
    text = re.sub(r'<table[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</table>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<tr[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<t[dh][^>]*>([^<]*)</t[dh]>', r'\1 ', text, flags=re.IGNORECASE)
    text = re.sub(r'<t[dh][^>]*/>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</t[dh]>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<col[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</col>', '', text, flags=re.IGNORECASE)

    # 清理多余空白
    text = re.sub(r'\n\s*\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    return text.strip()


def extract_clauses(content: str) -> List[Dict[str, Any]]:
    """
    提取条款列表（包含章节信息）

    Args:
        content: 文档内容

    Returns:
        list: 条款字典列表，每个包含 text 和 reference
    """
    clauses = []

    # 先清理HTML表格
    content = clean_html_tables(content)

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
        # 首先按双换行分割段落
        paragraphs = content.split('\n\n')
        for i, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) > 10:  # 降低阈值，保留更多有意义的段落
                clauses.append({
                    'text': para,
                    'reference': f"段落{i+1}"
                })

        # 如果段落数量仍然太少，尝试按单换行分割（针对Markdown文档）
        if len(clauses) < 3:
            clauses = []
            lines = content.split('\n')
            current_section = []
            section_title = ""

            for line in lines:
                line = line.strip()
                # 检测Markdown标题
                if line.startswith('##'):
                    # 保存之前的section
                    if current_section and any(len(l) > 5 for l in current_section):
                        clauses.append({
                            'text': '\n'.join(current_section),
                            'reference': section_title or "未命名段落"
                        })
                    section_title = line
                    current_section = [line]
                elif line:  # 非空行
                    current_section.append(line)

            # 保存最后一个section
            if current_section and any(len(l) > 5 for l in current_section):
                clauses.append({
                    'text': '\n'.join(current_section),
                    'reference': section_title or "未命名段落"
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


def _extract_product_info_from_result(extract_result) -> Dict[str, Any]:
    """从混合提取结果中提取产品信息"""
    from lib.hybrid_extractor import ExtractResult

    if not isinstance(extract_result, ExtractResult):
        return {}

    product_info = {
        'product_name': '',
        'insurance_company': '',
        'product_type': '',
        'insurance_period': '',
        'payment_method': '',
        'age_range': '',
        'occupation_class': ''
    }

    # 优先提取嵌套的 product_info 字典
    if 'product_info' in extract_result.data:
        llm_product_info = extract_result.data['product_info']
        if isinstance(llm_product_info, dict):
            # 从嵌套字典中提取
            product_info['product_name'] = llm_product_info.get('product_name', product_info['product_name'])
            product_info['insurance_company'] = llm_product_info.get('insurance_company', product_info['insurance_company'])
            product_info['product_type'] = llm_product_info.get('product_type', product_info['product_type'])
            product_info['insurance_period'] = llm_product_info.get('insurance_period', product_info['insurance_period'])
            product_info['payment_method'] = llm_product_info.get('payment_method', product_info['payment_method'])

            # 处理年龄范围
            age_min = llm_product_info.get('age_min', '')
            age_max = llm_product_info.get('age_max', '')
            if age_min and age_max:
                product_info['age_range'] = f"{age_min}-{age_max}岁"
            elif age_min:
                product_info['age_range'] = f"{age_min}岁起"
            elif age_max:
                product_info['age_range'] = f"至{age_max}岁"

    # 顶层字段映射（补充或覆盖）
    field_mapping = {
        'product_name': 'product_name',
        'insurance_company': 'insurance_company',
        'product_type': 'product_type',
        'insurance_period': 'insurance_period',
        'payment_method': 'payment_method'
    }

    for target_field, source_field in field_mapping.items():
        if source_field in extract_result.data and not product_info[target_field]:
            # 只有当product_info中该字段为空时才使用顶层字段
            product_info[target_field] = extract_result.data[source_field]

    # 组合年龄范围（顶层补充）
    if not product_info['age_range']:
        if 'age_min' in extract_result.data and 'age_max' in extract_result.data:
            product_info['age_range'] = f"{extract_result.data['age_min']}-{extract_result.data['age_max']}岁"
        elif 'age_min' in extract_result.data:
            product_info['age_range'] = f"{extract_result.data['age_min']}岁起"
        elif 'age_max' in extract_result.data:
            product_info['age_range'] = f"至{extract_result.data['age_max']}岁"

    # 职业类别
    if not product_info['occupation_class']:
        if 'occupation' in extract_result.data:
            product_info['occupation_class'] = extract_result.data['occupation']

    # 清理产品名称中的书名号
    if product_info['product_name']:
        product_info['product_name'] = product_info['product_name'].strip('《》').strip()

    return product_info


def _extract_clauses_from_result(extract_result) -> List[Dict[str, Any]]:
    """从混合提取结果中提取条款列表"""
    from lib.hybrid_extractor import ExtractResult

    if not isinstance(extract_result, ExtractResult):
        return []

    clauses = []

    # 优先查找直接的 clauses 字段（LLM返回的格式）
    if 'clauses' in extract_result.data:
        clauses_value = extract_result.data['clauses']
        if isinstance(clauses_value, list) and clauses_value:
            # LLM返回的数组格式
            for item in clauses_value:
                if isinstance(item, dict) and 'text' in item:
                    clauses.append({
                        'text': item['text'],
                        'reference': item.get('reference', 'unknown')
                    })
            return clauses

    # 查找展开的 clauses_* 格式
    for key, value in extract_result.data.items():
        if key.startswith('clauses_') and isinstance(value, dict):
            if 'text' in value:
                clauses.append({
                    'text': value['text'],
                    'reference': value.get('reference', key)
                })

    # 如果仍然没有找到，回退到查找单独的text字段
    if not clauses:
        for key, value in extract_result.data.items():
            if 'text' in key.lower() and isinstance(value, str) and len(value) > 20:
                clauses.append({
                    'text': value,
                    'reference': extract_result.provenance.get(key, 'unknown')
                })

    return clauses


def _extract_pricing_from_result(extract_result) -> Dict[str, Any]:
    """从混合提取结果中提取定价参数"""
    from lib.hybrid_extractor import ExtractResult

    if not isinstance(extract_result, ExtractResult):
        return {}

    pricing_params = {
        'mortality_rate': None,
        'interest_rate': None,
        'expense_rate': None,
        'premium_rate': None,
        'cash_value': None,
        'dividend': None
    }

    # 直接映射
    field_mapping = {
        'interest_rate': 'interest_rate',
        'expense_rate': 'expense_rate',
        'premium_rate': 'premium_rate'
    }

    for target_field, source_field in field_mapping.items():
        if source_field in extract_result.data:
            value = extract_result.data[source_field]
            # 尝试转换为数值
            try:
                pricing_params[target_field] = float(str(value).replace('%', '').replace('，', '.'))
            except (ValueError, TypeError):
                pricing_params[target_field] = value

    # 现金价值检查
    if 'cash_value' in extract_result.data:
        pricing_params['cash_value'] = bool(extract_result.data['cash_value'])

    return pricing_params


if __name__ == '__main__':
    sys.exit(main())
