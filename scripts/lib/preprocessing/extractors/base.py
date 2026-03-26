#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器基类

定义所有提取器的通用接口。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass(frozen=True)
class ExtractionResult:
    """提取结果

    Attributes:
        data: 提取的数据
        confidence: 置信度 (0-1)
        extractor: 提取器名称
        duration: 处理耗时（秒）
        metadata: 额外元数据
    """
    data: Dict[str, Any]
    confidence: float
    extractor: str
    duration: float
    metadata: Dict[str, Any]

    def is_complete(self, required_fields: set) -> bool:
        """检查是否包含所有必需字段"""
        return all(field in self.data for field in required_fields)

    def get_field(self, field: str, default=None):
        """获取字段值"""
        return self.data.get(field, default)

    def merge(self, other: 'ExtractionResult') -> 'ExtractionResult':
        """合并两个结果（other 覆盖 self）"""
        merged_data = {**self.data, **other.data}
        merged_metadata = {**self.metadata, **other.metadata}
        # 使用更高的置信度
        merged_confidence = max(self.confidence, other.confidence)

        return ExtractionResult(
            data=merged_data,
            confidence=merged_confidence,
            extractor=f"{self.extractor}+{other.extractor}",
            duration=self.duration + other.duration,
            metadata=merged_metadata
        )


class Extractor(ABC):
    """提取器基类"""

    # 提取器名称
    name: str = "base_extractor"

    # 提取器描述
    description: str = ""

    def __init__(self, llm_client=None):
        """
        初始化提取器

        Args:
            llm_client: LLM 客户端（可选）
        """
        self.llm_client = llm_client

    @abstractmethod
    def can_handle(self, document: str, structure: Dict[str, Any]) -> bool:
        """
        判断是否可以处理此文档

        Args:
            document: 文档内容
            structure: 语义分析结果

        Returns:
            是否可以处理
        """
        pass

    @abstractmethod
    def extract(self, document: str, structure: Dict[str, Any],
                required_fields: set) -> ExtractionResult:
        """
        执行提取

        Args:
            document: 文档内容
            structure: 语义分析结果
            required_fields: 必需字段集合

        Returns:
            提取结果
        """
        pass

    def estimate_cost(self, document: str) -> float:
        """
        估算提取成本（相对值）

        Args:
            document: 文档内容

        Returns:
            成本值（越低越便宜）
        """
        # 默认基于文档长度
        return len(document) / 1000

    def estimate_duration(self, document: str) -> float:
        """
        估算处理时间（秒）

        Args:
            document: 文档内容

        Returns:
            预估耗时
        """
        return self.estimate_cost(document) * 0.1

    def get_confidence(self, result: Dict[str, Any],
                      required_fields: set) -> float:
        """
        计算提取结果的置信度

        Args:
            result: 提取结果
            required_fields: 必需字段

        Returns:
            置信度 (0-1)
        """
        # 基于必需字段覆盖率计算
        covered = sum(1 for f in required_fields if f in result and result[f])
        total = len(required_fields)
        if total == 0:
            return 0.5
        return covered / total
