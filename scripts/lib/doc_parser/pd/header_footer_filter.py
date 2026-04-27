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
        r"第\s*页", r"共\s*页",  # 无数字的页码占位符
        r"^\d+\s+\d+$",  # 纯数字组合如 "9 18"（页码/总页数）
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
        page_height = page.height

        # 从 chars 构建文本行，同时记录每行的 y 坐标
        line_data = self._build_lines_from_chars(page)

        if not line_data:
            return page.extract_text() or ""

        header_region_threshold = page_height * self.header_region_ratio
        footer_region_threshold = page_height * (1 - self.footer_region_ratio)

        filtered_lines: List[str] = []
        for y_pos, text in line_data:
            stripped = text.strip()
            if not stripped:
                continue

            # pdfplumber 坐标：top 从上往下增长
            # - y_pos < header_region_threshold → 页眉（靠近顶部）
            # - y_pos > footer_region_threshold → 页脚（靠近底部）
            if y_pos < header_region_threshold:
                if self._is_header(stripped):
                    logger.debug(f"过滤页眉: {stripped[:30]}")
                    continue

            if y_pos > footer_region_threshold:
                if self._is_footer(stripped):
                    logger.debug(f"过滤页脚: {stripped[:30]}")
                    continue

            filtered_lines.append(stripped)

        return '\n'.join(filtered_lines)

    def _build_lines_from_chars(self, page) -> List[Tuple[float, str]]:
        """从 chars 构建文本行，返回 [(y_pos, text)] 列表"""
        chars = page.chars
        if not chars:
            return []

        # 按 y 坐标分组字符（同一行的字符 y 坐标可能有基线偏移）
        # 使用较大 tolerance 并采用 floor 分组，避免边界值问题
        y_tolerance = 8.0
        lines_by_y: dict[float, List[dict]] = {}
        for c in chars:
            y_key = round(c['top'] / y_tolerance) * y_tolerance
            if y_key not in lines_by_y:
                lines_by_y[y_key] = []
            lines_by_y[y_key].append(c)

        # 按 y 坐标从上到下排序（y 增大）
        result: List[Tuple[float, str]] = []
        for y_pos in sorted(lines_by_y.keys()):
            # 按 x 坐标排序字符，并在间隙处插入空格
            sorted_chars = sorted(lines_by_y[y_pos], key=lambda c: c['x0'])
            text_parts = []
            prev_x_end = None
            for c in sorted_chars:
                if prev_x_end is not None:
                    gap = c['x0'] - prev_x_end
                    # 间隙大于平均字符宽度的一半 → 可能是空格
                    avg_width = (c['width'] + (prev_x_end - sorted_chars[0]['x0'])) / (len(text_parts) + 1)
                    if gap > avg_width * 0.3 and gap > 2:  # 阈值：字符宽度的 30% 或至少 2pt
                        text_parts.append(' ')
                text_parts.append(c['text'])
                prev_x_end = c['x0'] + c['width']
            text = ''.join(text_parts)
            result.append((y_pos, text))

        return result

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
