#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 合并单元格处理器"""
from __future__ import annotations

import logging
from typing import List, Optional

from docx.table import Table, _Cell
from docx.oxml.ns import qn

logger = logging.getLogger(__name__)


class MergedCellProcessor:
    """Word 合并单元格处理器

    处理 python-docx 读取合并单元格时的数据丢失问题。
    """

    @staticmethod
    def get_cell_actual_text(cell: _Cell) -> str:
        """获取单元格实际文本（处理合并单元格）

        对于垂直合并的单元格：
        - 如果是起始单元格（vMerge="restart"），返回单元格文本
        - 如果是续接单元格（vMerge="continue"），向上查找起始单元格内容

        Args:
            cell: python-docx 的 _Cell 对象

        Returns:
            单元格的实际文本内容
        """
        tc = cell._tc
        tcPr = tc.find(qn('w:tcPr'))

        if tcPr is None:
            return cell.text.strip()

        vMerge = tcPr.find(qn('w:vMerge'))
        if vMerge is None:
            return cell.text.strip()

        merge_val = vMerge.get(qn('w:val'), 'continue')

        if merge_val == 'restart' or merge_val == '1':
            # 起始单元格
            return cell.text.strip()

        # 续接单元格，查找起始单元格
        merged_text = MergedCellProcessor._find_merged_content(cell)
        return merged_text if merged_text else cell.text.strip()

    @staticmethod
    def _find_merged_content(cell: _Cell) -> str:
        """向上查找合并单元格的起始内容

        Args:
            cell: 续接单元格

        Returns:
            起始单元格的文本内容，或空字符串
        """
        try:
            # 获取表格和单元格位置
            table_element = cell._tc.getparent().getparent()  # row -> table
            cell_idx = MergedCellProcessor._get_cell_index(cell)

            if cell_idx is None:
                return ''

            # 获取当前行索引
            current_row = cell._tc.getparent()
            row_idx = list(table_element).index(current_row)

            # 向上遍历查找起始单元格
            for i in range(row_idx - 1, -1, -1):
                row = table_element[i]
                cells = row.findall(qn('w:tc'))
                if cell_idx < len(cells):
                    prev_tc = cells[cell_idx]
                    tcPr = prev_tc.find(qn('w:tcPr'))
                    if tcPr is not None:
                        vMerge = tcPr.find(qn('w:vMerge'))
                        if vMerge is not None:
                            merge_val = vMerge.get(qn('w:val'), 'continue')
                            if merge_val in ('restart', '1'):
                                # 找到起始单元格
                                return MergedCellProcessor._extract_text_from_tc(prev_tc)

            return ''
        except Exception as e:
            logger.debug(f"查找合并单元格内容失败: {e}")
            return ''

    @staticmethod
    def _get_cell_index(cell: _Cell) -> Optional[int]:
        """获取单元格在行中的索引"""
        try:
            row = cell._tc.getparent()
            cells = row.findall(qn('w:tc'))
            return cells.index(cell._tc)
        except Exception:
            return None

    @staticmethod
    def _extract_text_from_tc(tc) -> str:
        """从 tc 元素提取文本"""
        texts = []
        for t in tc.iter(qn('w:t')):
            if t.text:
                texts.append(t.text)
        return ''.join(texts).strip()

    @staticmethod
    def flatten_table(table: Table) -> List[List[str]]:
        """展开合并单元格，返回完整二维数组

        Args:
            table: python-docx 的 Table 对象

        Returns:
            二维字符串数组，合并单元格已展开
        """
        rows: List[List[str]] = []
        for row in table.rows:
            cells = [
                MergedCellProcessor.get_cell_actual_text(cell)
                for cell in row.cells
            ]
            rows.append(cells)
        return rows
