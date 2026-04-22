#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 表格解析工具"""
from __future__ import annotations

import re
from typing import List, Tuple, Optional

from ..models import MarkdownTable

# Markdown 表格正则模式
MARKDOWN_TABLE_PATTERN = re.compile(
    r'^(\|[^\n]+\|\n)'           # 表头行
    r'(\|[-:| ]+\|\n)'           # 分隔行
    r'(\|[^\n]+\|\n?)+',         # 数据行
    re.MULTILINE
)


def find_tables(text: str) -> List[MarkdownTable]:
    """识别文本中所有 Markdown 表格"""
    tables: List[MarkdownTable] = []

    for match in MARKDOWN_TABLE_PATTERN.finditer(text):
        table_text = match.group(0)
        start_pos = match.start()
        end_pos = match.end()

        parsed = parse_table(table_text)
        if parsed:
            header, rows = parsed
            tables.append(MarkdownTable(
                header=header,
                rows=rows,
                raw_text=table_text,
                start_pos=start_pos,
                end_pos=end_pos,
            ))

    return tables


def parse_table(table_text: str) -> Optional[Tuple[List[str], List[List[str]]]]:
    """解析单个 Markdown 表格"""
    lines = [line.strip() for line in table_text.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        return None

    header = parse_table_row(lines[0])
    if not header:
        return None

    rows: List[List[str]] = []
    for line in lines[2:]:
        row = parse_table_row(line)
        if row:
            rows.append(row)

    return header, rows


def parse_table_row(line: str) -> List[str]:
    """解析表格行"""
    if not line.startswith('|') or not line.endswith('|'):
        return []

    cells = line[1:-1].split('|')
    return [cell.strip() for cell in cells]


def is_within_table(pos: int, tables: List[MarkdownTable]) -> bool:
    """检查位置是否在某个表格内"""
    for table in tables:
        if table.start_pos <= pos < table.end_pos:
            return True
    return False
