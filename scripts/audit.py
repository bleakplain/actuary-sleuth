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

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib.database import get_connection as db_get_connection
from lib.config import get_config
from lib.id_generator import IDGenerator
from lib.exceptions import (
    MissingParameterException,
    DocumentPreprocessException,
    NegativeListCheckException,
    PricingAnalysisException,
    ReportGenerationException,
    AuditStepException,
    ActuarySleuthException
)
from lib.logger import get_audit_logger
from lib.audit_context import AuditContext


# ========== 类型定义 ==========

class AuditParams(TypedDict):
    """审核参数类型"""
    documentUrl: str


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
        DocumentPreprocessException: 预处理步骤错误
        NegativeListCheckException: 负面清单检查错误
        PricingAnalysisException: 定价分析错误
        ReportGenerationException: 报告生成错误
        AuditStepException: 其他步骤错误
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
            raise DocumentPreprocessException(
                error_msg,
                details={'document_url': document_url}
            )
        elif '负面清单' in step_name:
            raise NegativeListCheckException(error_msg)
        elif '定价' in step_name:
            raise PricingAnalysisException(error_msg)
        elif '报告' in step_name:
            raise ReportGenerationException(error_msg)
        else:
            raise AuditStepException(f"{step_name} failed: {error_msg}")

    return result


