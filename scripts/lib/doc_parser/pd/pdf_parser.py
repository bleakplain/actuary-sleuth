#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

from ..models import (
    AuditDocument,
    DataTable,
    DocumentParseError,
    TableType,
)
from .header_footer_filter import HeaderFooterFilter
from .section_detector import SectionDetector
from .table_classifier import TableClassifier
from .toc_detector import TocDetector
from .numbered_blocks import (
    SourceRecord,
    SourceRecordKind,
    assemble_numbered_content,
    is_numbering_table_rows,
)
from .product_name_recognizer import recognize_product_name, resolve_product_name
from .product_tagging import build_product_tags


class PdfParser:
    """PDF 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()
        self.header_footer_filter = HeaderFooterFilter()
        self.table_classifier = TableClassifier()
        self.toc_detector = TocDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.pdf']

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
            opening_lines: List[str] = []
            for page in pdf.pages[:5]:
                opening_lines.extend((page.extract_text() or "").splitlines())
            recognized = recognize_product_name(opening_lines)
            name_resolution = resolve_product_name(
                recognized, display_file_name, user_product_name,
            )
            recognition = name_resolution.recognition
            records = self._extract_source_records(pdf.pages)
            content = assemble_numbered_content(records, self.detector)
            warnings.extend(content.warnings)
        finally:
            pdf.close()

        warnings.extend(name_resolution.warnings)
        audit_doc = AuditDocument(
            file_name=display_file_name,
            file_type='.pdf',
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

    def _extract_source_records(
        self,
        pages: List,
    ) -> tuple[SourceRecord, ...]:
        """把 PDF 页面转换为与 Word 相同的有序记录。

        被识别为表格的 bbox 会从普通文本行中过滤，避免表格正文重复进入
        条款和独立表格块。
        """
        records: list[SourceRecord] = []
        order = 0
        previous_table: Optional[DataTable] = None
        for page_index, page in enumerate(pages):
            is_toc, clean_toc_text = self.toc_detector.detect(
                page, page_index,
            )
            if is_toc:
                for line_index, line in enumerate(clean_toc_text.splitlines()):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    records.append(SourceRecord(
                        order=order,
                        kind=SourceRecordKind.TEXT,
                        fields=(stripped,),
                        page_number=page_index + 1,
                        paragraph_index=line_index,
                    ))
                    order += 1
                continue

            events: list[tuple[float, int, SourceRecord]] = []
            excluded_bboxes: list[
                Tuple[float, float, float, float]
            ] = []
            found_tables = page.find_tables()
            for table_index, table in enumerate(found_tables):
                extracted = table.extract()
                if not extracted:
                    continue
                rows = tuple(
                    tuple(str(cell or "").strip() for cell in row)
                    for row in extracted
                )
                bbox = tuple(getattr(table, "bbox", (0, 0, 0, 0)))
                if is_numbering_table_rows(rows):
                    excluded_bboxes.append(bbox)
                    table_rows = getattr(table, "rows", ())
                    for row_index, row in enumerate(rows):
                        if not any(row):
                            continue
                        row_bbox = (
                            tuple(table_rows[row_index].bbox)
                            if row_index < len(table_rows)
                            else bbox
                        )
                        events.append((
                            float(row_bbox[1]),
                            0,
                            SourceRecord(
                                order=-1,
                                kind=SourceRecordKind.TABLE_ROW,
                                fields=row,
                                page_number=page_index + 1,
                                table_index=table_index,
                                row_index=row_index,
                                bbox=row_bbox,
                                numbering_stream=True,
                            ),
                        ))
                    continue
                if not self._is_structured_pdf_table(rows):
                    continue
                excluded_bboxes.append(bbox)
                classification = self.table_classifier.classify(table)
                table_type = classification.table_type
                title = self._extract_table_title(page, table)
                is_continuation = self._is_continuation_table(
                    previous_table,
                    current_page_index=page_index,
                    table_top=float(bbox[1]),
                    page_height=float(page.height),
                    column_count=len(rows[0]),
                )
                table_data = [list(row) for row in rows]
                if is_continuation and previous_table is not None:
                    title = title or previous_table.remark
                    if table_type == TableType.OTHER:
                        table_type = previous_table.table_type
                    table_data = self._inherit_continuation_header(
                        previous_table.data[0],
                        table_data,
                    )
                if table_type == TableType.OTHER:
                    table_type = self._classify_by_context(
                        page.extract_text() or "",
                        table_data,
                        title,
                        previous_table.table_type if previous_table else None,
                    )
                raw_text = "\n".join("\t".join(row) for row in table_data)
                data_table = DataTable(
                    data=table_data,
                    table_type=table_type,
                    raw_text=raw_text,
                    remark=title,
                    page_number=page_index + 1,
                    bbox=bbox,
                    table_index=table_index,
                )
                previous_table = data_table
                events.append((
                    float(bbox[1]),
                    1,
                    SourceRecord(
                        order=-1,
                        kind=SourceRecordKind.DATA_TABLE,
                        page_number=page_index + 1,
                        table_index=table_index,
                        bbox=bbox,
                        data_table=data_table,
                    ),
                ))

            filtered_page = page
            if excluded_bboxes:
                filtered_page = page.filter(
                    lambda obj: self._outside_bboxes(obj, excluded_bboxes),
                )
            for line_index, (top, text) in enumerate(
                self.header_footer_filter._build_lines_from_chars(
                    filtered_page,
                ),
            ):
                stripped = text.strip()
                if not stripped or self._is_pdf_margin_line(
                    stripped, top, page.height,
                ):
                    continue
                events.append((
                    float(top),
                    2,
                    SourceRecord(
                        order=-1,
                        kind=SourceRecordKind.TEXT,
                        fields=(stripped,),
                        page_number=page_index + 1,
                        paragraph_index=line_index,
                        bbox=(0.0, float(top), float(page.width), float(top)),
                    ),
                ))

            for _, _, record in sorted(
                events,
                key=lambda item: (item[0], item[1]),
            ):
                records.append(replace(record, order=order))
                order += 1
        return tuple(records)

    @staticmethod
    def _is_continuation_table(
        previous_table: Optional[DataTable],
        *,
        current_page_index: int,
        table_top: float,
        page_height: float,
        column_count: int,
    ) -> bool:
        """判断表格是否紧接上一页。

        ``DataTable.page_number`` 是 1-based，而 ``current_page_index`` 是
        0-based；两者相等恰好表示前表位于当前页的上一页。
        """
        return bool(
            previous_table is not None
            and previous_table.data
            and table_top < page_height * 0.15
            and previous_table.page_number == current_page_index
            and len(previous_table.data[0]) == column_count
        )

    @staticmethod
    def _inherit_continuation_header(
        previous_header: List[str],
        current_data: List[List[str]],
    ) -> List[List[str]]:
        """续表缺表头时补入上一页表头，已有重复表头时保持原样。"""
        if not current_data or current_data[0] == previous_header:
            return current_data
        return [list(previous_header), *current_data]

    @staticmethod
    def _is_structured_pdf_table(
        rows: tuple[tuple[str, ...], ...],
    ) -> bool:
        return bool(
            len(rows) >= 2
            and rows
            and sum(bool(cell) for cell in rows[0]) >= 2
        )

    @staticmethod
    def _outside_bboxes(
        obj: Dict[str, Any],
        bboxes: List[Tuple[float, float, float, float]],
    ) -> bool:
        if obj.get("object_type") != "char":
            return True
        x = (float(obj.get("x0", 0)) + float(obj.get("x1", 0))) / 2
        top = float(obj.get("top", 0))
        bottom = float(obj.get("bottom", top))
        y = (top + bottom) / 2
        return not any(
            left <= x <= right and box_top <= y <= box_bottom
            for left, box_top, right, box_bottom in bboxes
        )

    def _is_pdf_margin_line(
        self,
        text: str,
        top: float,
        page_height: float,
    ) -> bool:
        if (
            top < page_height * self.header_footer_filter.header_region_ratio
            and self.header_footer_filter._is_header(text)
        ):
            return True
        return bool(
            top > page_height * (
                1 - self.header_footer_filter.footer_region_ratio
            )
            and self.header_footer_filter._is_footer(text)
        )

    def _classify_by_context(
        self,
        page_text: str,
        data: List[List[str]],
        table_title: str,
        prev_table_type: Optional[TableType] = None,
    ) -> TableType:
        """利用页面上下文辅助表格分类

        当表头分类结果为 OTHER 时，检查：
        1. 上一页同类型表格（续表）
        2. 表名是否包含 "附表" 等关键词
        3. 表格内容特征（如包含分期指标 "Ⅰ期"、"Ⅱ期"）
        4. 跨页上下文中的附表标题行（独立行格式）

        Args:
            page_text: 页面文本（含前后页面上下文）
            data: 表格数据
            table_title: 表名
            prev_table_type: 上一页底部表格的类型（用于续表检测）

        Returns:
            TableType 或 OTHER
        """
        # 续表：沿用上一页表格的类型
        if prev_table_type and prev_table_type != TableType.OTHER:
            return prev_table_type

        # 检查表名
        if table_title:
            if '附表' in table_title or '附录' in table_title:
                return TableType.APPENDIX

        # 检查表格内容是否有分期指标（TNM 分期表特征）
        staging_indicators = ['Ⅰ期', 'Ⅱ期', 'Ⅲ期', 'ⅣA期', 'ⅣB期', 'ⅣC期']
        for row in data[:5]:
            for cell in row:
                cell_str = str(cell or '')
                # 精确匹配分期指标（必须包含"期"）
                if any(indicator in cell_str for indicator in staging_indicators):
                    return TableType.APPENDIX

        # 检查跨页上下文中的附表标题行
        # 注意：目录中的"附表"引用不算（如"见附表一"），只有独立标题行才算
        for line in page_text.split('\n'):
            stripped = line.strip()
            if stripped.startswith('附表') or stripped.startswith('附录'):
                return TableType.APPENDIX

        return TableType.OTHER

    def _extract_table_title(self, page, table) -> str:
        """提取表格上方的表名（如"附表一 恶性肿瘤分期表"）

        Args:
            page: pdfplumber 页面对象
            table: pdfplumber 表格对象

        Returns:
            表名或空字符串
        """
        bbox = getattr(table, 'bbox', None)
        if not bbox:
            return ''

        table_top = bbox[1]  # y0
        chars = page.chars

        # 收集表格上方 50-80px 范围内的字符
        above_chars = [
            c for c in chars
            if c['top'] < table_top and c['top'] > table_top - 80
        ]

        if not above_chars:
            return ''

        # 按 y 坐标分组
        y_tolerance = 3.0
        lines_by_y: Dict[float, List[str]] = {}
        for c in above_chars:
            y_key = round(c['top'] / y_tolerance) * y_tolerance
            if y_key not in lines_by_y:
                lines_by_y[y_key] = []
            lines_by_y[y_key].append(c['text'])

        # 从最靠近表格的行开始，查找包含"附表"或表名特征的行
        sorted_y = sorted(lines_by_y.keys(), reverse=True)
        for y in sorted_y:
            line_text = ''.join(lines_by_y[y]).strip()
            if not line_text:
                continue
            # 检查是否为表名（包含"附表"或短标题行）
            if '附表' in line_text or '附录' in line_text:
                return line_text
            # 短行（< 30字）可能是表名
            if len(line_text) < 30 and not any(kw in line_text for kw in ['注', '说明', '本公司']):
                return line_text

        return ''
