"""法规标签解析与产品适用性判断。

只有产品事实与法规限制明确冲突时才排除法规；产品标签未知时返回
indeterminate，避免为了缩短检索上下文而制造漏查。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

from lib.common.product_tags import ProductTags


class MatchStatus(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


_TAG_DIMENSIONS: Dict[str, str] = {
    "life": "line",
    "health": "line",
    "accident": "line",
    "term_life": "subtype",
    "whole_life": "subtype",
    "endowment": "subtype",
    "annuity": "subtype",
    "disease": "subtype",
    "critical_illness": "subtype",
    "medical": "subtype",
    "disability_income": "subtype",
    "nursing": "subtype",
    "medical_accident": "subtype",
    "ordinary": "design_type",
    "participating": "design_type",
    "universal": "design_type",
    "unit_linked": "design_type",
    "long_term": "term_class",
    "short_term": "term_class",
    "individual": "customer_scope",
    "group": "customer_scope",
    "main": "contract_role",
    "rider": "contract_role",
    "internet_exclusive": "special_feature",
    "tax_advantaged_health": "special_feature",
    "rate_adjustable": "special_feature",
}

_SPECIAL_PRODUCT_FIELDS = {
    "internet_exclusive": "is_internet_exclusive",
    "tax_advantaged_health": "is_tax_advantaged_health",
    "rate_adjustable": "is_rate_adjustable",
}


def _split_values(raw: Any) -> Tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        normalized = raw.replace("，", ",").replace("、", ",").replace("\n", ",")
        return tuple(value.strip() for value in normalized.split(",") if value.strip())
    if isinstance(raw, Iterable):
        return tuple(str(value).strip() for value in raw if str(value).strip())
    return (str(raw).strip(),) if str(raw).strip() else ()


@dataclass(frozen=True)
class RegulationApplicability:
    lines: FrozenSet[str] = frozenset()
    subtypes: FrozenSet[str] = frozenset()
    design_types: FrozenSet[str] = frozenset()
    term_classes: FrozenSet[str] = frozenset()
    customer_scopes: FrozenSet[str] = frozenset()
    contract_roles: FrozenSet[str] = frozenset()
    special_features: FrozenSet[str] = frozenset()
    clause_topics: FrozenSet[str] = frozenset()
    unknown_tags: FrozenSet[str] = frozenset()

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> "RegulationApplicability":
        grouped: Dict[str, set[str]] = {
            "line": set(),
            "subtype": set(),
            "design_type": set(),
            "term_class": set(),
            "customer_scope": set(),
            "contract_role": set(),
            "special_feature": set(),
        }
        unknown_tags: set[str] = set()
        applicability_tags = (
            ()
            if metadata.get("适用标签语义") == "涉及"
            else _split_values(metadata.get("适用标签"))
        )
        for tag in applicability_tags:
            dimension = _TAG_DIMENSIONS.get(tag)
            if dimension:
                grouped[dimension].add(tag)
            else:
                unknown_tags.add(tag)
        return cls(
            lines=frozenset(grouped["line"]),
            subtypes=frozenset(grouped["subtype"]),
            design_types=frozenset(grouped["design_type"]),
            term_classes=frozenset(grouped["term_class"]),
            customer_scopes=frozenset(grouped["customer_scope"]),
            contract_roles=frozenset(grouped["contract_role"]),
            special_features=frozenset(grouped["special_feature"]),
            clause_topics=frozenset(_split_values(metadata.get("条款主题"))),
            unknown_tags=frozenset(unknown_tags),
        )


@dataclass(frozen=True)
class ApplicabilityResult:
    status: MatchStatus
    matched_dimensions: Tuple[str, ...] = ()
    indeterminate_dimensions: Tuple[str, ...] = ()
    excluded_by: Tuple[str, ...] = ()
    reasons: Tuple[str, ...] = ()


def _known_enum_value(value: Any) -> Optional[str]:
    raw = getattr(value, "value", value)
    if raw in (None, "", "unknown"):
        return None
    return str(raw)


def _match_dimension(
    dimension: str,
    allowed: FrozenSet[str],
    actual: Optional[str],
) -> Tuple[str, str]:
    if not allowed:
        return "unrestricted", f"{dimension}: 法规未限制"
    if actual is None:
        return "indeterminate", f"{dimension}: 产品标签未知，保守保留"
    if actual in allowed:
        return "matched", f"{dimension}: {actual} 命中 {sorted(allowed)}"
    return "excluded", f"{dimension}: {actual} 不在 {sorted(allowed)}"


def match_regulation_applicability(
    product_tags: ProductTags,
    regulation: RegulationApplicability,
) -> ApplicabilityResult:
    """判断法规是否适用于产品，明确冲突优先于信息不足。"""
    dimensions = (
        ("line", regulation.lines, _known_enum_value(product_tags.line)),
        ("subtype", regulation.subtypes, _known_enum_value(product_tags.primary_subtype)),
        ("design_type", regulation.design_types, _known_enum_value(product_tags.design_type)),
        ("term_class", regulation.term_classes, _known_enum_value(product_tags.term_class)),
        ("customer_scope", regulation.customer_scopes, _known_enum_value(product_tags.customer_scope)),
        ("contract_role", regulation.contract_roles, _known_enum_value(product_tags.contract_role)),
    )
    matched: list[str] = []
    indeterminate: list[str] = []
    excluded: list[str] = []
    reasons: list[str] = []
    for dimension, allowed, actual in dimensions:
        outcome, reason = _match_dimension(dimension, allowed, actual)
        reasons.append(reason)
        if outcome == "matched":
            matched.append(dimension)
        elif outcome == "indeterminate":
            indeterminate.append(dimension)
        elif outcome == "excluded":
            excluded.append(dimension)

    for feature in sorted(regulation.special_features):
        field_name = _SPECIAL_PRODUCT_FIELDS[feature]
        actual = getattr(product_tags, field_name)
        reasons.append(
            f"special_feature.{feature}: "
            + ("命中" if actual is True else "明确不满足" if actual is False else "产品标签未知，保守保留")
        )
        if actual is True:
            matched.append(f"special_feature.{feature}")
        elif actual is False:
            excluded.append(f"special_feature.{feature}")
        else:
            indeterminate.append(f"special_feature.{feature}")

    if regulation.unknown_tags:
        indeterminate.append("unknown_regulation_tags")
        reasons.append(f"未识别法规标签 {sorted(regulation.unknown_tags)}，不据此排除")

    if excluded:
        status = MatchStatus.NOT_APPLICABLE
    elif indeterminate:
        status = MatchStatus.INDETERMINATE
    else:
        status = MatchStatus.APPLICABLE
    return ApplicabilityResult(
        status=status,
        matched_dimensions=tuple(matched),
        indeterminate_dimensions=tuple(indeterminate),
        excluded_by=tuple(excluded),
        reasons=tuple(reasons),
    )
