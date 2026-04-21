#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据质量检查器

对知识库文档和分块进行质量检查，包括：
- 文档级：frontmatter 验证、编码检测、内容质量
- Chunk级：去重、信息密度评估
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set

from llama_index.core import Document
from llama_index.core.schema import TextNode

logger = logging.getLogger(__name__)

# 质量检查阈值
MIN_CONTENT_CHARS = 50
MAX_DUPLICATE_RATIO = 0.3
MIN_UNIQUE_RATIO = 0.3


@dataclass(frozen=True)
class QualityIssue:
    """质量问题"""
    severity: str           # 'error', 'warning', 'info'
    category: str           # 'frontmatter', 'encoding', 'content', 'duplicate'
    message: str
    location: str = ""      # 文件名或 chunk_id


@dataclass
class QualityReport:
    """质量检查报告"""
    issues: List[QualityIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len([i for i in self.issues if i.severity == 'error']) == 0

    @property
    def error_count(self) -> int:
        return len([i for i in self.issues if i.severity == 'error'])

    @property
    def warning_count(self) -> int:
        return len([i for i in self.issues if i.severity == 'warning'])


class QualityChecker:
    """数据质量检查器"""

    def __init__(
        self,
        min_content_chars: int = MIN_CONTENT_CHARS,
        max_duplicate_ratio: float = MAX_DUPLICATE_RATIO,
        min_unique_ratio: float = MIN_UNIQUE_RATIO,
    ):
        self.min_content_chars = min_content_chars
        self.max_duplicate_ratio = max_duplicate_ratio
        self.min_unique_ratio = min_unique_ratio

    def check_document(self, doc: Document) -> QualityReport:
        """文档级质量检查"""
        issues: List[QualityIssue] = []
        file_name = doc.metadata.get('file_name', 'unknown')

        issues.extend(self._check_frontmatter(doc, file_name))
        issues.extend(self._check_encoding(doc, file_name))
        issues.extend(self._check_content_quality(doc, file_name))

        return QualityReport(issues=issues)

    def check_chunks(self, nodes: List[TextNode]) -> List[TextNode]:
        """Chunk级检查 + 去重"""
        nodes = self._deduplicate_chunks(nodes)
        nodes = self._filter_low_quality(nodes)
        return nodes

    def _check_frontmatter(self, doc: Document, file_name: str) -> List[QualityIssue]:
        """检查 frontmatter 完整性"""
        issues: List[QualityIssue] = []
        text = doc.text

        if not text.startswith('---'):
            issues.append(QualityIssue(
                severity='warning',
                category='frontmatter',
                message='缺少 YAML frontmatter',
                location=file_name,
            ))
            return issues

        fm_end = text.find('---', 3)
        if fm_end == -1:
            issues.append(QualityIssue(
                severity='error',
                category='frontmatter',
                message='frontmatter 格式错误：未找到结束标记',
                location=file_name,
            ))
            return issues

        frontmatter = text[3:fm_end].strip()
        if not frontmatter:
            issues.append(QualityIssue(
                severity='warning',
                category='frontmatter',
                message='frontmatter 为空',
                location=file_name,
            ))

        # 检查关键字段
        if 'regulation:' not in text[:fm_end] and 'collection:' not in text[:fm_end]:
            issues.append(QualityIssue(
                severity='warning',
                category='frontmatter',
                message='缺少 regulation 或 collection 字段',
                location=file_name,
            ))

        return issues

    def _check_encoding(self, doc: Document, file_name: str) -> List[QualityIssue]:
        """检查编码问题"""
        issues: List[QualityIssue] = []
        text = doc.text

        # 检查乱码特征
        garbled_patterns = [
            r'[\x00-\x08\x0b\x0c\x0e-\x1f]',  # 控制字符
            r'锘',  # BOM 残留
            r'\ufffd',  # 替换字符
        ]

        for pattern in garbled_patterns:
            if re.search(pattern, text):
                issues.append(QualityIssue(
                    severity='warning',
                    category='encoding',
                    message=f'检测到编码问题：{pattern}',
                    location=file_name,
                ))
                break

        return issues

    def _check_content_quality(self, doc: Document, file_name: str) -> List[QualityIssue]:
        """检查内容质量"""
        issues: List[QualityIssue] = []

        # 提取正文（跳过 frontmatter）
        text = doc.text
        if text.startswith('---'):
            fm_end = text.find('---', 3)
            if fm_end != -1:
                text = text[fm_end + 3:].strip()

        # 检查空内容
        if len(text) < self.min_content_chars:
            issues.append(QualityIssue(
                severity='error',
                category='content',
                message=f'内容过短：{len(text)} chars < {self.min_content_chars}',
                location=file_name,
            ))
            return issues

        # 检查低信息密度
        unique_chars = len(set(text))
        unique_ratio = unique_chars / len(text)
        if unique_ratio < self.min_unique_ratio:
            issues.append(QualityIssue(
                severity='info',
                category='content',
                message=f'字符多样性低：{unique_ratio:.2%} < {self.min_unique_ratio:.2%}',
                location=file_name,
            ))

        return issues

    def _deduplicate_chunks(self, nodes: List[TextNode]) -> List[TextNode]:
        """基于内容哈希去重"""
        seen_hashes: Set[str] = set()
        unique_nodes: List[TextNode] = []
        duplicate_count = 0

        for node in nodes:
            content_hash = hashlib.md5(node.text.encode()).hexdigest()
            if content_hash in seen_hashes:
                duplicate_count += 1
                continue
            seen_hashes.add(content_hash)
            unique_nodes.append(node)

        if duplicate_count > 0:
            logger.info(f"去重：移除 {duplicate_count} 个重复 chunk")

        return unique_nodes

    def _filter_low_quality(self, nodes: List[TextNode]) -> List[TextNode]:
        """过滤低质量 chunk"""
        filtered: List[TextNode] = []
        removed_count = 0

        for node in nodes:
            # 过滤过短内容
            if len(node.text) < self.min_content_chars:
                removed_count += 1
                continue

            # 过滤纯空白
            if not node.text.strip():
                removed_count += 1
                continue

            filtered.append(node)

        if removed_count > 0:
            logger.info(f"质量过滤：移除 {removed_count} 个低质量 chunk")

        return filtered
