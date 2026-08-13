#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文档解析器"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Set, Tuple, Union, cast

from docx import Document
from docx.parts.hdrftr import FooterPart, HeaderPart
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image

from ..models import (
    AuditDocument,
    DataTable,
    DocumentAnnotation,
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

_PURE_NAVIGATION_LINE_PATTERN = re.compile(
    r"^(?:请)?(?:"
    r"(?:扫码|扫一扫|扫描(?:上方|下方)?二维码)"
    r"(?:(?:查看(?:电子保单|电子条款|更多详情))|"
    r"(?:关注(?:微信公众号|公众号)))?"
    r"|二维码"
    r"|关注(?:微信公众号|公众号)"
    r"|查看(?:电子保单|电子条款|更多详情)"
    r"|扫描以查询验证条款"
    r")[。.!！；;,，：:]*$"
)
_NAVIGATION_IDENTIFIER_LINE_PATTERN = re.compile(
    r"^[\u3400-\u9fff]{2,20}[\[［]\d{4}[\]］]"
    r"[A-Za-z0-9\u3400-\u9fff（）().．·-]{2,40}"
    r"保险\d{3,6}号$"
)


@dataclass(frozen=True)
class _AuxiliaryTextEntry:
    identifier: str
    text: str
    has_unparsed_content: bool = False


@dataclass(frozen=True)
class _DocxSourceExtraction:
    records: Tuple[SourceRecord, ...]
    referenced_note_ids: Tuple[Tuple[str, str], ...]
    ignored_navigation_text_box_count: int = 0
    unparsed_text_box_count: int = 0


@dataclass(frozen=True)
class _ImageClassification:
    unresolved_count: int = 0
    ignored_qr_count: int = 0


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

        source = self._extract_source_records(doc)
        content = assemble_numbered_content(source.records, self.detector)
        annotations = self._extract_annotations(doc)
        ignored_header_footer_part_count = (
            self._count_nonempty_header_footer_parts(doc)
        )
        images = self._classify_embedded_images(doc)
        unparsed_auxiliary_part_count = self._count_unparsed_auxiliary_parts(
            doc,
            referenced_note_ids=set(source.referenced_note_ids),
        )
        if any((
            source.unparsed_text_box_count,
            images.unresolved_count,
            unparsed_auxiliary_part_count,
        )):
            omitted_kinds = []
            if source.unparsed_text_box_count:
                omitted_kinds.append(
                    f"{source.unparsed_text_box_count} 个未完整解析的文本框"
                )
            if images.unresolved_count:
                omitted_kinds.append(
                    f"{images.unresolved_count} 个可能承载正文的嵌入图像"
                )
            if unparsed_auxiliary_part_count:
                omitted_kinds.append(
                    f"{unparsed_auxiliary_part_count} 个未完整解析的正文辅助部件"
                )
            content = replace(
                content,
                coverage_attestation=replace(
                    content.coverage_attestation,
                    coverage_attested=False,
                    coverage_attested_facts=(),
                    unparsed_text_box_count=source.unparsed_text_box_count,
                    unparsed_image_count=images.unresolved_count,
                    unparsed_auxiliary_part_count=(
                        unparsed_auxiliary_part_count
                    ),
                    ignored_header_footer_part_count=(
                        ignored_header_footer_part_count
                    ),
                    ignored_qr_image_count=images.ignored_qr_count,
                    ignored_navigation_text_box_count=(
                        source.ignored_navigation_text_box_count
                    ),
                ),
                warnings=(
                    *content.warnings,
                    "Word 文档含 " + "、".join(omitted_kinds) + "，"
                    "当前未能证明这些内容不承载条款原文；"
                    "已禁用依赖全文零命中的负向推断",
                ),
            )
        else:
            content = replace(
                content,
                coverage_attestation=replace(
                    content.coverage_attestation,
                    ignored_header_footer_part_count=(
                        ignored_header_footer_part_count
                    ),
                    ignored_qr_image_count=images.ignored_qr_count,
                    ignored_navigation_text_box_count=(
                        source.ignored_navigation_text_box_count
                    ),
                ),
            )
        ignored_kinds = []
        if ignored_header_footer_part_count:
            ignored_kinds.append(
                f"{ignored_header_footer_part_count} 个页眉/页脚部件"
            )
        if images.ignored_qr_count:
            ignored_kinds.append(f"{images.ignored_qr_count} 个二维码")
        if source.ignored_navigation_text_box_count:
            ignored_kinds.append(
                f"{source.ignored_navigation_text_box_count} 个二维码导航文本框"
            )
        if ignored_kinds:
            content = replace(
                content,
                warnings=(
                    *content.warnings,
                    "已按审核范围忽略 " + "、".join(ignored_kinds),
                ),
            )
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
            annotations=annotations,
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

    def _extract_source_records(self, doc) -> _DocxSourceExtraction:
        """按正文顺序读取段落、表格、文本框及被引用的脚注/尾注。"""
        records: list[SourceRecord] = []
        notes = self._extract_note_entries(doc)
        emitted_notes: set[tuple[str, str]] = set()
        referenced_note_ids: list[tuple[str, str]] = []
        ignored_navigation_text_box_count = 0
        unparsed_text_box_count = 0
        alternate_text_boxes: set[tuple[str, str]] = set()
        ordinary_text = self._ordinary_document_text(doc)
        order = 0
        paragraph_index = 0
        table_index = 0
        parent = doc._body

        def emit_referenced_notes(
            element,
            *,
            paragraph_location: Optional[int] = None,
            table_location: Optional[int] = None,
            row_location: Optional[int] = None,
        ) -> None:
            nonlocal order
            for note_kind, note_id in self._list_note_references(element):
                reference = (note_kind, note_id)
                referenced_note_ids.append(reference)
                entry = notes.get(reference)
                if entry is None or reference in emitted_notes:
                    continue
                emitted_notes.add(reference)
                records.append(SourceRecord(
                    order=order,
                    kind=SourceRecordKind.AUXILIARY_TEXT,
                    fields=(
                        f"【{self._note_label(note_kind)} {note_id}】"
                        f"{entry.text}",
                    ),
                    paragraph_index=paragraph_location,
                    table_index=table_location,
                    row_index=row_location,
                ))
                order += 1

        def emit_text_box_records(
            box_text: str,
            *,
            paragraph_location: Optional[int] = None,
            table_location: Optional[int] = None,
        ) -> None:
            nonlocal order
            for line in box_text.splitlines():
                if not line.strip():
                    continue
                records.append(SourceRecord(
                    order=order,
                    kind=SourceRecordKind.TEXT,
                    fields=(line.strip(),),
                    paragraph_index=paragraph_location,
                    table_index=table_location,
                ))
                order += 1

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
                # 先跟随引用段落发射脚注，避免后续文本框改变归属。
                emit_referenced_notes(
                    element,
                    paragraph_location=paragraph_index,
                )
                for text_box in element.xpath(".//w:txbxContent"):
                    box_text = self._extract_xml_text(text_box)
                    if not box_text:
                        continue
                    alternate_key = self._alternate_text_box_key(
                        text_box, box_text,
                    )
                    if (
                        alternate_key is not None
                        and alternate_key in alternate_text_boxes
                    ):
                        continue
                    if alternate_key is not None:
                        alternate_text_boxes.add(alternate_key)
                    if self._is_pure_navigation_text_box(box_text):
                        ignored_navigation_text_box_count += 1
                        continue
                    if self._is_redundant_navigation_text_box(
                        box_text, ordinary_text,
                    ):
                        ignored_navigation_text_box_count += 1
                        continue
                    emit_text_box_records(
                        box_text,
                        paragraph_location=paragraph_index,
                    )
                    if self._xml_has_nontext_content(text_box):
                        unparsed_text_box_count += 1
                paragraph_index += 1
                continue
            if element_type == "txbxContent":
                box_text = self._extract_xml_text(element)
                if box_text:
                    if self._is_pure_navigation_text_box(box_text):
                        ignored_navigation_text_box_count += 1
                    elif self._is_redundant_navigation_text_box(
                        box_text, ordinary_text,
                    ):
                        ignored_navigation_text_box_count += 1
                    else:
                        emit_text_box_records(
                            box_text,
                            paragraph_location=paragraph_index,
                        )
                paragraph_index += 1
                continue
            if element_type != "tbl":
                continue
            table = Table(element, parent)
            table_rows = tuple(table.rows)
            rows = tuple(_unique_row_values(row) for row in table_rows)
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
                    emit_referenced_notes(
                        table_rows[row_index]._tr,
                        table_location=table_index,
                        row_location=row_index,
                    )
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
                emit_referenced_notes(
                    element,
                    table_location=table_index,
                )
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
                    emit_referenced_notes(
                        table_rows[row_index]._tr,
                        table_location=table_index,
                        row_location=row_index,
                    )
            for text_box in element.xpath(".//w:txbxContent"):
                box_text = self._extract_xml_text(text_box)
                if not box_text:
                    continue
                alternate_key = self._alternate_text_box_key(text_box, box_text)
                if (
                    alternate_key is not None
                    and alternate_key in alternate_text_boxes
                ):
                    continue
                if alternate_key is not None:
                    alternate_text_boxes.add(alternate_key)
                if self._is_pure_navigation_text_box(box_text):
                    ignored_navigation_text_box_count += 1
                    continue
                if self._is_redundant_navigation_text_box(
                    box_text, ordinary_text,
                ):
                    ignored_navigation_text_box_count += 1
                    continue
                emit_text_box_records(
                    box_text,
                    table_location=table_index,
                )
                if self._xml_has_nontext_content(text_box):
                    unparsed_text_box_count += 1
            table_index += 1
        return _DocxSourceExtraction(
            records=tuple(records),
            referenced_note_ids=tuple(referenced_note_ids),
            ignored_navigation_text_box_count=(
                ignored_navigation_text_box_count
            ),
            unparsed_text_box_count=unparsed_text_box_count,
        )

    @staticmethod
    def _extract_xml_text(element) -> str:
        paragraphs: list[str] = []
        for paragraph in element.iter():
            if paragraph.tag.rsplit("}", 1)[-1] != "p":
                continue
            text = "".join(
                str(node.text or "")
                for node in paragraph.iter()
                if node.tag.rsplit("}", 1)[-1] in {"t", "instrText"}
            ).strip()
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n".join(paragraphs)
        return "".join(
            str(node.text or "")
            for node in element.iter()
            if node.tag.rsplit("}", 1)[-1] in {"t", "instrText"}
        ).strip()

    @staticmethod
    def _is_pure_navigation_text_box(text: str) -> bool:
        """只忽略纯扫码/查询导航提示。

        严格逐行全匹配是安全边界：同一文本框只要还有条款编号或
        其他实质文字，就必须保留整个文本框。
        """
        lines = [
            re.sub(r"\s+", "", line)
            for line in text.splitlines()
            if line.strip()
        ]
        navigation_flags = tuple(
            bool(_PURE_NAVIGATION_LINE_PATTERN.fullmatch(line))
            for line in lines
        )
        return bool(lines) and any(navigation_flags) and all(
            navigation
            or bool(_NAVIGATION_IDENTIFIER_LINE_PATTERN.fullmatch(line))
            for line, navigation in zip(lines, navigation_flags)
        )

    @staticmethod
    def _ordinary_document_text(doc) -> str:
        values = [paragraph.text.strip() for paragraph in doc.paragraphs]
        for table in doc.tables:
            values.extend(
                cell.strip()
                for row in (_unique_row_values(item) for item in table.rows)
                for cell in row
                if cell.strip()
            )
        return "\n".join(value for value in values if value)

    @staticmethod
    def _is_redundant_navigation_text_box(
        text: str,
        ordinary_text: str,
    ) -> bool:
        """仅在目录项可逐项由正式正文印证时忽略目录导航框。"""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        navigation_lines = (
            lines[1:]
            if lines and lines[0] in {"目录", "条款目录"}
            else lines
        )
        entries: list[tuple[str, str]] = []
        unmatched_lines: list[str] = []
        for line in navigation_lines:
            match = re.match(
                r"^(\d+(?:[.．]\d+)+)\s+(.+?)(?:\s+\d+)?$",
                line,
            )
            if match:
                entries.append((
                    match.group(1).replace("．", "."),
                    match.group(2).strip(),
                ))
            else:
                unmatched_lines.append(line)
        chapter_headings_only = all(
            re.fullmatch(r"\d+[.．]\s*[^\d\s].*", line)
            for line in unmatched_lines
        )
        if (
            len(entries) < 3
            or len(entries) + len(unmatched_lines) != len(navigation_lines)
            or not chapter_headings_only
        ):
            return False
        normalized_body = re.sub(r"\s+", "", ordinary_text)
        return all(
            re.sub(r"\s+", "", number) in normalized_body
            and re.sub(r"\s+", "", title) in normalized_body
            for number, title in entries
        )

    @staticmethod
    def _alternate_text_box_key(
        text_box,
        text: str,
    ) -> Optional[Tuple[str, str]]:
        ancestor = text_box.getparent()
        while ancestor is not None:
            if ancestor.tag.rsplit("}", 1)[-1] == "AlternateContent":
                # lxml may create more than one Python proxy for the same XML
                # node, so ``id(ancestor)`` is not a stable logical identity.
                return ancestor.getroottree().getpath(ancestor), text
            ancestor = ancestor.getparent()
        return None

    @staticmethod
    def _note_label(note_kind: str) -> str:
        return "脚注" if note_kind == "footnote" else "尾注"

    @staticmethod
    def _list_note_references(element) -> Tuple[Tuple[str, str], ...]:
        references: list[tuple[str, str]] = []
        reference_tags = {
            "footnoteReference": "footnote",
            "endnoteReference": "endnote",
        }
        for node in element.iter():
            kind = reference_tags.get(node.tag.rsplit("}", 1)[-1])
            if kind is None:
                continue
            identifier = next((
                value for key, value in node.attrib.items()
                if key.rsplit("}", 1)[-1] == "id"
            ), "")
            if identifier and identifier not in {"-1", "0"}:
                references.append((kind, identifier))
        return tuple(references)

    @classmethod
    def _extract_note_entries(
        cls,
        doc,
    ) -> Mapping[Tuple[str, str], _AuxiliaryTextEntry]:
        entries: Dict[Tuple[str, str], _AuxiliaryTextEntry] = {}
        for part in doc.part.package.parts:
            part_name = str(part.partname).lower()
            kind = (
                "footnote" if part_name == "/word/footnotes.xml"
                else "endnote" if part_name == "/word/endnotes.xml"
                else ""
            )
            if not kind:
                continue
            try:
                root = ET.fromstring(part.blob)
            except ET.ParseError:
                continue
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != kind:
                    continue
                identifier = next((
                    value for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "id"
                ), "")
                if identifier in {"", "-1", "0"}:
                    continue
                entries[(kind, identifier)] = _AuxiliaryTextEntry(
                    identifier=identifier,
                    text=cls._extract_xml_text(node),
                    has_unparsed_content=cls._xml_has_nontext_content(node),
                )
        return entries

    @classmethod
    def _classify_embedded_images(
        cls,
        doc,
    ) -> _ImageClassification:
        logical_images: Dict[Tuple[str, str], Tuple[bytes, bool]] = {}
        missing_image_count = 0
        for node in doc.element.body.iter():
            if node.tag.rsplit("}", 1)[-1] not in {"blip", "imagedata"}:
                continue
            if not cls._is_selected_alternate_content_branch(node):
                continue
            relationship_id = cls._image_relationship_id(node)
            relationship = (
                doc.part.rels.get(relationship_id)
                if relationship_id
                else None
            )
            blob = b""
            if relationship is not None and not relationship.is_external:
                blob = getattr(relationship.target_part, "blob", b"")
            container = cls._logical_image_container(node)
            if not relationship_id and not blob:
                missing_image_count += 1
                continue
            payload_key = (
                sha256(blob).hexdigest()
                if blob
                else f"relationship:{relationship_id}"
            )
            container_path = container.getroottree().getpath(container)
            key = (container_path, payload_key)
            navigation_context = cls._has_navigation_text_box_context(node)
            previous = logical_images.get(key)
            logical_images[key] = (
                blob or (previous[0] if previous else b""),
                navigation_context or (previous[1] if previous else False),
            )
        unresolved_count = 0
        ignored_qr_count = 0
        for blob, navigation_context in logical_images.values():
            if navigation_context or cls._is_qr_image(blob):
                ignored_qr_count += 1
            else:
                unresolved_count += 1
        return _ImageClassification(
            unresolved_count=unresolved_count + missing_image_count,
            ignored_qr_count=ignored_qr_count,
        )

    @staticmethod
    def _logical_image_container(node):
        """把 Choice/Fallback 表示视为一个图像对象，避免重复计数。"""
        ancestor = node.getparent()
        drawing_container = node
        while ancestor is not None:
            name = ancestor.tag.rsplit("}", 1)[-1]
            if name == "AlternateContent":
                return ancestor
            if name in {"drawing", "pict"}:
                drawing_container = ancestor
            ancestor = ancestor.getparent()
        return drawing_container

    @staticmethod
    def _is_selected_alternate_content_branch(node) -> bool:
        """解析器可读取现代 Choice，因此不再同时遍历兼容 Fallback。"""
        ancestor = node.getparent()
        branch = None
        while ancestor is not None:
            name = ancestor.tag.rsplit("}", 1)[-1]
            if name in {"Choice", "Fallback"}:
                branch = ancestor
            if name == "AlternateContent":
                choices = [
                    child for child in ancestor
                    if child.tag.rsplit("}", 1)[-1] == "Choice"
                ]
                fallback = next((
                    child for child in ancestor
                    if child.tag.rsplit("}", 1)[-1] == "Fallback"
                ), None)
                selected = choices[0] if choices else fallback
                if (
                    branch is None
                    or selected is None
                    or branch.getroottree().getpath(branch)
                    != selected.getroottree().getpath(selected)
                ):
                    return False
                branch = None
            ancestor = ancestor.getparent()
        return True

    @classmethod
    def _has_navigation_text_box_context(cls, node) -> bool:
        """只有与纯导航提示共处一个文本框的图片才走豁免。"""
        ancestor = node.getparent()
        while ancestor is not None:
            if ancestor.tag.rsplit("}", 1)[-1] == "txbxContent":
                return cls._is_pure_navigation_text_box(
                    cls._extract_xml_text(ancestor),
                )
            ancestor = ancestor.getparent()
        return False

    @staticmethod
    def _image_relationship_id(node) -> str:
        return next((
            value for key, value in node.attrib.items()
            if key.rsplit("}", 1)[-1] in {"embed", "link", "id"}
        ), "")

    @staticmethod
    def _open_image(blob: bytes) -> Optional[Image.Image]:
        if not blob:
            return None
        try:
            image = Image.open(BytesIO(blob))
            image.load()
            return image
        except (OSError, ValueError):
            return None

    @classmethod
    def _is_qr_image(cls, blob: bytes) -> bool:
        image = cls._open_image(blob)
        if image is None:
            return False
        width, height = image.size
        if width != height or not 21 <= width <= 1024:
            return False
        grayscale = image.convert("L")
        extrema = grayscale.getextrema()
        if not (
            isinstance(extrema, tuple)
            and len(extrema) == 2
            and isinstance(extrema[0], (int, float))
            and isinstance(extrema[1], (int, float))
        ) or extrema[1] - extrema[0] < 96:
            return False
        binary = grayscale.point(lambda value: 0 if value < 128 else 255)
        pixels = binary.load()
        if pixels is None:
            return False
        horizontal_hits = [
            (center, y)
            for y in range(height)
            for center in cls._finder_pattern_centers(
                tuple(cast(int, pixels[x, y]) < 128 for x in range(width))
            )
        ]
        vertical_hits = [
            (x, center)
            for x in range(width)
            for center in cls._finder_pattern_centers(
                tuple(cast(int, pixels[x, y]) < 128 for y in range(height))
            )
        ]
        corner_regions = (
            lambda x, y: x < width * 0.45 and y < height * 0.45,
            lambda x, y: x > width * 0.55 and y < height * 0.45,
            lambda x, y: x < width * 0.45 and y > height * 0.55,
        )
        return all(
            any(region(x, y) for x, y in horizontal_hits)
            and any(region(x, y) for x, y in vertical_hits)
            for region in corner_regions
        )

    @staticmethod
    def _finder_pattern_centers(values: Tuple[bool, ...]) -> Tuple[float, ...]:
        """识别二维码定位框横截面的黑白黑白黑 ``1:1:3:1:1`` 比例。"""
        if not values:
            return ()
        runs: list[tuple[bool, int, int]] = []
        start = 0
        current = values[0]
        for index, value in enumerate(values[1:], start=1):
            if value == current:
                continue
            runs.append((current, start, index - start))
            current = value
            start = index
        runs.append((current, start, len(values) - start))
        centers: list[float] = []
        expected = (1.0, 1.0, 3.0, 1.0, 1.0)
        for index in range(len(runs) - 4):
            window = runs[index:index + 5]
            if tuple(color for color, _, _ in window) != (
                True, False, True, False, True,
            ):
                continue
            total = sum(length for _, _, length in window)
            module = total / 7.0
            if module < 1.0:
                continue
            outer_lengths = tuple(
                window[position][2] for position in (0, 1, 3, 4)
            )
            central_length = window[2][2]
            if central_length < 2.2 * max(outer_lengths):
                continue
            if not all(
                abs(length - module * ratio)
                <= max(0.75, module * ratio * 0.35)
                for (_, _, length), ratio in zip(window, expected)
            ):
                continue
            _, central_start, central_length = window[2]
            centers.append(central_start + central_length / 2.0)
        return tuple(centers)

    @staticmethod
    def _count_nonempty_header_footer_parts(doc) -> int:
        """统计被排除在产品条款审核范围外的非空页眉页脚。"""
        parts = {
            id(relationship.target_part): relationship.target_part
            for relationship in doc.part.rels.values()
            if not relationship.is_external
            and isinstance(relationship.target_part, (HeaderPart, FooterPart))
        }
        return sum(
            DocxParser._header_footer_part_has_content(part)
            for part in parts.values()
        )

    @staticmethod
    def _header_footer_part_has_content(
        part: Union[HeaderPart, FooterPart],
    ) -> bool:
        element = part.element
        if any(
            str(node.text or "").strip()
            for node in element.iter()
            if node.tag.rsplit("}", 1)[-1] in {"t", "instrText"}
        ):
            return True
        content_tags = {
            "tbl", "drawing", "pict", "object", "fldSimple", "fldChar",
            "sdt", "tab", "br", "cr", "sym",
        }
        return any(
            node.tag.rsplit("}", 1)[-1] in content_tags
            for node in element.iter()
        )

    @staticmethod
    def _count_unparsed_auxiliary_parts(
        doc,
        *,
        referenced_note_ids: Set[Tuple[str, str]],
    ) -> int:
        """只统计仍可能承载正式正文、且未进入审核文本的 OOXML part。"""
        notes = DocxParser._extract_note_entries(doc)
        count = 0
        for reference in referenced_note_ids:
            entry = notes.get(reference)
            if entry is None or not entry.text or entry.has_unparsed_content:
                count += 1
        for part in doc.part.package.parts:
            part_name = str(part.partname).lower()
            if part_name in {"/word/footnotes.xml", "/word/endnotes.xml"}:
                continue
            if part_name.startswith("/word/comments"):
                continue
            if (
                DocxParser._is_unparsed_auxiliary_part(part_name)
                and DocxParser._auxiliary_part_has_content(part_name, part.blob)
            ):
                count += 1
        return count

    @classmethod
    def _extract_annotations(cls, doc) -> Tuple[DocumentAnnotation, ...]:
        """保留批注供人工追溯，但不把批注意见当成正式保险条款正文。"""
        range_start_by_comment: Dict[str, int] = {}
        range_end_by_comment: Dict[str, int] = {}
        reference_by_comment: Dict[str, int] = {}
        paragraphs = (
            node for node in doc.element.body.iter()
            if node.tag.rsplit("}", 1)[-1] == "p"
        )
        marker_targets = {
            "commentRangeStart": range_start_by_comment,
            "commentRangeEnd": range_end_by_comment,
            "commentReference": reference_by_comment,
        }
        for paragraph_index, paragraph in enumerate(paragraphs):
            for node in paragraph.iter():
                target = marker_targets.get(node.tag.rsplit("}", 1)[-1])
                if target is None:
                    continue
                identifier = next((
                    value for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "id"
                ), "")
                if identifier:
                    target.setdefault(identifier, paragraph_index)
        annotations: list[DocumentAnnotation] = []
        for part in doc.part.package.parts:
            part_name = str(part.partname).lower()
            if not part_name.startswith("/word/comments"):
                continue
            try:
                root = ET.fromstring(part.blob)
            except ET.ParseError:
                continue
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "comment":
                    continue
                identifier = next((
                    value for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "id"
                ), "")
                author = next((
                    value for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "author"
                ), "").strip() or None
                created_at = next((
                    value for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "date"
                ), "").strip() or None
                text = cls._extract_xml_text(node)
                if not identifier or not text:
                    continue
                anchor_start = range_start_by_comment.get(identifier)
                anchor_end = range_end_by_comment.get(identifier)
                reference = reference_by_comment.get(identifier)
                if anchor_start is None and anchor_end is None:
                    anchor_start = reference
                    anchor_end = reference
                anchor_paragraph_index = (
                    anchor_start
                    if anchor_start is not None
                    else anchor_end
                    if anchor_end is not None
                    else reference
                )
                annotations.append(DocumentAnnotation(
                    kind="comment",
                    annotation_id=identifier,
                    text=text,
                    author=author,
                    created_at=created_at,
                    anchor_start_paragraph_index=anchor_start,
                    anchor_end_paragraph_index=anchor_end,
                    paragraph_index=anchor_paragraph_index,
                ))
        return tuple(annotations)

    @staticmethod
    def _is_unparsed_auxiliary_part(part_name: str) -> bool:
        return (
            part_name in {"/word/footnotes.xml", "/word/endnotes.xml"}
            or part_name.startswith("/word/comments")
            or part_name == "/word/glossary/document.xml"
            or (
                part_name.startswith("/customxml/item")
                and "itemprops" not in part_name
            )
            or part_name.startswith("/word/embeddings/")
            or part_name.startswith("/word/activex/")
            or part_name.startswith("/word/diagrams/")
            or part_name.startswith("/word/drawings/")
        )

    @staticmethod
    def _auxiliary_part_has_content(part_name: str, blob: bytes) -> bool:
        if not blob:
            return False
        if part_name.startswith(("/word/embeddings/", "/word/activex/")):
            return True
        try:
            root = ET.fromstring(blob)
        except ET.ParseError:
            return True

        container_tag = (
            "footnote"
            if part_name == "/word/footnotes.xml"
            else "endnote"
            if part_name == "/word/endnotes.xml"
            else ""
        )
        if container_tag:
            entries = (
                node
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == container_tag
                and next((
                    value
                    for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "id"
                ), "") not in {"-1", "0"}
            )
            return any(
                DocxParser._xml_element_has_content(node)
                for node in entries
            )
        return DocxParser._xml_element_has_content(root)

    @staticmethod
    def _xml_element_has_content(element: ET.Element) -> bool:
        if any(str(text).strip() for text in element.itertext()):
            return True
        content_tags = {
            "tbl", "drawing", "pict", "object", "blip", "imagedata",
            "fldSimple", "fldChar", "sdt", "sym",
        }
        return any(
            node.tag.rsplit("}", 1)[-1] in content_tags
            for node in element.iter()
        )

    @staticmethod
    def _xml_has_nontext_content(element: ET.Element) -> bool:
        content_tags = {
            "tbl", "drawing", "pict", "object", "blip", "imagedata",
        }
        return any(
            node.tag.rsplit("}", 1)[-1] in content_tags
            for node in element.iter()
        )

    @staticmethod
    def _is_structured_data_table(
        rows: tuple[tuple[str, ...], ...],
    ) -> bool:
        return bool(
            len(rows) >= 2
            and rows
            and sum(bool(cell.strip()) for cell in rows[0]) >= 2
        )
