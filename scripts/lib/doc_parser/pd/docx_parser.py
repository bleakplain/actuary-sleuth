#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文档解析器"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..models import (
    AuditDocument,
    DataTable,
    DocumentParseError,
)
from .product_name_recognizer import recognize_product_name, resolve_product_name
from .product_tagging import build_product_tags
from .numbered_blocks import (
    SourceRecord,
    SourceRecordKind,
    assemble_numbered_content,
    is_numbering_table_rows,
)
from .section_detector import SectionDetector
from .table_classifier import TableClassifier

logger = logging.getLogger(__name__)


def _unique_row_values(row) -> tuple[str, ...]:
    """按底层 ``w:tc`` 身份去除合并单元格代理。"""
    seen_cells: set[int] = set()
    values: list[str] = []
    for cell in row.cells:
        identity = id(cell._tc)
        if identity in seen_cells:
            continue
        seen_cells.add(identity)
        values.append((cell.text or "").strip())
    return tuple(values)


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

        records = self._extract_source_records(doc)
        content = assemble_numbered_content(records, self.detector)
        warnings.extend(content.warnings)
        audit_doc = AuditDocument(
            file_name=display_file_name,
            file_type='.docx',
            clauses=content.clauses,
            tables=content.tables,
            unclassified_sections=content.unclassified_sections,
            notices=content.notices,
            health_disclosures=content.health_disclosures,
            exclusions=content.exclusions,
            rider_clauses=content.rider_clauses,
            coverage_attestation=content.coverage_attestation,
            product_name=recognition.product_name,
            product_name_source=name_resolution.source,
            is_rider=recognition.is_rider,
            group_or_individual=recognition.group_or_individual,
            duration_type=recognition.duration_type,
            design_type=recognition.design_type,
            naming_warnings=recognition.warnings,
            parse_time=datetime.now(),
            warnings=warnings,
        )
        product_tags = build_product_tags(
            recognition.product_name,
            audit_doc.canonical_text,
            product_name_source=name_resolution.source,
            complete_document=(
                content.coverage_attestation.coverage_attested
            ),
        )
        return replace(
            audit_doc,
            product_tags=product_tags,
            warnings=[*warnings, *product_tags.warnings],
        )

    def _extract_source_records(self, doc) -> tuple[SourceRecord, ...]:
        """按 ``w:body`` 顺序交错读取段落与表格。"""
        records: list[SourceRecord] = []
        order = 0
        paragraph_index = 0
        table_index = 0
        parent = doc._body
        for element in doc.element.body.iterchildren():
            element_type = element.tag.rsplit("}", 1)[-1]
            if element_type == "p":
                paragraph = Paragraph(element, parent)
                text = paragraph.text.strip()
                if text:
                    records.append(SourceRecord(
                        order=order,
                        kind=SourceRecordKind.TEXT,
                        fields=(text,),
                        paragraph_index=paragraph_index,
                    ))
                    order += 1
                paragraph_index += 1
                continue
            if element_type != "tbl":
                continue
            table = Table(element, parent)
            rows = tuple(_unique_row_values(row) for row in table.rows)
            if is_numbering_table_rows(rows):
                for row_index, row in enumerate(rows):
                    if not any(row):
                        continue
                    records.append(SourceRecord(
                        order=order,
                        kind=SourceRecordKind.TABLE_ROW,
                        fields=row,
                        table_index=table_index,
                        row_index=row_index,
                        numbering_stream=True,
                    ))
                    order += 1
            elif self._is_structured_data_table(rows):
                raw_text = "\n".join("\t".join(row) for row in rows)
                data_table = DataTable(
                    data=[list(row) for row in rows],
                    table_type=self.table_classifier.classify_by_header(
                        " ".join(rows[0]),
                    ),
                    raw_text=raw_text,
                    table_index=table_index,
                    document_order=order,
                )
                records.append(SourceRecord(
                    order=order,
                    kind=SourceRecordKind.DATA_TABLE,
                    table_index=table_index,
                    data_table=data_table,
                ))
                order += 1
            else:
                for row_index, row in enumerate(rows):
                    if not any(row):
                        continue
                    records.append(SourceRecord(
                        order=order,
                        kind=SourceRecordKind.TABLE_ROW,
                        fields=row,
                        table_index=table_index,
                        row_index=row_index,
                    ))
                    order += 1
            table_index += 1
        return tuple(records)

    @staticmethod
    def _is_structured_data_table(
        rows: tuple[tuple[str, ...], ...],
    ) -> bool:
        return bool(
            len(rows) >= 2
            and rows
            and sum(bool(cell.strip()) for cell in rows[0]) >= 2
        )
