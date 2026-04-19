#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容类型检测器"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Set

from ..models import SectionType


class SectionDetector:
    """内容类型检测器

    关键词通过 data/keywords.json 配置，可替换为其他领域的配置。
    """

    CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s*$')

    def __init__(self, keywords_path: Optional[str] = None):
        if keywords_path:
            config_path = Path(keywords_path)
        else:
            config_path = Path(__file__).parent / 'data' / 'keywords.json'

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.section_keywords: dict = config['section_keywords']
        self.premium_table_keywords: Set[str] = set(config['premium_table_keywords'])
        self.non_clause_table_keywords: Set[str] = set(config['non_clause_table_keywords'])

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
        return bool(self.CLAUSE_NUMBER_PATTERN.match(first_col.strip()))

    def is_premium_table(self, header_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in header_row)
        return any(kw in text for kw in self.premium_table_keywords)

    def is_non_clause_table(self, first_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in first_row)
        return any(kw in text for kw in self.non_clause_table_keywords)
