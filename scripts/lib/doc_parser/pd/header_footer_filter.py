#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 页眉页脚过滤器"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterConfig:
    """过滤配置"""
    header_patterns: Tuple[str, ...] = (
        "内部资料", "严禁外传", "仅供内部使用", "保密",
    )
    footer_patterns: Tuple[str, ...] = (
        r"第\s*\d+\s*页", r"Page\s*\d+", r"共\s*\d+\s*页",
        r"\d+\s*/\s*\d+",
    )
    header_max_length: int = 60
    footer_max_length: int = 40


class HeaderFooterFilter:
    """页眉页脚过滤器"""

    def __init__(
        self,
        config: FilterConfig = None,
        header_region_ratio: float = 0.08,
        footer_region_ratio: float = 0.08,
    ):
        self.config = config or FilterConfig()
        self.header_region_ratio = header_region_ratio
        self.footer_region_ratio = footer_region_ratio

    def filter(self, page) -> str:
        """过滤页眉页脚，返回清洁文本

        Args:
            page: pdfplumber 的页面对象

        Returns:
            过滤后的文本
        """
        text = page.extract_text() or ""
        lines = text.split('\n')
        page_height = page.height

        if not lines:
            return ""

        line_positions = self._get_line_positions(page)

        filtered_lines: List[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            y_pos = line_positions[i] if i < len(line_positions) else page_height / 2

            if y_pos > page_height * (1 - self.header_region_ratio):
                if self._is_header(stripped):
                    logger.debug(f"过滤页眉: {stripped[:30]}")
                    continue

            if y_pos < page_height * self.footer_region_ratio:
                if self._is_footer(stripped):
                    logger.debug(f"过滤页脚: {stripped[:30]}")
                    continue

            filtered_lines.append(stripped)

        return '\n'.join(filtered_lines)

    def _get_line_positions(self, page) -> List[float]:
        """获取每行的 y 坐标（从 chars 中提取）"""
        chars = page.chars
        if not chars:
            return []

        lines_by_y: dict = {}
        y_tolerance = 3.0
        for c in chars:
            y_key = round(c['top'] / y_tolerance) * y_tolerance
            if y_key not in lines_by_y:
                lines_by_y[y_key] = []

        return sorted(lines_by_y.keys(), reverse=True)

    def _is_header(self, line: str) -> bool:
        """检测是否为页眉"""
        if len(line) > self.config.header_max_length:
            return False
        for pattern in self.config.header_patterns:
            if pattern in line:
                return True
        return False

    def _is_footer(self, line: str) -> bool:
        """检测是否为页脚"""
        if len(line) > self.config.footer_max_length:
            return False
        for pattern in self.config.footer_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False