def _handle_report_export(context: AuditContext) -> Optional[Dict[str, Any]]:
    """
    处理报告导出 - 生成Word文档并推送到飞书

    Args:
        context: 审核上下文（包含所有需要的数据）

    Returns:
        导出结果，包含docx_export和feishu_push信息
    """
    config = get_config()

    # 检查是否启用报告导出
    if not config.report.export_feishu:
        print(f"[{context.audit_id}] Step 6: Report export skipped (not configured)", file=sys.stderr)
        return None

    print(f"[{context.audit_id}] Step 6: Generating Word report and pushing to Feishu...", file=sys.stderr)

    try:
        # 导入新的Word导出模块
        from lib.reporting.export import DocxExporter
        from lib.reporting.model import _InsuranceProduct

        # 构建产品对象
        product = _InsuranceProduct(
            name=context.product_info.get('product_name', '未知产品'),
            type=context.product_info.get('product_type', '未知'),
            company=context.product_info.get('insurance_company', ''),
            version=context.product_info.get('version', ''),
            document_url=context.product_info.get('document_url', '')
        )

        # 更新 evaluation 中的 product
        context.evaluation.product = product
        context.evaluation.violations = context.violations
        context.evaluation.pricing_analysis = context.pricing_analysis.get('pricing', {})

        # 使用DocxExporter生成并推送Word文档
        exporter = DocxExporter(
            validate=False,
            auto_push=True
        )

        export_result = exporter.export(context.evaluation)

        # 构建返回结果
        result = {
            'success': export_result.get('success', False),
            'docx_export': {
                'success': export_result.get('success', False),
                'file_path': export_result.get('file_path'),
                'file_size': export_result.get('file_size'),
                'title': export_result.get('title')
            }
        }

        # 添加推送结果
        push_result = export_result.get('push_result')
        if push_result:
            result['feishu_push'] = {
                'success': push_result.get('success', False),
                'message_id': push_result.get('message_id'),
                'group_id': push_result.get('group_id')
            }

        if export_result.get('success'):
            print(f"[{context.audit_id}] ✅ Word report generated: {export_result.get('title')}", file=sys.stderr)
            if push_result and push_result.get('success'):
                print(f"[{context.audit_id}] ✅ Pushed to Feishu: {push_result.get('message_id')}", file=sys.stderr)
        else:
            error = export_result.get('error', 'Unknown error')
            print(f"[{context.audit_id}] ⚠️ Export failed: {error}", file=sys.stderr)
            result['error'] = error

        return result

    except Exception as e:
        error_msg = str(e)
        print(f"[{context.audit_id}] ⚠️ Report export error: {error_msg}", file=sys.stderr)
        return {
            'success': False,
            'error': error_msg,
            'error_type': type(e).__name__
        }


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Product Audit Script')
    parser.add_argument('--documentUrl', required=False, help='Feishu document URL')
    parser.add_argument('--documentContent', required=False, help='Document content (Markdown format)')
    args = parser.parse_args()

    # 验证参数：至少提供一个
    if not args.documentUrl and not args.documentContent:
        print(json.dumps({
            "success": False,
            "error": "Either --documentUrl or --documentContent must be provided"
        }, ensure_ascii=False), file=sys.stderr)
        return 1

    # 构建参数
    params = {}
    if args.documentUrl:
        params['documentUrl'] = args.documentUrl
    if args.documentContent:
        params['documentContent'] = args.documentContent

    # 执行业务逻辑
    try:
        result = execute(params)
        # 输出结果（JSON格式）
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        # 统一错误处理
        from lib.exceptions import ActuarySleuthException

        error_result = {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

        # 如果是自定义异常，添加详细信息
        if isinstance(e, ActuarySleuthException):
            error_result["details"] = e.details

        print(json.dumps(error_result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


def _fetch_feishu_content(document_url: str) -> str:
    """
    从飞书URL获取文档内容（使用feishu2md）

    Args:
        document_url: 飞书文档URL

    Returns:
        str: 文档内容（Markdown格式）

    Raises:
        Exception: 获取文档内容失败
    """
    import subprocess
    import os

    # 提取文档token
    import re
    match = re.search(r'/docx/([a-zA-Z0-9]+)', document_url)
    if not match:
        raise Exception(f"Invalid Feishu document URL: {document_url}")

    doc_token = match.group(1)
    md_filename = f"{doc_token}.md"

    # 使用 feishu2md 下载文档到当前目录
    try:
        # 先切换到临时目录执行下载，避免污染当前目录
        import tempfile
        old_cwd = os.getcwd()

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            result = subprocess.run(
                ['feishu2md', 'download', document_url],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )

            os.chdir(old_cwd)

            # feishu2md 会在执行目录生成 {token}.md 文件
            md_file = os.path.join(tmpdir, md_filename)

            if not os.path.exists(md_file):
                raise Exception(f"Markdown file not generated: {md_file}")

            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()

            return content

    except subprocess.CalledProcessError as e:
        os.chdir(old_cwd)
        raise Exception(f"feishu2md download failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        os.chdir(old_cwd)
        raise Exception(f"Timeout downloading Feishu document: {document_url}")
    except FileNotFoundError:
        os.chdir(old_cwd)
        raise Exception("feishu2md not found. Please install: gem install feishu2md")
    except Exception as e:
        os.chdir(old_cwd)
        raise Exception(f"Failed to fetch Feishu document: {str(e)}")


def execute(params: Dict[str, Any]) -> AuditResult:
    """
    执行完整的产品审核流程

    Args:
        params: 包含文档信息的字典
            - documentUrl: 飞书文档URL（可选）
            - documentContent: 文档内容（可选，Markdown格式）

    Returns:
        dict: 包含完整审核结果的字典
    """
    # 创建审核上下文
    context = AuditContext()
    context.audit_id = IDGenerator.generate_audit()
    context.document_url = params.get('documentUrl', '')

    # 获取文档内容
    document_content = params.get('documentContent', '')
    if context.document_url and not document_content:
        document_content = _fetch_feishu_content(context.document_url)

    if not document_content:
        raise MissingParameterException('documentContent or documentUrl')

    step_logger = get_audit_logger(context.audit_id)

    try:
        # Step 1: 文档预处理
        _preprocess(context, document_content)

        # Step 2: 负面清单检查
        _check_violations(context)

        # Step 3: 定价分析
        _analyze_pricing(context)

        # Step 4: 生成报告
        _generate_report(context)

        # Step 5: 保存审核记录
        step_logger.step("保存审核记录")
        save_audit_record(
            context.audit_id,
            context.document_url,
            context.violations,
            context.evaluation.score or 0
        )

        # Step 6: 导出报告（如果配置启用）
        _export_report(context)

        print(f"[{context.audit_id}] Audit completed successfully!", file=sys.stderr)
        return context.to_result()

    except Exception as e:
        print(f"[{context.audit_id}] Audit failed: {str(e)}", file=sys.stderr)
        raise


def _preprocess(context: AuditContext, document_content: str) -> None:
    """
    执行文档预处理步骤

    Args:
        context: 审核上下文
        document_content: 文档内容

    Raises:
        DocumentPreprocessException: 预处理失败
    """
    result = _run_audit_step(
        "预处理文档",
        run_preprocess,
        document_content,
        context.document_url,
        audit_id=context.audit_id,
        document_url=context.document_url
    )

    # 将结果写入上下文
    context.product_info = result.get('product_info', {})
    context.clauses = result.get('clauses', [])
    context.pricing_params = result.get('pricing_params', {})


def _check_violations(context: AuditContext) -> None:
    """
    执行负面清单检查步骤

    Args:
        context: 审核上下文

    Raises:
        NegativeListCheckException: 检查失败
    """
    result = _run_audit_step(
        "负面清单检查",
        run_negative_list_check,
        context.clauses,
        audit_id=context.audit_id
    )

    # 将结果写入上下文
    context.violations = result.get('violations', [])


def _analyze_pricing(context: AuditContext) -> None:
    """
    执行定价分析步骤

    Args:
        context: 审核上下文

    Raises:
        PricingAnalysisException: 分析失败
    """
    product_type = context.product_info.get('product_type', 'unknown')
    result = _run_audit_step(
        "定价分析",
        run_pricing_analysis,
        context.pricing_params,
        product_type,
        audit_id=context.audit_id
    )

    # 将结果写入上下文
    context.pricing_analysis = result


def _generate_report(context: AuditContext) -> None:
    """
    执行报告生成步骤

    Args:
        context: 审核上下文

    Raises:
        ReportGenerationException: 生成失败
    """
    # 将 document_url 添加到 product_info 中
    product_info = context.product_info.copy()
    product_info['document_url'] = context.document_url

    result = _run_audit_step(
        "生成报告",
        run_report_generation,
        context.violations,
        context.pricing_analysis,
        product_info,
        audit_id=context.audit_id
    )

    # 将评估结果写入上下文的 evaluation 对象
    from lib.reporting.model import _InsuranceProduct
    product = _InsuranceProduct(
        name=product_info.get('product_name', '未知产品'),
        type=product_info.get('product_type', '未知'),
        company=product_info.get('insurance_company', ''),
        version=product_info.get('version', ''),
        document_url=product_info.get('document_url', '')
    )

    # 构建 EvaluationContext
    context.evaluation.product = product
    context.evaluation.violations = context.violations
    context.evaluation.pricing_analysis = result.get('pricing_analysis', {}).get('pricing', {})
    context.evaluation.score = result.get('score', 0)
    context.evaluation.grade = result.get('grade', '')

    # 转换 summary 格式为扁平结构
    raw_summary = result.get('summary', {})
    violation_severity = raw_summary.get('violation_severity', {})
    context.evaluation.summary = {
        'high': violation_severity.get('high', 0),
        'medium': violation_severity.get('medium', 0),
        'low': violation_severity.get('low', 0),
        'total_violations': raw_summary.get('total_violations', 0),
        'has_issues': raw_summary.get('has_issues', False)
    }


def _export_report(context: AuditContext) -> None:
    """
    执行报告导出步骤

    Args:
        context: 审核上下文
    """
    result = _handle_report_export(context)
    context.export_result = result


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
    # 直接导入check模块调用execute函数
    import check

    input_params = {
        'clauses': clauses
    }

    try:
        return check.execute(input_params)
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


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
