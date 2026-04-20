#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 跨页表格合并器"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional

from lib.rag_engine.tokenizer import jaccard_similarity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableBoundary:
    """表格边界信息"""
    page_num: int
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    header_row: List[str]
    row_count: int


class TableMerger:
    """跨页表格合并器

    检测并合并 PDF 中跨页断裂的表格。
    """

    HEADER_SIMILARITY_THRESHOLD = 0.8

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold

    def detect_continuation(
        self,
        table1: TableBoundary,
        table2: TableBoundary,
    ) -> bool:
        """检测 table2 是否是 table1 的续表。

        判断依据：
        1. 必须是相邻页
        2. 表头相似度超过阈值，或 table2 首行为数据行
        """
        # 必须是相邻页
        if table2.page_num != table1.page_num + 1:
            return False

        # 表头相似度检测
        header_similarity = self._compute_header_similarity(
            table1.header_row, table2.header_row
        )
        if header_similarity >= self.similarity_threshold:
            return True

        # 无表头续表检测：table2 首行看起来像数据行而非表头
        if self._is_data_row(table2.header_row):
            return True

        return False

    def _compute_header_similarity(
        self,
        header1: List[str],
        header2: List[str],
    ) -> float:
        """计算表头相似度（Jaccard 系数）"""
        if not header1 or not header2:
            return 0.0

        set1 = set(cell.strip() for cell in header1 if cell and cell.strip())
        set2 = set(cell.strip() for cell in header2 if cell and cell.strip())

        return jaccard_similarity(set1, set2)

    def _is_data_row(self, row: List[str]) -> bool:
        """判断是否为数据行（非表头）

        数据行通常包含数字或特定关键词。
        """
        if not row:
            return False

        text = ' '.join(str(cell) for cell in row if cell)

        # 数据行指示词：年龄、费率、金额等
        data_indicators = ['年龄', '费率', '保费', '保额', '元', '周岁', '性别']
        if any(indicator in text for indicator in data_indicators):
            return True

        # 检查是否包含数字
        digit_count = sum(1 for c in text if c.isdigit())
        if digit_count > len(text) * 0.3:
            return True

        return False

    def merge_tables(
        self,
        tables: List[List[List[str]]],
        skip_duplicate_headers: bool = True,
    ) -> List[List[str]]:
        """合并多个表格数据。

        Args:
            tables: 表格数据列表，每个表格是二维数组
            skip_duplicate_headers: 是否跳过重复的表头

        Returns:
            合并后的二维数组
        """
        if not tables:
            return []
        if len(tables) == 1:
            return tables[0]

        merged = list(tables[0])  # 复制第一个表格

        for table in tables[1:]:
            if not table:
                continue

            # 检查首行是否是重复表头
            if skip_duplicate_headers and merged and table:
                if self._is_same_header(merged[0], table[0]):
                    # 跳过表头，只添加数据行
                    merged.extend(table[1:])
                    continue

            merged.extend(table)

        return merged

    def _is_same_header(
        self,
        header1: List[str],
        header2: List[str],
    ) -> bool:
        """判断两行是否是相同的表头"""
        if not header1 or not header2:
            return False

        similarity = self._compute_header_similarity(header1, header2)
        return similarity >= self.similarity_threshold

    def group_cross_page_tables(
        self,
        boundaries: List[TableBoundary],
    ) -> List[List[int]]:
        """将跨页表格分组。

        Args:
            boundaries: 按 page_num 排序的表格边界列表

        Returns:
            分组列表，每组包含 table 索引
        """
        if not boundaries:
            return []

        groups: List[List[int]] = []
        current_group: List[int] = [0]  # 第一个表格开始新组

        for i in range(1, len(boundaries)):
            prev_table = boundaries[i - 1]
            curr_table = boundaries[i]

            if self.detect_continuation(prev_table, curr_table):
                current_group.append(i)
            else:
                groups.append(current_group)
                current_group = [i]

        groups.append(current_group)
        return groups
