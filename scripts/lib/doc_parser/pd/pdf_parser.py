#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber

from ..models import AuditDocument, Clause, DocumentParseError, PremiumTable, SectionType
from .section_detector import SectionDetector
from .utils import add_section, separate_title_and_text

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
            error_msg = str(e).lower()
            if "password" in error_msg or "encrypted" in error_msg:
                raise DocumentParseError(
                    "PDF 文件已加密，不支持加密文档",
                    file_path,
                    "请提供未加密的 PDF 文档"
                )
            raise DocumentParseError("PDF 文件解析失败", file_path, str(e))

        warnings: List[str] = []

        try:
            clauses = self._extract_clauses(pdf.pages, warnings)
            premium_tables = self._extract_premium_tables(pdf.pages, warnings)
            sections_data = self._extract_special_sections(pdf.pages, warnings)
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

    def _extract_clauses(self, pages: List, warnings: List[str]) -> List[Clause]:
        """提取条款内容。

        从文本流识别条款编号和标题，合并跨页重复条款。
        """
        clauses_dict: Dict[str, Clause] = {}

        pending_number: Optional[str] = None
        pending_title: Optional[str] = None
        pending_content: List[str] = []
        pending_page: int = 1

        for page_idx, page in enumerate(pages):
            text = page.extract_text() or ''
            lines = text.split('\n')

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                match = self._match_clause_line(stripped)
                if match:
                    number = match.group(1)
                    title = match.group(2).strip()

                    if pending_number is not None and pending_number != number:
                        self._merge_clause(
                            clauses_dict,
                            pending_number,
                            pending_title or '',
                            pending_content,
                            pending_page,
                        )
                        pending_content = []

                    pending_number = number
                    pending_title = title
                    pending_page = page_idx + 1
                elif pending_number is not None:
                    pending_content.append(stripped)

        if pending_number is not None:
            self._merge_clause(
                clauses_dict,
                pending_number,
                pending_title or '',
                pending_content,
                pending_page,
            )

        clauses = list(clauses_dict.values())

        def sort_key(c: Clause) -> List[int]:
            parts = c.number.split('.')
            return [int(p) for p in parts]

        clauses.sort(key=sort_key)
        return clauses

    def _match_clause_line(self, line: str):
        """匹配条款行：编号 + 空格 + 标题。

        复用 SectionDetector.is_clause_table 验证编号格式，
        同时提取标题部分。
        """
        stripped = line.strip()
        # 匹配格式：编号 + 空格 + 标题内容
        import re
        match = re.match(r'^(\d+(?:\.\d+)*)\s+(.+)$', stripped)
        if match:
            number = match.group(1)
            # 复用 is_clause_table 验证编号格式是否有效
            if self.detector.is_clause_table(number):
                return match
        return None

    def _merge_clause(
        self,
        clauses_dict: Dict[str, Clause],
        number: str,
        title: str,
        content_lines: List[str],
        page_number: int,
    ) -> None:
        """合并条款到字典，处理跨页重复和章节标题干扰。"""
        filtered_lines = [line for line in content_lines if not self._is_chapter_header(line)]

        if number in clauses_dict:
            existing = clauses_dict[number]
            combined_text = existing.text
            if filtered_lines:
                new_text = '\n'.join(filtered_lines).strip()
                if new_text:
                    combined_text = f"{combined_text}\n{new_text}" if combined_text else new_text
            clauses_dict[number] = Clause(
                number=existing.number,
                title=existing.title or title,
                text=combined_text,
                page_number=existing.page_number,
            )
        else:
            clause = self._build_clause(number, title, filtered_lines, page_number)
            clauses_dict[number] = clause

    def _is_chapter_header(self, line: str) -> bool:
        """检测章节标题行（用于过滤目录页干扰）。"""
        stripped = line.strip()
        chapter_titles = [
            '其他事项', '合同效力', '保险费', '保险金的申请及给付',
            '名词释义', '投保范围', '保险责任及责任免除',
        ]
        return any(stripped.endswith(t) and len(stripped) < 20 for t in chapter_titles)

    def _build_clause(
        self,
        number: str,
        title: str,
        content_lines: List[str],
        page_number: int,
    ) -> Clause:
        """构建条款对象。"""
        full_title, extra_text = separate_title_and_text(title)
        all_content = ([extra_text] if extra_text else []) + content_lines
        text = '\n'.join(all_content).strip()

        return Clause(
            number=number,
            title=full_title,
            text=text,
            page_number=page_number,
        )

    def _extract_premium_tables(self, pages: List, warnings: List[str]) -> List[PremiumTable]:
        """提取费率表。"""
        premium_tables: List[PremiumTable] = []

        for page_idx, page in enumerate(pages):
            tables = page.find_tables()
            for table_idx, table in enumerate(tables):
                rows = table.extract()
                if not rows:
                    continue

                header = [str(cell or '').strip() for cell in rows[0]]
                if self.detector.is_premium_table(header):
                    raw_text = '\n'.join(
                        '\t'.join(str(cell or '') for cell in row)
                        for row in rows
                    )
                    data = [[str(cell or '') for cell in row] for row in rows]
                    bbox = getattr(table, 'bbox', None)
                    premium_tables.append(PremiumTable(
                        raw_text=raw_text,
                        data=data,
                        page_number=page_idx + 1,
                        bbox=bbox,
                        table_index=table_idx,
                    ))

        return premium_tables

    def _extract_special_sections(self, pages: List, warnings: List[str]) -> Dict[str, List[Any]]:
        """提取特殊章节（告知事项、健康告知、责任免除、附加条款）。"""
        result: Dict[str, List[Any]] = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        current_type: Optional[SectionType] = None
        current_content: List[str] = []

        for page in pages:
            text = page.extract_text() or ''
            lines = text.split('\n')

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                detected = self.detector.detect_section_type(stripped)
                if detected:
                    if current_type and current_content:
                        add_section(result, current_type, '', '\n'.join(current_content))
                    current_type = detected
                    current_content = []
                elif current_type:
                    current_content.append(stripped)

        if current_type and current_content:
            add_section(result, current_type, '', '\n'.join(current_content))

        return result
