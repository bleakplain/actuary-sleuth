#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from lib.preprocessing.document_fetcher import fetch_feishu_document, DocumentFetchError
from lib.audit.evaluation import calculate_result
from lib.common.id_generator import IDGenerator
from lib.common.logger import get_audit_logger
from lib.common.date_utils import get_current_timestamp
from lib.common.database import save_audit_record
from lib.common.audit import (
    PreprocessedResult,
    CheckedResult,
    AnalyzedResult,
)
from lib.common.models import Product
from lib.common.product import map_to_scoring_type
from lib.common.exceptions import AuditStepException


def main():
    parser = argparse.ArgumentParser(description='Actuary Sleuth - Product Audit Script')
    parser.add_argument('--documentUrl', required=True, help='Feishu document URL')
    args = parser.parse_args()

    try:
        result = execute(args.documentUrl)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except DocumentFetchError as e:
        error_result = {"success": False, "error": str(e), "error_type": "DocumentFetchError"}
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as e:
        error_result = {"success": False, "error": str(e), "error_type": type(e).__name__}
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        return 1


def execute(document_url: str) -> dict:
    audit_id = IDGenerator.generate_audit()
    step_logger = get_audit_logger(audit_id)

    step_logger.step("开始审核流程")

    document_content = fetch_feishu_document(document_url)
    preprocessed = execute_preprocess(audit_id, document_url, document_content)
    checked = execute_check(preprocessed)
    analyzed = execute_score(checked)
    result = calculate_result(analyzed)

    step_logger.step("保存审核记录")
    save_success = save_audit_record(
        audit_id,
        document_url,
        result.get_violations(),
        result.score
    )

    if not save_success:
        raise AuditStepException("保存审核记录到数据库失败")

    step_logger.step("审核完成")
    return result.to_dict()


def execute_preprocess(audit_id: str, document_url: str, document_content: str):
    import preprocess

    step_logger = get_audit_logger(audit_id)
    step_logger.step("预处理文档")
    result = preprocess.execute({'documentContent': document_content})
    if not result.success:
        from lib.common.exceptions import DocumentPreprocessException
        raise DocumentPreprocessException(result.error)

    product_info = result.get_product_info()
    product_info['document_url'] = document_url

    return PreprocessedResult(
        audit_id=audit_id,
        document_url=document_url,
        timestamp=get_current_timestamp(),
        product=Product.from_dict(product_info),
        clauses=result.get_clauses(),
        pricing_params=result.get_pricing_params()
    )


def execute_check(preprocessed):
    import check

    step_logger = get_audit_logger(preprocessed.audit_id)
    if not preprocessed.clauses:
        from lib.common.exceptions import NegativeListCheckException
        raise NegativeListCheckException("没有可审核的条款")

    step_logger.step("负面清单检查")

    result = check.execute({'clauses': preprocessed.clauses})

    if not result.success:
        from lib.common.exceptions import NegativeListCheckException
        raise NegativeListCheckException(result.error)

    return CheckedResult(
        preprocessed=preprocessed,
        violations=result.get_violations()
    )


def execute_score(checked):
    import scoring

    category = checked.product.category
    scoring_type = map_to_scoring_type(category)

    step_logger = get_audit_logger(checked.audit_id)
    step_logger.step("定价分析")

    result = scoring.execute({
        'pricing_params': checked.preprocessed.pricing_params,
        'scoring_type': scoring_type
    })

    if not result.success:
        from lib.common.exceptions import PricingAnalysisException
        raise PricingAnalysisException(result.error)

    return AnalyzedResult(
        checked=checked,
        pricing_analysis=result.get_pricing()
    )


if __name__ == '__main__':
    sys.exit(main())
