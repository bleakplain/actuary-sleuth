#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""条款目录页检测器

检测 PDF 文档中的条款目录页，过滤目录条目，保留非目录内容。
"""
from __future__ import annotations

import logging
import re
from typing import Tuple, List

logger = logging.getLogger(__name__)


class TocDetector:
    """条款目录页检测器"""

    TOC_KEYWORDS = ['条款目录', '目录', '目 录', 'CONTENTS', 'Content']

    # 正文内容关键词 — 出现这些说明从目录区域进入了正文
    BODY_START_KEYWORDS = [
        '凡投保', '凡出生', '保险期间为', '自首次投保', '在保证续保',
    ]

    CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+\.\d+(?:\.\d+)*)\s+(.+)$')

    # 章节标题格式：'1．被保险人范围'、'2．保险责任及责任免除'
    CHAPTER_TITLE_PATTERN = re.compile(r'^\d+[．.]\s*.+$')

    def detect(self, page, page_idx: int) -> Tuple[bool, str]:
        """检测是否为目录页，返回过滤后的文本"""
        text = page.extract_text() or ""

        if page_idx > 2:
            return False, text

        has_keyword = any(kw in text for kw in self.TOC_KEYWORDS)
        if not has_keyword:
            return False, text

        clean_text = self._filter_toc_entries(text)
        logger.debug(f"Page {page_idx + 1} detected as TOC page, filtered entries")
        return True, clean_text

    def _filter_toc_entries(self, text: str) -> str:
        """过滤目录条目，保留非目录内容。

        从"条款目录"关键词开始，到正文开始为止，中间的目录条目全部过滤。
        目录条目 = X.Y/X.Y.Z 格式的短标题行 + 章节标题行（'1．被保险人范围'）。
        """
        lines = text.split('\n')
        filtered: List[str] = []

        # 找到目录区域起始行
        toc_start_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if any(kw in stripped for kw in self.TOC_KEYWORDS):
                toc_start_idx = i
                break

        if toc_start_idx == -1:
            return text

        in_toc = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 目录区域之前的行全部保留
            if i < toc_start_idx:
                filtered.append(line)
                continue

            # 目录关键词行本身跳过
            if i == toc_start_idx:
                in_toc = True
                continue

            # 已进入目录区域，检测正文开始
            if in_toc and self._is_body_start(stripped):
                in_toc = False
                filtered.append(line)
                continue

            # 在目录区域内，过滤目录条目
            if in_toc and self._is_toc_entry(stripped):
                continue

            filtered.append(line)

        return '\n'.join(filtered)

    def _is_body_start(self, line: str) -> bool:
        """检测正文开始。正文特征：条款编号后紧跟较长描述（> 40 字）。"""
        stripped = line.strip()
        if not stripped:
            return False

        # 正文关键词
        for kw in self.BODY_START_KEYWORDS:
            if kw in stripped:
                return True

        # 条款编号 + 长内容
        match = self.CLAUSE_NUMBER_PATTERN.match(stripped)
        if match and len(match.group(2).strip()) > 40:
            return True

        return False

    def _is_toc_entry(self, line: str) -> bool:
        """判断是否为目录条目。

        目录条目：
        - X.Y/X.Y.Z 格式短标题（标题 <= 25 字）
        - 章节标题（'1．被保险人范围'）
        - 空行
        """
        stripped = line.strip()
        if not stripped:
            return False

        # X.Y/X.Y.Z 格式
        match = self.CLAUSE_NUMBER_PATTERN.match(stripped)
        if match and len(match.group(2).strip()) <= 25:
            return True

        # 章节标题（'1．被保险人范围'、'2．保险责任及责任免除'）
        if self.CHAPTER_TITLE_PATTERN.match(stripped):
            return True

        return False