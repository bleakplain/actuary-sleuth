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

    def detect_section_type(self, title: str) -> Optional[SectionType]:
        for section_type in self._priority:
            keywords = self.section_keywords.get(section_type.value, [])
            for kw in keywords:
                if kw in title:
                    return section_type
        return None

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
