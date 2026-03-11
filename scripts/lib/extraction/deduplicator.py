#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
条款去重模块

去除重复的条款，使用哈希策略。
"""
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any

from lib.constants import DEDUP_PREFIX_LENGTH, DEDUP_SUFFIX_LENGTH


logger = logging.getLogger(__name__)


class BaseDeduplicator(ABC):
    """去重器基类"""

    @abstractmethod
    def deduplicate(self, clauses: List[Dict]) -> List[Dict]:
        """
        去重

        Args:
            clauses: 条款列表

        Returns:
            去重后的条款列表
        """
        pass


class HashDeduplicator(BaseDeduplicator):
    """
    哈希去重器

    使用哈希策略：前N字符 + 长度 + 后M字符
    """

    def __init__(self, prefix_length: int = DEDUP_PREFIX_LENGTH, suffix_length: int = DEDUP_SUFFIX_LENGTH):
        """
        初始化哈希去重器

        Args:
            prefix_length: 前缀字符数
            suffix_length: 后缀字符数
        """
        self.prefix_length = prefix_length
        self.suffix_length = suffix_length

    def _hash_clause(self, text: str) -> str:
        """计算条款哈希"""
        prefix = text[:self.prefix_length]
        suffix = text[-self.suffix_length:] if len(text) > self.suffix_length else ''
        content = f"{prefix}|||{len(text)}|||{suffix}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def deduplicate(self, clauses: List[Dict]) -> List[Dict]:
        """去重"""
        seen = set()
        unique = []

        for clause in clauses:
            text = clause.get('text', '')
            if not text:
                continue

            h = self._hash_clause(text)
            if h not in seen:
                seen.add(h)
                unique.append(clause)

        if len(unique) < len(clauses):
            logger.info(f"去重: {len(clauses)} -> {len(unique)} 条条款")

        return unique


class ReferenceDeduplicator(BaseDeduplicator):
    """
    基于引用号去重

    简单策略：相同 reference 的条款只保留第一条。
    适用于 reference 规范的情况。
    """

    def deduplicate(self, clauses: List[Dict]) -> List[Dict]:
        """按 reference 去重"""
        seen_refs = set()
        unique = []

        for clause in clauses:
            ref = clause.get('reference', '')
            if not ref:
                unique.append(clause)
            elif ref not in seen_refs:
                seen_refs.add(ref)
                unique.append(clause)

        return unique
