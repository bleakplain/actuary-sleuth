#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 表格解析测试"""
import pytest
import sys
sys.path.insert(0, 'scripts')
from lib.doc_parser.kb.table_utils import (
    find_tables,
    parse_table,
    parse_table_row,
    is_within_table,
)


class TestParseTableRow:
    def test_simple_row(self):
        assert parse_table_row("| a | b | c |") == ["a", "b", "c"]

    def test_row_with_spaces(self):
        assert parse_table_row("|  列1  |  列2  |") == ["列1", "列2"]

    def test_invalid_row_no_pipe(self):
        assert parse_table_row("a | b | c") == []


class TestParseTable:
    def test_simple_table(self):
        table_text = "| 列1 | 列2 |\n|---|---|\n| a | b |\n| c | d |"
        result = parse_table(table_text)
        assert result is not None
        header, rows = result
        assert header == ["列1", "列2"]
        assert rows == [["a", "b"], ["c", "d"]]


class TestFindTables:
    def test_find_single_table(self):
        text = "# 标题\n\n这是一段文字。\n\n| 列1 | 列2 |\n|---|---|\n| a | b |\n\n另一段文字。"
        tables = find_tables(text)
        assert len(tables) == 1
        assert tables[0].header == ["列1", "列2"]

    def test_no_table(self):
        text = "这是一段普通文字，没有表格。"
        tables = find_tables(text)
        assert len(tables) == 0


class TestIsWithinTable:
    def test_position_in_table(self):
        table_text = "| a | b |\n|---|---|\n| c | d |"
        tables = find_tables(table_text)
        assert len(tables) == 1
        assert is_within_table(0, tables) is True
        assert is_within_table(100, tables) is False
