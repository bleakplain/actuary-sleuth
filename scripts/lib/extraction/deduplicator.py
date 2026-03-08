#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
条款去重模块

去除重复的条款，支持多种去重策略。
"""
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Callable


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

    使用改进的哈希策略：前200字符 + 长度 + 后100字符
    比原有的 (前100字符, 长度//50) 更可靠。
    """

    def __init__(self, hash_func: Callable[[str], str] = None):
        """
        初始化

        Args:
            hash_func: 自定义哈希函数，默认使用内置策略
        """
        self.hash_func = hash_func or self._default_hash

    def _default_hash(self, text: str) -> str:
        """
        默认哈希函数：前200字符 + 长度 + 后100字符

        这种组合能区分：
        - 前缀相似但内容不同的条款
        - 长度差异显著的条款
        - 后缀不同的条款
        """
        prefix = text[:200]
        suffix = text[-100:] if len(text) > 100 else ''
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

            h = self.hash_func(text)
            if h not in seen:
                seen.add(h)
                unique.append(clause)
            else:
                logger.debug(f"去重: {clause.get('reference', 'unknown')}")

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
            else:
                logger.debug(f"去重(按reference): {ref}")

        return unique


class SemanticDeduplicator(BaseDeduplicator):
    """
    语义去重器（预留接口）

    基于语义相似度去重，需要 embedding 模型支持。
    对于内容相似但表述不同的条款，能更好地识别。
    """

    def __init__(self, threshold: float = 0.95):
        """
        初始化

        Args:
            threshold: 相似度阈值，超过此值视为重复
        """
        self.threshold = threshold
        # TODO: 初始化 embedding 模型

    def deduplicate(self, clauses: List[Dict]) -> List[Dict]:
        """
        语义去重（待实现）

        需要集成 embedding 模型，计算条款间的余弦相似度。
        """
        logger.warning("SemanticDeduplicator 未实现，退化为哈希去重")
        return HashDeduplicator().deduplicate(clauses)
