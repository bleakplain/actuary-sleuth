#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成脚本

生成结构化的审核报告，支持导出为飞书在线文档

使用 ReportGenerator 类进行报告生成，本脚本作为入口层负责：
- 参数解析和验证
- 调用 ReportGenerator
- 飞书文档导出
- 结果输出
"""
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, Any

from lib.config import get_config
from lib.reporting import ReportGenerator, FeishuExporter


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
    生成审核报告（使用 ReportGenerator）

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

    # 使用 ReportGenerator 生成报告
    generator = ReportGenerator()
    result = generator.generate(
        violations=violations,
        pricing_analysis=pricing_analysis,
        product_info=product_info,
        score=score
    )

    return result


def export_to_feishu(blocks: list, title: str = None) -> Dict[str, Any]:
    """
    将报告导出为飞书在线文档

    Args:
        blocks: 飞书文档块列表
        title: 文档标题（可选）

    Returns:
        dict: 包含文档 URL 的结果
    """
    exporter = FeishuExporter()
    return exporter.export(blocks, title)


if __name__ == '__main__':
    sys.exit(main())
