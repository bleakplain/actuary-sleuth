#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析数据模型"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any


class SectionType(str, Enum):
    """内容类型枚举"""
    CLAUSE = "clause"
    PREMIUM_TABLE = "premium_table"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"


@dataclass
class DocumentMeta:
    """文档级元数据（内部结构化表示）

    从 YAML frontmatter 解析而来，提供类型安全的访问接口。
    对外输出通过 to_chunk_metadata() 转换为 Dict，保证与现有检索系统兼容。
    """
    collection: str
    category: str              # 从 collection 提取
    law_name: str              # = regulation
    issuing_authority: str = ""
    doc_number: str = ""
    insurance_type: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, frontmatter: dict) -> 'DocumentMeta':
        """从 YAML frontmatter 构建"""
        collection = str(frontmatter.get('collection', ''))
        category = collection.split('_', 1)[1] if '_' in collection else collection

        return cls(
            collection=collection,
            category=category,
            law_name=str(frontmatter.get('regulation', '')),
            issuing_authority=cls._first_non_empty(frontmatter.get('发文机关', [])),
            doc_number=cls._first_non_empty(frontmatter.get('文号', [])),
            insurance_type=str(frontmatter.get('险种类型', '')),
            extra={
                '备注': cls._first_non_empty(frontmatter.get('备注', [])),
            }
        )

    def to_chunk_metadata(self, article_number: str, source_file: str) -> Dict[str, Any]:
        """转换为 TextNode.metadata 格式

        输出字段与现有 ChecklistChunker 完全一致，保证向量存储和检索兼容。
        """
        metadata: Dict[str, Any] = {
            'law_name': self.law_name,
            'article_number': article_number,
            'category': self.category,
            'source_file': source_file,
            'hierarchy_path': f"{self.category} > {self.law_name} > {article_number}",
        }
        if self.issuing_authority:
            metadata['issuing_authority'] = self.issuing_authority
        if self.doc_number:
            metadata['doc_number'] = self.doc_number
        if self.insurance_type:
            metadata['险种类型'] = self.insurance_type
        metadata.update({k: v for k, v in self.extra.items() if v})
        return metadata

    @staticmethod
    def _first_non_empty(values: list) -> str:
        for v in values:
            if v and str(v).strip():
                return str(v).strip()
        return ''


@dataclass(frozen=True)
class Clause:
    """条款"""
    number: str       # 条款编号，如 "1.2.3"
    title: str        # 条款标题
    text: str         # 条款正文
    section_type: str = "clause"


@dataclass
class PremiumTable:
    """费率表"""
    raw_text: str              # 原始文本
    data: List[List[str]]      # 结构化数据（二维表格）
    remark: str = ""           # 备注
    section_type: str = "premium_table"


@dataclass
class DocumentSection:
    """通用文档章节"""
    title: str        # 章节标题
    content: str      # 章节内容
    section_type: str # 内容类型：notice, health_disclosure, exclusion, rider


@dataclass
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .docx, .pdf

    clauses: List[Clause] = field(default_factory=list)
    premium_tables: List[PremiumTable] = field(default_factory=list)
    notices: List[DocumentSection] = field(default_factory=list)
    health_disclosures: List[DocumentSection] = field(default_factory=list)
    exclusions: List[DocumentSection] = field(default_factory=list)
    rider_clauses: List[Clause] = field(default_factory=list)

    parse_time: datetime = field(default_factory=datetime.now)
    warnings: List[str] = field(default_factory=list)


class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
