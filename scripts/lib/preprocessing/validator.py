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


class ExtractResultValidator:
    """提取结果验证器"""

    # 业务规则
    BUSINESS_RULES = [
        # 年龄规则
        BusinessRule(
            name="age_range",
            check=lambda data: (
                int(data.get('age_min', 0)) < int(data.get('age_max', 999))
            ),
            error_message="最低投保年龄必须小于最高投保年龄"
        ),

        # 等待期规则
        BusinessRule(
            name="waiting_period",
            check=lambda data: (
                0 <= int(data.get('waiting_period', 0)) <= 365
            ),
            error_message="等待期必须在 0-365 天之间"
        ),
    ]

    def __init__(self):
        pass

    def validate(self, result: ExtractResult) -> ValidationResult:
        """验证提取结果"""
        errors = []
        warnings = []

        # 1. 必需字段检查
        from .path_selector import ExtractionPathSelector
        missing = ExtractionPathSelector.get_required_fields() - set(result.data.keys())
        if missing:
            errors.append(f"缺失必需字段: {missing}")

        # 2. 数据类型检查
        type_errors = self._validate_data_types(result.data)
        errors.extend(type_errors)

        # 3. 业务规则检查
        rule_errors = self._validate_business_rules(result.data)
        errors.extend(rule_errors)

        # 4. 置信度检查
        low_confidence = [
            k for k, v in result.confidence.items()
            if v < 0.7
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

    def _validate_business_rules(self, data: Dict) -> List[str]:
        """验证业务规则"""
        errors = []

        for rule in self.BUSINESS_RULES:
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
        score -= error_count * 20

        # 警告扣分
        score -= warning_count * 5

        return max(score, 0)
