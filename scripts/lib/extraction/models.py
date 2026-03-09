#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取结果数据模型

定义文档提取过程中使用的数据结构。
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List
from collections import Counter


@dataclass(frozen=True)
class ExtractResult:
    """提取结果"""
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    provenance: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """验证数据完整性"""
        data_keys = set(self.data.keys())
        conf_keys = set(self.confidence.keys())
        prov_keys = set(self.provenance.keys())

        if not data_keys == conf_keys == prov_keys:
            raise ValueError(
                f"ExtractResult字段不一致: data={sorted(data_keys)}, "
                f"confidence={sorted(conf_keys)}, provenance={sorted(prov_keys)}"
            )

    def get_source_summary(self) -> Dict[str, int]:
        """获取来源统计"""
        sources = Counter(self.provenance.values())
        return dict(sources)

    def get_low_confidence_fields(self, threshold: float = 0.7) -> List[str]:
        """获取低置信度字段"""
        return [
            k for k, v in self.confidence.items()
            if v < threshold
        ]


@dataclass
class QualityMetrics:
    """质量指标"""
    completeness: float  # 完整性 0-1
    accuracy: float      # 准确性 0-1
    consistency: float   # 一致性 0-1
    reasonableness: float # 合理性 0-1

    def overall_score(self) -> int:
        """总体质量评分 (0-100)"""
        from lib.constants import QUALITY_WEIGHTS
        score = sum(
            getattr(self, k) * QUALITY_WEIGHTS[k]
            for k in QUALITY_WEIGHTS
        )
        return int(score * 100)
