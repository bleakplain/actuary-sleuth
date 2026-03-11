#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果合并与质量评估

合并LLM提取和规则提取的结果，并评估质量。
"""
import logging
from typing import Dict, Any, Set, Optional

from lib.constants import QUALITY_WEIGHTS, LLM_DEFAULT_CONFIDENCE
from .models import ExtractResult, QualityMetrics


logger = logging.getLogger(__name__)


class ExtractQualityAssessor:
    """提取质量评估器"""

    # 默认必填字段
    DEFAULT_REQUIRED_FIELDS = {
        'product_name', 'insurance_company',
        'waiting_period', 'premium_rate'
    }

    def __init__(self, required_fields: Optional[Set[str]] = None):
        """
        初始化质量评估器

        Args:
            required_fields: 必填字段集合，默认使用 DEFAULT_REQUIRED_FIELDS
        """
        self.required_fields = required_fields if required_fields is not None else self.DEFAULT_REQUIRED_FIELDS

    def assess(self, result: ExtractResult) -> QualityMetrics:
        """评估提取结果质量"""
        return QualityMetrics(
            completeness=self._assess_completeness(result),
            accuracy=self._assess_accuracy(result),
            consistency=self._assess_consistency(result),
            reasonableness=self._assess_reasonableness(result)
        )

    def _assess_completeness(self, result: ExtractResult) -> float:
        """评估完整性"""
        if not result.data:
            return 0.0

        all_keys = set(result.data.keys())
        for v in result.data.values():
            if isinstance(v, dict):
                all_keys |= {k for k, val in v.items() if val}

        present = len(self.required_fields & all_keys)
        required = len(self.required_fields)
        return present / required

    def _assess_accuracy(self, result: ExtractResult) -> float:
        """评估准确性"""
        if not result.confidence:
            return 0.0
        return sum(result.confidence.values()) / len(result.confidence)

    def _assess_consistency(self, result: ExtractResult) -> float:
        """评估一致性"""
        data = result.data
        amounts = []
        for k, v in data.items():
            if 'rate' in k or 'premium' in k:
                amounts.append(str(v))

        if not amounts:
            return 1.0

        formats = set()
        for amount in amounts:
            if '%' in amount:
                formats.add('percent')
            elif '元' in amount:
                formats.add('currency')

        return 1.0 if len(formats) <= 1 else 0.7

    def _assess_reasonableness(self, result: ExtractResult) -> float:
        """评估合理性"""
        data = result.data
        score = 1.0

        if 'age_min' in data and 'age_max' in data:
            try:
                min_age = int(data['age_min'])
                max_age = int(data['age_max'])
                if min_age >= max_age:
                    score -= 0.3
                if max_age > 100 or min_age < 0:
                    score -= 0.2
            except (ValueError, TypeError):
                score -= 0.2

        if 'waiting_period' in data:
            try:
                period = int(data['waiting_period'])
                if not (0 <= period <= 365):
                    score -= 0.2
            except (ValueError, TypeError):
                score -= 0.1

        return max(score, 0.0)


class LLMRuleMerger:
    """LLM与规则结果合并器"""

    def merge(self, llm_result: ExtractResult, rule_result: Dict) -> ExtractResult:
        """
        合并提取结果（LLM优先，规则回退）

        Args:
            llm_result: LLM提取结果
            rule_result: 规则提取结果
        """
        if not llm_result or not llm_result.data:
            # 将dict转换为ExtractResult
            if isinstance(rule_result, dict):
                return ExtractResult(
                    data=rule_result,
                    confidence={k: 0.85 for k in rule_result},
                    provenance={k: 'rule' for k in rule_result}
                )
            return llm_result

        merged_data = {}
        merged_confidence = {}
        merged_provenance = {}

        all_fields = set(llm_result.data) | set(rule_result.keys())

        for field in all_fields:
            llm_value = llm_result.data.get(field)
            rule_value = rule_result.get(field)

            if llm_value:
                merged_data[field] = llm_value
                merged_confidence[field] = llm_result.confidence.get(field, LLM_DEFAULT_CONFIDENCE)
                merged_provenance[field] = llm_result.provenance.get(field, 'llm')
            elif rule_value:
                merged_data[field] = rule_value
                merged_confidence[field] = 0.85 * 0.9
                merged_provenance[field] = 'rule_fallback'

        return ExtractResult(
            data=merged_data,
            confidence=merged_confidence,
            provenance=merged_provenance
        )
