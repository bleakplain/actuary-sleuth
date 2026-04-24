#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表格分类器

识别表格类型：费率表、保障计划表、药品清单、手术并发症表、医院名单等。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional

from ..models import TableType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableClassification:
    """表格分类结果"""
    table_type: TableType
    confidence: float
    bbox: Tuple[float, float, float, float]


class TableClassifier:
    """表格类型分类器"""

    # 表格类型关键词
    PREMIUM_KEYWORDS = ['费率', '保险费', '保费', '基本保险金额']
    COVERAGE_KEYWORDS = ['给付比例', '保障计划', '保险责任', '保险金额']
    GENE_TEST_KEYWORDS = ['基因检测', '产品名称', '检测产品']
    DRUG_KEYWORDS = ['药品', '商品名', '通用名', '靶向药']
    COMPLICATION_KEYWORDS = ['并发症', '手术', '诊疗类别', '介入诊疗']
    HOSPITAL_KEYWORDS = ['指定医院', '医疗机构', '医院名单', '医院名称']

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

        rows = table.extract()
        if not rows or not rows[0]:
            return TableClassification(
                table_type=TableType.UNKNOWN,
                confidence=0.5,
                bbox=bbox,
            )

        header = ' '.join(str(cell or '') for cell in rows[0])

        # 按关键词匹配表格类型
        table_type = self._match_type(header)
        confidence = 0.9 if table_type != TableType.OTHER else 0.6

        return TableClassification(
            table_type=table_type,
            confidence=confidence,
            bbox=bbox,
        )

    def _match_type(self, header: str) -> TableType:
        """根据表头关键词匹配表格类型"""
        # 基因检测产品清单（优先匹配，避免被药品关键词误匹配）
        for kw in self.GENE_TEST_KEYWORDS:
            if kw in header:
                return TableType.GENE_TEST

        # 药品清单表
        for kw in self.DRUG_KEYWORDS:
            if kw in header:
                return TableType.DRUG_LIST

        # 手术并发症表
        for kw in self.COMPLICATION_KEYWORDS:
            if kw in header:
                return TableType.COMPLICATION

        # 医院名单表
        for kw in self.HOSPITAL_KEYWORDS:
            if kw in header:
                return TableType.HOSPITAL

        # 给付比例表/保障计划表
        for kw in self.COVERAGE_KEYWORDS:
            if kw in header:
                return TableType.COVERAGE

        # 费率表
        for kw in self.PREMIUM_KEYWORDS:
            if kw in header:
                return TableType.PREMIUM

        return TableType.OTHER

    def classify_by_header(self, header: str) -> TableType:
        """直接根据表头字符串分类表格类型"""
        return self._match_type(header)

    def has_borders(self, table) -> bool:
        """判断是否有边框"""
        edges = getattr(table, 'edges', None)
        if edges is not None:
            edge_count = len(edges) if isinstance(edges, list) else 0
            if edge_count >= 8:
                return True

        bbox = getattr(table, 'bbox', (0, 0, 0, 0))
        if bbox and (bbox[2] - bbox[0]) > 0 and (bbox[3] - bbox[1]) > 0:
            return True

        return False
