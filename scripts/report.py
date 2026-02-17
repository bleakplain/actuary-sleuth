#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成脚本（修复版）
生成结构化的审核报告，支持导出为飞书在线文档
"""
import json
import argparse
import sys
import os
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib import db
from lib.config import get_config


# 飞书 API 配置
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


def get_feishu_access_token(app_id: str, app_secret: str) -> str:
    """获取飞书访问令牌"""
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("code") == 0:
        return data.get("tenant_access_token")
    else:
        raise Exception(f"获取飞书令牌失败: {data.get('msg')}")


def convert_markdown_to_feishu_blocks(markdown: str) -> List[Dict[str, Any]]:
    """
    将 Markdown 内容转换为飞书文档块（使用文本块模拟表格）

    Args:
        markdown: Markdown 格式的文本

    Returns:
        List[Dict]: 飞书文档块列表
    """
    blocks = []
    lines = markdown.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # 空行
        if not line.strip():
            blocks.append(create_text_block(""))
            i += 1
            continue

        # 一级标题
        if line.strip() == "保险产品精算审核报告":
            blocks.append(create_heading_1_block(line.strip()))
        # 二级标题（中文数字）
        elif line.strip().startswith("一、") or line.strip().startswith("二、") or \
             line.strip().startswith("三、") or line.strip().startswith("四、"):
            blocks.append(create_heading_2_block(line.strip()))
        # 表格标题（粗体文本）
        elif line.strip().startswith("**表") and "表" in line:
            blocks.append(create_bold_text_block(line.strip().replace("**", "")))
        # 粗体文本
        elif "**" in line.strip():
            # 简单处理粗体
            content = line.strip().replace("**", "")
            if content:
                blocks.append(create_bold_text_block(content))
        # 分隔线
        elif line.strip().startswith("────"):
            blocks.append(create_divider_block())
        # 表格行
        elif line.strip().startswith("|"):
            # 收集整个表格
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1

            # 解析表格并创建文本块
            table_blocks = parse_table_to_text_blocks(table_lines)
            blocks.extend(table_blocks)
            continue
        # 列表项
        elif line.strip().startswith("- ") or line.strip().startswith("1. "):
            content = line.strip().replace("- ", "").replace("1. ", "")
            blocks.append(create_text_block(f"  • {content}"))
        # 普通文本
        else:
            content = line.strip()
            if content:
                blocks.append(create_text_block(content))

        i += 1

    return blocks


def create_heading_1_block(text: str) -> Dict[str, Any]:
    """创建一级标题块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True,
                        "text_size": "largest"
                    }
                }
            }]
        }
    }


def create_heading_2_block(text: str) -> Dict[str, Any]:
    """创建二级标题块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True,
                        "text_size": "large"
                    }
                }
            }]
        }
    }


def create_bold_text_block(text: str) -> Dict[str, Any]:
    """创建粗体文本块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True
                    }
                }
            }]
        }
    }


def parse_table_to_text_blocks(table_lines: List[str]) -> List[Dict[str, Any]]:
    """将 Markdown 表格解析为飞书文本块（使用等宽字体对齐）"""
    if len(table_lines) < 2:
        return []

    blocks = []
    data_rows = []

    # 解析表格数据
    for line in table_lines:
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            # 跳过分隔行
            if not all(cell.startswith('---') or cell == '' for cell in cells):
                data_rows.append(cells)

    if not data_rows:
        return []

    # 计算每列最大宽度
    col_widths = []
    if data_rows:
        num_cols = len(data_rows[0])
        for col_idx in range(num_cols):
            max_width = 0
            for row in data_rows:
                if col_idx < len(row):
                    max_width = max(max_width, len(row[col_idx]))
            col_widths.append(min(max_width + 2, 30))

    # 为每一行创建文本块
    for row_idx, row in enumerate(data_rows):
        is_header = (row_idx == 0)

        # 对齐列
        row_parts = []
        for col_idx, cell in enumerate(row):
            if col_idx < len(col_widths):
                width = col_widths[col_idx]
                if is_header or col_idx in [1, 2]:
                    cell_text = f"{cell:<{width}}"
                else:
                    cell_text = f"{cell:>{width}}"
                row_parts.append(cell_text)

        row_text = " | ".join(row_parts)

        blocks.append({
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": row_text,
                        "style": {
                            "bold": is_header,
                            "font_family": "Courier New"
                        }
                    }
                }]
            }
        })

    return blocks


def create_heading_1_block(text: str) -> Dict[str, Any]:
    """创建一级标题块"""
    return {
        "block_type": 2,  # heading1
        "heading1": {
            "elements": [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {
                            "bold": True
                        }
                    }
                }
            ]
        }
    }


def create_heading_2_block(text: str) -> Dict[str, Any]:
    """创建二级标题块"""
    return {
        "block_type": 3,  # heading2
        "heading2": {
            "elements": [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {
                            "bold": True
                        }
                    }
                }
            ]
        }
    }


