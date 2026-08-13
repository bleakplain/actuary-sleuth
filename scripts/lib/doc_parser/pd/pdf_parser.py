#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

from dataclasses import dataclass, replace
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


@dataclass(frozen=True)
class _PdfImageCoverage:
    """PDF 图片完整性结果，只把仍可能承载正文的图片视为缺口。"""

    unreadable_pages: Tuple[int, ...] = ()
    unparsed_image_count: int = 0
    ignored_qr_image_count: int = 0


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
            records, image_coverage = self._extract_source_records(pdf.pages)
            content = assemble_numbered_content(records, self.detector)
            if (
                image_coverage.unparsed_image_count
                or image_coverage.ignored_qr_image_count
            ):
                content = replace(
                    content,
                    coverage_attestation=replace(
                        content.coverage_attestation,
                        coverage_attested=(
                            content.coverage_attestation.coverage_attested
                            and not image_coverage.unparsed_image_count
                        ),
                        coverage_attested_facts=(
                            ()
                            if image_coverage.unparsed_image_count
                            else content.coverage_attestation.coverage_attested_facts
                        ),
                        unreadable_pages=image_coverage.unreadable_pages,
                        unparsed_image_count=(
                            content.coverage_attestation.unparsed_image_count
                            + image_coverage.unparsed_image_count
                        ),
                        ignored_qr_image_count=(
                            content.coverage_attestation.ignored_qr_image_count
                            + image_coverage.ignored_qr_image_count
                        ),
                    ),
                    warnings=content.warnings,
                )
            if image_coverage.unparsed_image_count:
                content = replace(
                    content,
                    warnings=(
                        *content.warnings,
                        "PDF 存在无法确认是否承载条款原文的正文图像，"
                        "页面："
                        + "、".join(
                            str(page)
                            for page in image_coverage.unreadable_pages
                        )
                        + "；已禁用依赖全文零命中的负向推断",
                    ),
                )
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
            coverage_attested_facts=(
                content.coverage_attestation.coverage_attested_facts
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
    ) -> tuple[tuple[SourceRecord, ...], _PdfImageCoverage]:
        """把 PDF 页面转换为与 Word 相同的有序记录。

        被识别为表格的 bbox 会从普通文本行中过滤，避免表格正文重复进入
        条款和独立表格块。
        """
        records: list[SourceRecord] = []
        unreadable_pages: list[int] = []
        unparsed_image_count = 0
        ignored_qr_image_count = 0
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
                unresolved_count, qr_count = self._classify_page_images(page)
                if unresolved_count:
                    unreadable_pages.append(page_index + 1)
                unparsed_image_count += unresolved_count
                ignored_qr_image_count += qr_count
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
            unresolved_count, qr_count = self._classify_page_images(page)
            if unresolved_count:
                unreadable_pages.append(page_index + 1)
            unparsed_image_count += unresolved_count
            ignored_qr_image_count += qr_count
        return tuple(records), _PdfImageCoverage(
            unreadable_pages=tuple(unreadable_pages),
            unparsed_image_count=unparsed_image_count,
            ignored_qr_image_count=ignored_qr_image_count,
        )

    def _classify_page_images(self, page: Any) -> tuple[int, int]:
        """Return ``(unresolved, ignored_qr)`` for one page.

        Headers, footers and QR codes are outside the product-policy audit scope.
        Tiny image masks are layout artefacts. A large image is also safe when a
        substantial native text layer covers it; otherwise a body image remains
        unresolved because it may contain policy wording.
        """
        images = self._list_page_images(page)
        unresolved_count = 0
        ignored_qr_count = 0
        for image in images:
            bbox = self._image_bbox(image, page)
            if bbox is not None and self._is_qr_image(bbox, image, page):
                ignored_qr_count += 1
                continue
            if bbox is not None and self._is_margin_image(bbox, page):
                continue
            if bbox is not None and self._is_tiny_layout_image(bbox, image):
                continue
            if bbox is not None and self._native_text_covers_image(
                bbox, image, page,
            ):
                continue
            unresolved_count += 1
        return unresolved_count, ignored_qr_count

    @staticmethod
    def _list_page_images(page: Any) -> tuple[Dict[str, Any], ...]:
        images = getattr(page, "images", ())
        if images:
            return tuple(image for image in images if isinstance(image, dict))
        objects = getattr(page, "objects", {})
        if not isinstance(objects, dict):
            return ()
        return tuple(
            image
            for image in objects.get("image", ())
            if isinstance(image, dict)
        )

    @staticmethod
    def _image_bbox(
        image: Dict[str, Any],
        page: Any,
    ) -> Optional[Tuple[float, float, float, float]]:
        try:
            left = float(image["x0"])
            right = float(image["x1"])
            if "top" in image and "bottom" in image:
                top = float(image["top"])
                bottom = float(image["bottom"])
            else:
                page_height = float(page.height)
                top = page_height - float(image["y1"])
                bottom = page_height - float(image["y0"])
        except (KeyError, TypeError, ValueError):
            return None
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom

    def _is_qr_image(
        self,
        bbox: Tuple[float, float, float, float],
        image: Dict[str, Any],
        page: Any,
    ) -> bool:
        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top
        if not 24 <= min(width, height) or max(width, height) > 144:
            return False
        if max(width, height) / min(width, height) > 1.15:
            return False
        src_size = image.get("srcsize")
        if isinstance(src_size, (tuple, list)) and len(src_size) == 2:
            try:
                src_width = float(src_size[0])
                src_height = float(src_size[1])
            except (TypeError, ValueError):
                return False
            if (
                min(src_width, src_height) <= 0
                or max(src_width, src_height) / min(src_width, src_height)
                > 1.15
            ):
                return False
        rendered = self._render_image_luminance(page, bbox)
        return bool(
            rendered is not None
            and self._has_qr_finder_patterns(*rendered)
        )

    @staticmethod
    def _render_image_luminance(
        page: Any,
        bbox: Tuple[float, float, float, float],
    ) -> Optional[Tuple[int, int, Tuple[int, ...]]]:
        """Render only the image rectangle for an offline QR structure check."""
        try:
            rendered = page.crop(bbox).to_image(
                resolution=144,
                antialias=False,
            ).original.convert("L")
            width, height = rendered.size
            pixels = tuple(int(value) for value in rendered.getdata())
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0 or len(pixels) != width * height:
            return None
        return width, height, pixels

    @classmethod
    def _has_qr_finder_patterns(
        cls,
        width: int,
        height: int,
        luminance: Tuple[int, ...],
    ) -> bool:
        """Verify the three QR finder corners using the 1:1:3:1:1 pattern."""
        threshold = cls._otsu_threshold(luminance)
        bitmap = tuple(value <= threshold for value in luminance)
        horizontal = [0, 0, 0]
        vertical = [0, 0, 0]
        for y in range(height):
            centers = cls._finder_pattern_centers(
                bitmap[y * width:(y + 1) * width],
            )
            for x in centers:
                zone = cls._qr_corner_zone(x, y, width, height)
                if zone is not None:
                    horizontal[zone] += 1
        for x in range(width):
            centers = cls._finder_pattern_centers(tuple(
                bitmap[y * width + x]
                for y in range(height)
            ))
            for center_y in centers:
                zone = cls._qr_corner_zone(
                    x, center_y, width, height,
                )
                if zone is not None:
                    vertical[zone] += 1
        return bool(
            all(count >= 2 for count in horizontal)
            and all(count >= 2 for count in vertical)
        )

    @staticmethod
    def _otsu_threshold(values: Tuple[int, ...]) -> int:
        histogram = [0] * 256
        for value in values:
            histogram[max(0, min(255, value))] += 1
        total = len(values)
        total_sum = sum(
            value * count
            for value, count in enumerate(histogram)
        )
        background_weight = 0
        background_sum = 0
        best_threshold = 0
        best_variance = -1.0
        for value, count in enumerate(histogram):
            background_weight += count
            if not background_weight:
                continue
            foreground_weight = total - background_weight
            if not foreground_weight:
                break
            background_sum += value * count
            background_mean = background_sum / background_weight
            foreground_mean = (
                total_sum - background_sum
            ) / foreground_weight
            variance = (
                background_weight
                * foreground_weight
                * (background_mean - foreground_mean) ** 2
            )
            if variance > best_variance:
                best_variance = variance
                best_threshold = value
        return best_threshold

    @staticmethod
    def _finder_pattern_centers(
        line: Tuple[bool, ...],
    ) -> Tuple[float, ...]:
        if not line:
            return ()
        runs: list[Tuple[bool, int, int]] = []
        run_value = line[0]
        run_start = 0
        for index, value in enumerate(line[1:], 1):
            if value == run_value:
                continue
            runs.append((run_value, run_start, index - run_start))
            run_value = value
            run_start = index
        runs.append((run_value, run_start, len(line) - run_start))
        centers: list[float] = []
        for index in range(len(runs) - 4):
            candidate = runs[index:index + 5]
            if [run[0] for run in candidate] != [
                True, False, True, False, True,
            ]:
                continue
            widths = [run[2] for run in candidate]
            module_width = sum(widths) / 7
            if any(
                abs(widths[position] - module_width)
                > max(1.0, module_width * 0.8)
                for position in (0, 1, 3, 4)
            ):
                continue
            if abs(widths[2] - module_width * 3) > max(
                1.0, module_width * 1.2,
            ):
                continue
            centers.append(candidate[2][1] + candidate[2][2] / 2)
        return tuple(centers)

    @staticmethod
    def _qr_corner_zone(
        x: float,
        y: float,
        width: int,
        height: int,
    ) -> Optional[int]:
        if x < width * 0.45 and y < height * 0.45:
            return 0
        if x > width * 0.55 and y < height * 0.45:
            return 1
        if x < width * 0.45 and y > height * 0.55:
            return 2
        return None

    def _is_margin_image(
        self,
        bbox: Tuple[float, float, float, float],
        page: Any,
    ) -> bool:
        _, top, _, bottom = bbox
        page_height = float(page.height)
        return bool(
            bottom <= (
                page_height * self.header_footer_filter.header_region_ratio
            )
            or top >= page_height * (
                1 - self.header_footer_filter.footer_region_ratio
            )
        )

    @staticmethod
    def _is_tiny_layout_image(
        bbox: Tuple[float, float, float, float],
        image: Dict[str, Any],
    ) -> bool:
        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top
        return bool(
            max(width, height) <= 12
            or (
                image.get("imagemask") is True
                and min(width, height) <= 12
            )
        )

    @staticmethod
    def _native_text_covers_image(
        bbox: Tuple[float, float, float, float],
        image: Dict[str, Any],
        page: Any,
    ) -> bool:
        left, top, right, bottom = bbox
        image_width = right - left
        image_height = bottom - top
        page_area = max(float(page.width) * float(page.height), 1.0)
        if image_width * image_height < page_area * 0.2:
            return False
        covered_chars: list[Tuple[float, float, float, float]] = []
        for char in getattr(page, "chars", ()):
            try:
                char_left = float(char["x0"])
                char_right = float(char.get(
                    "x1", char_left + float(char.get("width", 0)),
                ))
                char_top = float(char["top"])
                char_bottom = float(char["bottom"])
            except (KeyError, TypeError, ValueError):
                continue
            center_x = (char_left + char_right) / 2
            center_y = (char_top + char_bottom) / 2
            if (
                left <= center_x <= right
                and top <= center_y <= bottom
                and str(char.get("text", "")).strip()
            ):
                covered_chars.append((
                    char_left, char_top, char_right, char_bottom,
                ))
        if len(covered_chars) < 100:
            return False
        text_left = min(char[0] for char in covered_chars)
        text_top = min(char[1] for char in covered_chars)
        text_right = max(char[2] for char in covered_chars)
        text_bottom = max(char[3] for char in covered_chars)
        occupied_cells = {
            (
                min(3, int(
                    ((char[0] + char[2]) / 2 - left)
                    / image_width * 4
                )),
                min(3, int(
                    ((char[1] + char[3]) / 2 - top)
                    / image_height * 4
                )),
            )
            for char in covered_chars
        }
        return bool(
            (text_right - text_left) / image_width >= 0.9
            and (text_bottom - text_top) / image_height >= 0.8
            and len(occupied_cells) >= 12
            and PdfParser._is_sparse_masked_decoration(image)
        )

    @staticmethod
    def _is_sparse_masked_decoration(image: Dict[str, Any]) -> bool:
        """Require explicit transparency and near-uniform pixels for artwork."""
        stream = image.get("stream")
        if stream is None:
            return False
        attributes = getattr(stream, "attrs", {})
        if not isinstance(attributes, dict) or not any(
            attributes.get(key) is not None
            for key in ("Mask", "SMask")
        ):
            return False
        try:
            data = stream.get_data()
        except (AttributeError, OSError, TypeError, ValueError):
            return False
        if not isinstance(data, bytes) or not data:
            return False
        stride = max(1, len(data) // 50000)
        counts: Dict[int, int] = {}
        sampled_count = 0
        for value in data[::stride]:
            counts[value] = counts.get(value, 0) + 1
            sampled_count += 1
        return bool(
            sampled_count
            and max(counts.values()) / sampled_count >= 0.97
        )

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
        if len(current_data[0]) != len(previous_header):
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
