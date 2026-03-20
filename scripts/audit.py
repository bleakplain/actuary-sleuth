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
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, TypedDict, Optional

# 添加 lib 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib.evaluation import calculate_result
from lib.common.audit import (
    PreprocessedResult,
    CheckedResult,
    AnalyzedResult,
    EvaluationResult,
    get_violations,
    get_product,
    get_clauses,
    get_pricing_analysis,
    get_audit_id,
    get_document_url,
    get_timestamp,
    get_preprocess_id
)
from lib.common.models import Product as ProductModel
from lib.config import get_config
from lib.common.product import map_to_scoring_type
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
import logging

logger = logging.getLogger(__name__)


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


class AuditApiResponse(TypedDict, total=False):
    """审核API响应类型"""
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

def _validate_report_completeness(
    result: EvaluationResult
) -> tuple[bool, List[str]]:
    """
    验证报告完整性

    Args:
        result: 评估结果

    Returns:
        tuple: (是否通过验证, 缺失字段列表)
    """
    missing_fields = []
    product = get_product(result)
    clauses = get_clauses(result)
    violations = get_violations(result)

    # 1. 验证产品信息完整性
    if not product.name:
        missing_fields.append('product.name')

    # 2. 验证条款数据
    if not clauses or len(clauses) == 0:
        missing_fields.append('clauses')
    else:
        # 验证条款内容是否为空
        empty_clauses = [i for i, clause in enumerate(clauses)
                        if not clause.get('text') or not clause.get('text').strip()]
        if empty_clauses:
            missing_fields.append(f'clauses[{empty_clauses[0]}].text (empty)')

    # 3. 验证违规数据
    if not violations:
        missing_fields.append('violations')

    is_valid = len(missing_fields) == 0

    if not is_valid:
        print(f"[{product.name}] ⚠️ Report validation failed, missing fields: {missing_fields}", file=sys.stderr)

    return is_valid, missing_fields


