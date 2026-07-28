#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析数据模型"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..common.product_tags import ProductTags


class SectionType(str, Enum):
    """内容类型枚举"""
    CLAUSE = "clause"
    UNCLASSIFIED = "unclassified"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"


class AuditBlockType(str, Enum):
    """统一审核内容块类型。"""
    UNCLASSIFIED = "unclassified"
    CLAUSE = "clause"
    TABLE = "table"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"


class TableType(str, Enum):
    """表格类型枚举"""
    PREMIUM = "premium"              # 费率表
    COVERAGE = "coverage"            # 保障计划表/给付比例表
    DRUG_LIST = "drug_list"          # 药品清单表
    GENE_TEST = "gene_test"          # 基因检测产品清单表
    COMPLICATION = "complication"    # 手术并发症表
    HOSPITAL = "hospital"            # 医院名单表
    APPENDIX = "appendix"            # 附表（如恶性肿瘤分期表、职业类别表等）
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
    topics: Tuple[str, ...] = ()


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
        chunk_idx = 0
        for i in range(1, len(self.data), max_rows - 1):
            chunk_data = [header] + self.data[i:i + max_rows - 1]
            chunk_idx += 1
            # 为每个 chunk 生成 raw_text
            chunk_raw_text = '\n'.join(
                '\t'.join(str(cell or '') for cell in row)
                for row in chunk_data
            )
            result.append(DataTable(
                data=chunk_data,
                table_type=self.table_type,
                raw_text=chunk_raw_text,
                remark=self.remark if chunk_idx == 1 else "",  # 仅第一个 chunk 显示备注
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
class ClauseBlock:
    """供审核主链消费的不可变产品内容块。"""
    clause_id: str
    document_fingerprint: str
    block_type: AuditBlockType
    source_index: int
    number: str
    title: str
    content: str
    topics: Tuple[str, ...] = ()
    page_number: Optional[int] = None
    table_index: Optional[int] = None


@dataclass(frozen=True)
class _BlockSeed:
    block_type: AuditBlockType
    source_index: int
    number: str
    title: str
    content: str
    topics: Tuple[str, ...] = ()
    page_number: Optional[int] = None
    table_index: Optional[int] = None

    def identity(self) -> Tuple[object, ...]:
        """只使用块自身的原始结构与原文，派生标签和页码不影响证据 ID。"""
        return (
            self.block_type.value,
            _normalize_identity_text(self.number),
            _normalize_identity_text(self.title),
            _normalize_content_identity(self.content),
        )


@dataclass(frozen=True)
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .doc, .docx, .pdf

    clauses: Sequence[Clause] = ()
    tables: Sequence[DataTable] = ()
    unclassified_sections: Sequence[DocumentSection] = ()
    notices: Sequence[DocumentSection] = ()
    health_disclosures: Sequence[DocumentSection] = ()
    exclusions: Sequence[DocumentSection] = ()
    rider_clauses: Sequence[Clause] = ()
    document_fingerprint: str = field(init=False, default="")
    audit_input_fingerprint: str = field(init=False, default="")
    audit_blocks: Tuple[ClauseBlock, ...] = field(init=False, default=())

    # 最终产品名按用户输入、正文识别、文件名的优先级确定。
    product_name: Optional[str] = None
    product_name_source: str = "unknown"
    is_rider: bool = False              # 是否附加险（产品名中含"附加"且位于"保险"之前）
    # 结构化标签维度（从产品名提取，供后续标签化法规筛选使用）
    group_or_individual: Optional[str] = None  # 投保对象标签：团体/个人
    duration_type: Optional[str] = None        # 保险期限标签：终身/定期
    design_type: Optional[str] = None          # 设计类型：普通型/分红型/万能型等
    naming_warnings: List[str] = field(default_factory=list)  # 命名合规校验警告
    product_tags: ProductTags = field(default_factory=ProductTags)

    parse_time: datetime = field(default_factory=datetime.now)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for field_name in (
            "clauses",
            "tables",
            "unclassified_sections",
            "notices",
            "health_disclosures",
            "exclusions",
            "rider_clauses",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        fingerprint, blocks = _build_audit_blocks(self)
        object.__setattr__(self, "document_fingerprint", fingerprint)
        object.__setattr__(
            self,
            "audit_input_fingerprint",
            calculate_audit_input_fingerprint(fingerprint, self.product_name or ""),
        )
        object.__setattr__(self, "audit_blocks", blocks)

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
        doc_type = "insurance_contract" if self.file_type in ['.doc', '.pdf', '.docx'] else "unknown"
        char_count = sum(len(c.text) for c in self.clauses) + sum(
            len(t.raw_text) for t in self.tables
        ) + sum(len(section.content) for section in self.unclassified_sections)
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


def _normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_content_identity(value: str) -> str:
    """规范字符和换行，但保留正文中的段落、行与表格列边界。"""
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" ") for line in normalized.split("\n"))


def _table_content(table: DataTable) -> str:
    if table.raw_text:
        return table.raw_text
    return "\n".join(
        "\t".join(str(cell or "") for cell in row)
        for row in table.data
    )


def calculate_document_fingerprint(
    blocks: Iterable[Tuple[str, str, str, str]],
) -> str:
    """根据有序块的原始类型、编号、标题和正文计算内容指纹。"""
    canonical = json.dumps(
        [
            (
                block_type,
                _normalize_identity_text(number),
                _normalize_identity_text(title),
                _normalize_content_identity(content),
            )
            for block_type, number, title, content in blocks
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calculate_clause_ids(
    blocks: Iterable[Tuple[str, str, str, str]],
) -> Tuple[str, ...]:
    """按块自身内容和同内容出现次序生成稳定证据 ID。"""
    occurrences: Dict[Tuple[str, str, str, str], int] = {}
    clause_ids = []
    for block_type, number, title, content in blocks:
        identity = (
            block_type,
            _normalize_identity_text(number),
            _normalize_identity_text(title),
            _normalize_content_identity(content),
        )
        occurrence = occurrences.get(identity, 0)
        occurrences[identity] = occurrence + 1
        encoded = json.dumps(
            (*identity, occurrence),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        clause_ids.append(
            f"clause_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]}"
        )
    return tuple(clause_ids)


def calculate_audit_input_fingerprint(
    document_fingerprint: str,
    product_name: str,
) -> str:
    """绑定内容指纹与本次审核采用的产品名称。"""
    canonical = json.dumps(
        [
            document_fingerprint,
            _normalize_identity_text(product_name),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_audit_document_text(
    blocks: Iterable[Tuple[str, int, str, str, str]],
) -> str:
    """按解析 API 的规范格式重建完整审核文本。"""
    rendered = []
    for block_type, source_index, number, title, content in blocks:
        if block_type == AuditBlockType.UNCLASSIFIED.value:
            heading = f"【未分类内容 {source_index + 1}】"
            rendered.append(f"{heading}{title}\n{content}")
        elif block_type == AuditBlockType.CLAUSE.value:
            rendered.append(f"【条款 {number}】{title}\n{content}")
        elif block_type == AuditBlockType.TABLE.value:
            rendered.append(f"【数据表 {source_index + 1}】\n{content}")
        elif block_type == AuditBlockType.NOTICE.value:
            rendered.append(f"【投保须知】{title}\n{content}")
        elif block_type == AuditBlockType.HEALTH_DISCLOSURE.value:
            rendered.append(f"【健康告知】{title}\n{content}")
        elif block_type == AuditBlockType.EXCLUSION.value:
            rendered.append(f"【责任免除】{title}\n{content}")
        elif block_type == AuditBlockType.RIDER.value:
            rendered.append(f"【附加险条款 {number}】{title}\n{content}")
        else:
            raise ValueError(f"未知审核块类型: {block_type}")
    return "\n\n".join(rendered)


def _build_audit_blocks(
    document: AuditDocument,
) -> Tuple[str, Tuple[ClauseBlock, ...]]:
    seeds: List[_BlockSeed] = []

    def add_seed(
        block_type: AuditBlockType,
        source_index: int,
        number: str,
        title: str,
        content: str,
        topics: Tuple[str, ...] = (),
        page_number: Optional[int] = None,
        table_index: Optional[int] = None,
    ) -> None:
        seeds.append(_BlockSeed(
            block_type=block_type,
            source_index=source_index,
            number=number,
            title=title,
            content=content,
            topics=tuple(topics),
            page_number=page_number,
            table_index=table_index,
        ))

    for index, section in enumerate(document.unclassified_sections):
        add_seed(
            AuditBlockType.UNCLASSIFIED,
            index,
            "",
            section.title,
            section.content,
        )
    for index, clause in enumerate(document.clauses):
        add_seed(
            AuditBlockType.CLAUSE, index, clause.number, clause.title,
            clause.text, clause.topics, clause.page_number, clause.table_index,
        )
    for index, table in enumerate(document.tables):
        add_seed(
            AuditBlockType.TABLE, index, str(index + 1), table.remark,
            _table_content(table), (), table.page_number, table.table_index,
        )
    section_groups = (
        (AuditBlockType.NOTICE, document.notices),
        (AuditBlockType.HEALTH_DISCLOSURE, document.health_disclosures),
        (AuditBlockType.EXCLUSION, document.exclusions),
    )
    for block_type, sections in section_groups:
        for index, section in enumerate(sections):
            add_seed(block_type, index, "", section.title, section.content)
    for index, clause in enumerate(document.rider_clauses):
        add_seed(
            AuditBlockType.RIDER, index, clause.number, clause.title,
            clause.text, clause.topics, clause.page_number, clause.table_index,
        )

    fingerprint = calculate_document_fingerprint(
        (
            seed.block_type.value,
            seed.number,
            seed.title,
            seed.content,
        )
        for seed in seeds
    )

    clause_ids = calculate_clause_ids(
        (
            seed.block_type.value,
            seed.number,
            seed.title,
            seed.content,
        )
        for seed in seeds
    )
    blocks: List[ClauseBlock] = []
    for seed, clause_id in zip(seeds, clause_ids):
        blocks.append(ClauseBlock(
            clause_id=clause_id,
            document_fingerprint=fingerprint,
            block_type=seed.block_type,
            source_index=seed.source_index,
            number=seed.number,
            title=seed.title,
            content=seed.content,
            topics=seed.topics,
            page_number=seed.page_number,
            table_index=seed.table_index,
        ))
    return fingerprint, tuple(blocks)


class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
