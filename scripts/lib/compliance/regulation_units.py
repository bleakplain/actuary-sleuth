"""法规物理 chunk 到稳定法规条款单元的聚合。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Tuple


def _metadata(candidate: Mapping[str, object]) -> Mapping[str, object]:
    metadata = candidate.get("metadata")
    return metadata if isinstance(metadata, Mapping) else {}


def _value(candidate: Mapping[str, object], key: str) -> object:
    value = candidate.get(key)
    if value not in (None, ""):
        return value
    return _metadata(candidate).get(key)


def _text(candidate: Mapping[str, object], key: str) -> str:
    value = _value(candidate, key)
    return str(value).strip() if value not in (None, "") else ""


def _strings(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.replace("，", ",").replace("、", ",").replace("\n", ",")
        return tuple(part.strip() for part in normalized.split(",") if part.strip())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _ordered_union(values: Iterable[Iterable[str]]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in values for item in group))


def _chunk_index(candidate: Mapping[str, object]) -> Optional[int]:
    for key in ("chunk_index", "chunk_id"):
        value = _value(candidate, key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def build_regulation_unit_id(
    kb_version: str,
    source_file: str,
    locator: str,
) -> str:
    """将版本、源文件和条款定位符编码为稳定 ID。"""
    components = json.dumps(
        [kb_version, source_file, locator],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(components.encode("utf-8")).hexdigest()
    return f"regulation-unit:{digest}"


@dataclass(frozen=True)
class RegulationChunk:
    chunk_id: str
    law_name: str
    article_number: str
    section_path: str
    source_file: str
    chunk_index: Optional[int]
    content: str
    regulation_topics: Tuple[str, ...] = ()
    retrieval_sources: Tuple[str, ...] = ()
    source_type: str = ""
    category: str = ""


@dataclass(frozen=True)
class RegulationUnit:
    unit_id: str
    kb_version: str
    source_file: str
    locator: str
    locator_type: str
    law_name: str
    article_number: str
    section_path: str
    chunks: Tuple[RegulationChunk, ...]
    applicability_status: str
    matched_dimensions: Tuple[str, ...] = ()
    indeterminate_dimensions: Tuple[str, ...] = ()
    excluded_by: Tuple[str, ...] = ()
    applicability_reasons: Tuple[str, ...] = ()
    regulation_topics: Tuple[str, ...] = ()
    retrieval_sources: Tuple[str, ...] = ()
    category: str = ""

    @property
    def chunk_ids(self) -> Tuple[str, ...]:
        return tuple(chunk.chunk_id for chunk in self.chunks)

    @property
    def content(self) -> str:
        return "\n\n".join(chunk.content for chunk in self.chunks if chunk.content)


@dataclass(frozen=True)
class RegulationUnitBuildResult:
    units: Tuple[RegulationUnit, ...]
    rejected_chunk_ids: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()


@dataclass
class _UnitAccumulator:
    first_rank: int
    kb_version: str
    source_file: str
    locator: str
    locator_type: str
    law_name: str
    article_number: str
    section_path: str
    categories: list[str]
    chunks: list[Tuple[int, RegulationChunk]]
    statuses: list[str]
    matched_dimensions: list[Tuple[str, ...]]
    indeterminate_dimensions: list[Tuple[str, ...]]
    excluded_by: list[Tuple[str, ...]]
    applicability_reasons: list[Tuple[str, ...]]
    regulation_topics: list[Tuple[str, ...]]
    retrieval_sources: list[Tuple[str, ...]]


def _candidate_chunk(candidate: Mapping[str, object]) -> RegulationChunk:
    metadata = _metadata(candidate)
    topics = candidate.get("regulation_topics")
    if topics is None:
        topics = metadata.get("条款主题")
    return RegulationChunk(
        chunk_id=_text(candidate, "id") or _text(candidate, "chunk_id"),
        law_name=_text(candidate, "law_name"),
        article_number=_text(candidate, "article_number"),
        section_path=_text(candidate, "section_path"),
        source_file=_text(candidate, "source_file"),
        category=_text(candidate, "category"),
        chunk_index=_chunk_index(candidate),
        content=_text(candidate, "content"),
        regulation_topics=_strings(topics),
        retrieval_sources=_strings(candidate.get("retrieval_sources")),
        source_type=_text(candidate, "_source_type") or _text(candidate, "source_type"),
    )


def aggregate_regulation_units(
    candidates: Iterable[Mapping[str, object]],
    kb_version: str = "",
) -> RegulationUnitBuildResult:
    """按版本、源文件和条款定位符聚合，并保留所有不同的物理 chunk。"""
    grouped: Dict[Tuple[str, str, str], _UnitAccumulator] = {}
    rejected: list[str] = []
    errors: list[str] = []

    for rank, candidate in enumerate(candidates):
        chunk = _candidate_chunk(candidate)
        candidate_version = _text(candidate, "kb_version") or kb_version
        article_number = _text(candidate, "article_number")
        section_path = _text(candidate, "section_path")
        locator = article_number or section_path
        locator_type = "article_number" if article_number else "section_path"
        chunk_ref = chunk.chunk_id or f"candidate:{rank}"
        missing = tuple(
            field
            for field, value in (
                ("kb_version", candidate_version),
                ("source_file", chunk.source_file),
                ("article_number/section_path", locator),
                ("chunk_id", chunk.chunk_id),
            )
            if not value
        )
        if missing:
            rejected.append(chunk_ref)
            errors.append(f"{chunk_ref}: 缺少法规单元身份字段 {', '.join(missing)}")
            continue

        key = (candidate_version, chunk.source_file, locator)
        status = _text(candidate, "applicability_status")
        matched_dimensions = _strings(candidate.get("matched_dimensions"))
        indeterminate_dimensions = _strings(candidate.get("indeterminate_dimensions"))
        excluded_by = _strings(candidate.get("excluded_by"))
        applicability_reasons = _strings(candidate.get("applicability_reasons"))
        if key not in grouped:
            grouped[key] = _UnitAccumulator(
                first_rank=rank,
                kb_version=candidate_version,
                source_file=chunk.source_file,
                locator=locator,
                locator_type=locator_type,
                law_name=chunk.law_name,
                article_number=article_number,
                section_path=section_path,
                categories=[],
                chunks=[],
                statuses=[],
                matched_dimensions=[],
                indeterminate_dimensions=[],
                excluded_by=[],
                applicability_reasons=[],
                regulation_topics=[],
                retrieval_sources=[],
            )
        accumulator = grouped[key]
        if chunk.chunk_id not in {current.chunk_id for _, current in accumulator.chunks}:
            accumulator.chunks.append((rank, chunk))
        accumulator.statuses.append(status)
        accumulator.matched_dimensions.append(matched_dimensions)
        accumulator.indeterminate_dimensions.append(indeterminate_dimensions)
        accumulator.excluded_by.append(excluded_by)
        accumulator.applicability_reasons.append(applicability_reasons)
        accumulator.categories.append(chunk.category)
        accumulator.regulation_topics.append(chunk.regulation_topics)
        accumulator.retrieval_sources.append(chunk.retrieval_sources)

    units: list[RegulationUnit] = []
    for accumulator in sorted(grouped.values(), key=lambda item: item.first_rank):
        statuses = tuple(status for status in dict.fromkeys(accumulator.statuses) if status)
        if len(statuses) == 1:
            status = statuses[0]
        else:
            status = "indeterminate"
            accumulator.applicability_reasons.append(
                ("同一法规条款单元的物理 chunk 适用性状态不一致，保守保留",)
            )
        ordered_chunks = tuple(
            chunk
            for _, chunk in sorted(
                accumulator.chunks,
                key=lambda item: (
                    item[1].chunk_index is None,
                    item[1].chunk_index if item[1].chunk_index is not None else item[0],
                    item[0],
                ),
            )
        )
        units.append(RegulationUnit(
            unit_id=build_regulation_unit_id(
                accumulator.kb_version,
                accumulator.source_file,
                accumulator.locator,
            ),
            kb_version=accumulator.kb_version,
            source_file=accumulator.source_file,
            locator=accumulator.locator,
            locator_type=accumulator.locator_type,
            law_name=accumulator.law_name,
            article_number=accumulator.article_number,
            section_path=accumulator.section_path,
            category=next(
                (category for category in accumulator.categories if category),
                "",
            ),
            chunks=ordered_chunks,
            applicability_status=status,
            matched_dimensions=_ordered_union(accumulator.matched_dimensions),
            indeterminate_dimensions=_ordered_union(accumulator.indeterminate_dimensions),
            excluded_by=_ordered_union(accumulator.excluded_by),
            applicability_reasons=_ordered_union(accumulator.applicability_reasons),
            regulation_topics=_ordered_union(accumulator.regulation_topics),
            retrieval_sources=_ordered_union(accumulator.retrieval_sources),
        ))
    return RegulationUnitBuildResult(
        units=tuple(units),
        rejected_chunk_ids=tuple(rejected),
        errors=tuple(errors),
    )
