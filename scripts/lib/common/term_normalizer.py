#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保险术语标准化器"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class TermNormalizer:
    """保险术语标准化器"""

    def __init__(self, synonyms_path: Optional[str] = None):
        if synonyms_path:
            config_path = Path(synonyms_path)
        else:
            config_path = Path(__file__).parent / 'data' / 'synonyms.json'

        self.synonym_to_standard: Dict[str, str] = {}
        self.standard_terms: Set[str] = set()

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                synonyms_dict: Dict[str, List[str]] = json.load(f)

            for standard, synonyms in synonyms_dict.items():
                self.standard_terms.add(standard)
                for syn in synonyms:
                    self.synonym_to_standard[syn] = standard

        except FileNotFoundError:
            logger.warning(f"同义词词典不存在: {config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"同义词词典解析失败: {e}")

    def normalize(self, text: str) -> str:
        """将文本中的同义词替换为标准术语"""
        if not text:
            return text

        result = text
        for syn, standard in sorted(
            self.synonym_to_standard.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            if syn in result:
                result = result.replace(syn, standard)

        return result

    def normalize_query(self, query: str) -> str:
        """标准化用户查询"""
        return self.normalize(query)

    def normalize_chunk(self, chunk_text: str) -> str:
        """标准化 Chunk 文本"""
        return self.normalize(chunk_text)

    def get_standard_term(self, term: str) -> str:
        """获取标准术语"""
        if term in self.standard_terms:
            return term
        return self.synonym_to_standard.get(term, term)
