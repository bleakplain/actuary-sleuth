#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品审核脚本
整合预处理、负面清单检查、定价分析和报告生成
"""
import json
import argparse
import sys
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib import db


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Product Audit Script')
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
    执行完整的产品审核流程

    Args:
        params: 包含文档内容的字典
            - documentContent: 文档内容
            - documentUrl: 文档URL（可选）
            - auditType: 审核类型（full/negative-only，默认full）

    Returns:
        dict: 包含完整审核结果的字典
    """
    # 验证输入参数
    if 'documentContent' not in params:
        raise ValueError("Missing required parameter: 'documentContent'")

    document_content = params['documentContent']
    document_url = params.get('documentUrl', '')
    audit_type = params.get('auditType', 'full')

    # 生成审核ID
    audit_id = f"AUD-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    try:
        # Step 1: 文档预处理
        print(f"[{audit_id}] Step 1: Preprocessing document...", file=sys.stderr)
        preprocess_result = run_preprocess(document_content, document_url)

        if not preprocess_result.get('success'):
            raise Exception("Preprocessing failed: " + preprocess_result.get('error', 'Unknown error'))

        # Step 2: 负面清单检查
        print(f"[{audit_id}] Step 2: Checking negative list...", file=sys.stderr)
        violations = run_negative_list_check(preprocess_result.get('clauses', []))

        if not violations.get('success'):
            raise Exception("Negative list check failed: " + violations.get('error', 'Unknown error'))

        # Step 3: 定价分析（仅full审核）
        pricing_analysis = None
        if audit_type == 'full':
            print(f"[{audit_id}] Step 3: Analyzing pricing...", file=sys.stderr)
            pricing_analysis = run_pricing_analysis(
                preprocess_result.get('pricing_params', {}),
                preprocess_result.get('product_info', {}).get('product_type', 'unknown')
            )

            if not pricing_analysis.get('success'):
                raise Exception("Pricing analysis failed: " + pricing_analysis.get('error', 'Unknown error'))

        # Step 4: 生成报告
        print(f"[{audit_id}] Step 4: Generating report...", file=sys.stderr)
        report_result = run_report_generation(
            violations.get('violations', []),
            pricing_analysis,
            preprocess_result.get('product_info', {})
        )

        if not report_result.get('success'):
            raise Exception("Report generation failed: " + report_result.get('error', 'Unknown error'))

        # Step 5: 保存审核记录
        print(f"[{audit_id}] Step 5: Saving audit record...", file=sys.stderr)
        save_audit_record(
            audit_id,
            document_url,
            violations.get('violations', []),
            report_result.get('score', 0)
        )

        # 构建最终结果
        result = {
            'success': True,
            'audit_id': audit_id,
            'violations': violations.get('violations', []),
            'violation_count': violations.get('count', 0),
            'violation_summary': violations.get('summary', {}),
            'pricing': pricing_analysis.get('pricing', {}) if pricing_analysis else {},
            'score': report_result.get('score', 0),
            'grade': report_result.get('grade', ''),
            'summary': report_result.get('summary', {}),
            'report': report_result.get('content', ''),
            'metadata': {
                'audit_type': audit_type,
                'document_url': document_url,
                'timestamp': datetime.now().isoformat(),
                'product_info': preprocess_result.get('product_info', {})
            }
        }

        print(f"[{audit_id}] Audit completed successfully!", file=sys.stderr)
        return result

    except Exception as e:
        print(f"[{audit_id}] Audit failed: {str(e)}", file=sys.stderr)
        raise


def run_preprocess(document_content: str, document_url: str) -> Dict[str, Any]:
    """
    运行预处理脚本

    Args:
        document_content: 文档内容
        document_url: 文档URL

    Returns:
        dict: 预处理结果
    """
    # 构建输入参数
    input_params = {
        'documentContent': document_content,
        'documentUrl': document_url
    }

    # 使用临时文件传递参数
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(input_params, f, ensure_ascii=False)
        input_file = f.name

    try:
        # 调用预处理脚本
        script_path = Path(__file__).parent / 'preprocess.py'
        result = subprocess.run(
            [sys.executable, str(script_path), '--input', input_file],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return {
                'success': False,
                'error': result.stderr,
                'error_type': 'SubprocessError'
            }

        return json.loads(result.stdout)

    finally:
        # 清理临时文件
        Path(input_file).unlink(missing_ok=True)


def run_negative_list_check(clauses: List[str]) -> Dict[str, Any]:
    """
    运行负面清单检查

    Args:
        clauses: 条款列表

    Returns:
        dict: 检查结果
    """
    # 导入check模块直接调用
    script_path = Path(__file__).parent / 'check.py'

    # 构建输入参数
    input_params = {
        'clauses': clauses
    }

    # 使用临时文件传递参数
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(input_params, f, ensure_ascii=False)
        input_file = f.name

    try:
        # 调用检查脚本
        result = subprocess.run(
            [sys.executable, str(script_path), '--input', input_file],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return {
                'success': False,
                'error': result.stderr,
                'error_type': 'SubprocessError'
            }

        return json.loads(result.stdout)

    finally:
        # 清理临时文件
        Path(input_file).unlink(missing_ok=True)


def run_pricing_analysis(pricing_params: Dict[str, Any], product_type: str) -> Dict[str, Any]:
    """
    运行定价分析

    Args:
        pricing_params: 定价参数
        product_type: 产品类型

    Returns:
        dict: 分析结果
    """
    # 导入scoring模块直接调用
    import scoring

    input_params = {
        'pricing_params': pricing_params,
        'product_type': product_type
    }

    try:
        return scoring.execute(input_params)
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def run_report_generation(
    violations: List[Dict[str, Any]],
    pricing_analysis: Dict[str, Any],
    product_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    生成审核报告

    Args:
        violations: 违规记录列表
        pricing_analysis: 定价分析结果
        product_info: 产品信息

    Returns:
        dict: 报告结果
    """
    # 导入report模块直接调用
    import report

    input_params = {
        'violations': violations,
        'pricing_analysis': pricing_analysis,
        'product_info': product_info
    }

    try:
        return report.execute(input_params)
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def save_audit_record(
    audit_id: str,
    document_url: str,
    violations: List[Dict[str, Any]],
    score: int
) -> bool:
    """
    保存审核记录到数据库

    Args:
        audit_id: 审核ID
        document_url: 文档URL
        violations: 违规记录列表
        score: 评分

    Returns:
        bool: 是否保存成功
    """
    try:
        record = {
            'id': audit_id,
            'document_url': document_url,
            'violations': violations,
            'score': score
        }
        return db.save_audit_record(record)
    except Exception as e:
        print(f"Warning: Failed to save audit record: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    sys.exit(main())
