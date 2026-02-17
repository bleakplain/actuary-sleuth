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


# 飞书 API 配置
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

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


def convert_markdown_to_feishu_blocks(content: str) -> List[Dict[str, Any]]:
    """
    将 Markdown 内容转换为飞书原生格式块

    Args:
        content: Markdown 格式的文本内容

    Returns:
        list: 飞书块列表
    """
    lines = content.split('\n')
    feishu_blocks = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # 跳过空行
        if not line:
            i += 1
            continue

        # 处理分隔符
        if line == '---':
            # 创建分隔线块（使用空文本块模拟）
            feishu_blocks.append({
                "block_type": 2,  # Text
                "text": {
                    "elements": [{
                        "text_run": {
                            "content": "　",
                            "style": {}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理一级标题 (# )
        if line.startswith('# ') and not line.startswith('## '):
            text_content = line[2:].strip()
            feishu_blocks.append({
                "block_type": 3,  # Heading 1
                "heading1": {
                    "elements": [{
                        "text_run": {
                            "content": text_content,
                            "style": {}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理二级标题 (## )
        if line.startswith('## ') and not line.startswith('### '):
            text_content = line[3:].strip()
            # 移除emoji前缀（如果有）
            if text_content.startswith(('📋', '📊', '⚠️', '💰', '📝')):
                text_content = text_content[1:].strip()
            feishu_blocks.append({
                "block_type": 4,  # Heading 2
                "heading2": {
                    "elements": [{
                        "text_run": {
                            "content": text_content,
                            "style": {}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理三级标题 (### )
        if line.startswith('### ') and not line.startswith('#### '):
            text_content = line[4:].strip()
            # 移除emoji前缀（如果有）
            if text_content.startswith(('🔴', '🟡', '🟢', '📈', '💵', '💸', '🌟', '✅', '⚠️', '❌', '🚫')):
                text_content = text_content[1:].strip()
            feishu_blocks.append({
                "block_type": 5,  # Heading 3
                "heading3": {
                    "elements": [{
                        "text_run": {
                            "content": text_content,
                            "style": {}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理四级标题 (#### )
        if line.startswith('#### '):
            text_content = line[5:].strip()
            # 移除数字前缀
            if text_content and text_content[0].isdigit():
                parts = text_content.split('.', 1)
                if len(parts) == 2:
                    text_content = parts[1].strip()
            feishu_blocks.append({
                "block_type": 2,  # Text
                "text": {
                    "elements": [{
                        "text_run": {
                            "content": text_content,
                            "style": {"bold": True}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理引用 (> )
        if line.startswith('>'):
            text_content = line[1:].strip()
            # 移除emoji前缀（如果有）
            if text_content.startswith(('💡', '📌', '⚠️')):
                text_content = text_content[1:].strip()
            # 移除markdown加粗标记
            text_content = text_content.replace('**', '').strip()
            feishu_blocks.append({
                "block_type": 2,  # Text
                "text": {
                    "elements": [{
                        "text_run": {
                            "content": f" {text_content}",
                            "style": {}
                        }
                    }]
                }
            })
            i += 1
            continue

        # 处理表格行 - 暂时简化为文本格式
        if line.startswith('|'):
            # 收集整个表格
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1

            # 解析表格并转换为格式化文本
            if len(table_lines) > 2:  # 至少包含表头和分隔符
                table_data = []
                for table_line in table_lines:
                    if table_line.startswith('|---'):
                        continue  # 跳过分隔符行
                    cells = [cell.strip().replace('**', '') for cell in table_line.split('|')[1:-1]]
                    table_data.append(cells)

                if table_data:
                    # 为每个表格行创建格式化文本块
                    for row_idx, row_data in enumerate(table_data):
                        # 计算每列的最大宽度
                        if row_idx == 0:
                            # 表头行，添加强调
                            row_text = " | ".join([f"【{cell}】" for cell in row_data])
                            feishu_blocks.append({
                                "block_type": 2,  # Text
                                "text": {
                                    "elements": [{
                                        "text_run": {
                                            "content": row_text,
                                            "style": {"bold": True}
                                        }
                                    }]
                                }
                            })
                        else:
                            # 数据行
                            row_text = " | ".join(row_data)
                            feishu_blocks.append({
                                "block_type": 2,  # Text
                                "text": {
                                    "elements": [{
                                        "text_run": {
                                            "content": row_text,
                                            "style": {}
                                        }
                                    }]
                                }
                            })

                    # 添加空行分隔
                    feishu_blocks.append({
                        "block_type": 2,  # Text
                        "text": {
                            "elements": [{
                                "text_run": {
                                    "content": "",
                                    "style": {}
                                }
                            }]
                        }
                    })
            continue

        # 处理普通文本
        if line:
            # 处理列表项
            if line.startswith('-'):
                text_content = line[1:].strip()
                # 移除markdown加粗标记
                text_content = text_content.replace('**', '').replace('`', '').strip()
                feishu_blocks.append({
                    "block_type": 2,  # Text
                    "text": {
                        "elements": [{
                            "text_run": {
                                "content": f"• {text_content}",
                                "style": {}
                            }
                        }]
                    }
                })
            elif line[0].isdigit() and '.' in line[:5]:
                # 有序列表
                text_content = line.split('.', 1)[1].strip() if '.' in line else line
                text_content = text_content.replace('**', '').replace('`', '').strip()
                feishu_blocks.append({
                    "block_type": 2,  # Text
                    "text": {
                        "elements": [{
                            "text_run": {
                                "content": f"{line.split('.')[0]}. {text_content}",
                                "style": {}
                            }
                        }]
                    }
                })
            else:
                # 普通段落
                text_content = line.replace('**', '').replace('`', '').strip()
                # 移除emoji前缀（如果有）
                if text_content and text_content[0] in ('📌', '📋', '▸', '•', '💡'):
                    text_content = text_content[1:].strip()

                feishu_blocks.append({
                    "block_type": 2,  # Text
                    "text": {
                        "elements": [{
                            "text_run": {
                                "content": text_content,
                                "style": {}
                            }
                        }]
                    }
                })

        i += 1

    return feishu_blocks


def get_feishu_access_token(app_id: str, app_secret: str) -> str:
    """
    获取飞书访问令牌

    Args:
        app_id: 飞书应用 ID
        app_secret: 飞书应用密钥

    Returns:
        str: 访问令牌
    """
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("code") == 0:
            return data.get("tenant_access_token")
        else:
            raise Exception(f"获取飞书令牌失败: {data.get('msg')}")
    except Exception as e:
        raise Exception(f"飞书 API 调用失败: {str(e)}")


def create_feishu_document(access_token: str, title: str, content: str) -> str:
    """
    创建飞书在线文档（使用原生格式）

    Args:
        access_token: 飞书访问令牌
        title: 文档标题
        content: 文档内容（Markdown 格式）

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

        # 将 Markdown 内容转换为飞书原生格式块
        # 使用正确的块类型：heading1 (block_type 2), heading2 (block_type 3), heading3 (block_type 4)
        feishu_blocks = convert_markdown_to_feishu_blocks(content)

        print(f"准备写入 {len(feishu_blocks)} 个块", file=sys.stderr)

        # 批量写入文档内容（每次最多 50 个块，飞书API限制）
        if feishu_blocks:
            for i in range(0, len(feishu_blocks), 50):
                chunk = feishu_blocks[i:i+50]
                update_url = f"{FEISHU_API_BASE}/docx/v1/documents/{document_id}/blocks/{page_block_id}/children"
                update_payload = {
                    "children": chunk,
                    "index": -1  # 添加到末尾
                }

                print(f"写入块 {i+1}-{min(i+50, len(feishu_blocks))}", file=sys.stderr)
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


def export_to_feishu(content: str, title: str = None, config: Dict = None) -> Dict[str, Any]:
    """
    将报告导出为飞书在线文档

    Args:
        content: 报告内容（Markdown 格式）
        title: 文档标题（可选）
        config: 飞书配置 {app_id, app_secret}

    Returns:
        dict: 包含文档 URL 的结果
    """
    # 从配置或环境变量获取飞书凭证
    if config is None:
        config = {}

    app_id = config.get('feishu', {}).get('app_id') or os.getenv('FEISHU_APP_ID')
    app_secret = config.get('feishu', {}).get('app_secret') or os.getenv('FEISHU_APP_SECRET')

    if not app_id or not app_secret:
        return {
            'success': False,
            'error': '缺少飞书配置，请设置 feishu_app_id 和 feishu_app_secret'
        }

    # 设置默认标题
    if title is None:
        title = f"审核报告-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    try:
        # 获取访问令牌
        access_token = get_feishu_access_token(app_id, app_secret)

        # 创建文档
        doc_url = create_feishu_document(access_token, title, content)

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

    # 自动读取配置
    config = load_config()

    # 读取输入
    with open(args.input, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 执行业务逻辑
    try:
        result = execute(params)

        # 导出飞书文档
        export_feishu = args.export_feishu or config.get('report', {}).get('export_feishu', False)

        if export_feishu:
            feishu_result = export_to_feishu(
                result['content'],
                title=f"审核报告-{params.get('product_info', {}).get('product_name', '未知产品')}",
                config=config
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
    生成报告文本内容（优化版 Markdown 格式，适配飞书文档）

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果
        product_info: 产品信息
        score: 分数
        grade: 评级
        summary: 关键信息

    Returns:
        str: 报告内容（Markdown 格式）
    """
    lines = []

    # 报告标题（居中大标题效果）
    lines.append("# 保险产品合规性审核报告")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 基本信息区域（使用表格形式，更清晰）
    lines.append("## 📋 产品基本信息")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| **产品名称** | {product_info.get('product_name', '未知产品')} |")
    lines.append(f"| **保险公司** | {product_info.get('insurance_company', '未知')} |")
    lines.append(f"| **产品类型** | {product_info.get('product_type', '未知')} |")
    lines.append(f"| **审核时间** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
    lines.append("")

    # 审核结果概览（使用emoji图标和卡片式布局）
    lines.append("## 📊 审核结果概览")
    lines.append("")

    # 评级emoji
    grade_emoji = {
        '优秀': '🟢',
        '良好': '🟡',
        '合格': '🟠',
        '不合格': '🔴'
    }.get(grade, '⚪')

    lines.append(f"### {grade_emoji} 综合评级：{grade}")
    lines.append("")
    lines.append(f"> **综合评分**：{score} 分 / 100 分")
    lines.append("")

    # 违规统计（使用表格）
    lines.append("| 违规级别 | 数量 | 占比 |")
    lines.append("|----------|------|------|")

    total = summary['total_violations']
    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    low_count = summary['violation_severity']['low']

    high_percent = f"{high_count/total*100:.1f}%" if total > 0 else "0%"
    medium_percent = f"{medium_count/total*100:.1f}%" if total > 0 else "0%"
    low_percent = f"{low_count/total*100:.1f}%" if total > 0 else "0%"

    lines.append(f"| 🔴 严重违规 | **{high_count}** 项 | {high_percent} |")
    lines.append(f"| 🟡 中等违规 | **{medium_count}** 项 | {medium_percent} |")
    lines.append(f"| 🟢 轻微违规 | **{low_count}** 项 | {low_percent} |")
    lines.append(f"| 📊 违规总数 | **{total}** 项 | 100% |")
    lines.append("")

    # 违规详情
    if violations:
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 违规详情")
        lines.append("")

        # 按严重程度分组
        high_violations = [v for v in violations if v.get('severity') == 'high']
        medium_violations = [v for v in violations if v.get('severity') == 'medium']
        low_violations = [v for v in violations if v.get('severity') == 'low']

        # 严重违规
        if high_violations:
            lines.append("### 🔴 严重违规")
            lines.append("")
            lines.append("> 需要立即整改的问题")
            lines.append("")

            for i, violation in enumerate(high_violations[:10], 1):
                lines.append(f"#### {i}. {violation.get('description', '未知违规')}")
                lines.append("")
                lines.append(f"| 项目 | 内容 |")
                lines.append("|------|------|")
                lines.append(f"| **规则编号** | `{violation.get('rule', 'N/A')}` |")
                lines.append(f"| **整改建议** | {violation.get('remediation', '无')} |")
                lines.append("")

        # 中等违规
        if medium_violations:
            lines.append("### 🟡 中等违规")
            lines.append("")

            for i, violation in enumerate(medium_violations[:5], 1):
                lines.append(f"**{i}. {violation.get('description', '未知违规')}**")
                lines.append("")
                lines.append(f"> 规则：`{violation.get('rule', 'N/A')}` | 建议：{violation.get('remediation', '无')}")
                lines.append("")

        # 轻微违规
        if low_violations:
            lines.append("### 🟢 轻微违规")
            lines.append("")

            for i, violation in enumerate(low_violations[:5], 1):
                lines.append(f"{i}. **{violation.get('description', '未知违规')}**")
                lines.append(f"   - 规则编号：`{violation.get('rule', 'N/A')}`")
                lines.append(f"   - 整改建议：{violation.get('remediation', '无')}")
                lines.append("")

    # 定价分析
    if pricing_analysis:
        lines.append("---")
        lines.append("")
        lines.append("## 💰 定价合理性分析")
        lines.append("")

        pricing = pricing_analysis.get('pricing', {})
        if isinstance(pricing, dict):
            for category in ['mortality', 'interest', 'expense']:
                analysis = pricing.get(category)
                if analysis:
                    category_info = {
                        'mortality': {'name': '死亡率/发生率', 'icon': '📈'},
                        'interest': {'name': '预定利率', 'icon': '💵'},
                        'expense': {'name': '费用率', 'icon': '💸'}
                    }.get(category, {'name': category, 'icon': '📊'})

                    icon = category_info['icon']
                    name = category_info['name']
                    is_reasonable = analysis.get('reasonable', True)
                    status_icon = '✅' if is_reasonable else '❌'
                    status_text = '合理' if is_reasonable else '不合理'

                    lines.append(f"### {icon} {name}")
                    lines.append("")
                    lines.append(f"| 指标 | 数值 |")
                    lines.append("|------|------|")
                    lines.append(f"| **当前值** | {analysis.get('value', 'N/A')} |")
                    lines.append(f"| **基准值** | {analysis.get('benchmark', 'N/A')} |")
                    lines.append(f"| **偏差** | {analysis.get('deviation', 'N/A')}% |")
                    lines.append(f"| **评估** | {status_icon} **{status_text}** |")
                    lines.append("")

                    if analysis.get('note'):
                        lines.append(f"> 💡 **说明**：{analysis['note']}")
                        lines.append("")

    # 审核结论
    lines.append("---")
    lines.append("")
    lines.append("## 📝 审核结论")
    lines.append("")

    # 根据评级生成结论
    if summary['has_critical_issues']:
        conclusion_icon = "🚫"
        conclusion_text = "该产品存在严重合规问题，建议进行重大修改后再提交审核。"
        conclusion_color = "🔴"
    elif score >= 90:
        conclusion_icon = "🌟"
        conclusion_text = "该产品合规性优秀，符合监管要求，可以推向市场。"
        conclusion_color = "🟢"
    elif score >= 75:
        conclusion_icon = "✅"
        conclusion_text = "该产品整体合规性良好，建议对指出的问题进行修改后可以推向市场。"
        conclusion_color = "🟢"
    elif score >= 60:
        conclusion_icon = "⚠️"
        conclusion_text = "该产品基本合规，但存在一些需要改进的问题，建议修改后再推向市场。"
        conclusion_color = "🟡"
    else:
        conclusion_icon = "❌"
        conclusion_text = "该产品合规性不足，需要进行全面修改。"
        conclusion_color = "🔴"

    lines.append(f"### {conclusion_icon} {conclusion_text}")
    lines.append("")

    # 关键指标摘要
    lines.append("**关键指标摘要**:")
    lines.append("")
    lines.append(f"- 综合评分：{score} 分")
    lines.append(f"- 合规评级：{conclusion_color} {grade}")
    lines.append(f"- 违规总数：{total} 项（严重：{high_count}，中等：{medium_count}，轻微：{low_count}）")
    lines.append(f"- 定价问题：{summary.get('pricing_issues', 0)} 项")
    lines.append("")

    # 页脚
    lines.append("---")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>📄 报告信息</summary>")
    lines.append("")
    lines.append("- **生成工具**：Actuary Sleuth v3.0")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("- **免责声明**：本报告由 AI 自动生成，仅供参考，最终决策应以监管部门官方解释为准。")
    lines.append("")
    lines.append("</details>")

    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main())
