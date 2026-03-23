#!/usr/bin/env python3
"""审核请求验证模块

提供 AuditRequest 数据验证功能。
"""
import re
from typing import List, Dict, Any, Optional

from lib.common.models import AuditRequest, Product, ProductCategory
from lib.common.constants import DocumentValidation
from lib.common.exceptions import ValidationException


class AuditRequestValidator:
    """审核请求验证器"""

    @staticmethod
    def validate_clauses(clauses: List[Dict[str, Any]]) -> None:
        """
        验证条款列表

        Args:
            clauses: 条款列表

        Raises:
            ValidationException: 验证失败
        """
        if not clauses:
            raise ValidationException(
                message="条款列表不能为空",
                details={'field': 'clauses'}
            )

        if len(clauses) > DocumentValidation.MAX_CLAUSES_COUNT:
            raise ValidationException(
                message=f"条款数量超过限制 ({DocumentValidation.MAX_CLAUSES_COUNT})",
                details={
                    'field': 'clauses',
                    'max_count': DocumentValidation.MAX_CLAUSES_COUNT,
                    'actual_count': len(clauses)
                }
            )

        for idx, clause in enumerate(clauses):
            AuditRequestValidator._validate_clause(clause, idx)

    @staticmethod
    def _validate_clause(clause: Dict[str, Any], index: int) -> None:
        """
        验证单个条款

        Args:
            clause: 条款数据
            index: 条款索引

        Raises:
            ValidationException: 验证失败
        """
        if not isinstance(clause, dict):
            raise ValidationException(
                message=f"条款 {index} 必须是字典类型",
                details={'index': index, 'type': type(clause).__name__}
            )

        text = clause.get('text', '')
        if not text or not text.strip():
            raise ValidationException(
                message=f"条款 {index} 的文本内容不能为空",
                details={'index': index}
            )

        text = text.strip()

        if len(text) < DocumentValidation.MIN_CLAUSE_LENGTH:
            raise ValidationException(
                message=f"条款 {index} 的文本过短（最少 {DocumentValidation.MIN_CLAUSE_LENGTH} 字符）",
                details={
                    'index': index,
                    'min_length': DocumentValidation.MIN_CLAUSE_LENGTH,
                    'actual_length': len(text)
                }
            )

        if len(text) > DocumentValidation.MAX_CLAUSE_LENGTH:
            raise ValidationException(
                message=f"条款 {index} 的文本过长（最多 {DocumentValidation.MAX_CLAUSE_LENGTH} 字符）",
                details={
                    'index': index,
                    'max_length': DocumentValidation.MAX_CLAUSE_LENGTH,
                    'actual_length': len(text)
                }
            )

    @staticmethod
    def validate_product(product: Product) -> None:
        """
        验证产品信息

        Args:
            product: 产品信息

        Raises:
            ValidationException: 验证失败
        """
        if not product.name or not product.name.strip():
            raise ValidationException(
                message="产品名称不能为空",
                details={'field': 'product.name'}
            )

        if not product.company or not product.company.strip():
            raise ValidationException(
                message="保险公司名称不能为空",
                details={'field': 'product.company'}
            )

        if not product.period or not product.period.strip():
            raise ValidationException(
                message="保险期间不能为空",
                details={'field': 'product.period'}
            )

        if product.category == ProductCategory.OTHER:
            raise ValidationException(
                message="产品类别不能为 'OTHER'（其他）",
                details={'field': 'product.category', 'value': str(product.category)}
            )

    @staticmethod
    def validate_request(request: AuditRequest) -> None:
        """
        完整验证审核请求

        Args:
            request: 审核请求

        Raises:
            ValidationException: 验证失败
        """
        AuditRequestValidator.validate_clauses(request.clauses)
        AuditRequestValidator.validate_product(request.product)

        total_length = sum(
            len(clause.get('text', '')) for clause in request.clauses
        )

        if total_length > DocumentValidation.MAX_TOTAL_TEXT_LENGTH:
            raise ValidationException(
                message=f"条款总长度超过限制 ({DocumentValidation.MAX_TOTAL_TEXT_LENGTH})",
                details={
                    'max_length': DocumentValidation.MAX_TOTAL_TEXT_LENGTH,
                    'actual_length': total_length
                }
            )