def create_heading_3_block(text: str) -> Dict[str, Any]:
    """创建三级标题块"""
    return {
        "block_type": 4,  # heading3
        "heading3": {
            "elements": [
                {
                    "text_run": {
                        "content": text,
                        "text_element_style": {
                            "bold": True
                        }
                    }
                }
            ]
        }
    }


def create_text_block(text: str) -> Dict[str, Any]:
    """创建文本块"""
    # 处理粗体标记
    content = text.replace('**', '').replace('*', '')
    return {
        "block_type": 2,  # text
        "text": {
            "elements": [
                {
                    "text_run": {
                        "content": content
                    }
                }
            ]
        }
    }


def create_divider_block() -> Dict[str, Any]:
    """创建分隔线块"""
    return {
        "block_type": 13  # divider
    }


def parse_table_to_blocks(table_lines: List[str]) -> List[Dict[str, Any]]:
    """
    将 Markdown 表格解析为飞书表格块

    Args:
        table_lines: 表格行列表

    Returns:
        List[Dict]: 飞书表格块
    """
    if len(table_lines) < 2:
        return []

    # 解析表格数据
    rows = []
    for line in table_lines:
        if line.startswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            # 跳过分隔行
            if not all(cell.startswith('---') or cell == '' for cell in cells):
                rows.append(cells)

    if not rows:
        return []

    # 创建表格块
    table_block = {
        "block_type": 3,  # table
        "table": {
            "table_block_id": f"table_{datetime.now().timestamp()}",
            "column_size": len(rows[0]),
            "row_size": len(rows),
            "header": {
                "cells": [
                    {
                        "column_id": str(i),
                        "value": rows[0][i] if i < len(rows[0]) else ""
                    }
                    for i in range(min(5, len(rows[0])))  # 最多5列
                ]
            }
        }
    }

    # 添加数据行
    for row_idx, row in enumerate(rows[1:20], 1):  # 最多20行
        for col_idx, cell_value in enumerate(row[:5]):  # 最多5列
            table_block["table"][f"row_{row_idx}"] = {
                "cells": [
                    {
                        "column_id": str(col_idx),
                        "value": cell_value
                    }
                    for col_idx in range(min(5, len(row)))
                ]
            }

    return [table_block]


def create_feishu_document(access_token: str, title: str, blocks: List[Dict[str, Any]]) -> str:
    """
    创建飞书在线文档（使用原生格式）

    Args:
        access_token: 飞书访问令牌
        title: 文档标题
        blocks: 飞书文档块列表

    Returns:
        str: 文档 URL
    """
    # 创建文档（使用正确的 API 格式）
    create_url = f"{FEISHU_API_BASE}/docx/v1/documents"
    create_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        # 创建文档（需要提供 title）
        create_payload = {
            "title": title,
            "folder_token": ""  # 空字符串表示根目录
        }

        create_response = requests.post(create_url, headers=create_headers, json=create_payload, timeout=10)

        # 打印调试信息
        print(f"飞书 API 响应状态: {create_response.status_code}", file=sys.stderr)
        if create_response.status_code != 200:
            print(f"飞书 API 响应内容: {create_response.text}", file=sys.stderr)

        create_response.raise_for_status()
        create_data = create_response.json()

        if create_data.get("code") != 0:
            raise Exception(f"创建文档失败: {create_data.get('msg')}")

        document_id = create_data.get("data", {}).get("document", {}).get("document_id")

        if not document_id:
            raise Exception("未能获取文档 ID")

        # 对于新创建的文档，直接使用 document_id 作为 page_block_id
        # 根据飞书API文档，新文档的根块ID就是document_id
        page_block_id = document_id
        print(f"📝 使用文档ID作为页面块 ID: {page_block_id}", file=sys.stderr)

        print(f"准备写入 {len(blocks)} 个块", file=sys.stderr)

        # 批量写入文档内容（每次最多 50 个块，飞书API限制）
        if blocks:
            for i in range(0, len(blocks), 50):
                chunk = blocks[i:i+50]
                update_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks/{page_block_id}/children"
                update_payload = {
                    "children": chunk,
                    "index": -1  # 添加到末尾
                }

                print(f"写入块 {i+1}-{min(i+50, len(blocks))}", file=sys.stderr)
                update_response = requests.post(update_url, headers=create_headers, json=update_payload, timeout=30)
                print(f"块写入响应: {update_response.status_code}", file=sys.stderr)

                if update_response.status_code != 200:
                    print(f"更新文档失败: {update_response.text}", file=sys.stderr)
                    raise Exception(f"写入内容失败: HTTP {update_response.status_code} - {update_response.text}")
                else:
                    update_data = update_response.json()
                    code = update_data.get('code')
                    print(f"块写入结果 code: {code}", file=sys.stderr)
                    if code != 0:
                        msg = update_data.get('msg', 'Unknown error')
                        raise Exception(f"写入内容失败: {msg}")

        # 返回文档链接
        doc_url = f"https://feishu.cn/docx/{document_id}"
        return doc_url

    except requests.exceptions.HTTPError as e:
        raise Exception(f"飞书 API 调用失败: {str(e)} - 响应: {e.response.text if e.response else 'No response'}")
    except Exception as e:
        raise Exception(f"创建飞书文档失败: {str(e)}")


