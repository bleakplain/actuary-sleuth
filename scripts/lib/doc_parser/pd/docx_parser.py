#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文档解析器"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from docx import Document
from docx.table import Table

import re

from ..models import (
    AuditDocument,
    Clause,
    DataTable,
    DocumentParseError,
    DocumentSection,
    SectionType,
    TableType,
)
from .product_name_recognizer import recognize_product_name, resolve_product_name
from .product_tagging import build_product_tags
from .clause_tagger import tag_clause_topics
from .section_detector import SectionDetector
from .table_classifier import TableClassifier
from .utils import split_title_and_content, add_section

logger = logging.getLogger(__name__)

# 条款编号格式：只匹配 X.Y 或 X.Y.Z 格式（至少包含一个点）
CLAUSE_NUMBER_PATTERN = re.compile(r'^\d+\.\d+(?:\.\d+)*$')


def _collapse_merged_cell_values(values: List[str]) -> List[str]:
    """python-docx 会为横向合并格重复返回同一文本，只折叠相邻重复值。"""
    collapsed: List[str] = []
    previous_key = ''
    for value in values:
        stripped = (value or '').strip()
        if not stripped:
            continue
        key = re.sub(r'\s+', ' ', stripped)
        if key == previous_key:
            continue
        collapsed.append(stripped)
        previous_key = key
    return collapsed


