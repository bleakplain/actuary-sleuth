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
from typing import Dict, List, Any, TypedDict, Callable, Optional

# 添加 infrastructure 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'infrastructure'))

from infrastructure.database import get_connection as db_get_connection
from infrastructure.config import get_config
from infrastructure.id_generator import IDGenerator
from infrastructure.exceptions import (
    MissingParameterError,
    DocumentPreprocessError,
    NegativeListCheckError,
    PricingAnalysisError,
    ReportGenerationError,
    AuditStepError,
    ActuarySleuthError
)
from infrastructure.logger import get_audit_logger


# ========== 类型定义 ==========

class AuditParams(TypedDict):
    """审核参数类型"""
    documentContent: str
    documentUrl: str
    auditType: str  # 'full' or 'negative-only'


class PreprocessResult(TypedDict, total=False):
    """预处理结果类型"""
    success: bool
    preprocess_id: str
    metadata: Dict[str, Any]
    product_info: Dict[str, Any]
    structure: Dict[str, Any]
    clauses: List[Dict[str, Any]]
    pricing_params: Dict[str, Any]
    error: str
    error_type: str


class CheckResult(TypedDict, total=False):
    """负面清单检查结果类型"""
    success: bool
    violations: List[Dict[str, Any]]
    count: int
    summary: Dict[str, int]
    error: str
    error_type: str


class PricingAnalysisResult(TypedDict, total=False):
    """定价分析结果类型"""
    success: bool
    pricing: Dict[str, Any]
    error: str
    error_type: str


class ReportResult(TypedDict, total=False):
    """报告生成结果类型"""
    success: bool
    report_id: str
    score: int
    grade: str
    summary: Dict[str, Any]
    content: str
    blocks: List[Dict[str, Any]]
    error: str
    error_type: str


class AuditResult(TypedDict, total=False):
    """审核结果类型"""
    success: bool
    audit_id: str
    violations: List[Dict[str, Any]]
    violation_count: int
    violation_summary: Dict[str, int]
    pricing: Dict[str, Any]
    score: int
    grade: str
    summary: Dict[str, Any]
    report: str
    metadata: Dict[str, Any]
    report_export: Dict[str, Any]
    error: str
    error_type: str
    details: Dict[str, Any]


# ========== 辅助函数 ==========

def _run_audit_step(
    step_name: str,
    step_func: Callable,
    *args,
    **kwargs
) -> Dict[str, Any]:
    """
    执行单个审核步骤

    Args:
        step_name: 步骤名称
        step_func: 步骤函数
        *args: 位置参数
        **kwargs: 关键字参数（可包含 audit_id，但不传递给步骤函数）

    Returns:
        步骤执行结果

    Raises:
        DocumentPreprocessError: 预处理步骤错误
        NegativeListCheckError: 负面清单检查错误
        PricingAnalysisError: 定价分析错误
        ReportGenerationError: 报告生成错误
        AuditStepError: 其他步骤错误
    """
    # 提取 audit_id 用于日志，但不传递给步骤函数
    audit_id = kwargs.pop('audit_id', '')
    document_url = kwargs.pop('document_url', '')

    step_logger = get_audit_logger(audit_id)
    step_logger.step(step_name)

    result = step_func(*args, **kwargs)

    if not result.get('success'):
        error_msg = result.get('error', 'Unknown error')

        # 根据步骤名称抛出对应的错误类型
        if '预处理' in step_name:
            raise DocumentPreprocessError(
                error_msg,
                details={'document_url': document_url}
            )
        elif '负面清单' in step_name:
            raise NegativeListCheckError(error_msg)
        elif '定价' in step_name:
            raise PricingAnalysisError(error_msg)
        elif '报告' in step_name:
            raise ReportGenerationError(error_msg)
        else:
            raise AuditStepError(f"{step_name} failed: {error_msg}")

    return result


def _build_audit_result(
    audit_id: str,
    violations: Dict[str, Any],
    pricing_analysis: Optional[Dict[str, Any]],
    report_result: Dict[str, Any],
    preprocess_result: Dict[str, Any],
    export_result: Optional[Dict[str, Any]] = None,
    audit_type: str = 'full',
    document_url: str = ''
) -> AuditResult:
    """
    构建审核结果

    Args:
        audit_id: 审核ID
        violations: 违规检查结果
        pricing_analysis: 定价分析结果
        report_result: 报告生成结果
        preprocess_result: 预处理结果
        export_result: 导出结果（可选）
        audit_type: 审核类型
        document_url: 文档URL

    Returns:
        完整的审核结果字典
    """
    product_info = preprocess_result.get('product_info', {})

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
            'product_info': product_info
        },
        'details': {
            'preprocess_id': preprocess_result.get('preprocess_id'),
            'product_info': product_info,
            'document_url': product_info.get('document_url', '')
        }
    }

    if export_result:
        result['report_export'] = export_result

    return result


