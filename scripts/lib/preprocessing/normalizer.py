#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档规范化器

统一不同来源的文档格式，为后续处理提供标准化输入。
"""
import logging
import re
from typing import Optional

from .models import NormalizedDocument, DocumentProfile, StructureMarkers


logger = logging.getLogger(__name__)


class Normalizer:
    """文档规范化器 - 统一输入格式"""

    def __init__(self):
        pass

    def normalize(self, document: str, source_type: str = 'text') -> NormalizedDocument:
        """
        规范化文档

        Args:
            document: 原始文档内容
            source_type: 来源类型 (pdf/html/text/scan)

        Returns:
            NormalizedDocument: 规范化后的文档
        """
        # 1. 编码统一
        normalized = self._normalize_encoding(document)

        # 2. 去除噪声
        normalized = self._remove_noise(normalized, source_type)

        # 3. 格式检测
        format_info = self._detect_format(normalized)

        # 4. 结构标记
        structure_markers = self._mark_structure(normalized)

        return NormalizedDocument(
            content=normalized,
            profile=format_info,
            structure_markers=structure_markers,
            metadata={
                'original_length': len(document),
                'normalized_length': len(normalized),
                'source_type': source_type
            }
        )

    def _normalize_encoding(self, document: str) -> str:
        """编码统一"""
        # 移除 BOM
        if document.startswith('\ufeff'):
            document = document[1:]

        # 统一换行符
        document = document.replace('\r\n', '\n').replace('\r', '\n')

        # 移除控制字符（保留换行和制表符）
        document = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', document)

        return document

    def _remove_noise(self, document: str, source_type: str) -> str:
        """去除噪声"""
        # PDF 转换文档的特殊噪声
        if source_type == 'pdf':
            # 移除页眉页脚（常见模式）
            document = re.sub(r'.{0,50}第\s*\d+\s*页.{0,20}\n', '\n', document)
            # 移除孤立的页码
            document = re.sub(r'\n\s*\d+\s*\n', '\n', document)
            # 移除过多的空行
            document = re.sub(r'\n\s*\n\s*\n+', '\n\n', document)

        # HTML 转换文档的特殊噪声
        elif source_type == 'html':
            # 优先处理 HTML 表格格式（飞书在线文档）
            # 将表格中的条款格式转换为更易读的格式
            # <td>**2.1**</td><td>**标题** 内容</td> -> **2.1** **标题** 内容
            document = re.sub(r'<td>\*\*(\d+\.\d+)\*\*\s*</td><td[^>]*>\*\*([^*]*)\*\*\s*', r'**\1** **\2** ', document)
            document = re.sub(r'<td>\*\*(\d+\.\d+)\*\*\s*</td><td[^>]*>([^<]*)', r'**\1** \2', document)
            document = re.sub(r'<td>\*\*(\d+)\*\*\s*</td><td[^>]*>\*\*([^*]*)\*\*\s*', r'**\1** **\2** ', document)
            # 移除剩余的 HTML 标签
            document = re.sub(r'<[^>]+>', '', document)
            # 移除多余空白和换行
            document = re.sub(r'\n\s*\n\s*\n+', '\n\n', document)
            # 清理 <br/> 残留
            document = document.replace('<br/>', '\n')
            document = document.replace('<br>', '\n')

        # 通用噪声处理
        # 移除全角空格
        document = document.replace('\u3000', ' ')
        # 移除零宽字符
        document = re.sub(r'[\u200b-\u200d\ufeff]', '', document)
        # 统一引号
        document = document.replace('"', '"').replace('"', '"')
        document = document.replace('\u2018', "'").replace('\u2019', "'")
        document = document.replace('\u201c', '"').replace('\u201d', '"')

        return document.strip()

    def _detect_format(self, document: str) -> DocumentProfile:
        """分析文档画像：提取用于路由决策的关键特征"""
        # 检测章节结构（至少5个章节才算有结构）
        section_patterns = [
            r'第[一二三四五六七八九十百千]+\s*[章节条款]',
            r'#{1,2}\s+',
            r'\d+\.[1-9]',
        ]
        section_count = sum(
            len(re.findall(p, document, re.MULTILINE))
            for p in section_patterns
        )
        is_structured = section_count >= 5

        # 检测是否有条款编号
        has_clause_numbers = bool(
            re.search(r'第[一二三四五六七八九十]+\s*条', document)
        )

        # 检测是否有费率表特征
        has_premium_table = bool(
            re.search(r'(年龄|岁).*?(保费|费率|元)', document)
        )

        return DocumentProfile(
            is_structured=is_structured,
            has_clause_numbers=has_clause_numbers,
            has_premium_table=has_premium_table
        )

    def _mark_structure(self, document: str) -> StructureMarkers:
        """标记文档结构"""
        markers = StructureMarkers()

        # 条款位置
        for match in re.finditer(r'第[一二三四五六七八九十]+\s*条', document):
            markers.clause_positions.append(match.start())

        # 表格位置
        for match in re.finditer(r'<tr', document):
            markers.table_positions.append(match.start())

        # 章节位置
        for match in re.finditer(r'(第[一二三四五六七八九十百千]+\s*[章节条款]|#{1,2}\s+)', document):
            markers.section_positions.append(match.start())

        return markers
