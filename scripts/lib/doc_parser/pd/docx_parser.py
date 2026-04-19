#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文档解析器"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from docx import Document
from docx.table import Table

from ..models import Clause, PremiumTable, AuditDocument, DocumentParseError, SectionType
from .section_detector import SectionDetector
from .utils import separate_title_and_text, add_section

logger = logging.getLogger(__name__)


class DocxParser:
    """Word (.docx) 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.docx']

    def parse(self, file_path: str) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)

        try:
            doc = Document(file_path)
        except Exception as e:
            raise DocumentParseError("Word 文件解析失败", file_path, str(e))

        warnings: List[str] = []

        clauses = self._extract_clauses(doc.tables, warnings)
        premium_tables = self._extract_premium_tables(doc.tables, warnings)
        sections = self._extract_sections(doc.paragraphs, warnings)

        return AuditDocument(
            file_name=path.name,
            file_type='.docx',
            clauses=clauses,
            premium_tables=premium_tables,
            notices=sections['notices'],
            health_disclosures=sections['health_disclosures'],
            exclusions=sections['exclusions'],
            rider_clauses=sections['rider_clauses'],
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses(self, tables: List[Table], warnings: List[str]) -> List[Clause]:
        clauses = []

        for table in tables:
            if not table.rows:
                continue

            first_row = [cell.text.strip() for cell in table.rows[0].cells]
            if self.detector.is_non_clause_table(first_row):
                continue

            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if not cells or not cells[0]:
                    continue

                if self.detector.is_clause_table(cells[0]):
                    number = cells[0].strip()
                    title, text = separate_title_and_text(cells[1] if len(cells) > 1 else '')
                    clauses.append(Clause(number=number, title=title, text=text))

        return clauses

    def _extract_premium_tables(self, tables: List[Table], warnings: List[str]) -> List[PremiumTable]:
        premium_tables = []

        for table in tables:
            if not table.rows:
                continue

            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if self.detector.is_premium_table(rows[0]):
                raw_text = '\n'.join('\t'.join(row) for row in rows)
                premium_tables.append(PremiumTable(raw_text=raw_text, data=rows))

        return premium_tables

    def _extract_sections(
        self,
        paragraphs: List,
        warnings: List[str],
    ) -> Dict[str, List[Any]]:
        result: Dict[str, List[Any]] = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        current_type: Optional[SectionType] = None
        current_content: List[str] = []

        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue

            detected = self.detector.detect_section_type(text)
            if detected:
                if current_type and current_content:
                    add_section(result, current_type, '', '\n'.join(current_content))
                current_type = detected
                current_content = []
            else:
                if current_type:
                    current_content.append(text)

        if current_type and current_content:
            add_section(result, current_type, '', '\n'.join(current_content))

        return result
