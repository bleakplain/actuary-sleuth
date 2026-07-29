"""按原文顺序和条款编号组装产品审核块。

编号是普通条款的唯一边界信号。段落、表格行和 PDF 行只负责提供
阅读顺序与来源定位，不能单独触发条款切分。
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from ..models import (
    Clause,
    CoverageAttestation,
    DataTable,
    DocumentSection,
    SectionType,
    TableType,
)
from .clause_tagger import tag_clause_topics
from .section_detector import SectionDetector
from .utils import split_title_and_content


class SourceRecordKind(str, Enum):
    TEXT = "text"
    TABLE_ROW = "table_row"
    DATA_TABLE = "data_table"


@dataclass(frozen=True)
class SourceRecord:
    """格式无关的有序原文记录。"""

    order: int
    kind: SourceRecordKind
    fields: Tuple[str, ...] = ()
    page_number: Optional[int] = None
    paragraph_index: Optional[int] = None
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    numbering_stream: bool = False
    data_table: Optional[DataTable] = None

    @property
    def text(self) -> str:
        return "\n".join(field.strip() for field in self.fields if field.strip())


@dataclass(frozen=True)
class NumberedContent:
    clauses: Tuple[Clause, ...]
    tables: Tuple[DataTable, ...]
    unclassified_sections: Tuple[DocumentSection, ...]
    notices: Tuple[DocumentSection, ...]
    health_disclosures: Tuple[DocumentSection, ...]
    exclusions: Tuple[DocumentSection, ...]
    rider_clauses: Tuple[Clause, ...]
    coverage_attestation: CoverageAttestation
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class _NumberMarker:
    number: str
    parts: Tuple[int, ...]
    payload: Tuple[str, ...]


@dataclass
class _ClauseBuilder:
    number: str
    parts: Tuple[int, ...]
    title: str
    lines: list[str]
    start_order: int
    end_order: int
    page_number: Optional[int]
    end_page_number: Optional[int]
    table_index: Optional[int]


@dataclass
class _SectionBuilder:
    section_type: SectionType
    title: str
    lines: list[str]
    start_order: int
    end_order: int
    role: str = ""


_EXACT_NUMBER = re.compile(r"^(\d+(?:[.．]\d+)*)(?:[.．])?$")
_INLINE_NUMBER = re.compile(
    r"^(\d+(?:[.．]\d+)*)(?:[.．])?[\s\u3000]+(.+)$",
)
_MEASUREMENT_PAYLOAD_PREFIX = re.compile(
    r"^(?:"
    r"(?:人民币\s*)?(?:\d[\d,，]*(?:[.．]\d+)?\s*)?"
    r"(?:亿元|万元|千元|百元|元|角|分|美元|港元)"
    r"|(?:\d[\d,，]*(?:[.．]\d+)?\s*)?(?:%|％|‰|百分点)"
    r"|(?:\d[\d,，]*(?:[.．]\d+)?\s*)?"
    r"(?:周岁|岁|年|个月|月|日|天|小时|分钟|秒)"
    r"|(?:\d[\d,，]*(?:[.．]\d+)?\s*)?(?:次|人|份|件|倍(?:数)?)"
    r"|(?:\d[\d,，]*(?:[.．]\d+)?\s*)?"
    r"(?:毫米|厘米|公里|平方米|千克|公斤|米|克)"
    r")"
    r"(?=$|[\s（(、，,。；;：:]|以下|以上|以内|以外|不满|超过|至|到|为|按|的)"
)
_ROOT_TITLE_CHARACTER = re.compile(r"[A-Za-z\u3400-\u9fff]")
_APPENDIX_HEADING = re.compile(
    r"^(?:附表|附录)\s*[一二三四五六七八九十百\d]+[：:]?(?:\s*.*)?$",
)


def normalize_clause_number(value: str) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """规范十进制层级编号；内部清单编号如 ``1）`` 不会匹配。

    条款层级必须从正整数开始。以零开头的 ``0.8`` 是数值而不是
    产品条款层级，不能仅因包含小数点就成为切块边界。
    """
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    match = _EXACT_NUMBER.fullmatch(normalized)
    if not match:
        return None
    raw_parts = match.group(1).replace("．", ".").split(".")
    parts = tuple(int(part) for part in raw_parts)
    if not parts or parts[0] == 0:
        return None
    return ".".join(str(part) for part in parts), parts


def is_numbering_table_rows(rows: Sequence[Sequence[str]]) -> bool:
    """只有形成层级序列的表格才作为条款编号流。

    两段数字（如 ``1.5``）既可能是条款号，也可能是费率或金额，单凭
    小数点无法消除歧义。因此表格必须具有明确的“条款编号”表头，或
    出现至少三级编号/祖先-后代前缀关系，才会被认定为编号流。
    """
    markers = [
        normalize_clause_number(row[0])
        for row in rows
        if row and row[0].strip()
    ]
    present = [marker for marker in markers if marker is not None]
    header = " ".join(rows[0]) if rows else ""
    explicit_clause_header = "条款" in header and "编号" in header
    if explicit_clause_header and present:
        return True
    parts_set = {parts for _, parts in present}
    if any(len(parts) >= 3 for parts in parts_set):
        return True
    return any(
        len(ancestor) < len(descendant)
        and descendant[:len(ancestor)] == ancestor
        for ancestor in parts_set
        for descendant in parts_set
    )


def _raw_marker(record: SourceRecord) -> Optional[_NumberMarker]:
    if record.kind is SourceRecordKind.DATA_TABLE or not record.fields:
        return None
    first = unicodedata.normalize("NFKC", record.fields[0] or "").strip()
    exact = normalize_clause_number(first)
    if exact is not None:
        number, parts = exact
        payload = tuple(
            field.strip()
            for field in record.fields[1:]
            if field.strip() and normalize_clause_number(field.strip()) != exact
        )
        if (
            payload
            and not record.numbering_stream
            and _is_measurement_payload(payload)
        ):
            return None
        return _NumberMarker(number=number, parts=parts, payload=payload)
    if record.kind is not SourceRecordKind.TEXT:
        return None
    match = _INLINE_NUMBER.match(first)
    if not match:
        return None
    normalized = normalize_clause_number(match.group(1))
    if normalized is None:
        return None
    number, parts = normalized
    payload = (
        match.group(2).strip(),
        *tuple(field.strip() for field in record.fields[1:] if field.strip()),
    )
    if _is_measurement_payload(payload):
        return None
    return _NumberMarker(number=number, parts=parts, payload=payload)


def _is_measurement_payload(payload: Sequence[str]) -> bool:
    """识别“数值 + 单位/比例”的行首，避免把小数值当层级编号。

    ``1.5`` 本身有语义歧义；只有紧随货币单位、比例或倍数时才能确定
    它是测量值。其他文本（如 ``1.5 保证续保``）仍交给层级上下文判断。
    """
    first = unicodedata.normalize("NFKC", payload[0] or "").strip()
    return bool(_MEASUREMENT_PAYLOAD_PREFIX.match(first))


def _marker_has_root_title(marker: _NumberMarker) -> bool:
    title = " ".join(
        value.strip() for value in marker.payload if value.strip()
    )
    return bool(
        title
        and _ROOT_TITLE_CHARACTER.search(title)
        and not _is_measurement_payload(marker.payload)
    )


def _root_only_sequence_orders(
    records: Sequence[SourceRecord],
    candidates: dict[int, _NumberMarker],
) -> Tuple[int, ...]:
    """确认没有子编号时的一级章节序列。

    单个 ``1 标题`` 与正文列表无法区分，因此只接受 TEXT 来源中从
    1 开始、至少三项、严格递增且每项都有文字标题的纯一级序列。
    任一多级编号候选存在时继续使用既有父子关系规则；金额、比例、
    年龄等数值行在形成候选前即被排除。
    """
    items = sorted(candidates.items())
    records_by_order = {record.order: record for record in records}
    if (
        len(items) < 3
        or any(len(marker.parts) != 1 for _, marker in items)
        or any(
            records_by_order[order].kind is not SourceRecordKind.TEXT
            for order, _ in items
        )
        or any(not _marker_has_root_title(marker) for _, marker in items)
    ):
        return ()
    numbers = tuple(marker.parts[0] for _, marker in items)
    if numbers[0] != 1 or any(
        current <= previous
        for previous, current in zip(numbers, numbers[1:])
    ):
        return ()
    return tuple(order for order, _ in items)


def _accepted_markers(
    records: Sequence[SourceRecord],
) -> dict[int, _NumberMarker]:
    candidates = {
        record.order: marker
        for record in records
        if (marker := _raw_marker(record)) is not None
    }
    accepted: dict[int, _NumberMarker] = {}
    by_order = {record.order: record for record in records}
    candidate_items = sorted(candidates.items())
    root_orders: dict[int, int] = {}
    for order in _root_only_sequence_orders(records, candidates):
        marker = candidates[order]
        root_orders.setdefault(marker.parts[0], order)
    for index, (order, marker) in enumerate(candidate_items):
        record = by_order[order]
        if len(marker.parts) > 1:
            continue
        if record.numbering_stream:
            root_orders.setdefault(marker.parts[0], order)
            continue
        if any(
            "条款编号" in by_order[prior_order].text
            for prior_order in range(max(0, order - 3), order)
            if prior_order in by_order
        ):
            root_orders.setdefault(marker.parts[0], order)
            continue
        for _, later in candidate_items[index + 1:]:
            if len(later.parts) == 1:
                break
            if later.parts[0] == marker.parts[0]:
                root_orders.setdefault(marker.parts[0], order)
                break
    for order, marker in candidate_items:
        record = by_order[order]
        if len(marker.parts) == 1:
            if root_orders.get(marker.parts[0]) == order:
                accepted[order] = marker
            continue
        if len(marker.parts) >= 3:
            accepted[order] = marker
            continue
        root_order = root_orders.get(marker.parts[0])
        has_descendant = any(
            len(later.parts) > len(marker.parts)
            and later.parts[:len(marker.parts)] == marker.parts
            for later_order, later in candidate_items
            if later_order > order
        )
        if (
            record.numbering_stream
            or has_descendant
            or (
                record.kind is SourceRecordKind.TEXT
                and bool(marker.payload)
                and (
                    root_order is None
                    or order > root_order
                )
            )
        ):
            accepted[order] = marker
    numbers_with_payload = {
        marker.number
        for marker in accepted.values()
        if marker.payload
    }
    accepted = {
        order: marker
        for order, marker in accepted.items()
        if marker.payload
        or marker.number not in numbers_with_payload
        or by_order[order].numbering_stream
    }
    return accepted


def _title_and_body(payload: Sequence[str]) -> Tuple[str, str]:
    values = [value.strip() for value in payload if value.strip()]
    if not values:
        return "", ""
    if len(values) >= 2:
        return values[0], "\n".join(values[1:])
    return split_title_and_content(values[0])


def _payload_preserved(
    payload: Sequence[str],
    title: str,
    body: str,
) -> bool:
    """校验标题拆分只改变边界和空白，不删除原文字符。"""

    def canonical(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value or "")
        return re.sub(r"\s+", "", normalized)

    source = canonical("\n".join(value for value in payload if value.strip()))
    materialized = canonical(f"{title}\n{body}")
    return source == materialized


def _ancestors(parts: Tuple[int, ...]) -> Tuple[str, ...]:
    return tuple(
        ".".join(str(part) for part in parts[:level])
        for level in range(1, len(parts))
    )


def _append_line(lines: list[str], value: str) -> None:
    stripped = value.strip()
    if stripped:
        lines.append(stripped)


def _data_grid_text(table: DataTable) -> str:
    return "\n".join(
        "\t".join(str(cell or "") for cell in row)
        for row in table.data
    )


def _canonical_table_field(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" ") for line in normalized.split("\n")).strip()


def _materialize_data_table(table: DataTable) -> Tuple[str, bool]:
    """渲染表名和表体，并逐一证明所有文本字段均已保留。"""
    remark = table.remark.strip()
    raw_text = table.raw_text.strip()
    data_text = _data_grid_text(table).strip()
    body = raw_text or data_text
    materialized = "\n".join(
        part for part in (remark, body) if part
    )
    canonical_body = _canonical_table_field(body)
    fully_preserved = bool(materialized) and all((
        not raw_text
        or _canonical_table_field(raw_text) == canonical_body,
        not data_text
        or _canonical_table_field(data_text) == canonical_body,
        not remark
        or _canonical_table_field(remark)
        in _canonical_table_field(materialized),
    ))
    return materialized, fully_preserved


def assemble_numbered_content(
    records: Iterable[SourceRecord],
    detector: Optional[SectionDetector] = None,
) -> NumberedContent:
    """把格式适配器产生的记录组装为按原文顺序排列的审核内容。"""
    ordered = tuple(sorted(records, key=lambda item: item.order))
    markers = _accepted_markers(ordered)
    section_detector = detector or SectionDetector()
    clauses: list[Clause] = []
    tables: list[DataTable] = []
    unclassified: list[DocumentSection] = []
    notices: list[DocumentSection] = []
    health: list[DocumentSection] = []
    exclusions: list[DocumentSection] = []
    riders: list[Clause] = []
    warnings: list[str] = []
    source_order_counts = Counter(record.order for record in ordered)
    assignment_counts: Counter[int] = Counter()
    truncated_orders: set[int] = set()
    current_clause: Optional[_ClauseBuilder] = None
    current_section: Optional[_SectionBuilder] = None

    def claim(record: SourceRecord, *, fully_preserved: bool = True) -> None:
        """在完整原文已进入一个输出块后登记唯一归属。"""
        assignment_counts[record.order] += 1
        if not fully_preserved:
            truncated_orders.add(record.order)

    def flush_clause() -> None:
        nonlocal current_clause
        if current_clause is None:
            return
        ancestors = _ancestors(current_clause.parts)
        text = "\n".join(current_clause.lines).strip()
        clauses.append(Clause(
            number=current_clause.number,
            title=current_clause.title,
            text=text,
            page_number=current_clause.page_number,
            table_index=current_clause.table_index,
            topics=tag_clause_topics(current_clause.title, text),
            document_order=current_clause.start_order,
            hierarchy_level=len(current_clause.parts),
            parent_number=ancestors[-1] if ancestors else None,
            ancestor_numbers=ancestors,
            hierarchy_path=" > ".join((*ancestors, current_clause.number)),
            source_start_order=current_clause.start_order,
            source_end_order=current_clause.end_order,
        ))
        current_clause = None

    def flush_section() -> None:
        nonlocal current_section
        if current_section is None:
            return
        content = "\n".join(current_section.lines).strip()
        if current_section.section_type is SectionType.RIDER:
            riders.append(Clause(
                number="",
                title=current_section.title,
                text=content,
                section_type=SectionType.RIDER.value,
                topics=tag_clause_topics(current_section.title, content),
                document_order=current_section.start_order,
                source_start_order=current_section.start_order,
                source_end_order=current_section.end_order,
            ))
        else:
            section = DocumentSection(
                title=current_section.title,
                content=content,
                section_type=current_section.section_type.value,
                document_order=current_section.start_order,
                source_start_order=current_section.start_order,
                source_end_order=current_section.end_order,
            )
            target = {
                SectionType.UNCLASSIFIED: unclassified,
                SectionType.NOTICE: notices,
                SectionType.HEALTH_DISCLOSURE: health,
                SectionType.EXCLUSION: exclusions,
            }[current_section.section_type]
            target.append(section)
        current_section = None

    def start_unclassified(record: SourceRecord, role: str = "") -> None:
        nonlocal current_section
        current_section = _SectionBuilder(
            section_type=SectionType.UNCLASSIFIED,
            title="",
            lines=[],
            start_order=record.order,
            end_order=record.order,
            role=role,
        )

    for record in ordered:
        marker = markers.get(record.order)
        if marker is not None:
            candidate_title, candidate_body = _title_and_body(marker.payload)
            marker_preserved = _payload_preserved(
                marker.payload,
                candidate_title,
                candidate_body,
            )
            is_cross_page_repeat = (
                current_clause is not None
                and current_clause.number == marker.number
                and current_clause.end_page_number is not None
                and record.page_number == current_clause.end_page_number + 1
                and (
                    not candidate_title
                    or not current_clause.title
                    or candidate_title == current_clause.title
                )
            )
            if is_cross_page_repeat:
                assert current_clause is not None
                if not current_clause.title and candidate_title:
                    current_clause.title = candidate_title
                _append_line(current_clause.lines, candidate_body)
                current_clause.end_order = record.order
                current_clause.end_page_number = record.page_number
                claim(record, fully_preserved=marker_preserved)
                continue
            flush_clause()
            flush_section()
            current_clause = _ClauseBuilder(
                number=marker.number,
                parts=marker.parts,
                title=candidate_title,
                lines=[candidate_body] if candidate_body else [],
                start_order=record.order,
                end_order=record.order,
                page_number=record.page_number,
                end_page_number=record.page_number,
                table_index=record.table_index,
            )
            claim(record, fully_preserved=marker_preserved)
            continue

        if record.kind is SourceRecordKind.DATA_TABLE:
            table = record.data_table
            if table is None:
                continue
            if current_clause is not None:
                table_text, table_preserved = _materialize_data_table(table)
                _append_line(current_clause.lines, table_text)
                current_clause.end_order = record.order
                current_clause.end_page_number = record.page_number
                claim(record, fully_preserved=table_preserved)
                continue
            if current_section is not None and current_section.role == "appendix":
                remark_parts = [
                    current_section.title,
                    *current_section.lines,
                    table.remark,
                ]
                table = replace(
                    table,
                    remark="\n".join(
                        part.strip() for part in remark_parts if part.strip()
                    ),
                    table_type=(
                        table.table_type
                        if table.table_type is not TableType.OTHER
                        else TableType.APPENDIX
                    ),
                    document_order=current_section.start_order,
                )
                current_section = None
            else:
                flush_section()
                table = replace(table, document_order=record.order)
            tables.append(table)
            _, table_preserved = _materialize_data_table(table)
            claim(
                record,
                fully_preserved=table_preserved,
            )
            continue

        text = record.text
        if not text:
            continue
        appendix_heading = (
            record.kind is SourceRecordKind.TEXT
            and _APPENDIX_HEADING.match(text.strip())
        )
        detected = (
            section_detector.detect_section_type(text)
            if record.kind is SourceRecordKind.TEXT
            else None
        )
        if appendix_heading:
            flush_clause()
            flush_section()
            start_unclassified(record, role="appendix")
            assert current_section is not None
            current_section.title = text.strip()
            claim(record)
            continue
        if current_clause is not None:
            _append_line(current_clause.lines, text)
            current_clause.end_order = record.order
            current_clause.end_page_number = (
                record.page_number or current_clause.end_page_number
            )
            claim(record)
            continue
        if detected is not None:
            flush_clause()
            flush_section()
            current_section = _SectionBuilder(
                section_type=detected,
                title=text.strip(),
                lines=[],
                start_order=record.order,
                end_order=record.order,
            )
            claim(record)
            continue
        if current_section is None:
            start_unclassified(record)
        assert current_section is not None
        _append_line(current_section.lines, text)
        current_section.end_order = record.order
        claim(record)

    flush_clause()
    flush_section()

    clause_numbers = {clause.number for clause in clauses}
    completed_clauses = []
    for clause in clauses:
        has_child = any(
            number.startswith(f"{clause.number}.")
            for number in clause_numbers
        )
        completed_clauses.append(replace(
            clause,
            container_only=bool(not clause.text and has_child),
        ))

    duplicate_numbers: dict[str, int] = {}
    for clause in completed_clauses:
        duplicate_numbers[clause.number] = (
            duplicate_numbers.get(clause.number, 0) + 1
        )
    for number, count in duplicate_numbers.items():
        if count > 1:
            warnings.append(
                f"条款编号 {number} 非连续重复出现 {count} 次，已分别保留",
            )

    duplicate_source_orders = tuple(sorted(
        order for order, count in source_order_counts.items() if count > 1
    ))
    unassigned_orders = tuple(sorted(
        order
        for order in source_order_counts
        if assignment_counts[order] != source_order_counts[order]
    ))
    multiply_assigned_orders = tuple(sorted(
        order
        for order, count in assignment_counts.items()
        if count > source_order_counts[order]
    ))
    assigned_record_count = sum(
        min(assignment_counts[order], count)
        for order, count in source_order_counts.items()
    )
    coverage_attested = bool(ordered) and not any((
        duplicate_source_orders,
        unassigned_orders,
        multiply_assigned_orders,
        truncated_orders,
    ))
    coverage = CoverageAttestation(
        coverage_attested=coverage_attested,
        source_record_count=len(ordered),
        assigned_record_count=assigned_record_count,
        unassigned_orders=unassigned_orders,
        multiply_assigned_orders=multiply_assigned_orders,
        duplicate_source_orders=duplicate_source_orders,
        truncated_orders=tuple(sorted(truncated_orders)),
    )
    if not coverage_attested:
        warnings.append(
            "原文覆盖证明未通过，已禁用依赖全文缺失事实的负向产品标签推断"
        )

    return NumberedContent(
        clauses=tuple(completed_clauses),
        tables=tuple(tables),
        unclassified_sections=tuple(unclassified),
        notices=tuple(notices),
        health_disclosures=tuple(health),
        exclusions=tuple(exclusions),
        rider_clauses=tuple(riders),
        coverage_attestation=coverage,
        warnings=tuple(warnings),
    )
