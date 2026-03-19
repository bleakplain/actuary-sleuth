#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果验证器

验证提取结果的完整性和业务规则。
"""
import logging
from typing import Dict, List
from dataclasses import dataclass

from .models import ExtractResult, ValidationResult


logger = logging.getLogger(__name__)


@dataclass
class BusinessRule:
    """业务规则"""
    name: str
    check: callable
    error_message: str


class ResultValidator:
    """提取结果验证器"""

    # 验证阈值常量
    LOW_CONFIDENCE_THRESHOLD = 0.7
    ERROR_PENALTY = 20
    WARNING_PENALTY = 5

    # 通用业务规则（适用于所有产品）
    COMMON_RULES = [
        BusinessRule(
            name="age_range",
            check=lambda data: (
                int(data.get('age_min', 0)) < int(data.get('age_max', 999))
            ),
            error_message="最低投保年龄必须小于最高投保年龄"
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

    def validate(self, result: ExtractResult) -> ValidationResult:
        """验证提取结果"""
        errors = []
        warnings = []

        # 1. 必需字段检查（根据产品类型动态确定）
        from .extractor_selector import ExtractorSelector
        product_type = result.metadata.get('product_type', 'life_insurance')
        required_fields = ExtractorSelector.get_required_fields(product_type)

        # 区分核心字段和条件字段
        from .extractor_selector import ExtractorSelector as ES
        missing_core = ES.CORE_REQUIRED_FIELDS - set(result.data.keys())
        missing = required_fields - set(result.data.keys())

        if missing_core:
            errors.append(f"缺失核心必需字段: {missing_core}")
        if missing - ES.CORE_REQUIRED_FIELDS:
            warnings.append(f"缺失条件必需字段: {missing - ES.CORE_REQUIRED_FIELDS}")

        # 2. 数据类型检查
        type_errors = self._validate_data_types(result.data)
        errors.extend(type_errors)

        # 3. 业务规则检查（根据产品类型）
        rule_errors = self._validate_business_rules(result.data, product_type)
        errors.extend(rule_errors)

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

    def _calculate_score(self, error_count: int, warning_count: int) -> int:
        """计算验证分数"""
        # 基础分 100
        score = 100

        # 错误扣分
        score -= error_count * self.ERROR_PENALTY

        # 警告扣分
        score -= warning_count * self.WARNING_PENALTY

        return max(score, 0)