def export_to_feishu(blocks: List[Dict[str, Any]], title: str = None) -> Dict[str, Any]:
    """
    将报告导出为飞书在线文档

    Args:
        blocks: 飞书文档块列表
        title: 文档标题（可选）

    Returns:
        dict: 包含文档 URL 的结果
    """
    config = get_config()

    app_id = config.feishu.app_id
    app_secret = config.feishu.app_secret

    if not app_id or not app_secret:
        return {
            'success': False,
            'error': '缺少飞书配置，请设置 feishu.app_id 和 feishu.app_secret'
        }

    # 设置默认标题
    if title is None:
        title = f"审核报告-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    try:
        # 获取访问令牌
        access_token = get_feishu_access_token(app_id, app_secret)

        # 创建文档
        doc_url = create_feishu_document(access_token, title, blocks)

        return {
            'success': True,
            'document_url': doc_url,
            'title': title,
            'export_time': datetime.now().isoformat()
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Report Generation Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    parser.add_argument('--export-feishu', action='store_true', help='导出为飞书在线文档')
    parser.add_argument('--output', help='输出文件路径（可选）')
    args = parser.parse_args()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 执行业务逻辑
    try:
        result = execute(params)

        # 导出飞书文档
        config = get_config()
        export_feishu = args.export_feishu or config.report.export_feishu

        if export_feishu:
            feishu_result = export_to_feishu(
                result.get('blocks', []),
                title=f"审核报告-{params.get('product_info', {}).get('product_name', '未知产品')}"
            )
            result['feishu_export'] = feishu_result

            if feishu_result.get('success'):
                print(f"✅ 飞书文档已创建: {feishu_result['document_url']}", file=sys.stderr)
            else:
                print(f"❌ 飞书文档创建失败: {feishu_result.get('error')}", file=sys.stderr)

        # 保存到文件
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        # 错误输出
        print(json.dumps({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "details": str(e)
        }, ensure_ascii=False), file=sys.stderr)
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
    if not isinstance(params, dict):
        params = {}

    violations = params.get('violations', [])
    if not isinstance(violations, list):
        violations = []

    pricing_analysis = params.get('pricing_analysis', {})
    if not isinstance(pricing_analysis, dict):
        pricing_analysis = {}

    product_info = params.get('product_info', {})
    if not isinstance(product_info, dict):
        product_info = {}

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

    # 生成报告块
    blocks = create_report(
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
        'blocks': blocks,  # 添加飞书块
        'metadata': {
            'product_name': product_info.get('product_name', '未知产品'),
            'insurance_company': product_info.get('insurance_company', '未知'),
            'product_type': product_info.get('product_type', '未知'),
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
        severity = violation.get('severity', 'low')
        if severity == 'high':
            score -= 20
        elif severity == 'medium':
            score -= 10
        elif severity == 'low':
            score -= 5

    # 根据定价分析扣分
    pricing = pricing_analysis.get('pricing', {})
    if isinstance(pricing, dict):
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category, {})
            if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                score -= 10

    # 确保分数在 0-100 范围内
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


def calculate_risk_score(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> float:
    """
    计算综合风险评分

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果

    Returns:
        float: 风险评分（0-100）
    """
    # 合规风险（40%权重）
    high_count = sum(1 for v in violations if v.get('severity') == 'high')
    medium_count = sum(1 for v in violations if v.get('severity') == 'medium')
    low_count = sum(1 for v in violations if v.get('severity') == 'low')

    compliance_score = max(0, 100 - high_count * 25 - medium_count * 10 - low_count * 5)

    # 定价风险（30%权重）
    pricing_issues = 0
    pricing = pricing_analysis.get('pricing', {})
    if isinstance(pricing, dict):
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category, {})
            if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                pricing_issues += 1
    pricing_score = max(0, 100 - pricing_issues * 20)

    # 条款风险（20%权重）
    clause_score = max(0, 100 - len(violations) * 3)

    # 操作风险（10%权重）
    operational_score = 85  # 基础分

    # 综合风险评分
    risk_score = (
        compliance_score * 0.4 +
        pricing_score * 0.3 +
        clause_score * 0.2 +
        operational_score * 0.1
    )

    return risk_score


def get_risk_level(score: float) -> str:
    """
    获取风险等级

    Args:
        score: 分数

    Returns:
        str: 风险等级
    """
    if score >= 80:
        return "🟢 低风险"
    elif score >= 60:
        return "🟡 中风险"
    elif score >= 40:
        return "🟠 中高风险"
    else:
        return "🔴 高风险"


def get_simple_risk_level(score: float) -> str:
    """获取风险等级（简化版，不含emoji）"""
    if score >= 80:
        return "低风险"
    elif score >= 60:
        return "中等风险"
    else:
        return "高风险"


def get_score_description(score: int) -> str:
    """
    获取评分描述

    Args:
        score: 分数

    Returns:
        str: 评分描述
    """
    if score >= 90:
        return "产品优秀，建议快速通过"
    elif score >= 80:
        return "产品良好，可正常上会"
    elif score >= 70:
        return "产品合格，建议完成修改后上会"
    elif score >= 60:
        return "产品基本合格，需补充说明材料"
    else:
        return "产品不合格，不建议提交审核"


def generate_summary(violations: List[Dict[str, Any]], pricing_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    生成报告摘要

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果

    Returns:
        dict: 关键信息
    """
    # 统计违规数量
    violation_summary = {
        'high': 0,
        'medium': 0,
        'low': 0
    }

    for violation in violations:
        severity = violation.get('severity', 'low')
        if severity in violation_summary:
            violation_summary[severity] += 1

    # 统计定价问题
    pricing_issues = 0
    pricing = pricing_analysis.get('pricing', {})
    if isinstance(pricing, dict):
        for category in ['mortality', 'interest', 'expense']:
            analysis = pricing.get(category, {})
            if isinstance(analysis, dict) and analysis.get('reasonable') is False:
                pricing_issues += 1

    return {
        'total_violations': len(violations),
        'violation_severity': violation_summary,
        'pricing_issues': pricing_issues,
        'has_critical_issues': violation_summary['high'] > 0 or pricing_issues > 1,
        'has_issues': len(violations) > 0 or pricing_issues > 0
    }


def generate_regulation_basis(violations: List[Dict[str, Any]], product_info: Dict[str, Any]) -> List[str]:
    """
    动态生成审核依据

    基于产品类型和违规情况，动态生成适用的法规依据列表

    Args:
        violations: 违规记录列表
        product_info: 产品信息

    Returns:
        list: 法规依据列表
    """
    basis = []

    # 基础法规（始终适用）
    basis.append("《中华人民共和国保险法》")

    # 根据产品类型添加专项法规
    product_type = product_info.get('product_type', '').lower()
    type_regulations = {
        '寿险': '《人身保险公司保险条款和保险费率管理办法》',
        '健康险': '《健康保险管理办法》',
        '意外险': '《意外伤害保险管理办法》',
        '万能险': '《万能型人身保险管理办法》',
        '分红险': '《分红型人身保险管理办法》',
    }

    for key, regulation in type_regulations.items():
        if key in product_type:
            basis.append(regulation)
            break

    # 如果没有匹配到专项法规，添加通用规定
    if len(basis) == 1:
        basis.append('《保险公司管理规定》')

    # 提取违规记录中引用的法规（如果有）
    if violations:
        cited_regs = set()
        for v in violations:
            if v.get('regulation_citation'):
                cited_regs.add(v['regulation_citation'])

        if cited_regs:
            basis.extend(sorted(cited_regs))

    return basis


def generate_conclusion_text(score: int, summary: Dict[str, Any]) -> tuple:
    """
    生成审核结论文本

    Args:
        score: 综合评分
        summary: 报告摘要

    Returns:
        tuple: (opinion, explanation)
    """
    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    total = summary['total_violations']

    # 审核意见决策
    if high_count > 0:
        opinion = "不推荐上会"
        explanation = f"产品存在{high_count}项严重违规，触及监管红线，需完成整改后重新审核"
    elif score >= 90:
        opinion = "推荐通过"
        explanation = "产品符合所有监管要求，未发现违规问题"
    elif score >= 75:
        opinion = "条件推荐"
        explanation = f"产品整体符合要求，存在{medium_count}项中等问题，建议完成修改后提交审核"
    elif score >= 60:
        opinion = "需补充材料"
        explanation = f"产品存在{total}项问题，建议补充说明材料后复审"
    else:
        opinion = "不予推荐"
        explanation = "产品合规性不足，不建议提交审核"

    return opinion, explanation


def generate_report_content(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    score: int,
    grade: str,
    summary: Dict[str, Any],
    params: Dict[str, Any] = None
) -> str:
    """
    生成精算审核报告

    动态生成，基于实际审核情况：
    - 有问题才显示问题章节
    - 审核依据根据产品类型动态生成
    - 表格只在有数据时显示

    结构：
    1. 审核结论（始终显示）
    2. 问题详情及依据（有问题时显示）
    3. 修改建议（有问题时显示）
    4. 报告信息（始终显示）
    """
    if params is None:
        params = {}

    lines = []
    report_id = f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    product_name = product_info.get('product_name', '未知产品')
    company_name = product_info.get('insurance_company', '未知保险公司')

    # ========== 标题 ==========
    lines.append("保险产品精算审核报告")
    lines.append("")
    lines.append("────────────────────────────────────────")
    lines.append("")

    # 产品信息
    lines.append(f"产品名称：{product_name}")
    lines.append(f"保险公司：{company_name}")
    lines.append(f"产品类型：{product_info.get('product_type', '未知')}")
    lines.append(f"审核日期：{datetime.now().strftime('%Y年%m月%d日')}")
    lines.append(f"报告编号：{report_id}")
    lines.append("")
    lines.append("────────────────────────────────────────")
    lines.append("")

    # ========== 审核结论（始终显示） ==========
    lines.extend(_generate_conclusion_section(score, grade, summary))
    lines.append("")

    # ========== 问题详情（有问题时显示） ==========
    if summary.get('has_issues', False):
        lines.extend(_generate_details_section(violations, pricing_analysis, product_info, summary))
        lines.append("")

    # ========== 修改建议（有问题时显示） ==========
    if summary.get('has_issues', False):
        lines.extend(_generate_suggestions_section(violations, summary))
        lines.append("")

    # ========== 报告信息（始终显示） ==========
    lines.extend(_generate_info_section(report_id))
    lines.append("")

    return '\n'.join(lines)


def _generate_conclusion_section(score: int, grade: str, summary: Dict[str, Any]) -> List[str]:
    """生成审核结论章节"""
    lines = []

    lines.append("一、审核结论")
    lines.append("")

    # 生成审核意见
    opinion, explanation = generate_conclusion_text(score, summary)

    lines.append(f"**审核意见**：{opinion}")
    lines.append("")
    lines.append(f"**说明**：{explanation}")
    lines.append("")

    # 关键数据表格
    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    low_count = summary['violation_severity']['low']
    total = summary['total_violations']
    pricing_issue_count = summary.get('pricing_issues', 0)

    lines.append("**表1-1：关键指标汇总表**")
    lines.append("")
    lines.append("| 序号 | 指标项 | 结果 | 说明 |")
    lines.append("|:----:|:------|:-----|:-----|")
    lines.append(f"| 1 | 综合评分 | {score}分 | {get_score_description(score)} |")
    lines.append(f"| 2 | 合规评级 | {grade} | 基于违规数量和严重程度评定 |")
    lines.append(f"| 3 | 违规总数 | {total}项 | 严重{high_count}项，中等{medium_count}项，轻微{low_count}项 |")
    lines.append(f"| 4 | 定价评估 | {'合理' if pricing_issue_count == 0 else '需关注'} | {pricing_issue_count}项定价参数需关注 |")
    lines.append("")
    lines.append("────────────────────────────────────────")

    return lines


def _generate_details_section(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    summary: Dict[str, Any]
) -> List[str]:
    """生成问题详情章节"""
    lines = []

    lines.append("二、问题详情及依据")
    lines.append("")

    # 生成审核依据（动态）
    regulation_basis = generate_regulation_basis(violations, product_info)
    lines.append("**审核依据**")
    lines.append("")
    for i, reg in enumerate(regulation_basis, 1):
        lines.append(f"{i}. {reg}")
    lines.append("")
    lines.append("────────────────────────────────────────")
    lines.append("")

    # 按严重程度分组
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']

    # 违规统计表
    lines.append("**表2-1：违规级别统计表**")
    lines.append("")
    lines.append("| 序号 | 违规级别 | 数量 | 占比 |")
    lines.append("|:----:|:--------|:----:|:----:|")

    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    low_count = summary['violation_severity']['low']
    total = summary['total_violations']

    if total > 0:
        high_percent = f"{high_count/total*100:.1f}%"
        medium_percent = f"{medium_count/total*100:.1f}%"
        low_percent = f"{low_count/total*100:.1f}%"
    else:
        high_percent = "0%"
        medium_percent = "0%"
        low_percent = "0%"

    lines.append(f"| 1 | 严重 | {high_count}项 | {high_percent} |")
    lines.append(f"| 2 | 中等 | {medium_count}项 | {medium_percent} |")
    lines.append(f"| 3 | 轻微 | {low_count}项 | {low_percent} |")
    lines.append(f"| **合计** | **总计** | **{total}项** | **100%** |")
    lines.append("")

    # 严重违规明细表
    if high_violations:
        lines.append("**表2-2：严重违规明细表**")
        lines.append("")
        lines.append("| 序号 | 规则编号 | 违规描述 | 涉及条款 | 整改建议 |")
        lines.append("|:----:|:--------|:---------|:--------|:---------|")
        for i, v in enumerate(high_violations[:20], 1):
            desc = v.get('description', '未知')[:25]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            remediation = v.get('remediation', '无')[:20]
            lines.append(f"| {i} | {v.get('rule', 'N/A')} | {desc}... | {clause} | {remediation}... |")
        lines.append("")

    # 中等违规明细表
    if medium_violations:
        lines.append("**表2-3：中等违规明细表**")
        lines.append("")
        lines.append("| 序号 | 规则编号 | 违规描述 | 涉及条款 | 整改建议 |")
        lines.append("|:----:|:--------|:---------|:--------|:---------|")
        for i, v in enumerate(medium_violations[:10], 1):
            desc = v.get('description', '未知')[:25]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            remediation = v.get('remediation', '无')[:20]
            lines.append(f"| {i} | {v.get('rule', 'N/A')} | {desc}... | {clause} | {remediation}... |")
        lines.append("")

    # 定价问题
    pricing = pricing_analysis.get('pricing', {})
    if isinstance(pricing, dict):
        pricing_issues = []
        for category in ['interest', 'expense']:
            analysis = pricing.get(category)
            if analysis and not analysis.get('reasonable', True):
                pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}：{analysis.get('note', '不符合监管要求')}")

        if pricing_issues:
            lines.append("**表2-4：定价问题汇总表**")
            lines.append("")
            lines.append("| 序号 | 问题类型 | 问题描述 |")
            lines.append("|:----:|:---------|:---------|")
            for i, issue in enumerate(pricing_issues, 1):
                lines.append(f"| {i} | {'预定利率' if '预定利率' in issue else '费用率'} | {issue.split('：')[1] if '：' in issue else issue} |")
            lines.append("")

    lines.append("────────────────────────────────────────")

    return lines


def _generate_suggestions_section(violations: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[str]:
    """生成修改建议章节"""
    lines = []

    lines.append("三、修改建议")
    lines.append("")

    # 按严重程度分组
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']

    if high_violations:
        lines.append("**表3-1：P0级整改事项表（必须立即整改）**")
        lines.append("")
        lines.append("| 序号 | 整改事项 | 涉及条款 |")
        lines.append("|:----:|:---------|:--------|")
        for i, v in enumerate(high_violations[:10], 1):
            desc = v.get('description', '未知')[:30]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            lines.append(f"| {i} | {desc} | {clause} |")
        lines.append("")

    if medium_violations:
        lines.append("**表3-2：P1级整改事项表（建议尽快整改）**")
        lines.append("")
        lines.append("| 序号 | 整改事项 | 涉及条款 |")
        lines.append("|:----:|:---------|:--------|")
        for i, v in enumerate(medium_violations[:5], 1):
            desc = v.get('description', '未知')[:30]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            lines.append(f"| {i} | {desc} | {clause} |")
        lines.append("")

    lines.append("────────────────────────────────────────")

    return lines


def _generate_info_section(report_id: str) -> List[str]:
    """生成报告信息章节"""
    lines = []

    lines.append("四、报告信息")
    lines.append("")
    lines.append(f"- 报告编号：{report_id}")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
    lines.append("- 审核系统：Actuary Sleuth v3.0")
    lines.append("")

    lines.append("**免责声明**")
    lines.append("")
    lines.append("本报告由AI精算审核系统生成，仅供内部参考。最终决策应以产品委员会审议结果和监管部门审批意见为准。")
    lines.append("")

    return lines


# ========== 报告块创建函数 ==========

def create_report(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    score: int,
    grade: str,
    summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    生成报告块（飞书格式）

    动态生成，基于实际审核情况：
    - 有问题才显示问题章节
    - 审核依据根据产品类型动态生成
    - 表格只在有数据时显示

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果
        product_info: 产品信息
        score: 分数
        grade: 评级
        summary: 关键信息

    Returns:
        list: 飞书文档块列表
    """
    blocks = []
    report_id = f"RPT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # ========== 标题 ==========
    blocks.append(create_heading_1("保险产品精算审核报告"))
    blocks.append(create_text(""))
    blocks.append(create_text("────────────────────────────────────────"))
    blocks.append(create_text(""))

    # 产品信息
    product_name = product_info.get('product_name', '未知产品')
    company_name = product_info.get('insurance_company', '未知保险公司')
    product_type = product_info.get('product_type', '未知')

    blocks.append(create_text(f"产品名称：{product_name}"))
    blocks.append(create_text(f"保险公司：{company_name}"))
    blocks.append(create_text(f"产品类型：{product_type}"))
    blocks.append(create_text(f"审核日期：{datetime.now().strftime('%Y年%m月%d日')}"))
    blocks.append(create_text(f"报告编号：{report_id}"))
    blocks.append(create_text(""))
    blocks.append(create_text("────────────────────────────────────────"))
    blocks.append(create_text(""))

    # ========== 审核结论（始终显示） ==========
    blocks.extend(_create_conclusion_blocks(score, grade, summary))
    blocks.append(create_text(""))

    # ========== 问题详情（有问题时显示） ==========
    if summary.get('has_issues', False):
        blocks.extend(_create_details_blocks(violations, pricing_analysis, product_info, summary))
        blocks.append(create_text(""))

    # ========== 修改建议（有问题时显示） ==========
    if summary.get('has_issues', False):
        blocks.extend(_create_suggestions_blocks(violations, summary))
        blocks.append(create_text(""))

    # ========== 报告信息（始终显示） ==========
    blocks.extend(_create_info_blocks(report_id))
    blocks.append(create_text(""))

    return blocks


def _create_conclusion_blocks(score: int, grade: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """创建审核结论章节块"""
    blocks = []

    blocks.append(create_heading_2("一、审核结论"))
    blocks.append(create_text(""))

    # 生成审核意见
    opinion, explanation = generate_conclusion_text(score, summary)

    blocks.append(create_bold_text(f"审核意见：{opinion}"))
    blocks.append(create_text(""))
    blocks.append(create_text(f"说明：{explanation}"))
    blocks.append(create_text(""))

    # 关键指标表格
    blocks.append(create_text("表1-1：关键指标汇总表"))
    blocks.append(create_text(""))

    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    low_count = summary['violation_severity']['low']
    total = summary['total_violations']
    pricing_issue_count = summary.get('pricing_issues', 0)

    key_metrics_data = [
        ["序号", "指标项", "结果", "说明"],
        ["1", "综合评分", f"{score}分", get_score_description(score)],
        ["2", "合规评级", grade, "基于违规数量和严重程度评定"],
        ["3", "违规总数", f"{total}项", f"严重{high_count}项，中等{medium_count}项，轻微{low_count}项"],
        ["4", "定价评估", "合理" if pricing_issue_count == 0 else "需关注", f"{pricing_issue_count}项定价参数需关注"]
    ]
    blocks.extend(create_table_blocks(key_metrics_data))
    blocks.append(create_text(""))
    blocks.append(create_text("────────────────────────────────────────"))

    return blocks


def _create_details_blocks(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any],
    summary: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """创建问题详情章节块"""
    blocks = []

    blocks.append(create_heading_2("二、问题详情及依据"))
    blocks.append(create_text(""))

    # 生成审核依据（动态）
    regulation_basis = generate_regulation_basis(violations, product_info)
    blocks.append(create_text("审核依据"))
    blocks.append(create_text(""))
    for reg in regulation_basis:
        blocks.append(create_text(reg))
    blocks.append(create_text(""))
    blocks.append(create_text("────────────────────────────────────────"))
    blocks.append(create_text(""))

    # 违规统计表
    blocks.append(create_text("表2-1：违规级别统计表"))
    blocks.append(create_text(""))

    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    low_count = summary['violation_severity']['low']
    total = summary['total_violations']

    if total > 0:
        high_percent = f"{high_count/total*100:.1f}%"
        medium_percent = f"{medium_count/total*100:.1f}%"
        low_percent = f"{low_count/total*100:.1f}%"
    else:
        high_percent = "0%"
        medium_percent = "0%"
        low_percent = "0%"

    violation_stats_data = [
        ["序号", "违规级别", "数量", "占比"],
        ["1", "严重", f"{high_count}项", high_percent],
        ["2", "中等", f"{medium_count}项", medium_percent],
        ["3", "轻微", f"{low_count}项", low_percent],
        ["合计", "总计", f"{total}项", "100%"]
    ]
    blocks.extend(create_table_blocks(violation_stats_data))
    blocks.append(create_text(""))

    # 按严重程度分组
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']

    # 严重违规明细表
    if high_violations:
        blocks.append(create_text("表2-2：严重违规明细表"))
        blocks.append(create_text(""))

        high_violation_data = [["序号", "规则编号", "违规描述", "涉及条款", "整改建议"]]
        for i, v in enumerate(high_violations[:20], 1):
            desc = v.get('description', '未知')[:25]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            remediation = v.get('remediation', '无')[:20]
            high_violation_data.append([str(i), v.get('rule', 'N/A'), f"{desc}...", clause, f"{remediation}..."])

        blocks.extend(create_table_blocks(high_violation_data))
        blocks.append(create_text(""))

    # 中等违规明细表
    if medium_violations:
        blocks.append(create_text("表2-3：中等违规明细表"))
        blocks.append(create_text(""))

        medium_violation_data = [["序号", "规则编号", "违规描述", "涉及条款", "整改建议"]]
        for i, v in enumerate(medium_violations[:10], 1):
            desc = v.get('description', '未知')[:25]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            remediation = v.get('remediation', '无')[:20]
            medium_violation_data.append([str(i), v.get('rule', 'N/A'), f"{desc}...", clause, f"{remediation}..."])

        blocks.extend(create_table_blocks(medium_violation_data))
        blocks.append(create_text(""))

    # 定价问题
    pricing = pricing_analysis.get('pricing', {})
    if isinstance(pricing, dict):
        pricing_issues = []
        for category in ['interest', 'expense']:
            analysis = pricing.get(category)
            if analysis and not analysis.get('reasonable', True):
                pricing_issues.append(f"{'预定利率' if category == 'interest' else '费用率'}：{analysis.get('note', '不符合监管要求')}")

        if pricing_issues:
            blocks.append(create_text("表2-4：定价问题汇总表"))
            blocks.append(create_text(""))

            pricing_data = [["序号", "问题类型", "问题描述"]]
            for i, issue in enumerate(pricing_issues, 1):
                pricing_data.append([str(i), '预定利率' if '预定利率' in issue else '费用率', issue.split('：')[1] if '：' in issue else issue])

            blocks.extend(create_table_blocks(pricing_data))
            blocks.append(create_text(""))

    blocks.append(create_text("────────────────────────────────────────"))

    return blocks


def _create_suggestions_blocks(violations: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """创建修改建议章节块"""
    blocks = []

    blocks.append(create_heading_2("三、修改建议"))
    blocks.append(create_text(""))

    # 按严重程度分组
    high_violations = [v for v in violations if v.get('severity') == 'high']
    medium_violations = [v for v in violations if v.get('severity') == 'medium']

    if high_violations:
        blocks.append(create_text("表3-1：P0级整改事项表（必须立即整改）"))
        blocks.append(create_text(""))

        p0_data = [["序号", "整改事项", "涉及条款"]]
        for i, v in enumerate(high_violations[:10], 1):
            desc = v.get('description', '未知')[:30]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            p0_data.append([str(i), desc, clause])

        blocks.extend(create_table_blocks(p0_data))
        blocks.append(create_text(""))

    if medium_violations:
        blocks.append(create_text("表3-2：P1级整改事项表（建议尽快整改）"))
        blocks.append(create_text(""))

        p1_data = [["序号", "整改事项", "涉及条款"]]
        for i, v in enumerate(medium_violations[:5], 1):
            desc = v.get('description', '未知')[:30]
            clause = f"第{v.get('clause_index', '?') + 1}条"
            p1_data.append([str(i), desc, clause])

        blocks.extend(create_table_blocks(p1_data))
        blocks.append(create_text(""))

    blocks.append(create_text("────────────────────────────────────────"))

    return blocks


def _create_info_blocks(report_id: str) -> List[Dict[str, Any]]:
    """创建报告信息章节块"""
    blocks = []

    blocks.append(create_heading_2("四、报告信息"))
    blocks.append(create_text(""))
    blocks.append(create_text(f"报告编号：{report_id}"))
    blocks.append(create_text(f"生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}"))
    blocks.append(create_text("审核系统：Actuary Sleuth v3.0"))
    blocks.append(create_text(""))

    blocks.append(create_text("免责声明"))
    blocks.append(create_text(""))
    blocks.append(create_text("本报告由AI精算审核系统生成，仅供内部参考。"))
    blocks.append(create_text("最终决策应以产品委员会审议结果和监管部门审批意见为准。"))
    blocks.append(create_text(""))

    return blocks


def create_heading_1(text: str) -> Dict[str, Any]:
    """创建一级标题块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True,
                        "text_size": "largest"
                    }
                }
            }]
        }
    }


def create_heading_2(text: str) -> Dict[str, Any]:
    """创建二级标题块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True,
                        "text_size": "large"
                    }
                }
            }]
        }
    }


