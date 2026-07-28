"""按版本化受控主题为单个法规条款单元路由产品条款。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Optional, Protocol, Sequence, Tuple

from lib.doc_parser.pd.clause_topics import (
    ClauseTopicConfigError,
    ClauseTopicRegistry,
    load_clause_topic_registry,
)


class ClauseRoute(str, Enum):
    DIRECT = "direct"
    RELATED = "related"
    UNKNOWN = "unknown"
    NOT_RELEVANT = "not_relevant"


class RoutableClause(Protocol):
    @property
    def clause_id(self) -> str: ...

    @property
    def topics(self) -> Tuple[str, ...]: ...


@dataclass(frozen=True)
class ClauseRoutingInput:
    clause_id: str
    topics: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ControlledExclusion:
    topic: str
    fixture_id: str


@dataclass(frozen=True)
class TopicRelation:
    regulation_topic: str
    related_topics: Tuple[str, ...] = ()
    not_relevant_topics: Tuple[ControlledExclusion, ...] = ()


@dataclass(frozen=True)
class TopicRelationRegistry:
    schema_version: str
    topic_schema_version: str
    relations: Tuple[TopicRelation, ...]

    def get(self, topic: str) -> Optional[TopicRelation]:
        return next(
            (relation for relation in self.relations if relation.regulation_topic == topic),
            None,
        )


@dataclass(frozen=True)
class ClauseRouteItem:
    clause_id: str
    route: ClauseRoute
    reason: str
    clause_topics: Tuple[str, ...] = ()
    matched_topics: Tuple[str, ...] = ()
    fixture_ids: Tuple[str, ...] = ()

    @property
    def selected(self) -> bool:
        return self.route is not ClauseRoute.NOT_RELEVANT


@dataclass(frozen=True)
class ClauseRoutingResult:
    regulation_topics: Tuple[str, ...]
    topic_schema_version: str
    relation_schema_version: str
    items: Tuple[ClauseRouteItem, ...]
    config_valid: bool
    warnings: Tuple[str, ...] = ()

    @property
    def selected_clause_ids(self) -> Tuple[str, ...]:
        return tuple(item.clause_id for item in self.items if item.selected)

    @property
    def excluded_clause_ids(self) -> Tuple[str, ...]:
        return tuple(item.clause_id for item in self.items if not item.selected)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClauseTopicConfigError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _read_relations(path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClauseTopicConfigError(f"无法读取条款主题关系 {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ClauseTopicConfigError(f"条款主题关系必须是 JSON object: {path}")
    return raw


def _topic_list(
    value: object,
    field_name: str,
    registry: ClauseTopicRegistry,
) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ClauseTopicConfigError(f"{field_name} 必须是数组")
    topics = tuple(_required_text(topic, field_name) for topic in value)
    unknown = sorted(set(topics).difference(registry.codes))
    if unknown:
        raise ClauseTopicConfigError(f"{field_name} 引用未注册主题: {', '.join(unknown)}")
    return topics


def load_topic_relation_registry(
    topic_registry: ClauseTopicRegistry,
    path: Optional[Path] = None,
) -> TopicRelationRegistry:
    relations_path = path or Path(__file__).parent / "data" / "clause_topic_relations.json"
    raw = _read_relations(relations_path)
    schema_version = _required_text(raw.get("schema_version"), "schema_version")
    topic_schema_version = _required_text(
        raw.get("topic_schema_version"),
        "topic_schema_version",
    )
    if schema_version != "1.0.0":
        raise ClauseTopicConfigError(f"不支持的主题关系版本: {schema_version}")
    if topic_schema_version != topic_registry.schema_version:
        raise ClauseTopicConfigError(
            "主题关系引用的主题体系版本与当前主题体系不一致: "
            f"{topic_schema_version} != {topic_registry.schema_version}"
        )
    raw_relations = raw.get("relations")
    if not isinstance(raw_relations, list):
        raise ClauseTopicConfigError("relations 必须是数组")
    relations: list[TopicRelation] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_relations):
        if not isinstance(item, Mapping):
            raise ClauseTopicConfigError(f"relations[{index}] 必须是 object")
        regulation_topic = _required_text(
            item.get("regulation_topic"),
            f"relations[{index}].regulation_topic",
        )
        if regulation_topic not in topic_registry.codes:
            raise ClauseTopicConfigError(f"关系源主题未注册: {regulation_topic}")
        if regulation_topic in seen:
            raise ClauseTopicConfigError(f"关系源主题重复: {regulation_topic}")
        seen.add(regulation_topic)
        related_topics = _topic_list(
            item.get("related_topics", []),
            f"relations[{index}].related_topics",
            topic_registry,
        )
        raw_exclusions = item.get("not_relevant_topics", [])
        if not isinstance(raw_exclusions, list):
            raise ClauseTopicConfigError(
                f"relations[{index}].not_relevant_topics 必须是数组"
            )
        exclusions: list[ControlledExclusion] = []
        for exclusion_index, exclusion in enumerate(raw_exclusions):
            if not isinstance(exclusion, Mapping):
                raise ClauseTopicConfigError(
                    f"relations[{index}].not_relevant_topics[{exclusion_index}] 必须是 object"
                )
            topic = _required_text(
                exclusion.get("topic"),
                f"relations[{index}].not_relevant_topics[{exclusion_index}].topic",
            )
            fixture_id = _required_text(
                exclusion.get("fixture_id"),
                f"relations[{index}].not_relevant_topics[{exclusion_index}].fixture_id",
            )
            if topic not in topic_registry.codes:
                raise ClauseTopicConfigError(f"明确不相关主题未注册: {topic}")
            exclusions.append(ControlledExclusion(topic=topic, fixture_id=fixture_id))
        relations.append(TopicRelation(
            regulation_topic=regulation_topic,
            related_topics=related_topics,
            not_relevant_topics=tuple(exclusions),
        ))
    return TopicRelationRegistry(
        schema_version=schema_version,
        topic_schema_version=topic_schema_version,
        relations=tuple(relations),
    )


def _unknown_items(
    clauses: Sequence[RoutableClause],
    reason: str,
) -> Tuple[ClauseRouteItem, ...]:
    return tuple(
        ClauseRouteItem(
            clause_id=clause.clause_id,
            route=ClauseRoute.UNKNOWN,
            reason=reason,
            clause_topics=tuple(clause.topics),
        )
        for clause in clauses
    )


def _route_one(
    regulation_topics: Tuple[str, ...],
    clause: RoutableClause,
    topic_registry: ClauseTopicRegistry,
    relation_registry: TopicRelationRegistry,
) -> ClauseRouteItem:
    clause_topics = tuple(dict.fromkeys(topic for topic in clause.topics if topic))
    if not clause_topics:
        return ClauseRouteItem(
            clause_id=clause.clause_id,
            route=ClauseRoute.UNKNOWN,
            reason="产品条款未标注受控主题，保守保留",
        )
    unknown_clause_topics = tuple(
        topic for topic in clause_topics if topic not in topic_registry.codes
    )
    direct = tuple(topic for topic in clause_topics if topic in regulation_topics)
    if direct:
        return ClauseRouteItem(
            clause_id=clause.clause_id,
            route=ClauseRoute.DIRECT,
            reason="产品条款主题与法规主题精确匹配",
            clause_topics=clause_topics,
            matched_topics=direct,
        )
    related_pairs: list[str] = []
    for regulation_topic in regulation_topics:
        relation = relation_registry.get(regulation_topic)
        if relation is None:
            continue
        related_pairs.extend(
            topic for topic in clause_topics if topic in relation.related_topics
        )
    if related_pairs:
        return ClauseRouteItem(
            clause_id=clause.clause_id,
            route=ClauseRoute.RELATED,
            reason="命中经版本治理的跨主题必要关系",
            clause_topics=clause_topics,
            matched_topics=tuple(dict.fromkeys(related_pairs)),
        )
    if unknown_clause_topics:
        return ClauseRouteItem(
            clause_id=clause.clause_id,
            route=ClauseRoute.UNKNOWN,
            reason="产品条款包含未注册主题，保守保留",
            clause_topics=clause_topics,
        )

    exclusion_fixture_ids: list[str] = []
    for regulation_topic in regulation_topics:
        relation = relation_registry.get(regulation_topic)
        if relation is None:
            return ClauseRouteItem(
                clause_id=clause.clause_id,
                route=ClauseRoute.UNKNOWN,
                reason="法规主题尚无受控关系，不能证明产品条款不相关",
                clause_topics=clause_topics,
            )
        fixture_by_topic = {
            exclusion.topic: exclusion.fixture_id
            for exclusion in relation.not_relevant_topics
        }
        for clause_topic in clause_topics:
            fixture_id = fixture_by_topic.get(clause_topic)
            if fixture_id is None:
                return ClauseRouteItem(
                    clause_id=clause.clause_id,
                    route=ClauseRoute.UNKNOWN,
                    reason="主题关系未覆盖该组合，不能证明产品条款不相关",
                    clause_topics=clause_topics,
                )
            exclusion_fixture_ids.append(fixture_id)
    return ClauseRouteItem(
        clause_id=clause.clause_id,
        route=ClauseRoute.NOT_RELEVANT,
        reason="所有法规主题与产品条款主题组合均有 fixture 覆盖的明确不相关关系",
        clause_topics=clause_topics,
        fixture_ids=tuple(dict.fromkeys(exclusion_fixture_ids)),
    )


def route_product_clauses(
    regulation_topics: Iterable[str],
    clauses: Sequence[RoutableClause],
    topic_registry_path: Optional[Path] = None,
    relation_registry_path: Optional[Path] = None,
) -> ClauseRoutingResult:
    controlled_regulation_topics = tuple(
        dict.fromkeys(topic for topic in regulation_topics if topic)
    )
    try:
        topic_registry = load_clause_topic_registry(topic_registry_path)
        relation_registry = load_topic_relation_registry(
            topic_registry,
            relation_registry_path,
        )
    except ClauseTopicConfigError as exc:
        return ClauseRoutingResult(
            regulation_topics=controlled_regulation_topics,
            topic_schema_version="unavailable",
            relation_schema_version="unavailable",
            items=_unknown_items(clauses, "主题配置不可用，全部保守保留"),
            config_valid=False,
            warnings=(str(exc),),
        )
    unknown_regulation_topics = tuple(
        topic
        for topic in controlled_regulation_topics
        if topic not in topic_registry.codes
    )
    if not controlled_regulation_topics:
        return ClauseRoutingResult(
            regulation_topics=(),
            topic_schema_version=topic_registry.schema_version,
            relation_schema_version=relation_registry.schema_version,
            items=_unknown_items(clauses, "法规未标注主题，全部保守保留"),
            config_valid=True,
        )
    if unknown_regulation_topics:
        return ClauseRoutingResult(
            regulation_topics=controlled_regulation_topics,
            topic_schema_version=topic_registry.schema_version,
            relation_schema_version=relation_registry.schema_version,
            items=_unknown_items(clauses, "法规包含未注册主题，全部保守保留"),
            config_valid=False,
            warnings=(
                f"法规引用未注册主题: {', '.join(unknown_regulation_topics)}",
            ),
        )
    routed = tuple(
        _route_one(
            controlled_regulation_topics,
            clause,
            topic_registry,
            relation_registry,
        )
        for clause in clauses
    )
    priority = {
        ClauseRoute.DIRECT: 0,
        ClauseRoute.RELATED: 1,
        ClauseRoute.UNKNOWN: 2,
        ClauseRoute.NOT_RELEVANT: 3,
    }
    original_rank = {id(item): rank for rank, item in enumerate(routed)}
    ordered = tuple(sorted(
        routed,
        key=lambda item: (priority[item.route], original_rank[id(item)]),
    ))
    return ClauseRoutingResult(
        regulation_topics=controlled_regulation_topics,
        topic_schema_version=topic_registry.schema_version,
        relation_schema_version=relation_registry.schema_version,
        items=ordered,
        config_valid=True,
    )
