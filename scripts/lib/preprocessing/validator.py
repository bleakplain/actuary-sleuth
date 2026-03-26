#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果验证器

验证提取结果的完整性和业务规则。
"""
import logging
from typing import Dict, List, Callable, Optional, Set
from dataclasses import dataclass

from .models import ExtractResult, ValidationResult


logger = logging.getLogger(__name__)


@dataclass
class BusinessRule:
    """业务规则"""
    name: str
    check: Callable[[Dict], bool]
    error_message: str


class Validator:
    """提取结果验证器"""

    # 验证阈值常量
    LOW_CONFIDENCE_THRESHOLD = 0.7
    ERROR_PENALTY = 20
    WARNING_PENALTY = 5

    # 核心必需字段（所有产品）
    CORE_REQUIRED_FIELDS = {'product_name', 'insurance_company'}

    # 条件必需字段（根据产品类型）
    CONDITIONAL_REQUIRED_FIELDS = {'insurance_period', 'waiting_period'}

    # 通用业务规则（适用于所有产品）
    COMMON_RULES = [
        BusinessRule(
            name="age_range",
            check=lambda data: (
                int(data.get('age_min', 0)) < int(data.get('age_max', 999))
            ),
            error_message="最低投保年龄必须小于最高投保年龄"
        ),
        BusinessRule(
            name="age_min_positive",
            check=lambda data: int(data.get('age_min', 0)) >= 0,
            error_message="最低投保年龄不能为负数"
        ),
        BusinessRule(
            name="age_max_reasonable",
            check=lambda data: int(data.get('age_max', 999)) <= 100,
            error_message="最高投保年龄不应超过 100 岁"
        ),
    ]

    # 产品特定规则
    PRODUCT_RULES = {
        'critical_illness': [
            BusinessRule(
                name="waiting_period",
                check=lambda data: 0 <= int(data.get('waiting_period', 90)) <= 180,
                error_message="重疾险等待期应在 0-180 天"
            ),
        ],
        'medical_insurance': [
            BusinessRule(
                name="waiting_period",
                check=lambda data: 0 <= int(data.get('waiting_period', 30)) <= 90,
                error_message="医疗险等待期应在 0-90 天"
            ),
        ],
        'life_insurance': [
            BusinessRule(
                name="waiting_period_optional",
                check=lambda data: data.get('waiting_period') is None or 0 <= int(data.get('waiting_period', 0)) <= 365,
                error_message="寿险等待期应在 0-365 天（可为空）"
            ),
        ],
    }

    def __init__(self):
        pass

    def get_required_fields(self, product_type: Optional[str] = None) -> set:
        """获取指定产品类型的必需字段"""
        fields = self.CORE_REQUIRED_FIELDS.copy()
        if product_type in ['critical_illness', 'medical_insurance', 'accident_insurance']:
            fields.update({'insurance_period', 'waiting_period'})
        elif product_type in ['term_life', 'whole_life', 'annuity', 'universal_life']:
            fields.add('insurance_period')
        return fields

    def validate(self, result: ExtractResult) -> ValidationResult:
        """验证提取结果"""
        errors = []
        warnings = []

        # 1. 必需字段检查
        product_type = result.metadata.get('product_type', 'life_insurance')
        required_fields = self.get_required_fields(product_type)

        # 区分核心字段和条件字段
        missing_core = self.CORE_REQUIRED_FIELDS - set(result.data.keys())
        missing = required_fields - set(result.data.keys())

        if missing_core:
            errors.append(f"缺失核心必需字段: {missing_core}")
        if missing - self.CORE_REQUIRED_FIELDS:
            warnings.append(f"缺失条件必需字段: {missing - self.CORE_REQUIRED_FIELDS}")

        # 2. 数据类型检查
        type_errors = self._validate_data_types(result.data)
        errors.extend(type_errors)

        # 3. 业务规则检查（根据产品类型）
        rule_errors = self._validate_business_rules(result.data, product_type)
        errors.extend(rule_errors)

        # 4. 条款验证
        clause_errors = self._validate_clauses(result.data)
        errors.extend(clause_errors)

        # 4. 置信度检查
        low_confidence = [
            k for k, v in result.confidence.items()
            if v < self.LOW_CONFIDENCE_THRESHOLD
        ]
        if low_confidence:
            warnings.append(f"低置信度字段: {low_confidence}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            score=self._calculate_score(len(errors), len(warnings))
        )

    def _validate_data_types(self, data: Dict) -> List[str]:
        """验证数据类型"""
        errors = []

        # 金额字段
        for field in ['premium_rate', 'expense_rate', 'interest_rate']:
            if field in data:
                try:
                    float(str(data[field]).replace('%', '').replace('元', ''))
                except (ValueError, AttributeError):
                    errors.append(f"{field} 格式错误")

        # 年龄字段
        for field in ['age_min', 'age_max']:
            if field in data:
                try:
                    int(data[field])
                except (ValueError, TypeError):
                    errors.append(f"{field} 必须是整数")

        return errors

    def _validate_business_rules(self, data: Dict, product_type: str) -> List[str]:
        """验证业务规则"""
        errors = []

        # 通用规则
        for rule in self.COMMON_RULES:
            try:
                if not rule.check(data):
                    errors.append(f"{rule.name}: {rule.error_message}")
            except Exception as e:
                logger.debug(f"规则 {rule.name} 验证失败: {e}")

        # 产品特定规则
        product_rules = self.PRODUCT_RULES.get(product_type, [])
        for rule in product_rules:
            try:
                if not rule.check(data):
                    errors.append(f"{rule.name}: {rule.error_message}")
            except Exception as e:
                logger.debug(f"规则 {rule.name} 验证失败: {e}")

        return errors

    def _validate_clauses(self, data: Dict) -> List[str]:
        """验证条款数据"""
        errors: List[str] = []
        clauses = data.get('clauses', [])

        if not clauses:
            return errors

        # 检查条款编号唯一性
        clause_numbers = []
        for clause in clauses:
            if isinstance(clause, dict):
                number = clause.get('number')
                if number:
                    if number in clause_numbers:
                        errors.append(f"重复的条款编号: {number}")
                    clause_numbers.append(number)

                # 检查条款内容非空
                text = clause.get('text', '')
                if len(text.strip()) < 10:
                    errors.append(f"条款 {number} 内容过短")

        return errors

    def _calculate_score(self, error_count: int, warning_count: int) -> int:
        """计算验证分数"""
        # 基础分 100
        score = 100

        # 错误扣分
        score -= error_count * self.ERROR_PENALTY

        # 警告扣分
        score -= warning_count * self.WARNING_PENALTY

        return max(score, 0)
