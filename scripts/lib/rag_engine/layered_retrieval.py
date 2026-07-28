"""对混合检索结果执行产品适用性与条款主题分层。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from lib.common.product_tags import ProductTags
from lib.compliance.applicability import (
    ApplicabilityResult,
    MatchStatus,
    RegulationApplicability,
    match_regulation_applicability,
)


@dataclass(frozen=True)
class RetrievalTrace:
    law_name: str
    article_number: str
    status: MatchStatus
    layer: str
    matched_dimensions: Tuple[str, ...]
    indeterminate_dimensions: Tuple[str, ...]
    excluded_by: Tuple[str, ...]


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


def layer_regulation_candidates(
    candidates: Sequence[Dict[str, Any]],
    product_tags: ProductTags,
    clause_topics: Iterable[str] = (),
    top_k: int = 8,
) -> LayeredRetrievalResult:
    """按适用性和主题对已排序的混合检索候选进行稳定分层。"""
    current_topics = frozenset(topic for topic in clause_topics if topic)
    deduplicated: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = get_candidate_identity(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(candidate)

    ranked: List[Tuple[int, float, int, Dict[str, Any], RetrievalTrace]] = []
    traces: List[RetrievalTrace] = []
    excluded_count = 0
    for original_rank, candidate in enumerate(deduplicated):
        regulation = RegulationApplicability.from_metadata(_metadata(candidate))
        applicability = match_regulation_applicability(product_tags, regulation)
        if applicability.status is MatchStatus.NOT_APPLICABLE:
            layer = "excluded"
            excluded_count += 1
            trace = RetrievalTrace(
                law_name=str(candidate.get("law_name", "")),
                article_number=str(candidate.get("article_number", "")),
                status=applicability.status,
                layer=layer,
                matched_dimensions=applicability.matched_dimensions,
                indeterminate_dimensions=applicability.indeterminate_dimensions,
                excluded_by=applicability.excluded_by,
            )
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
            "matched_dimensions": list(applicability.matched_dimensions),
            "indeterminate_dimensions": list(applicability.indeterminate_dimensions),
            "matched_topics": list(matched_topics),
            "fallback_layer": layer,
        })
        trace = RetrievalTrace(
            law_name=str(candidate.get("law_name", "")),
            article_number=str(candidate.get("article_number", "")),
            status=applicability.status,
            layer=layer,
            matched_dimensions=applicability.matched_dimensions,
            indeterminate_dimensions=applicability.indeterminate_dimensions,
            excluded_by=applicability.excluded_by,
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
    selected = tuple(item[3] for item in ranked[:max(top_k, 0)])
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
