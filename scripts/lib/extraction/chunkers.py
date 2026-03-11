#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档分块策略

将长文档分割成适合LLM处理的小块，不同策略适用于不同格式。
"""
import re
import logging
from abc import ABC, abstractmethod
from typing import List

from lib.constants import (
    DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP,
    TABLE_DENSITY_THRESHOLD, DENSITY_CALCULATION_MULTIPLIER,
    SECTION_MIN_COUNT
)


logger = logging.getLogger(__name__)


class BaseChunker(ABC):
    """分块策略基类"""

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP):
        """
        初始化分块器

        Args:
            chunk_size: 每块的最大字符数
            overlap: 块之间的重叠字符数
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    @abstractmethod
    def split(self, document: str) -> List[str]:
        """
        分块

        Args:
            document: 文档内容

        Returns:
            文档块列表
        """
        pass


class TableSplitter(BaseChunker):
    """
    HTML 表格分块器

    按 <tr> 边界分块，保持表格行的完整性。
    适用于 feishu2md 转换的表格型条款文档。
    """

    def split(self, document: str) -> List[str]:
        """按 <tr> 边界分块"""
        # 找所有 <tr> 位置
        tr_positions = [m.start() for m in re.finditer(r'\n<tr', document)]

        if not tr_positions:
            return [document]

        # 添加文档末尾作为最后一个分割点
        split_points = tr_positions + [len(document)]
        split_points.sort()

        chunks = []
        current_start = 0

        for i, split_pos in enumerate(split_points):
            # 检查当前块大小
            if split_pos - current_start > self.chunk_size:
                # 需要找一个中间的 <tr> 作为分割点
                for j in range(i, max(0, i - 20), -1):
                    mid_pos = split_points[j]
                    if mid_pos - current_start <= self.chunk_size and mid_pos > current_start:
                        chunks.append(document[current_start:mid_pos].strip())
                        # 添加重叠
                        current_start = max(0, mid_pos - self.overlap)
                        break

        # 最后一块
        if current_start < len(document):
            chunks.append(document[current_start:].strip())

        # 过滤空块
        chunks = [c for c in chunks if c]

        logger.info(f"TableSplitter: {len(document)}字符 -> {len(chunks)}块")
        return chunks


class SectionSplitter(BaseChunker):
    """
    章节分块器

    按章节标题分块，适用于有清晰结构的文档。
    支持的模式：第X条、## 标题、数字列表等。
    """

    # 章节模式
    SECTION_PATTERNS = [
        r'\n\s*第[一二三四五六七八九十百千]+\s*[章节条款][\s、．.：（]',
        r'\n\s*\d+[\s、．.：（]\S+',
        r'\n\s*#{1,2}\s+',
    ]

    def split(self, document: str) -> List[str]:
        """按章节标题分块"""
        # 找所有章节标题位置
        positions = []
        for pattern in self.SECTION_PATTERNS:
            for match in re.finditer(pattern, document, re.MULTILINE):
                positions.append(match.start())

        if not positions:
            # 没有找到章节，退化为语义分块
            return SemanticSplitter(self.chunk_size, self.overlap).split(document)

        positions.sort()
        # 添加文档末尾
        positions = positions + [len(document)]

        chunks = []
        current_start = 0

        for pos in positions:
            if pos - current_start > self.chunk_size:
                chunks.append(document[current_start:pos].strip())
                # 添加重叠
                current_start = max(0, pos - self.overlap)

        if current_start < len(document):
            chunks.append(document[current_start:].strip())

        chunks = [c for c in chunks if c]

        logger.info(f"SectionSplitter: {len(document)}字符 -> {len(chunks)}块")
        return chunks


class SemanticSplitter(BaseChunker):
    """
    语义分块器

    按段落边界分块，适用于纯文本或无明确结构的文档。
    """

    def split(self, document: str) -> List[str]:
        """按段落边界分块"""
        # 按双换行分割段落
        paragraphs = re.split(r'\n\s*\n', document)

        chunks = []
        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para)

            # 如果单个段落超过 chunk_size，强制分割
            if para_size > self.chunk_size:
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = []
                    current_size = 0

                # 按句子分割大段落
                sentences = re.split(r'[。！？；\n]', para)
                temp_chunk = []
                temp_size = 0

                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if temp_size + len(sent) > self.chunk_size and temp_chunk:
                        chunks.append('。'.join(temp_chunk))
                        temp_chunk = [sent]
                        temp_size = len(sent)
                    else:
                        temp_chunk.append(sent)
                        temp_size += len(sent) + 1  # +1 for separator

                if temp_chunk:
                    chunks.append('。'.join(temp_chunk))
                continue

            # 正常情况：段落加入当前块
            if current_size + para_size > self.chunk_size and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size + 2  # +2 for \n\n

        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))

        chunks = [c for c in chunks if c]

        logger.info(f"SemanticSplitter: {len(document)}字符 -> {len(chunks)}块")
        return chunks


class HybridChunker(BaseChunker):
    """
    混合分块器

    根据文档结构特征自动选择最佳分块策略：
    - HTML表格密集 → TableSplitter
    - 章节结构清晰 → SectionSplitter
    - 纯文本段落 → SemanticSplitter
    """

    def split(self, document: str) -> List[str]:
        """混合分块策略"""
        # 1. 计算表格密度
        tr_count = len(re.findall(r'<tr', document))
        table_density = tr_count * DENSITY_CALCULATION_MULTIPLIER / len(document) if document else 0

        # 2. 计算章节密度
        section_count = 0
        for pattern in SectionSplitter.SECTION_PATTERNS:
            section_count += len(re.findall(pattern, document, re.MULTILINE))

        section_density = section_count * DENSITY_CALCULATION_MULTIPLIER / len(document) if document else 0

        logger.debug(f"文档特征: 表格密度={table_density:.2f}, 章节密度={section_density:.2f}")

        # 3. 根据特征选择策略
        if table_density > TABLE_DENSITY_THRESHOLD:
            logger.info("检测到表格密集文档，使用 TableSplitter")
            return TableSplitter(self.chunk_size, self.overlap).split(document)

        if section_count >= SECTION_MIN_COUNT:
            logger.info("检测到章节结构，使用 SectionSplitter")
            return SectionSplitter(self.chunk_size, self.overlap).split(document)

        logger.info("未检测到明确结构，使用 SemanticSplitter")
        return SemanticSplitter(self.chunk_size, self.overlap).split(document)
