#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
融合机制

对多个提取器的结果进行投票融合，选择最佳结果。
"""
import logging
from typing import Dict, List, Any, Set
from collections import Counter

from .extractors.base import ExtractionResult


logger = logging.getLogger(__name__)


class Fuser:
    """融合器 - 融合多个提取器的结果"""

    def __init__(self, min_agreement: float = 0.5):
        self.min_agreement = min_agreement

    def fuse(self, results: List[ExtractionResult],
             required_fields: Set[str]) -> ExtractionResult:
        if not results:
            return ExtractionResult(
                data={},
                confidence=0.0,
                extractor="none",
                duration=0.0,
                metadata={'error': 'No results to fuse'}
            )

        if len(results) == 1:
            return results[0]

        all_fields: Set[str] = set()
        for result in results:
            all_fields.update(result.data.keys())

        fused_data = {}
        field_agreement = {}

        for field in all_fields:
            values = []
            weights = []

            for result in results:
                if field in result.data and result.data[field]:
                    values.append(result.data[field])
                    weights.append(result.confidence)

            if not values:
                continue

            if len(values) == 1:
                fused_data[field] = values[0]
                field_agreement[field] = 1.0
            else:
                voted_value, agreement = self._vote(values, weights)
                fused_data[field] = voted_value
                field_agreement[field] = agreement

        overall_confidence = self._compute_overall_confidence(results, fused_data)
        agreement_score = self._compute_agreement_score(field_agreement, required_fields)
        total_duration = sum(r.duration for r in results)
        strategies = '+'.join(r.extractor for r in results)

        logger.info(f"融合完成: {len(results)} 个提取器, "
                   f"字段 {len(fused_data)}/{len(required_fields)}, "
                   f"一致性 {agreement_score:.2f}, "
                   f"置信度 {overall_confidence:.2f}")

        return ExtractionResult(
            data=fused_data,
            confidence=overall_confidence,
            extractor=f"fused({strategies})",
            duration=total_duration,
            metadata={
                'num_extractors': len(results),
                'agreement_score': agreement_score,
                'field_agreement': field_agreement,
                'extractors_used': [r.extractor for r in results],
                'fields_extracted': list(fused_data.keys())
            }
        )

    def _vote(self, values: List[Any], weights: List[float]) -> tuple:
        counter: Counter = Counter()
        for value, weight in zip(values, weights):
            key = self._normalize_value(value)
            counter[key] += int(weight * 100)

        most_common = counter.most_common(1)
        if not most_common:
            return values[0], 0.0

        winning_key = most_common[0][0]
        total_weight = sum(counter.values())
        agreement = most_common[0][1] / total_weight if total_weight > 0 else 0.0

        for value in values:
            if self._normalize_value(value) == winning_key:
                return value, agreement

        return values[0], agreement

    def _normalize_value(self, value: Any) -> str:
        if isinstance(value, str):
            return ''.join(c.lower() for c in value if c.isalnum())
        elif isinstance(value, list):
            return f"list[{len(value)}]"
        elif isinstance(value, dict):
            return f"dict[{','.join(sorted(value.keys()))}]"
        else:
            return str(value)

    def _compute_overall_confidence(self, results: List[ExtractionResult],
                                     fused_data: Dict) -> float:
        if not fused_data:
            return 0.0

        confidences = []
        for field in fused_data:
            field_confidences = []
            for result in results:
                if field in result.data:
                    field_confidences.append(result.confidence)
            if field_confidences:
                confidences.append(max(field_confidences))

        return sum(confidences) / len(confidences) if confidences else 0.0

    def _compute_agreement_score(self, field_agreement: Dict[str, float],
                                 required_fields: Set[str]) -> float:
        if not required_fields:
            return 1.0

        required_agreements = []
        for field in required_fields:
            if field in field_agreement:
                required_agreements.append(field_agreement[field])

        if not required_agreements:
            return 0.0

        return sum(required_agreements) / len(required_agreements)
