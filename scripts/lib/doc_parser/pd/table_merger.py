#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 跨页表格合并器"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)

HEADER_SIMILARITY_THRESHOLD = 0.8
SAME_TABLE_MAX_GAP_PAGES = 1


@dataclass
class ExtractedTable:
    """从 PDF 提取的表格信息"""
    page_num: int
    bbox: Tuple[float, float, float, float]
    header: List[str]
    rows: List[List[str]]
    raw_data: List[List[str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.header) if self.header else 0


class TableMerger:
    """PDF 跨页表格合并器"""

    def __init__(self, header_similarity_threshold: float = HEADER_SIMILARITY_THRESHOLD):
        self.header_similarity_threshold = header_similarity_threshold

    def merge_tables(self, tables: List[ExtractedTable]) -> List[ExtractedTable]:
        """合并跨页表格"""
        if not tables:
            return []

        sorted_tables = sorted(tables, key=lambda t: t.page_num)

        merged: List[ExtractedTable] = []
        current: ExtractedTable | None = None

        for table in sorted_tables:
            if current is None:
                current = table
                continue

            if self._should_merge(current, table):
                current = self._do_merge(current, table)
            else:
                merged.append(current)
                current = table

        if current:
            merged.append(current)

        return merged

    def _should_merge(self, table1: ExtractedTable, table2: ExtractedTable) -> bool:
        """判断两个表格是否应该合并"""
        if table2.page_num - table1.page_num > SAME_TABLE_MAX_GAP_PAGES:
            return False

        if table1.column_count != table2.column_count:
            return False

        if not table2.header or all(not cell.strip() for cell in table2.header):
            return True

        similarity = self._calculate_header_similarity(table1.header, table2.header)
        return similarity >= self.header_similarity_threshold

    def _calculate_header_similarity(self, h1: List[str], h2: List[str]) -> float:
        """计算表头相似度"""
        if not h1 or not h2 or len(h1) != len(h2):
            return 0.0

        matches = sum(1 for a, b in zip(h1, h2) if a.strip() == b.strip())
        return matches / len(h1)

    def _do_merge(self, table1: ExtractedTable, table2: ExtractedTable) -> ExtractedTable:
        """合并两个表格"""
        return ExtractedTable(
            page_num=table1.page_num,
            bbox=table1.bbox,
            header=table1.header,
            rows=table1.rows + table2.rows,
            raw_data=table1.raw_data + table2.raw_data,
        )


def extract_table_with_header(raw_data: List[List[str]]) -> ExtractedTable:
    """从原始表格数据提取表头和数据行"""
    if not raw_data:
        return ExtractedTable(
            page_num=0,
            bbox=(0, 0, 0, 0),
            header=[],
            rows=[],
            raw_data=[],
        )

    header = [str(cell or '').strip() for cell in raw_data[0]]
    rows = [[str(cell or '').strip() for cell in row] for row in raw_data[1:]]

    return ExtractedTable(
        page_num=0,
        bbox=(0, 0, 0, 0),
        header=header,
        rows=rows,
        raw_data=raw_data,
    )
