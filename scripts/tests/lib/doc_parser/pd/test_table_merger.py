#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表格合并器测试"""
import pytest
from lib.doc_parser.pd.table_merger import TableMerger, TableBoundary


class TestTableMerger:
    """跨页表格合并器测试"""

    def test_detect_cross_page_continuation_same_header(self):
        """相同表头的跨页续表应被检测到"""
        merger = TableMerger()

        table1 = TableBoundary(
            page_num=1,
            bbox=(0, 0, 100, 100),
            header_row=['年龄', '性别', '费率'],
            row_count=10
        )
        table2 = TableBoundary(
            page_num=2,
            bbox=(0, 0, 100, 50),
            header_row=['年龄', '性别', '费率'],
            row_count=5
        )

        assert merger.detect_continuation(table1, table2) is True

    def test_detect_no_continuation_different_pages(self):
        """非相邻页不应合并"""
        merger = TableMerger()

        table1 = TableBoundary(
            page_num=1,
            bbox=(0, 0, 100, 100),
            header_row=['年龄', '性别', '费率'],
            row_count=10
        )
        table2 = TableBoundary(
            page_num=3,  # 不相邻
            bbox=(0, 0, 100, 50),
            header_row=['年龄', '性别', '费率'],
            row_count=5
        )

        assert merger.detect_continuation(table1, table2) is False

    def test_detect_no_continuation_different_headers(self):
        """不同表头不应合并"""
        merger = TableMerger()

        table1 = TableBoundary(
            page_num=1,
            bbox=(0, 0, 100, 100),
            header_row=['年龄', '性别', '费率'],
            row_count=10
        )
        table2 = TableBoundary(
            page_num=2,
            bbox=(0, 0, 100, 50),
            header_row=['公司', '地址', '电话'],  # 完全不同的表头
            row_count=5
        )

        assert merger.detect_continuation(table1, table2) is False

    def test_detect_continuation_data_row_header(self):
        """续表首行为数据行时也应合并"""
        merger = TableMerger()

        table1 = TableBoundary(
            page_num=1,
            bbox=(0, 0, 100, 100),
            header_row=['年龄', '性别', '费率'],
            row_count=10
        )
        table2 = TableBoundary(
            page_num=2,
            bbox=(0, 0, 100, 50),
            header_row=['18', '男', '100'],  # 数据行，非表头
            row_count=5
        )

        assert merger.detect_continuation(table1, table2) is True

    def test_merge_tables_skip_header(self):
        """合并表格时跳过重复表头"""
        merger = TableMerger()

        tables = [
            [['年龄', '费率'], ['18', '100'], ['19', '105']],
            [['年龄', '费率'], ['20', '110'], ['21', '115']],  # 续表
        ]

        merged = merger.merge_tables(tables)

        assert len(merged) == 5  # 表头 + 4 条数据
        assert merged[0] == ['年龄', '费率']
        assert merged[1] == ['18', '100']
        assert merged[4] == ['21', '115']

    def test_merge_tables_no_skip(self):
        """不跳过表头时保留所有行"""
        merger = TableMerger()

        tables = [
            [['年龄', '费率'], ['18', '100']],
            [['公司', '地址']],  # 不同的表头
        ]

        merged = merger.merge_tables(tables, skip_duplicate_headers=False)

        assert len(merged) == 3  # 全部保留（第一表 2 行 + 第二表 1 行）

    def test_group_cross_page_tables(self):
        """跨页表格分组"""
        merger = TableMerger()

        boundaries = [
            TableBoundary(page_num=1, bbox=(0, 0, 100, 100),
                         header_row=['年龄', '费率'], row_count=5),
            TableBoundary(page_num=2, bbox=(0, 0, 100, 50),
                         header_row=['年龄', '费率'], row_count=3),  # 续表
            TableBoundary(page_num=3, bbox=(0, 0, 100, 100),
                         header_row=['公司', '地址'], row_count=2),  # 新表
        ]

        groups = merger.group_cross_page_tables(boundaries)

        assert len(groups) == 2  # 两组
        assert groups[0] == [0, 1]  # 前两个是跨页表
        assert groups[1] == [2]  # 第三个是独立表

    def test_header_similarity(self):
        """表头相似度计算"""
        merger = TableMerger()

        # 完全相同
        assert merger._compute_header_similarity(
            ['年龄', '性别', '费率'],
            ['年龄', '性别', '费率']
        ) == 1.0

        # 部分相同 (2 个相同 / 4 个唯一 = 0.5)
        similarity = merger._compute_header_similarity(
            ['年龄', '性别', '费率'],
            ['年龄', '性别', '保费']
        )
        assert 0.4 <= similarity <= 0.6

        # 完全不同
        assert merger._compute_header_similarity(
            ['年龄', '性别'],
            ['公司', '地址']
        ) == 0.0