class DocxParser:
    """Word (.docx) 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()
        self.table_classifier = TableClassifier()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.docx']

    def parse(
        self,
        file_path: str,
        *,
        original_file_name: Optional[str] = None,
        user_product_name: Optional[str] = None,
    ) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)
        display_file_name = (
            Path(original_file_name).name if original_file_name else path.name
        )

        try:
            doc = Document(file_path)
        except Exception as e:
            raise DocumentParseError("Word 文件解析失败", file_path, str(e))

        warnings: List[str] = []
        paragraph_texts = [p.text for p in doc.paragraphs]
        recognized = recognize_product_name(paragraph_texts)
        name_resolution = resolve_product_name(
            recognized, display_file_name, user_product_name,
        )
        recognition = name_resolution.recognition
        warnings.extend(name_resolution.warnings)

        clauses = self._extract_clauses(doc.tables, warnings)
        if len(clauses) < 5:
            para_clauses = self._extract_clauses_from_paragraphs(doc.paragraphs, warnings)
            if len(para_clauses) > len(clauses):
                clauses = para_clauses
        tables = self._extract_tables(doc.tables, warnings)
        sections = self._extract_sections(doc.paragraphs, warnings)
        self._preserve_unrepresented_content(
            doc.paragraphs,
            doc.tables,
            clauses,
            tables,
            sections,
        )
        clauses = [replace(clause, topics=tag_clause_topics(clause.title, clause.text)) for clause in clauses]
        sections["rider_clauses"] = [
            replace(clause, topics=tag_clause_topics(clause.title, clause.text))
            for clause in sections["rider_clauses"]
        ]
        document_parts = [f"{clause.title}\n{clause.text}" for clause in clauses]
        document_parts.extend(table.raw_text for table in tables)
        for section_name in (
            'unclassified_sections',
            'notices',
            'health_disclosures',
            'exclusions',
            'rider_clauses',
        ):
            document_parts.extend(
                f"{item.title}\n{getattr(item, 'content', getattr(item, 'text', ''))}"
                for item in sections[section_name]
            )
        document_content = "\n".join(part for part in document_parts if part)
        product_tags = build_product_tags(
            recognition.product_name,
            document_content,
            product_name_source=name_resolution.source,
            complete_document=True,
        )
        warnings.extend(product_tags.warnings)

        return AuditDocument(
            file_name=display_file_name,
            file_type='.docx',
            clauses=clauses,
            tables=tables,
            unclassified_sections=sections['unclassified_sections'],
            notices=sections['notices'],
            health_disclosures=sections['health_disclosures'],
            exclusions=sections['exclusions'],
            rider_clauses=sections['rider_clauses'],
            product_name=recognition.product_name,
            product_name_source=name_resolution.source,
            is_rider=recognition.is_rider,
            group_or_individual=recognition.group_or_individual,
            duration_type=recognition.duration_type,
            design_type=recognition.design_type,
            naming_warnings=recognition.warnings,
            product_tags=product_tags,
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses(self, tables: List[Table], warnings: List[str]) -> List[Clause]:
        """提取条款，只提取 X.Y 格式的条款，过滤章节标题。

        支持多种表格结构：
        - 2 列：编号 + 内容（标题和正文合并）
        - 3+ 列：编号 + 标题 + 正文（正文在第 3 列）
        """
        clauses = []

        for table in tables:
            if not table.rows:
                continue

            first_row = [cell.text.strip() for cell in table.rows[0].cells]
            if self.detector.is_non_clause_table(first_row):
                continue

            for row in table.rows:
                cells = [(cell.text or '').strip() for cell in row.cells]
                if not cells or not cells[0]:
                    continue

                number = cells[0].strip()
                # 只匹配 X.Y 或 X.Y.Z 格式，过滤单数字章节标题
                if CLAUSE_NUMBER_PATTERN.match(number):
                    payload = _collapse_merged_cell_values(cells[1:])
                    if len(payload) >= 2:
                        # 3+ 列结构：编号 + 标题 + 一个或多个不同正文格。
                        title = payload[0]
                        text = '\n'.join(payload[1:])
                    else:
                        # 2 列或横向合并结构：编号 + 标题正文合并内容。
                        title, text = split_title_and_content(
                            payload[0] if payload else '',
                        )
                    clauses.append(Clause(number=number, title=title, text=text))

        return clauses

    def _extract_clauses_from_paragraphs(self, paragraphs: List, warnings: List[str]) -> List[Clause]:
        clauses: List[Clause] = []
        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue
            match = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s+(.+)$', text)
            if match:
                number = match.group(1)
                rest = match.group(2).strip()
                title, content = split_title_and_content(rest)
                clauses.append(Clause(number=number, title=title, text=content))
        if clauses:
            warnings.append(f"从段落提取了 {len(clauses)} 条条款（表格提取不足）")
        return clauses

    def _extract_tables(self, tables: List[Table], warnings: List[str]) -> List[DataTable]:
        """提取数据表格，使用 TableClassifier 分类表格类型。"""
        result: List[DataTable] = []

        for table in tables:
            if not table.rows:
                continue

            rows = [[(cell.text or '').strip() for cell in row.cells] for row in table.rows]
            if len(rows) < 2:
                continue
            if any(
                row and CLAUSE_NUMBER_PATTERN.match(row[0])
                for row in rows
            ):
                continue

            header = [h for h in rows[0] if h]
            if len(header) < 2:
                continue

            classification = self.table_classifier.classify_by_header(' '.join(rows[0]))
            raw_text = '\n'.join('\t'.join(row) for row in rows)

            result.append(DataTable(
                data=rows,
                table_type=classification,
                raw_text=raw_text,
            ))

        return result

    def _extract_sections(
        self,
        paragraphs: List,
        warnings: List[str],
    ) -> Dict[str, List[Any]]:
        result: Dict[str, List[Any]] = {
            'unclassified_sections': [],
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        current_type: Optional[SectionType] = None
        current_title = ''
        current_content: List[str] = []

        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue
            if re.match(r'^\d+\.\d+(?:\.\d+)*\s+.+$', text):
                continue

            detected = self.detector.detect_section_type(text)
            if detected:
                if current_type:
                    add_section(
                        result,
                        current_type,
                        current_title,
                        '\n'.join(current_content),
                    )
                current_type = detected
                current_title = text
                current_content = []
            else:
                if current_type:
                    current_content.append(text)
                else:
                    result['unclassified_sections'].append(DocumentSection(
                        title='',
                        content=text,
                        section_type=SectionType.UNCLASSIFIED.value,
                    ))

        if current_type:
            add_section(
                result,
                current_type,
                current_title,
                '\n'.join(current_content),
            )

        return result

    def _preserve_unrepresented_content(
        self,
        paragraphs: List,
        source_tables: List[Table],
        clauses: List[Clause],
        tables: List[DataTable],
        sections: Dict[str, List[Any]],
    ) -> None:
        """把未进入任何结构的 DOCX 原文保守纳入未分类审核块。"""
        represented: List[str] = []

        def normalize(value: str) -> str:
            return re.sub(r'\s+', ' ', value or '').strip()

        def register(value: str) -> None:
            normalized = normalize(value)
            if normalized:
                represented.append(normalized)

        def is_represented(value: str) -> bool:
            normalized = normalize(value)
            return not normalized or any(
                normalized == item or normalized in item
                for item in represented
            )

        for clause in clauses:
            register(clause.number)
            register(clause.title)
            register(clause.text)
            register(f"{clause.title} {clause.text}")
            register(f"{clause.number} {clause.title} {clause.text}")
        for table in tables:
            register(table.raw_text)
            for row in table.data:
                register('\t'.join(str(cell or '') for cell in row))
        for section_name in (
            'unclassified_sections',
            'notices',
            'health_disclosures',
            'exclusions',
            'rider_clauses',
        ):
            for item in sections[section_name]:
                title = item.title
                content = getattr(item, 'content', getattr(item, 'text', ''))
                register(title)
                register(content)
                register(f"{title} {content}")

        def preserve(value: str) -> None:
            if is_represented(value):
                return
            sections['unclassified_sections'].append(DocumentSection(
                title='',
                content=value.strip(),
                section_type=SectionType.UNCLASSIFIED.value,
            ))
            register(value)

        for paragraph in paragraphs:
            preserve(paragraph.text)
        for source_table in source_tables:
            for row in source_table.rows:
                row_text = '\t'.join(
                    _collapse_merged_cell_values([
                        (cell.text or '').strip()
                        for cell in row.cells
                    ])
                )
                preserve(row_text)
