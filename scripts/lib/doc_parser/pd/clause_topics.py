"""版本化条款主题表及关键词配置校验。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple


class ClauseTopicConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClauseTopicDefinition:
    code: str
    label: str
    status: str


@dataclass(frozen=True)
class ClauseTopicRegistry:
    schema_version: str
    topics: Tuple[ClauseTopicDefinition, ...]

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(topic.code for topic in self.topics)


def _read_object(path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClauseTopicConfigError(f"无法读取条款主题配置 {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ClauseTopicConfigError(f"条款主题配置必须是 JSON object: {path}")
    return raw


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClauseTopicConfigError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _parse_registry(raw: Mapping[str, object]) -> ClauseTopicRegistry:
    schema_version = _required_text(raw.get("schema_version"), "schema_version")
    raw_topics = raw.get("topics")
    if not isinstance(raw_topics, list) or not raw_topics:
        raise ClauseTopicConfigError("topics 必须是非空数组")
    topics: list[ClauseTopicDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_topics):
        if not isinstance(item, Mapping):
            raise ClauseTopicConfigError(f"topics[{index}] 必须是 object")
        code = _required_text(item.get("code"), f"topics[{index}].code")
        label = _required_text(item.get("label"), f"topics[{index}].label")
        status = _required_text(item.get("status"), f"topics[{index}].status")
        if status not in {"active", "deprecated"}:
            raise ClauseTopicConfigError(f"topics[{index}].status 非法: {status}")
        if code in seen:
            raise ClauseTopicConfigError(f"主题代码重复: {code}")
        seen.add(code)
        topics.append(ClauseTopicDefinition(code=code, label=label, status=status))
    return ClauseTopicRegistry(schema_version=schema_version, topics=tuple(topics))


@lru_cache(maxsize=1)
def _load_default_registry() -> ClauseTopicRegistry:
    path = Path(__file__).parent / "data" / "clause_topics.json"
    return _parse_registry(_read_object(path))


def load_clause_topic_registry(path: Optional[Path] = None) -> ClauseTopicRegistry:
    return _parse_registry(_read_object(path)) if path is not None else _load_default_registry()


def load_clause_topic_keywords(
    registry: ClauseTopicRegistry,
    path: Optional[Path] = None,
) -> Dict[str, Tuple[str, ...]]:
    keywords_path = path or Path(__file__).parent / "data" / "clause_topic_keywords.json"
    raw = _read_object(keywords_path)
    unknown_codes = sorted(str(code) for code in raw if str(code) not in registry.codes)
    if unknown_codes:
        raise ClauseTopicConfigError(
            f"关键词配置引用未注册主题: {', '.join(unknown_codes)}"
        )
    keywords: Dict[str, Tuple[str, ...]] = {}
    for code, value in raw.items():
        if not isinstance(code, str) or not code:
            raise ClauseTopicConfigError("关键词配置主题代码必须是非空字符串")
        if not isinstance(value, list) or not value:
            raise ClauseTopicConfigError(f"关键词配置 {code} 必须是非空数组")
        words = tuple(
            _required_text(word, f"{code}.keywords")
            for word in value
        )
        keywords[code] = words
    return keywords