def create_text(text: str) -> Dict[str, Any]:
    """创建文本块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {}
                }
            }]
        }
    }


def create_bold_text(text: str) -> Dict[str, Any]:
    """创建粗体文本块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": text,
                    "style": {
                        "bold": True
                    }
                }
            }]
        }
    }


def create_table_blocks(table_data: List[List[str]]) -> List[Dict[str, Any]]:
    """创建表格块（使用文本块模拟）"""
    blocks = []

    for row_idx, row in enumerate(table_data):
        is_header = (row_idx == 0)

        # 对齐列（使用固定宽度）
        col_widths = [8, 20, 15, 15, 20]
        row_parts = []
        for col_idx, cell in enumerate(row):
            if col_idx < len(col_widths):
                width = col_widths[col_idx]
                # 左对齐或右对齐
                if is_header or col_idx in [0]:
                    cell_text = f"{cell:<{width}}"
                else:
                    cell_text = f"{cell:>{width}}"
                row_parts.append(cell_text)

        row_text = " | ".join(row_parts)

        blocks.append({
            "block_type": 2,
            "text": {
                "elements": [{
                    "text_run": {
                        "content": row_text,
                        "style": {
                            "bold": is_header,
                            "font_family": "Courier New"
                        }
                    }
                }]
            }
        })

    return blocks


def get_score_description(score: int) -> str:
    """获取评分描述"""
    if score >= 90:
        return "产品优秀，建议快速通过"
    elif score >= 80:
        return "产品良好，可正常上会"
    elif score >= 70:
        return "产品合格，建议完成修改后上会"
    elif score >= 60:
        return "产品基本合格，需补充说明材料"
    else:
        return "产品不合格，不建议提交审核"


if __name__ == '__main__':
    sys.exit(main())
