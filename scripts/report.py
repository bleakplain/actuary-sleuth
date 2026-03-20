#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成脚本

生成结构化的审核报告，支持导出为飞书在线文档

使用 ReportGenerationTemplate 类进行报告生成，本脚本作为入口层负责：
- 参数解析和验证
- 调用 ReportGenerationTemplate
- 飞书文档导出
- 结果输出
"""
import json
import argparse
import sys
from pathlib import Path
from typing import Dict, Any

from lib.config import get_config
from lib.reporting.template import ReportGenerationTemplate
from lib.reporting.model import EvaluationContext
from lib.common.models import Product
from lib.exceptions import InvalidParameterException


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Report Generation Script')
    parser.add_argument('--input', required=True, help='JSON input file')
    parser.add_argument('--export-feishu', action='store_true', help='导出为飞书在线文档')
    parser.add_argument('--output', help='输出文件路径（可选）')
    args = parser.parse_args()

    # 验证输入文件路径
    input_path = Path(args.input).resolve()
    if not input_path.exists() or not input_path.is_file():
        raise InvalidParameterException('input', str(input_path), f'File does not exist or is not a file')

    # 读取输入
    with open(input_path, 'r', encoding='utf-8') as f:
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
                title=f"审核报告-{params.get('details', {}).get('product_name', '未知产品')}"
            )
            result['report_export'] = feishu_result

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
    生成审核报告（使用 ReportGenerationTemplate）

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

    details = params.get('details', {})
    if not isinstance(details, dict):
        details = {}

    score = params.get('score', 0)

    # 构建统一的 EvaluationContext
    product = Product.from_dict(details)
    context = EvaluationContext(
        product=product,
        violations=violations,
        clauses=violations,  # 使用相同数据
        pricing_analysis=pricing_analysis,
        score=score,
        grade=None,  # 将由模板计算
        summary=None  # 将由模板计算
    )

    # 使用 ReportGenerationTemplate 生成报告
    generator = ReportGenerationTemplate()
    result = generator.generate(context)

    return result


if __name__ == '__main__':
    sys.exit(main())
