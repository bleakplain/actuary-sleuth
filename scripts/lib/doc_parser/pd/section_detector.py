#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容类型检测器"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Match, Optional, Set

from ..models import SectionType

logger = logging.getLogger(__name__)


# 中文数字字符集（用于正则）
_CN_NUM_CHARS = '一二三四五六七八九十'
_CN_NUM_CHARS_EXT = _CN_NUM_CHARS + '百'  # 扩展支持百

# 中文数字映射
_CHINESE_NUM_MAP = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '零': 0,
}


class SectionDetector:
    """内容类型检测器

    关键词通过 data/keywords.json 配置，可替换为其他领域的配置。
    """

    # 支持的条款编号格式
    CLAUSE_NUMBER_PATTERNS = [
        re.compile(r'^(\d+(?:\.\d+)*)\s*$'),  # 数字格式: 1, 1.2, 1.2.3
        re.compile(r'^第([' + _CN_NUM_CHARS_EXT + r']+)条\s*$'),  # 中文格式: 第一条
        re.compile(r'^([' + _CN_NUM_CHARS + r']+)\s*[、.．]\s*$'),  # 中文数字: 一、二、
        re.compile(r'^\s*[（\(]([' + _CN_NUM_CHARS + r'\d]+)[）\)]\s*$'),  # 括号格式: （一）、(1)
    ]

    # 条款头匹配正则（编号 + 空格 + 标题）
    CLAUSE_HEADER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s+(.+)$')

    def __init__(self, keywords_path: Optional[str] = None):
        if keywords_path:
            config_path = Path(keywords_path)
        else:
            config_path = Path(__file__).parent / 'data' / 'keywords.json'

        # 加载关键词配置
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except FileNotFoundError:
            logger.error(f"关键词配置文件不存在: {config_path}，section 检测功能将不可用")
            config = {}
        except json.JSONDecodeError as e:
            logger.error(f"关键词配置文件 JSON 解析失败: {config_path}, {e}，section 检测功能将不可用")
            config = {}

        self.section_keywords: dict = config.get('section_keywords', {})
        self.premium_table_keywords: Set[str] = set(config.get('premium_table_keywords', []))
        self.non_clause_table_keywords: Set[str] = set(config.get('non_clause_table_keywords', []))

        self._priority = [
            SectionType.HEALTH_DISCLOSURE,
            SectionType.EXCLUSION,
            SectionType.NOTICE,
            SectionType.RIDER,
        ]

    # 章节标题正则：X.Y 格式 或 X．格式（中文句号）
    SECTION_TITLE_PATTERN = re.compile(r'^(\d+[\.\．]\d*[\.\．]?\d*)\s+.+$')

    def detect_section_type(self, line: str) -> Optional[SectionType]:
        """检测章节标题行，返回章节类型。

        只检测符合章节标题格式的行，避免误匹配正文中的引用：
        - 格式：'2.6 责任免除'、'2．保险责任及责任免除'
        - 标题行不含条款编号时，直接检测关键词

        Args:
            line: 文本行

        Returns:
            SectionType 或 None
        """
        stripped = line.strip()
        if not stripped:
            return None

        # 检测是否为章节标题格式（带编号）
        # 格式：编号 + 空格 + 标题（可能后续有正文内容）
        # 例如："2.6 责免除"、"2.1 保险期间 本附加险合同..."
        section_match = self.CLAUSE_HEADER_PATTERN.match(stripped)

        for section_type in self._priority:
            keywords = self.section_keywords.get(section_type.value, [])
            for kw in keywords:
                # 章节标题格式（带编号）
                if section_match:
                    full_content = section_match.group(2)
                    # 专用章节标题匹配规则：
                    # 1) 关键词在标题开头 → "责任免除"、"健康告知事项"
                    # 2) 标题等于关键词 → 精确匹配
                    # 3) 关键词在标题结尾，但标题是短词组 → "其他免责条款"
                    # 不匹配：组合标题（如"保险责任及责任免除"）
                    #   这类标题包含多个主题，关键词只是其中之一
                    is_pure_title = (
                        full_content.startswith(kw)
                        or full_content == kw
                        or (full_content.endswith(kw) and len(full_content) < len(kw) * 2)
                    )
                    if is_pure_title:
                        return section_type
                    # 标题词组后有空格+正文的情况
                    space_idx = full_content.find(' ')
                    if space_idx > 0:
                        title_word = full_content[:space_idx]
                        if title_word.startswith(kw) or title_word.endswith(kw):
                            return section_type
                    continue

                # 非编号格式：独立章节标题行
                if len(stripped) < 40:
                    if stripped.startswith(kw) or stripped.endswith(kw):
                        return section_type

        return None

    @staticmethod
    def _extract_title_from_content(content: str) -> str:
        """从条款编号后的内容中提取纯标题部分

        条款行格式：编号 + 空格 + 标题词 + [空格 + 正文内容]
        例如："保险期间 本附加险合同的保险期间为1年"
        标题部分："保险期间"，正文部分："本附加险合同的保险期间为1年"

        结构规则：标题与正文之间用空格分隔，标题本身不含空格
        """
        # 标题是第一个空格之前的内容
        # 如果无空格，则整行都是标题（如"责任免除"、"保证续保"）
        space_idx = content.find(' ')
        if space_idx > 0:
            return content[:space_idx]
        return content

    def is_clause_table(self, first_col: str) -> bool:
        """检测是否为条款表格第一列。

        支持多种条款编号格式：
        - 数字格式: 1, 1.2, 1.2.3
        - 中文格式: 第一条
        - 中文数字: 一、二、
        - 括号格式: （一）、(1)
        """
        text = first_col.strip()
        for pattern in self.CLAUSE_NUMBER_PATTERNS:
            if pattern.match(text):
                return True
        return False

    def is_premium_table(self, header_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in header_row)
        return any(kw in text for kw in self.premium_table_keywords)

    def is_non_clause_table(self, first_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in first_row)
        return any(kw in text for kw in self.non_clause_table_keywords)

    def match_clause_header(self, line: str) -> Optional[Match[str]]:
        """匹配文本流中的条款头。

        匹配格式：编号 + 空格 + 标题
        例如：'1.2 保险期间'、'2.3.1 等待期设置'

        Args:
            line: 文本行

        Returns:
            Match 对象（group(1)=编号, group(2)=标题）或 None
        """
        return self.CLAUSE_HEADER_PATTERN.match(line.strip())
