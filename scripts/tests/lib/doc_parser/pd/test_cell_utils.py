#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 合并单元格处理器测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.doc_parser.pd.cell_utils import MergedCellProcessor


class TestMergedCellProcessor:
    """合并单元格处理器测试"""

    def test_get_cell_text_normal_cell(self):
        """普通单元格应返回自身文本"""
        cell = MagicMock()
        cell.text = "正常内容"
        cell._tc = MagicMock()
        cell._tc.find.return_value = None  # 无 tcPr

        result = MergedCellProcessor.get_cell_actual_text(cell)
        assert result == "正常内容"

    def test_get_cell_text_no_vmerge(self):
        """无合并标记的单元格应返回自身文本"""
        cell = MagicMock()
        cell.text = "普通文本"
        cell._tc = MagicMock()

        tcPr = MagicMock()
        tcPr.find.return_value = None  # 无 vMerge
        cell._tc.find.return_value = tcPr

        result = MergedCellProcessor.get_cell_actual_text(cell)
        assert result == "普通文本"

    def test_get_cell_text_restart_cell(self):
        """合并起始单元格应返回自身文本"""
        cell = MagicMock()
        cell.text = "起始内容"
        cell._tc = MagicMock()

        tcPr = MagicMock()
        vMerge = MagicMock()
        vMerge.get.return_value = "restart"
        tcPr.find.return_value = vMerge
        cell._tc.find.return_value = tcPr

        result = MergedCellProcessor.get_cell_actual_text(cell)
        assert result == "起始内容"

    def test_get_cell_text_continue_cell_finds_parent(self):
        """续接单元格应查找起始单元格内容"""
        cell = MagicMock()
        cell.text = ""  # 续接单元格本身为空
        cell._tc = MagicMock()

        tcPr = MagicMock()
        vMerge = MagicMock()
        vMerge.get.return_value = "continue"  # 续接标记
        tcPr.find.return_value = vMerge
        cell._tc.find.return_value = tcPr

        # Mock _find_merged_content 返回起始内容
        with patch.object(
            MergedCellProcessor, '_find_merged_content', return_value="父单元格内容"
        ):
            result = MergedCellProcessor.get_cell_actual_text(cell)
            assert result == "父单元格内容"

    def test_flatten_table(self):
        """表格展开应正确处理所有单元格"""
        # 创建模拟表格
        table = MagicMock()
        row1 = MagicMock()
        row1.cells = [MagicMock(text="A1"), MagicMock(text="B1")]
        row2 = MagicMock()
        row2.cells = [MagicMock(text="A2"), MagicMock(text="B2")]
        table.rows = [row1, row2]

        # Mock get_cell_actual_text
        with patch.object(
            MergedCellProcessor, 'get_cell_actual_text',
            side_effect=lambda c: c.text
        ):
            result = MergedCellProcessor.flatten_table(table)

        assert len(result) == 2
        assert result[0] == ["A1", "B1"]
        assert result[1] == ["A2", "B2"]

    def test_get_cell_index_success(self):
        """成功获取单元格索引"""
        cell = MagicMock()
        cell._tc = MagicMock()

        row = MagicMock()
        cells = [MagicMock(), cell._tc, MagicMock()]
        row.findall.return_value = cells
        cell._tc.getparent.return_value = row

        result = MergedCellProcessor._get_cell_index(cell)
        assert result == 1

    def test_get_cell_index_not_found(self):
        """单元格不在行中时返回 None"""
        cell = MagicMock()
        cell._tc = MagicMock()

        row = MagicMock()
        row.findall.return_value = [MagicMock(), MagicMock()]
        cell._tc.getparent.return_value = row

        result = MergedCellProcessor._get_cell_index(cell)
        assert result is None

    def test_extract_text_from_tc(self):
        """从 tc 元素提取文本"""
        tc = MagicMock()

        # 模拟 <w:t> 元素
        text_elements = [
            MagicMock(text="第一段"),
            MagicMock(text="第二段"),
        ]
        tc.iter.return_value = text_elements

        result = MergedCellProcessor._extract_text_from_tc(tc)
        assert result == "第一段第二段"

    def test_extract_text_from_tc_empty(self):
        """空 tc 元素返回空字符串"""
        tc = MagicMock()
        tc.iter.return_value = []
        result = MergedCellProcessor._extract_text_from_tc(tc)
        assert result == ""

    def test_find_merged_content_exception_handling(self):
        """异常情况返回空字符串"""
        cell = MagicMock()
        cell._tc = MagicMock()
        cell._tc.getparent.side_effect = Exception("测试异常")

        result = MergedCellProcessor._find_merged_content(cell)
        assert result == ""
