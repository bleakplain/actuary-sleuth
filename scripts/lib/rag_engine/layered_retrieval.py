"""对混合检索结果执行产品适用性与条款主题分层。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from lib.common.product_tags import ProductTags
from lib.compliance.applicability import (
    ApplicabilityResult,
    MatchStatus,
    RegulationApplicability,
    match_regulation_applicability,
)


@dataclass(frozen=True)
class RetrievalTrace:
    chunk_id: str
    kb_version: str
    source_file: str
    section_path: str
    law_name: str
    article_number: str
    category: str
    status: MatchStatus
    layer: str
    regulation_topics: Tuple[str, ...]
    matched_dimensions: Tuple[str, ...]
    indeterminate_dimensions: Tuple[str, ...]
    excluded_by: Tuple[str, ...]
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class LayeredRetrievalResult:
    chunks: Tuple[Dict[str, Any], ...]
    candidate_count: int
    excluded_count: int
    fallback_used: bool
    trace: Tuple[RetrievalTrace, ...]


def _metadata(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = candidate.get("metadata")
    return metadata if isinstance(metadata, Mapping) else candidate


def _value(candidate: Mapping[str, Any], key: str) -> Any:
    value = candidate.get(key)
    if value not in (None, ""):
        return value
    return _metadata(candidate).get(key)


def _text(candidate: Mapping[str, Any], key: str) -> str:
    value = _value(candidate, key)
    return str(value).strip() if value not in (None, "") else ""


def _chunk_index(candidate: Mapping[str, Any]) -> Any:
    return _value(candidate, "chunk_index") or _value(candidate, "chunk_id")


def get_candidate_identity(candidate: Mapping[str, Any]) -> str:
    """优先使用全局 chunk ID，避免把同一条款的多个正文段落错误合并。"""
    explicit_id = candidate.get("id")
    if explicit_id in (None, ""):
        explicit_id = candidate.get("chunk_id")
    if explicit_id not in (None, ""):
        return f"id:{explicit_id}"
    metadata = _metadata(candidate)
    source_file = candidate.get("source_file") or metadata.get("source_file") or ""
    local_chunk_id = metadata.get("chunk_id")
    if local_chunk_id not in (None, ""):
        return f"chunk:{source_file}:{local_chunk_id}"
    identity = "\0".join((
        str(candidate.get("law_name", "")),
        str(candidate.get("article_number", "")),
        str(candidate.get("content", "")),
    ))
    return f"content:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _topic_family(topic: str) -> str:
    return topic.split(".", 1)[0]


def _topic_layer(
    regulation_topics: frozenset[str],
    clause_topics: frozenset[str],
) -> Tuple[int, str, Tuple[str, ...]]:
    if not clause_topics:
        return 0, "no_clause_topic_signal", ()
    exact = tuple(sorted(regulation_topics.intersection(clause_topics)))
    if exact:
        return 0, "exact_topic", exact
    if not regulation_topics:
        return 2, "untagged_topic", ()
    clause_families = {_topic_family(topic) for topic in clause_topics}
    general = tuple(sorted(
        topic for topic in regulation_topics
        if topic.endswith(".general") and _topic_family(topic) in clause_families
    ))
    if general:
        return 1, "topic_family_general", general
    return 3, "topic_mismatch_fallback", ()


def _layer_rank(
    applicability: ApplicabilityResult,
    topic_rank: int,
) -> int:
    applicability_rank = 0 if applicability.status is MatchStatus.APPLICABLE else 1
    return applicability_rank * 4 + topic_rank


def _retrieval_score(candidate: Mapping[str, Any]) -> float:
    score = candidate.get("score")
    return float(score) if isinstance(score, (int, float)) else 0.0


def _regulation_unit_key(candidate: Mapping[str, Any]) -> Tuple[str, str, str]:
    """以法规单元身份聚合同条款的物理块；缺字段时保持块级隔离。"""
    version = _text(candidate, "kb_version")
    source_file = _text(candidate, "source_file")
    locator = _text(candidate, "article_number") or _text(
        candidate,
        "section_path",
    )
    if version and source_file and locator:
        return version, source_file, locator
    return "invalid", get_candidate_identity(candidate), ""


def layer_regulation_candidates(
    candidates: Sequence[Dict[str, Any]],
    product_tags: ProductTags,
    clause_topics: Iterable[str] = (),
    top_k: Optional[int] = 8,
) -> LayeredRetrievalResult:
    """按适用性和主题稳定分层；top_k=None 时冻结全部保留候选。"""
    current_topics = frozenset(topic for topic in clause_topics if topic)
    deduplicated: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = get_candidate_identity(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)

    applicability_by_identity: Dict[str, ApplicabilityResult] = {}
    unit_statuses: Dict[Tuple[str, str, str], set[MatchStatus]] = {}
    for candidate in deduplicated:
        identity = get_candidate_identity(candidate)
        regulation = RegulationApplicability.from_metadata(_metadata(candidate))
        applicability = match_regulation_applicability(product_tags, regulation)
        applicability_by_identity[identity] = applicability
        unit_statuses.setdefault(
            _regulation_unit_key(candidate),
            set(),
        ).add(applicability.status)

    ranked: List[Tuple[int, float, int, Dict[str, Any], RetrievalTrace]] = []
    traces: List[RetrievalTrace] = []
    excluded_count = 0
    for original_rank, candidate in enumerate(deduplicated):
        regulation = RegulationApplicability.from_metadata(_metadata(candidate))
        applicability = applicability_by_identity[get_candidate_identity(candidate)]
        statuses = unit_statuses[_regulation_unit_key(candidate)]
        if (
            applicability.status is MatchStatus.NOT_APPLICABLE
            and statuses != {MatchStatus.NOT_APPLICABLE}
        ):
            applicability = ApplicabilityResult(
                status=MatchStatus.INDETERMINATE,
                matched_dimensions=applicability.matched_dimensions,
                indeterminate_dimensions=tuple(dict.fromkeys((
                    *applicability.indeterminate_dimensions,
                    "unit_chunk_consistency",
                ))),
                excluded_by=(),
                reasons=(
                    *applicability.reasons,
                    "同一法规条款单元的物理 chunk 适用性不一致，全文保守保留",
                ),
            )
        trace = RetrievalTrace(
            chunk_id=_text(candidate, "id") or _text(candidate, "chunk_id")
            or get_candidate_identity(candidate),
            kb_version=_text(candidate, "kb_version"),
            source_file=_text(candidate, "source_file"),
            section_path=_text(candidate, "section_path"),
            law_name=str(candidate.get("law_name", "")),
            article_number=str(candidate.get("article_number", "")),
            category=_text(candidate, "category"),
            status=applicability.status,
            layer="excluded",
            regulation_topics=tuple(sorted(regulation.clause_topics)),
            matched_dimensions=applicability.matched_dimensions,
            indeterminate_dimensions=applicability.indeterminate_dimensions,
            excluded_by=applicability.excluded_by,
            reasons=applicability.reasons,
        )
        if applicability.status is MatchStatus.NOT_APPLICABLE:
            excluded_count += 1
            traces.append(trace)
            continue

        topic_rank, topic_layer, matched_topics = _topic_layer(
            regulation.clause_topics, current_topics,
        )
        layer = (
            topic_layer
            if applicability.status is MatchStatus.APPLICABLE
            else f"indeterminate_{topic_layer}"
        )
        enriched = dict(candidate)
        enriched.update({
            "applicability_status": applicability.status.value,
            "applicability_reasons": list(applicability.reasons),
            "matched_dimensions": list(applicability.matched_dimensions),
            "indeterminate_dimensions": list(applicability.indeterminate_dimensions),
            "excluded_by": list(applicability.excluded_by),
            "regulation_topics": sorted(regulation.clause_topics),
            "matched_topics": list(matched_topics),
            "fallback_layer": layer,
            "kb_version": _text(candidate, "kb_version"),
            "source_file": _text(candidate, "source_file"),
            "section_path": _text(candidate, "section_path"),
            "chunk_index": _chunk_index(candidate),
        })
        trace = RetrievalTrace(
            chunk_id=trace.chunk_id,
            kb_version=trace.kb_version,
            source_file=trace.source_file,
            section_path=trace.section_path,
            law_name=trace.law_name,
            article_number=trace.article_number,
            category=trace.category,
            status=trace.status,
            layer=layer,
            regulation_topics=trace.regulation_topics,
            matched_dimensions=trace.matched_dimensions,
            indeterminate_dimensions=trace.indeterminate_dimensions,
            excluded_by=trace.excluded_by,
            reasons=trace.reasons,
        )
        traces.append(trace)
        ranked.append((
            _layer_rank(applicability, topic_rank),
            -_retrieval_score(candidate),
            original_rank,
            enriched,
            trace,
        ))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    selected_ranked = ranked if top_k is None else ranked[:max(top_k, 0)]
    selected = tuple(item[3] for item in selected_ranked)
    fallback_used = any(
        item.get("applicability_status") == MatchStatus.INDETERMINATE.value
        for item in selected
    )
    return LayeredRetrievalResult(
        chunks=selected,
        candidate_count=len(deduplicated),
        excluded_count=excluded_count,
        fallback_used=fallback_used,
        trace=tuple(traces),
    )
