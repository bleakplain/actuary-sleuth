"""为单个法规条款单元选择最小、可追溯的产品条款证据。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Optional, Protocol, Sequence, Tuple

from rank_bm25 import BM25L  # type: ignore[import-untyped]

from lib.compliance.clause_routing import ClauseRoute, route_product_clauses
from lib.doc_parser.pd.clause_topics import (
    ClauseTopicConfigError,
    load_clause_topic_registry,
)
from lib.rag_engine.tokenizer import tokenize_chinese


class ClauseEvidenceConfigError(ValueError):
    pass


class EvidenceSourceLayer(str, Enum):
    TRIGGER_FACT = "trigger_fact"
    EXACT_TOPIC = "exact_topic"
    RELATED_TOPIC = "related_topic"
    BUSINESS_TERMS = "business_terms"
    BM25 = "bm25"


class EvidenceClause(Protocol):
    @property
    def clause_id(self) -> str: ...

    @property
    def number(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def topics(self) -> Tuple[str, ...]: ...

    @property
    def parent_number(self) -> Optional[str]: ...

    @property
    def ancestor_numbers(self) -> Tuple[str, ...]: ...

    @property
    def hierarchy_path(self) -> str: ...

    @property
    def container_only(self) -> bool: ...


@dataclass(frozen=True)
class FactEvidenceReference:
    fact_name: str
    clause_id: str


@dataclass(frozen=True)
class TopicEvidenceConstraint:
    topic: str
    required_any_groups: Tuple[Tuple[str, ...], ...]


@dataclass(frozen=True)
class ClauseEvidenceRuleRegistry:
    schema_version: str
    default_min_bm25_score: float
    default_max_bm25_candidates: int
    topic_constraints: Tuple[TopicEvidenceConstraint, ...]

    def constraints_for(
        self,
        topics: Iterable[str],
    ) -> Tuple[TopicEvidenceConstraint, ...]:
        requested = frozenset(topics)
        return tuple(
            constraint
            for constraint in self.topic_constraints
            if constraint.topic in requested
        )


@dataclass(frozen=True)
class ClauseOutlineItem:
    clause_id: str
    number: str
    title: str
    topics: Tuple[str, ...]
    parent_number: Optional[str]
    ancestor_numbers: Tuple[str, ...]
    hierarchy_path: str


@dataclass(frozen=True)
class ClauseEvidenceMatch:
    clause_id: str
    source_layer: EvidenceSourceLayer
    selection_reason: str
    score: float
    matched_values: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ClauseEvidenceSelection:
    regulation_topics: Tuple[str, ...]
    selected_clause_ids: Tuple[str, ...]
    matches: Tuple[ClauseEvidenceMatch, ...]
    full_outline: Tuple[ClauseOutlineItem, ...]
    relation_schema_version: str
    rule_schema_version: str
    config_valid: bool
    warnings: Tuple[str, ...] = ()


_DEFAULT_RULE_PATH = Path(__file__).parent / "data" / "clause_evidence_rules.json"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClauseEvidenceConfigError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _required_number(value: object, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ClauseEvidenceConfigError(f"{field_name} 必须是数字")
    number = float(value)
    if number < 0:
        raise ClauseEvidenceConfigError(f"{field_name} 不能小于 0")
    return number


def _term_groups(value: object, field_name: str) -> Tuple[Tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ClauseEvidenceConfigError(f"{field_name} 必须是数组")
    groups = []
    for group_index, group in enumerate(value):
        if not isinstance(group, list) or not group:
            raise ClauseEvidenceConfigError(
                f"{field_name}[{group_index}] 必须是非空数组"
            )
        terms = tuple(dict.fromkeys(
            _required_text(term, f"{field_name}[{group_index}]")
            for term in group
        ))
        groups.append(terms)
    return tuple(groups)


def load_clause_evidence_rule_registry(
    path: Optional[Path] = None,
) -> ClauseEvidenceRuleRegistry:
    rules_path = path or _DEFAULT_RULE_PATH
    try:
        raw = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClauseEvidenceConfigError(
            f"无法读取动态条款证据规则 {rules_path}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise ClauseEvidenceConfigError("动态条款证据规则必须是 JSON object")
    schema_version = _required_text(raw.get("schema_version"), "schema_version")
    if schema_version != "1.0.0":
        raise ClauseEvidenceConfigError(f"不支持的动态条款证据规则版本: {schema_version}")
    minimum_score = _required_number(
        raw.get("default_min_bm25_score"),
        "default_min_bm25_score",
    )
    maximum_candidates = _required_number(
        raw.get("default_max_bm25_candidates"),
        "default_max_bm25_candidates",
    )
    if not maximum_candidates.is_integer() or maximum_candidates < 1:
        raise ClauseEvidenceConfigError("default_max_bm25_candidates 必须是正整数")
    raw_constraints = raw.get("topic_constraints")
    if not isinstance(raw_constraints, list):
        raise ClauseEvidenceConfigError("topic_constraints 必须是数组")
    topic_registry = load_clause_topic_registry()
    constraints = []
    seen_topics = set()
    for index, item in enumerate(raw_constraints):
        if not isinstance(item, Mapping):
            raise ClauseEvidenceConfigError(f"topic_constraints[{index}] 必须是 object")
        topic = _required_text(item.get("topic"), f"topic_constraints[{index}].topic")
        if topic not in topic_registry.codes:
            raise ClauseEvidenceConfigError(f"动态条款证据规则引用未注册主题: {topic}")
        if topic in seen_topics:
            raise ClauseEvidenceConfigError(f"动态条款证据主题重复: {topic}")
        seen_topics.add(topic)
        constraints.append(TopicEvidenceConstraint(
            topic=topic,
            required_any_groups=_term_groups(
                item.get("required_any_groups"),
                f"topic_constraints[{index}].required_any_groups",
            ),
        ))
    return ClauseEvidenceRuleRegistry(
        schema_version=schema_version,
        default_min_bm25_score=minimum_score,
        default_max_bm25_candidates=int(maximum_candidates),
        topic_constraints=tuple(constraints),
    )


def _outline(clauses: Sequence[EvidenceClause]) -> Tuple[ClauseOutlineItem, ...]:
    return tuple(
        ClauseOutlineItem(
            clause_id=clause.clause_id,
            number=clause.number,
            title=clause.title,
            topics=tuple(clause.topics),
            parent_number=clause.parent_number,
            ancestor_numbers=tuple(clause.ancestor_numbers),
            hierarchy_path=clause.hierarchy_path,
        )
        for clause in clauses
    )


def _matched_terms(
    content: str,
    required_any_groups: Sequence[Tuple[str, ...]],
) -> Optional[Tuple[str, ...]]:
    matched: list[str] = []
    for group in required_any_groups:
        group_matches = tuple(term for term in group if term in content)
        if not group_matches:
            return None
        matched.extend(group_matches)
    return tuple(dict.fromkeys(matched))


def _bm25_scores(
    query: str,
    clauses: Sequence[EvidenceClause],
) -> Tuple[float, ...]:
    query_tokens = tuple(tokenize_chinese(query))
    corpus = tuple(
        tuple(tokenize_chinese(f"{clause.title}\n{clause.text}"))
        for clause in clauses
    )
    if not query_tokens or not corpus:
        return tuple(0.0 for _ in clauses)
    if not any(corpus):
        return tuple(0.0 for _ in clauses)
    return tuple(float(score) for score in BM25L(corpus).get_scores(query_tokens))


def _explicit_constraints(
    search_all_terms: Iterable[str],
    search_any_terms: Iterable[str],
) -> Tuple[Tuple[str, ...], ...]:
    all_terms = tuple(dict.fromkeys(
        term.strip() for term in search_all_terms if term.strip()
    ))
    any_terms = tuple(dict.fromkeys(
        term.strip() for term in search_any_terms if term.strip()
    ))
    return tuple((term,) for term in all_terms) + ((any_terms,) if any_terms else ())


def _business_term_matches_by_topic(
    content: str,
    topic_constraint_branches: Sequence[Sequence[TopicEvidenceConstraint]],
    explicit_constraints: Sequence[Tuple[str, ...]],
) -> Optional[Tuple[str, ...]]:
    """逐主题分支求值后取 OR，避免一个主题的门槛污染其他主题。"""
    explicit_matches = _matched_terms(content, explicit_constraints)
    if explicit_matches is None:
        return None
    for branch in topic_constraint_branches:
        if not branch:
            return explicit_matches
        for constraint in branch:
            topic_matches = _matched_terms(content, constraint.required_any_groups)
            if topic_matches is not None:
                return tuple(dict.fromkeys((*explicit_matches, *topic_matches)))
    return None


def _has_clause_body(clause: EvidenceClause) -> bool:
    return not clause.container_only and bool(clause.text.strip())


def select_clause_evidence(
    regulation_topics: Iterable[str],
    regulation_text: str,
    clauses: Sequence[EvidenceClause],
    fact_evidence_clause_ids: Iterable[str] = (),
    fact_evidence: Iterable[FactEvidenceReference] = (),
    search_all_terms: Iterable[str] = (),
    search_any_terms: Iterable[str] = (),
    min_bm25_score: Optional[float] = None,
    max_bm25_candidates: Optional[int] = None,
    topic_registry_path: Optional[Path] = None,
    relation_registry_path: Optional[Path] = None,
    rule_registry_path: Optional[Path] = None,
) -> ClauseEvidenceSelection:
    topics = tuple(dict.fromkeys(topic for topic in regulation_topics if topic))
    warnings = []
    try:
        registry = load_clause_evidence_rule_registry(rule_registry_path)
    except (ClauseEvidenceConfigError, ClauseTopicConfigError) as exc:
        registry = None
        warnings.append(str(exc))
    routing = route_product_clauses(
        topics,
        clauses,
        topic_registry_path=topic_registry_path,
        relation_registry_path=relation_registry_path,
    )
    warnings.extend(routing.warnings)
    minimum_score = (
        min_bm25_score
        if min_bm25_score is not None
        else registry.default_min_bm25_score if registry is not None else 1.0
    )
    maximum_candidates = (
        max_bm25_candidates
        if max_bm25_candidates is not None
        else registry.default_max_bm25_candidates if registry is not None else 5
    )
    if minimum_score < 0:
        raise ValueError("min_bm25_score 不能小于 0")
    if maximum_candidates < 1:
        raise ValueError("max_bm25_candidates 必须是正整数")

    clause_by_id = {clause.clause_id: clause for clause in clauses}
    clause_order = {clause.clause_id: index for index, clause in enumerate(clauses)}
    matches = []
    fact_references = (
        *(
            FactEvidenceReference("trigger_fact", clause_id)
            for clause_id in fact_evidence_clause_ids
        ),
        *fact_evidence,
    )
    for reference in fact_references:
        if reference.clause_id not in clause_by_id:
            warnings.append(
                f"触发事实 {reference.fact_name} 引用的条款不在完整目录: "
                f"{reference.clause_id}"
            )
            continue
        if not _has_clause_body(clause_by_id[reference.clause_id]):
            warnings.append(
                f"触发事实 {reference.fact_name} 引用了无正文或容器条款: "
                f"{reference.clause_id}"
            )
            continue
        matches.append(ClauseEvidenceMatch(
            clause_id=reference.clause_id,
            source_layer=EvidenceSourceLayer.TRIGGER_FACT,
            selection_reason=f"触发事实 {reference.fact_name} 的逐字证据条款",
            score=1.0,
            matched_values=(reference.fact_name,),
        ))

    route_by_id = {item.clause_id: item for item in routing.items}
    for clause in clauses:
        if not _has_clause_body(clause):
            continue
        route = route_by_id[clause.clause_id]
        if route.route is ClauseRoute.DIRECT:
            matches.append(ClauseEvidenceMatch(
                clause_id=clause.clause_id,
                source_layer=EvidenceSourceLayer.EXACT_TOPIC,
                selection_reason="产品条款主题与法规目标主题精确匹配",
                score=1.0,
                matched_values=route.matched_topics,
            ))
        elif route.route is ClauseRoute.RELATED:
            matches.append(ClauseEvidenceMatch(
                clause_id=clause.clause_id,
                source_layer=EvidenceSourceLayer.RELATED_TOPIC,
                selection_reason="命中版本化受控关联主题",
                score=1.0,
                matched_values=route.matched_topics,
            ))

    topic_constraint_branches = tuple(
        registry.constraints_for((topic,))
        for topic in topics
    ) if registry is not None and topics else ((),)
    explicit_constraints = _explicit_constraints(search_all_terms, search_any_terms)
    content_by_id = {
        clause.clause_id: f"{clause.title}\n{clause.text}"
        for clause in clauses
    }
    constrained = bool(explicit_constraints) or any(topic_constraint_branches)
    if constrained:
        for clause in clauses:
            if not _has_clause_body(clause):
                continue
            if route_by_id[clause.clause_id].route is ClauseRoute.NOT_RELEVANT:
                continue
            matched_terms = _business_term_matches_by_topic(
                content_by_id[clause.clause_id],
                topic_constraint_branches,
                explicit_constraints,
            )
            if not matched_terms:
                continue
            matches.append(ClauseEvidenceMatch(
                clause_id=clause.clause_id,
                source_layer=EvidenceSourceLayer.BUSINESS_TERMS,
                selection_reason="满足法规要求的业务对象词组约束",
                score=1.0,
                matched_values=matched_terms,
            ))

    if registry is not None:
        bm25_candidates = []
        selectable_clauses = tuple(
            clause for clause in clauses if _has_clause_body(clause)
        )
        for clause, score in zip(
            selectable_clauses,
            _bm25_scores(regulation_text, selectable_clauses),
        ):
            if score <= 0 or score < minimum_score:
                continue
            if route_by_id[clause.clause_id].route is ClauseRoute.NOT_RELEVANT:
                continue
            if (
                constrained
                and _business_term_matches_by_topic(
                    content_by_id[clause.clause_id],
                    topic_constraint_branches,
                    explicit_constraints,
                ) is None
            ):
                continue
            bm25_candidates.append((clause, score))
        bm25_candidates.sort(
            key=lambda item: (-item[1], clause_order[item[0].clause_id])
        )
        for clause, score in bm25_candidates[:maximum_candidates]:
            matches.append(ClauseEvidenceMatch(
                clause_id=clause.clause_id,
                source_layer=EvidenceSourceLayer.BM25,
                selection_reason=(
                    f"BM25 分数 {score:.4f} 达到最低门槛 {minimum_score:.4f}"
                ),
                score=score,
            ))

    layer_priority = {
        EvidenceSourceLayer.TRIGGER_FACT: 0,
        EvidenceSourceLayer.EXACT_TOPIC: 1,
        EvidenceSourceLayer.RELATED_TOPIC: 2,
        EvidenceSourceLayer.BUSINESS_TERMS: 3,
        EvidenceSourceLayer.BM25: 4,
    }
    ordered_matches = tuple(sorted(
        matches,
        key=lambda item: (
            layer_priority[item.source_layer],
            clause_order[item.clause_id],
            -item.score,
        ),
    ))
    selected_set = {item.clause_id for item in ordered_matches}
    selected_clause_ids = tuple(
        clause.clause_id for clause in clauses if clause.clause_id in selected_set
    )
    if not selected_clause_ids:
        warnings.append("未找到满足证据强度、业务对象约束和最低分门槛的产品条款")
    return ClauseEvidenceSelection(
        regulation_topics=topics,
        selected_clause_ids=selected_clause_ids,
        matches=ordered_matches,
        full_outline=_outline(clauses),
        relation_schema_version=routing.relation_schema_version,
        rule_schema_version=(
            registry.schema_version if registry is not None else "unavailable"
        ),
        config_valid=registry is not None and routing.config_valid,
        warnings=tuple(dict.fromkeys(warnings)),
    )