def _handle_report_export(
    audit_id: str,
    report_result: Dict[str, Any],
    preprocess_result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    处理报告导出

    Args:
        audit_id: 审核ID
        report_result: 报告生成结果
        preprocess_result: 预处理结果

    Returns:
        导出结果，如果未配置导出则返回 None
    """
    config = get_config()

    if not config.report.export_feishu:
        print(f"[{audit_id}] Step 6: Report export skipped (not configured)", file=sys.stderr)
        return None

    print(f"[{audit_id}] Step 6: Exporting report...", file=sys.stderr)

    export_result = export_report(
        report_result.get('content', ''),
        preprocess_result.get('product_info', {}),
        report_result.get('blocks')
    )

    if export_result.get('success'):
        print(f"[{audit_id}] ✅ Report exported: {export_result.get('document_url')}", file=sys.stderr)
    else:
        print(f"[{audit_id}] ⚠️ Report export failed: {export_result.get('error', 'Unknown error')}", file=sys.stderr)

    return export_result


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Product Audit Script')
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
        # 统一错误处理
        from infrastructure.exceptions import ActuarySleuthError

        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

        # 如果是自定义异常，添加详细信息
        if isinstance(e, ActuarySleuthError):
            error_result["details"] = e.details

        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def execute(params: Dict[str, Any]) -> AuditResult:
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
        raise MissingParameterError('documentContent')

    document_content = params['documentContent']
    document_url = params.get('documentUrl', '')
    audit_type = params.get('auditType', 'full')

    # 生成审核ID (使用统一ID生成器)
    audit_id = IDGenerator.generate_audit()
    step_logger = get_audit_logger(audit_id)

    try:
        # Step 1: 文档预处理
        preprocess_result = _run_audit_step(
            "预处理文档",
            run_preprocess,
            document_content,
            document_url,
            audit_id=audit_id,
            document_url=document_url
        )

        # Step 2: 负面清单检查
        violations = _run_audit_step(
            "负面清单检查",
            run_negative_list_check,
            preprocess_result.get('clauses', []),
            audit_id=audit_id
        )

        # Step 3: 定价分析（仅full审核）
        pricing_analysis = None
        if audit_type == 'full':
            pricing_analysis = _run_audit_step(
                "定价分析",
                run_pricing_analysis,
                preprocess_result.get('pricing_params', {}),
                preprocess_result.get('product_info', {}).get('product_type', 'unknown'),
                audit_id=audit_id
            )

        # Step 4: 生成报告
        # 将 document_url 添加到 product_info 中，以便报告生成时可以引用原文
        product_info = preprocess_result.get('product_info', {})
        product_info['document_url'] = document_url
        report_result = _run_audit_step(
            "生成报告",
            run_report_generation,
            violations.get('violations', []),
            pricing_analysis,
            product_info,
            audit_id=audit_id
        )

        # Step 5: 保存审核记录
        step_logger.step("保存审核记录")
        save_audit_record(
            audit_id,
            document_url,
            violations.get('violations', []),
            report_result.get('score', 0)
        )

        # Step 6: 导出报告（如果配置启用）
        export_result = _handle_report_export(audit_id, report_result, preprocess_result)

        # 构建最终结果
        result = _build_audit_result(
            audit_id=audit_id,
            violations=violations,
            pricing_analysis=pricing_analysis,
            report_result=report_result,
            preprocess_result=preprocess_result,
            export_result=export_result,
            audit_type=audit_type,
            document_url=document_url
        )

        print(f"[{audit_id}] Audit completed successfully!", file=sys.stderr)
        return result

    except Exception as e:
        print(f"[{audit_id}] Audit failed: {str(e)}", file=sys.stderr)
        raise


def run_preprocess(document_content: str, document_url: str) -> PreprocessResult:
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


def run_negative_list_check(clauses: List[Dict[str, Any]]) -> CheckResult:
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


def run_pricing_analysis(pricing_params: Dict[str, Any], product_type: str) -> PricingAnalysisResult:
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
    pricing_analysis: PricingAnalysisResult,
    product_info: Dict[str, Any]
) -> ReportResult:
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


def export_report(
    report_content: str,
    product_info: Dict[str, Any],
    report_blocks: List[Dict[str, Any]] = None,
    export_format: str = None
) -> Dict[str, Any]:
    """
    导出审核报告到目标平台

    基于配置自动选择导出方式：
    - 默认：导出到飞书在线文档
    - 可扩展：支持其他导出格式（PDF、本地文件等）

    Args:
        report_content: 报告内容（Markdown 格式，备用）
        product_info: 产品信息
        report_blocks: 报告块列表（推荐格式）
        export_format: 导出格式（None 表示使用配置默认值）

    Returns:
        dict: 导出结果，包含 success 和 document_url 或 error
    """
    # 导入 report 模块使用其导出功能
    import report

    # 构建文档标题（产品名-审核报告）
    product_name = product_info.get('product_name', '未知产品')
    title = f"{product_name} - 审核报告"

    try:
        # 如果有 blocks，使用 blocks；否则使用简单转换
        if report_blocks:
            return report.export_to_feishu(
                report_blocks,
                title=title
            )
        else:
            # 备用方案：将 Markdown 内容转换为简单块
            import re
            blocks = []
            for line in report_content.split('\n'):
                if line.strip():
                    blocks.append(report.create_text(line))
                else:
                    blocks.append(report.create_text(""))
            return report.export_to_feishu(
                blocks,
                title=title
            )
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
        # 直接保存，不再通过db模块
        import sqlite3
        import json
        from pathlib import Path

        DB_PATH = Path(__file__).parent.parent / 'data' / 'actuary.db'

        try:
            conn = sqlite3.connect(
                str(DB_PATH),
                timeout=30,
                check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")

            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_history (id, user_id, document_url, violations, score)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                record['id'],
                record.get('user_id', ''),
                record.get('document_url', ''),
                json.dumps(record.get('violations', []), ensure_ascii=False),
                record.get('score', 0)
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Warning: Failed to save audit record: {e}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Warning: Failed to save audit record: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    sys.exit(main())
