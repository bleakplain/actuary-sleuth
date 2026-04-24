#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析数据模型"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple


class SectionType(str, Enum):
    """内容类型枚举"""
    CLAUSE = "clause"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"


class TableType(str, Enum):
    """表格类型枚举"""
    PREMIUM = "premium"              # 费率表
    COVERAGE = "coverage"            # 保障计划表/给付比例表
    DRUG_LIST = "drug_list"          # 药品清单表
    COMPLICATION = "complication"    # 手术并发症表
    HOSPITAL = "hospital"            # 医院名单表
    OTHER = "other"                  # 其他数据表格
    UNKNOWN = "unknown"              # 未知类型


@dataclass(frozen=True)
class ChunkMetadata:
    """Chunk 元数据"""
    doc_id: str
    doc_name: str
    doc_type: str
    section_path: str
    section_level: int
    chunk_index: int
    char_count: int
    is_key_clause: bool = False
    has_table: bool = False
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    parse_confidence: float = 0.95
    update_time: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'doc_id': self.doc_id,
            'doc_name': self.doc_name,
            'doc_type': self.doc_type,
            'section_path': self.section_path,
            'section_level': self.section_level,
            'chunk_index': self.chunk_index,
            'char_count': self.char_count,
            'is_key_clause': self.is_key_clause,
            'has_table': self.has_table,
            'prev_chunk_id': self.prev_chunk_id,
            'next_chunk_id': self.next_chunk_id,
            'parse_confidence': self.parse_confidence,
            'update_time': self.update_time,
        }


@dataclass(frozen=True)
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

        输出字段保持稳定，保证向量存储和检索兼容。
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
    page_number: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    table_index: Optional[int] = None


@dataclass(frozen=True)
class DataTable:
    """数据表格"""
    data: List[List[str]]              # 结构化数据（二维表格）
    table_type: TableType              # 表格类型
    raw_text: str = ""                 # 原始文本
    remark: str = ""                   # 备注
    page_number: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    table_index: Optional[int] = None

    def to_markdown(self) -> str:
        """转换为 Markdown 表格格式"""
        if not self.data:
            return ""
        lines: List[str] = []
        headers = [str(cell).replace('\n', ' ') for cell in self.data[0]]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in self.data[1:]:
            cells = [str(cell).replace('\n', ' ') for cell in row]
            while len(cells) < len(headers):
                cells.append("")
            lines.append("| " + " | ".join(cells[:len(headers)]) + " |")
        if self.remark:
            lines.append(f"\n*{self.remark}*")
        return "\n".join(lines)

    def split_for_chunking(self, max_rows: int = 50) -> List['DataTable']:
        """将大表格分割为多个子表格，每个子表格携带表头"""
        if len(self.data) <= max_rows:
            return [self]
        result: List['DataTable'] = []
        header = self.data[0]
        for i in range(1, len(self.data), max_rows - 1):
            chunk_data = [header] + self.data[i:i + max_rows - 1]
            result.append(DataTable(
                data=chunk_data,
                table_type=self.table_type,
                raw_text="",
                remark=self.remark,
                page_number=self.page_number,
                bbox=self.bbox,
            ))
        return result


@dataclass(frozen=True)
class DocumentSection:
    """通用文档章节"""
    title: str        # 章节标题
    content: str      # 章节内容
    section_type: str # 内容类型：notice, health_disclosure, exclusion, rider


@dataclass(frozen=True)
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .docx, .pdf

    clauses: List[Clause] = field(default_factory=list)
    tables: List[DataTable] = field(default_factory=list)      # 数据表格
    notices: List[DocumentSection] = field(default_factory=list)
    health_disclosures: List[DocumentSection] = field(default_factory=list)
    exclusions: List[DocumentSection] = field(default_factory=list)
    rider_clauses: List[Clause] = field(default_factory=list)

    parse_time: datetime = field(default_factory=datetime.now)
    warnings: List[str] = field(default_factory=list)

    def get_chunk_metadata(
        self,
        section_path: str,
        chunk_index: int,
        is_key_clause: bool = False,
        has_table: bool = False,
        prev_chunk_id: Optional[str] = None,
        next_chunk_id: Optional[str] = None,
    ) -> ChunkMetadata:
        """生成 Chunk 元数据"""
        doc_id = self.file_name.replace('.', '_')
        doc_type = "insurance_contract" if self.file_type in ['.pdf', '.docx'] else "unknown"
        char_count = sum(len(c.text) for c in self.clauses) + sum(
            len(t.raw_text) for t in self.tables
        )
        return ChunkMetadata(
            doc_id=doc_id,
            doc_name=self.file_name,
            doc_type=doc_type,
            section_path=section_path,
            section_level=section_path.count('>') + 1,
            chunk_index=chunk_index,
            char_count=char_count,
            is_key_clause=is_key_clause,
            has_table=has_table,
            prev_chunk_id=prev_chunk_id,
            next_chunk_id=next_chunk_id,
            parse_confidence=0.95,
            update_time=self.parse_time.isoformat(),
        )


class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
