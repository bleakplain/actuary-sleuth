#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义去重器

使用文本指纹和 embedding 相似度识别重复条款，替代编号去重。
"""
import hashlib
import logging
import re
from typing import Dict, List, Any, Optional

from .utils.constants import config
from lib.llm import LLMClientFactory


logger = logging.getLogger(__name__)


class Deduplicator:
    """语义去重器 - 智能选择去重策略"""

    def __init__(self):
        self.embedding_client = None
        self._embedding_client_initialized = False

    def _get_embedding_client(self):
        if not self._embedding_client_initialized:
            try:
                self.embedding_client = LLMClientFactory.create_embed_llm()
                logger.info("Embedding 客户端初始化成功")
            except Exception as e:
                logger.warning(f"Embedding 客户端初始化失败: {e}")
            self._embedding_client_initialized = True
        return self.embedding_client

    def _should_use_embedding(self, clauses: List[Dict]) -> bool:
        """智能判断是否需要使用语义去重"""
        if not clauses:
            return False

        # 条件1: 无编号条款占比较高 (>30%)
        numbered_count = sum(1 for c in clauses if c.get('number'))
        unnumbered_ratio = 1 - (numbered_count / len(clauses))

        if unnumbered_ratio > 0.3:
            logger.info(f"无编号条款占比 {unnumbered_ratio:.0%}，使用语义去重")
            return True

        # 条件2: 编号格式混乱（检测多种编号格式）
        number_formats = set()
        for clause in clauses:
            number = clause.get('number', '')
            if number:
                if re.match(r'^\d+\.\d+$', number):
                    number_formats.add('decimal')
                elif re.match(r'^[一二三四五六七八九十]+$', number):
                    number_formats.add('chinese')
                elif re.match(r'^第.*条$', number):
                    number_formats.add('clause')
                else:
                    number_formats.add('other')

        if len(number_formats) > 1:
            logger.info(f"检测到多种编号格式 {number_formats}，使用语义去重")
            return True

        # 条件3: 条款数量多且可能重复（通过文本长度方差判断）
        if len(clauses) > 50:
            text_lengths = [len(c.get('text', '')) for c in clauses]
            if text_lengths:
                avg_length = sum(text_lengths) / len(text_lengths)
                if avg_length < 100:
                    logger.info(f"条款平均长度 {avg_length:.0f} 字符，可能存在重复，使用语义去重")
                    return True

        logger.debug("使用指纹去重")
        return False

    def deduplicate_clauses(self, clauses: List[Dict]) -> List[Dict]:
        if not clauses:
            return []

        logger.info(f"开始去重，原始条款数: {len(clauses)}")

        numbered, unnumbered = self._group_by_number(clauses)
        deduped_numbered = self._deduplicate_numbered(numbered)

        if unnumbered:
            use_embedding = self._should_use_embedding(unnumbered)
            if use_embedding:
                deduped_unnumbered = self._deduplicate_with_embedding(unnumbered)
            else:
                deduped_unnumbered = self._deduplicate_with_fingerprint(unnumbered)
        else:
            deduped_unnumbered = []

        result = deduped_numbered + deduped_unnumbered

        logger.info(f"去重完成，剩余条款数: {len(result)} (减少 {len(clauses) - len(result)} 个)")
        return result

    def _group_by_number(self, clauses: List[Dict]) -> tuple:
        """
        按编号分组条款

        Args:
            clauses: 条款列表

        Returns:
            (有编号条款字典, 无编号条款列表)
        """
        numbered: Dict[str, List[Dict]] = {}
        unnumbered: List[Dict] = []

        for clause in clauses:
            number = clause.get('number')
            if number:
                if number not in numbered:
                    numbered[number] = []
                numbered[number].append(clause)
            else:
                unnumbered.append(clause)

        return numbered, unnumbered

    def _deduplicate_numbered(self, numbered: Dict) -> List[Dict]:
        """
        对有编号条款去重（保留最完整的版本）

        Args:
            numbered: {编号: [条款列表]}

        Returns:
            去重后的条款列表
        """
        deduped = []

        for number, clause_list in numbered.items():
            # 选择文本最长的
            clause_list.sort(key=lambda c: len(c.get('text', '')), reverse=True)
            deduped.append(clause_list[0])

        return deduped

    def _deduplicate_with_fingerprint(self, clauses: List[Dict]) -> List[Dict]:
        """
        使用文本指纹去重（快速方法）

        Args:
            clauses: 无编号条款列表

        Returns:
            去重后的条款列表
        """
        if not clauses:
            return []

        seen = set()
        deduped = []

        for clause in clauses:
            text = clause.get('text', '')
            if not text:
                # 如果没有文本，使用标题
                text = clause.get('title', '')

            if not text:
                # 如果也没有标题，跳过
                continue

            # 生成指纹
            fingerprint = self._generate_fingerprint(text)

            if fingerprint not in seen:
                seen.add(fingerprint)
                deduped.append(clause)
            else:
                logger.debug(f"发现重复条款 (指纹): {text[:50]}...")

        return deduped

    def _generate_fingerprint(self, text: str, length: int = 100) -> str:
        """
        生成文本指纹

        Args:
            text: 输入文本
            length: 指纹长度（字符数）

        Returns:
            MD5 哈希值（前 8 位）
        """
        # 规范化
        text = self._normalize_text(text)

        # 取前 N 个字符
        text = text[:length]

        # 生成哈希
        return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]

    def _normalize_text(self, text: str) -> str:
        """
        规范化文本（用于指纹生成）

        Args:
            text: 输入文本

        Returns:
            规范化后的文本
        """
        # 统一换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # 移除多余空格
        text = re.sub(r'\s+', ' ', text)

        # 转小写
        text = text.lower()

        # 移除标点符号
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)

        return text.strip()

    def _deduplicate_with_embedding(self, clauses: List[Dict]) -> List[Dict]:
        if not clauses:
            return []

        client = self._get_embedding_client()
        if not client:
            return self._deduplicate_with_fingerprint(clauses)

        texts = []
        for clause in clauses:
            text = clause.get('text', '') or clause.get('title', '')
            texts.append(text)

        try:
            embeddings = client.get_text_embeddings(texts)
        except Exception as e:
            logger.warning(f"Embedding 计算失败: {e}，回退到指纹去重")
            return self._deduplicate_with_fingerprint(clauses)

        return self._deduplicate_with_similarity(clauses, embeddings)

    def _deduplicate_with_similarity(self, clauses: List[Dict], embeddings: List[List[float]]) -> List[Dict]:
        import numpy as np

        deduped = []
        used = set()

        for i in range(len(clauses)):
            if i in used:
                continue

            deduped.append(clauses[i])
            used.add(i)

            for j in range(i + 1, len(clauses)):
                if j in used:
                    continue

                similarity = self._cosine_similarity(embeddings[i], embeddings[j])

                if similarity > config.SEMANTIC_SIMILARITY_THRESHOLD:
                    used.add(j)
                    logger.debug(f"发现重复条款 (相似度={similarity:.2f}): "
                               f"{clauses[i].get('title', '')[:30]}...")

        return deduped

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        import numpy as np

        vec1_arr = np.array(vec1)
        vec2_arr = np.array(vec2)

        dot_product = np.dot(vec1_arr, vec2_arr)
        norm1 = np.linalg.norm(vec1_arr)
        norm2 = np.linalg.norm(vec2_arr)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))