def _export_report(result: EvaluationResult) -> Optional[Dict[str, Any]]:
    """
    导出报告 - 生成Word文档并推送到飞书

    先验证报告完整性，再决定是否推送到飞书

    Args:
        result: 评估结果

    Returns:
        导出结果，包含docx_export和feishu_push信息
    """
    config = get_config()
    product = get_product(result)
    violations = get_violations(result)
    clauses = get_clauses(result)
    pricing_analysis = get_pricing_analysis(result)

    # 检查是否启用报告导出
    if not config.report.export_feishu:
        print(f"[{product.name}] Step 6: Report export skipped (not configured)", file=sys.stderr)
        return None

    # 验证报告完整性
    is_valid, missing_fields = _validate_report_completeness(result)
    if not is_valid:
        print(f"[{product.name}] Step 6: Report export skipped (validation failed: {missing_fields})", file=sys.stderr)
        return {
            'success': False,
            'error': f'Report validation failed, missing fields: {missing_fields}',
            'error_type': 'ValidationError',
            'validation_result': {
                'is_valid': False,
                'missing_fields': missing_fields
            }
        }

    print(f"[{product.name}] Step 6: Generating Word report and pushing to Feishu...", file=sys.stderr)

    try:
        # 导入新的Word导出模块
        from lib.reporting.export import DocxExporter

        exporter = DocxExporter(
            validate=False,
            auto_push=True
        )

        # 将数据转换为 DocxExporter 期望的格式
        from lib.reporting.model import EvaluationContext
        context = EvaluationContext.from_evaluation_result(result)

        export_result = exporter.export(context)

        # 构建返回结果
        export_dict = {
            'success': export_result.get('success', False),
            'docx_export': {
                'success': export_result.get('success', False),
                'file_path': export_result.get('file_path'),
                'file_size': export_result.get('file_size'),
                'title': export_result.get('title')
            },
            'validation_result': {
                'is_valid': True,
                'missing_fields': []
            }
        }

        # 添加推送结果
        push_result = export_result.get('push_result')
        if push_result:
            export_dict['feishu_push'] = {
                'success': push_result.get('success', False),
                'message_id': push_result.get('message_id'),
                'group_id': push_result.get('group_id')
            }

        if export_result.get('success'):
            print(f"[{product.name}] ✅ Word report generated: {export_result.get('title')}", file=sys.stderr)
            if push_result and push_result.get('success'):
                print(f"[{product.name}] ✅ Pushed to Feishu: {push_result.get('message_id')}", file=sys.stderr)
        else:
            error = export_result.get('error', 'Unknown error')
            print(f"[{product.name}] ⚠️ Export failed: {error}", file=sys.stderr)
            export_dict['error'] = error

        return export_dict

    except Exception as e:
        error_msg = str(e)
        print(f"[{product.name}] ⚠️ Report export error: {error_msg}", file=sys.stderr)
        return {
            'success': False,
            'error': error_msg,
            'error_type': type(e).__name__
        }


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Product Audit Script')
    parser.add_argument('--documentUrl', required=True, help='Feishu document URL')
    args = parser.parse_args()

    # 构建参数
    params = {
        'documentUrl': args.documentUrl
    }

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
    output_dir = "/tmp"

    # 使用 feishu2md 下载文档到 /tmp 目录
    try:
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)

        # 切换到输出目录执行下载
        old_cwd = os.getcwd()
        os.chdir(output_dir)

        result = subprocess.run(
            ['feishu2md', 'download', document_url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )

        os.chdir(old_cwd)

        # feishu2md 会在执行目录生成 {token}.md 文件
        md_file = os.path.join(output_dir, md_filename)

        if not os.path.exists(md_file):
            raise Exception(f"Markdown file not generated: {md_file}")

        with open(md_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 不再截断文档，保留完整内容
        # LLM 可以通过分块处理和重试机制应对长文档
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


def execute(params: Dict[str, Any]) -> AuditApiResponse:
    """
    执行完整的产品审核流程

    调整后的流程确保事务一致性：
    1. 阶段一：执行审核（preprocess → check → analyze → evaluate）
    2. 阶段二：保存到数据库
    3. 阶段三：导出报告（仅在数据库保存成功后）

    Args:
        params: 包含文档信息的字典
            - documentUrl: 飞书文档URL（可选）
            - documentContent: 文档内容（可选，Markdown格式）

    Returns:
        dict: 包含完整审核结果的字典
    """
    # 创建审核对象
    audit_id = IDGenerator.generate_audit()
    document_url = params.get('documentUrl', '')

    # 获取文档内容
    document_content = params.get('documentContent', '')
    if document_url and not document_content:
        document_content = _fetch_feishu_content(document_url)

    if not document_content:
        raise MissingParameterException('documentContent or documentUrl')

    step_logger = get_audit_logger(audit_id)

    try:
        # ========== 阶段一：执行审核 ==========
        # Step 1: 预处理
        preprocessed = _preprocess(audit_id, document_url, document_content)

        # Step 2: 负面清单检查
        checked = _check_violations(preprocessed)

        # Step 3: 定价分析
        analyzed = _analyze_pricing(checked)

        # Step 4: 计算评估结果
        result = calculate_result(analyzed)

        # ========== 阶段二：保存到数据库 ==========
        step_logger.step("保存审核记录")
        violations = get_violations(result)
        save_success = save_audit_record(
            audit_id,
            document_url,
            violations,
            result.score
        )

        if not save_success:
            raise AuditStepException("保存审核记录到数据库失败", step="save_audit_record")

        # ========== 阶段三：导出报告（仅在保存成功后） ==========
        export_result = None
        config = get_config()
        if config.report.export_feishu:
            step_logger.step("导出报告")
            export_result = _export_report(result)

        print(f"[{audit_id}] Audit completed successfully!", file=sys.stderr)
        return _build_result(result, export_result)

    except Exception as e:
        print(f"[{audit_id}] Audit failed: {str(e)}", file=sys.stderr)
        raise


def _preprocess(audit_id: str, document_url: str, document_content: str) -> PreprocessedResult:
    """
    执行文档预处理步骤

    Args:
        audit_id: 审核ID
        document_url: 文档URL
        document_content: 文档内容

    Returns:
        PreprocessedResult: 预处理结果

    Raises:
        DocumentPreprocessException: 预处理失败
    """
    step_logger = get_audit_logger(audit_id)
    step_logger.step("预处理文档")

    result = run_preprocess(document_content, document_url)

    # 验证结果并构建 PreprocessedResult
    if not result.get('success'):
        raise DocumentPreprocessException(
            result.get('error', 'Unknown preprocessing error'),
            details={'document_url': document_url}
        )

    product_info = result.get('product_info', {})
    product_info['document_url'] = document_url
    product = ProductModel.from_dict(product_info)

    return PreprocessedResult(
        audit_id=audit_id,
        document_url=document_url,
        timestamp=datetime.now(),
        product=product,
        clauses=result.get('clauses', []),
        pricing_params=result.get('pricing_params', {})
    )


def _check_violations(preprocessed: PreprocessedResult) -> CheckedResult:
    """
    执行负面清单检查步骤

    Args:
        preprocessed: 预处理结果

    Returns:
        CheckedResult: 检查结果

    Raises:
        NegativeListCheckException: 检查失败
    """
    # 验证条款不为空
    if not preprocessed.clauses:
        raise NegativeListCheckException("没有可审核的条款：预处理未提取到任何条款内容")

    step_logger = get_audit_logger(preprocessed.audit_id)
    step_logger.step("负面清单检查")

    result = run_negative_list_check(preprocessed.clauses)

    # 验证结果并构建 CheckedResult
    if not result.get('success'):
        raise NegativeListCheckException(
            result.get('error', 'Unknown negative list check error')
        )

    return CheckedResult(
        preprocessed=preprocessed,
        violations=result.get('violations', [])
    )


def _analyze_pricing(checked: CheckedResult) -> AnalyzedResult:
    """
    执行定价分析步骤

    Args:
        checked: 检查结果

    Returns:
        AnalyzedResult: 分析结果

    Raises:
        PricingAnalysisException: 分析失败
    """
    # 将 ProductCategory 映射到 scoring 模块期望的类型
    category = checked.preprocessed.product.category
    scoring_type = map_to_scoring_type(category)

    step_logger = get_audit_logger(checked.preprocessed.audit_id)
    step_logger.step("定价分析")

    result = run_pricing_analysis(checked.preprocessed.pricing_params, scoring_type)

    # 验证结果并构建 AnalyzedResult
    if not result.get('success'):
        raise PricingAnalysisException(
            result.get('error', 'Unknown pricing analysis error')
        )

    return AnalyzedResult(
        checked=checked,
        pricing_analysis=result.get('pricing', {})
    )


def _build_result(
    result: EvaluationResult,
    export_result: Optional[Dict[str, Any]]
) -> AuditApiResponse:
    """
    构建最终审核结果

    数据流：EvaluationResult → AuditApiResponse (API响应)
                                  ↓
                          Export (报告生成)

    Args:
        result: 评估结果
        export_result: 导出结果

    Returns:
        AuditApiResponse: 审核结果（API响应格式）
    """
    violations = get_violations(result)
    product = get_product(result)
    clauses = get_clauses(result)
    pricing_analysis = get_pricing_analysis(result)
    audit_id = get_audit_id(result)
    document_url = get_document_url(result)
    timestamp = get_timestamp(result)
    preprocess_id = get_preprocess_id(result)

    total_violations = len(violations)

    return {
        'success': True,
        'audit_id': audit_id,
        'violations': violations,
        'violation_count': total_violations,
        'violation_summary': {
            'high': sum(1 for v in violations if v.get('severity') == 'high'),
            'medium': sum(1 for v in violations if v.get('severity') == 'medium'),
            'low': sum(1 for v in violations if v.get('severity') == 'low'),
        },
        'pricing': pricing_analysis,
        'score': result.score,
        'grade': result.grade,
        'summary': result.summary,
        'report': '',
        'metadata': {
            'audit_type': 'full',
            'document_url': document_url,
            'timestamp': timestamp.isoformat(),
        },
        'details': {
            'preprocess_id': preprocess_id,
            'product_name': product.name,
            'product_type': product.type,
            'insurance_company': product.company,
            'clauses': clauses,
            'document_url': document_url
        },
        'report_export': export_result or {}
    }


def run_preprocess(document_content: str, document_url: str) -> PreprocessResult:
    """
    运行预处理脚本

    Args:
        document_content: 文档内容
        document_url: 文档URL

    Returns:
        dict: 预处理结果

    Raises:
        DocumentPreprocessException: 预处理失败时
    """
    import preprocess

    input_params = {
        'documentContent': document_content,
        'documentUrl': document_url
    }

    result = preprocess.execute(input_params)

    # 验证结果，失败时抛出异常
    if not result.get('success'):
        raise DocumentPreprocessException(
            result.get('error', 'Unknown preprocessing error'),
            details={'document_url': document_url}
        )

    return result


def run_negative_list_check(clauses: List[Dict[str, Any]]) -> CheckResult:
    """
    运行负面清单检查

    Args:
        clauses: 条款列表

    Returns:
        dict: 检查结果

    Raises:
        NegativeListCheckException: 检查失败时
    """
    # 直接导入check模块调用execute函数
    import check

    input_params = {
        'clauses': clauses
    }

    result = check.execute(input_params)

    # 验证结果，失败时抛出异常
    if not result.get('success'):
        raise NegativeListCheckException(
            result.get('error', 'Unknown negative list check error')
        )

    return result


def run_pricing_analysis(pricing_params: Dict[str, Any], product_type: str) -> PricingAnalysisResult:
    """
    运行定价分析

    Args:
        pricing_params: 定价参数
        product_type: 产品类型

    Returns:
        dict: 分析结果

    Raises:
        PricingAnalysisException: 分析失败时
    """
    # 导入scoring模块直接调用
    import scoring

    input_params = {
        'pricing_params': pricing_params,
        'product_type': product_type
    }

    result = scoring.execute(input_params)

    # 验证结果，失败时抛出异常
    if not result.get('success'):
        raise PricingAnalysisException(
            result.get('error', 'Unknown pricing analysis error')
        )

    return result


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
    from lib.common.database import save_audit_record as save_to_database

    record = {
        'id': audit_id,
        'document_url': document_url,
        'violations': violations,
        'score': score
    }
    return save_to_database(record)


if __name__ == '__main__':
    sys.exit(main())
