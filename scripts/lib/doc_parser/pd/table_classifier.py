#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 表格分类器

基于边框线检测判断表格类型。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableClassification:
    """表格分类结果"""
    table_type: str  # "bordered", "borderless", "unknown"
    confidence: float
    bbox: Tuple[float, float, float, float]


class TableClassifier:
    """表格类型分类器

    基于边框线检测判断表格类型。
    """

    def __init__(self, border_threshold: float = 0.5):
        self.border_threshold = border_threshold

    def classify(self, table) -> TableClassification:
        """分类表格类型

        Args:
            table: pdfplumber 的表格对象

        Returns:
            TableClassification 结果
        """
        bbox = getattr(table, 'bbox', (0, 0, 0, 0))

        edges = getattr(table, 'edges', None)

        if edges is not None:
            edge_count = len(edges) if isinstance(edges, list) else 0
            if edge_count >= 8:
                return TableClassification(
                    table_type="bordered",
                    confidence=0.9,
                    bbox=bbox,
                )

        if bbox and (bbox[2] - bbox[0]) > 0 and (bbox[3] - bbox[1]) > 0:
            return TableClassification(
                table_type="bordered",
                confidence=0.7,
                bbox=bbox,
            )

        return TableClassification(
            table_type="unknown",
            confidence=0.5,
            bbox=bbox,
        )

    def has_borders(self, table) -> bool:
        """判断是否有边框

        Args:
            table: pdfplumber 的表格对象

        Returns:
            True 如果有边框
        """
        result = self.classify(table)
        return result.table_type == "bordered" and result.confidence >= self.border_threshold
