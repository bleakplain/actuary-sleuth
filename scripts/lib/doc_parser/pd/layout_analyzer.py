#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 版面分析器

基于 pdfplumber 的字符坐标信息检测多栏结构和页眉页脚区域。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutRegion:
    """版面区域"""
    region_type: str  # "body", "left_col", "right_col", "header", "footer"
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    content: str = ""
    confidence: float = 1.0


class LayoutAnalyzer:
    """PDF 版面分析器

    基于 pdfplumber 的字符坐标信息检测多栏结构和页眉页脚区域。
    """

    def __init__(
        self,
        column_gap_threshold: float = 30.0,
        header_region_ratio: float = 0.08,
        footer_region_ratio: float = 0.08,
    ):
        self.column_gap_threshold = column_gap_threshold
        self.header_region_ratio = header_region_ratio
        self.footer_region_ratio = footer_region_ratio

    def analyze(self, page) -> Tuple[str, List[LayoutRegion]]:
        """分析页面版面结构

        Args:
            page: pdfplumber 的页面对象

        Returns:
            (reordered_text, regions): 重组后的文本和区域列表
        """
        chars = page.chars
        if not chars:
            return "", []

        page_width = page.width
        page_height = page.height

        columns = self._detect_columns(chars, page_width)

        if len(columns) > 1:
            text = self._reconstruct_multi_column(chars, columns, page_height)
            regions = [
                LayoutRegion(
                    region_type="left_col",
                    bbox=(0, 0, columns[0]['x1'], page_height),
                ),
                LayoutRegion(
                    region_type="right_col",
                    bbox=(columns[1]['x0'], 0, page_width, page_height),
                ),
            ]
        else:
            text = page.extract_text() or ""
            regions = [LayoutRegion(
                region_type="body",
                bbox=(0, 0, page_width, page_height),
            )]

        return text, regions

    def _detect_columns(self, chars: List[dict], page_width: float) -> List[dict]:
        """检测多栏结构

        通过统计字符 x 坐标分布，寻找中间空白区域（栏间分隔）。
        """
        if not chars:
            return []

        x_positions = [c['x0'] for c in chars]
        min_x = min(x_positions)
        max_x = max(x_positions)

        num_bins = 20
        bin_width = (max_x - min_x) / num_bins if num_bins > 0 else 1
        bins = [0] * num_bins

        for x in x_positions:
            bin_idx = int((x - min_x) / bin_width) if bin_width > 0 else 0
            bin_idx = min(bin_idx, num_bins - 1)
            bins[bin_idx] += 1

        avg_density = sum(bins) / num_bins if num_bins > 0 else 0
        threshold = avg_density * 0.1

        gaps: List[float] = []
        for i in range(1, num_bins - 1):
            if bins[i] < threshold and bins[i-1] >= threshold and bins[i+1] >= threshold:
                gap_center = min_x + (i + 0.5) * bin_width
                if 0.3 * page_width < gap_center < 0.7 * page_width:
                    gaps.append(gap_center)

        if len(gaps) == 1:
            gap = gaps[0]
            return [
                {'x0': min_x, 'x1': gap - self.column_gap_threshold},
                {'x0': gap + self.column_gap_threshold, 'x1': max_x},
            ]

        return [{'x0': min_x, 'x1': max_x}]

    def _reconstruct_multi_column(
        self,
        chars: List[dict],
        columns: List[dict],
        page_height: float,
    ) -> str:
        """按多栏逻辑顺序重组文本"""
        if len(columns) < 2:
            return ""
        left_chars = [c for c in chars if c['x0'] < columns[1]['x0']]
        right_chars = [c for c in chars if c['x0'] >= columns[1]['x0']]

        left_text = self._chars_to_text(left_chars)
        right_text = self._chars_to_text(right_chars)

        return left_text + "\n\n" + right_text

    def _chars_to_text(self, chars: List[dict]) -> str:
        """将字符列表转换为文本"""
        if not chars:
            return ""

        lines: Dict[float, List[dict]] = {}
        y_tolerance = 3.0
        for c in chars:
            y_key = round(c['top'] / y_tolerance) * y_tolerance
            if y_key not in lines:
                lines[y_key] = []
            lines[y_key].append(c)

        sorted_lines: List[str] = []
        for y in sorted(lines.keys(), reverse=True):
            line_chars = sorted(lines[y], key=lambda c: c['x0'])
            line_text = ''.join(c['text'] for c in line_chars)
            sorted_lines.append(line_text)

        return '\n'.join(sorted_lines)

    def get_header_region(self, page) -> LayoutRegion:
        """获取页眉区域"""
        page_height = page.height
        header_height = page_height * self.header_region_ratio
        return LayoutRegion(
            region_type="header",
            bbox=(0, page_height - header_height, page.width, page_height),
        )

    def get_footer_region(self, page) -> LayoutRegion:
        """获取页脚区域"""
        footer_height = page.height * self.footer_region_ratio
        return LayoutRegion(
            region_type="footer",
            bbox=(0, 0, page.width, footer_height),
        )
