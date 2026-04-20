#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import pdfplumber

from ..models import Clause, PremiumTable, AuditDocument, DocumentParseError, SectionType
from .section_detector import SectionDetector
from .utils import separate_title_and_text, add_section

logger = logging.getLogger(__name__)


class PdfParser:
    """PDF 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.pdf']

    def parse(self, file_path: str) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as e:
            raise DocumentParseError("PDF 文件解析失败", file_path, str(e))

        warnings: List[str] = []
        clauses: List[Clause] = []
        premium_tables: List[PremiumTable] = []
        sections_data: Dict[str, List[Any]] = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        try:
            for page in pdf.pages:
                tables = page.find_tables()

                page_clauses = self._extract_clauses_from_tables(tables, warnings)
                clauses.extend(page_clauses)

                page_premium = self._extract_premium_from_tables(tables, warnings)
                premium_tables.extend(page_premium)

                page_sections = self._extract_sections_from_page(page, warnings)
                for key, items in page_sections.items():
                    sections_data[key].extend(items)
        finally:
            pdf.close()

        return AuditDocument(
            file_name=path.name,
            file_type='.pdf',
            clauses=clauses,
            premium_tables=premium_tables,
            notices=sections_data['notices'],
            health_disclosures=sections_data['health_disclosures'],
            exclusions=sections_data['exclusions'],
            rider_clauses=sections_data['rider_clauses'],
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses_from_tables(self, tables, warnings: List[str]) -> List[Clause]:
        clauses = []

        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            for row in rows:
                if not row or not row[0]:
                    continue

                first_cell = str(row[0] or '').strip()
                if self.detector.is_clause_table(first_cell):
                    number = first_cell
                    content = str(row[1] or '').strip() if len(row) > 1 else ''
                    title, text = separate_title_and_text(content)
                    clauses.append(Clause(number=number, title=title, text=text))

        return clauses

    def _extract_premium_from_tables(self, tables, warnings: List[str]) -> List[PremiumTable]:
        premium_tables = []

        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            header = [str(cell or '').strip() for cell in rows[0]] if rows else []
            if self.detector.is_premium_table(header):
                raw_text = '\n'.join('\t'.join(str(cell or '') for cell in row) for row in rows)
                data = [[str(cell or '') for cell in row] for row in rows]
                premium_tables.append(PremiumTable(raw_text=raw_text, data=data))

        return premium_tables

    def _extract_sections_from_page(self, page, warnings: List[str]) -> Dict[str, List[Any]]:
        result: Dict[str, List[Any]] = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        text = page.extract_text() or ''
        lines = text.split('\n')

        current_type: Optional[SectionType] = None
        current_content: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            detected = self.detector.detect_section_type(line)
            if detected:
                if current_type and current_content:
                    add_section(result, current_type, '', '\n'.join(current_content))
                current_type = detected
                current_content = []
            else:
                if current_type:
                    current_content.append(line)

        if current_type and current_content:
            add_section(result, current_type, '', '\n'.join(current_content))

        return result
