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
    "other_health": "subtype",
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
    "has_renewal": "renewal_condition",
    "no_renewal": "renewal_condition",
    "internet_exclusive": "special_feature",
    "tax_advantaged_health": "special_feature",
    "rate_adjustable": "special_feature",
    "specific_disease": "special_feature",
    "out_of_hospital_drug": "special_feature",
    "cancer_specific": "special_feature",
    "critical_illness_definition_term": "special_feature",
    "increasing_sum_assured": "special_feature",
    "guaranteed_renewal": "renewal_condition",
    "non_guaranteed_renewal": "renewal_condition",
}

_SPECIAL_PRODUCT_FIELDS = {
    "internet_exclusive": "is_internet_exclusive",
    "tax_advantaged_health": "is_tax_advantaged_health",
    "rate_adjustable": "is_rate_adjustable",
    "specific_disease": "is_specific_disease_product",
    "out_of_hospital_drug": "mentions_out_of_hospital_drug",
    "cancer_specific": "is_cancer_specific_product",
    "critical_illness_definition_term": "mentions_critical_illness_definition_term",
    "increasing_sum_assured": "is_increasing_sum_assured_product",
}

_RISK_TRIGGER_TAGS = frozenset({
    "rate_adjustable",
    "guaranteed_renewal",
    "specific_disease",
    "out_of_hospital_drug",
    "cancer_specific",
    "accidental_medical_coverage",
    "critical_illness_definition_term",
})

_SUBTYPE_ANCESTORS = {
    "critical_illness": frozenset({"disease"}),
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
    renewal_conditions: FrozenSet[str] = frozenset()
    special_features: FrozenSet[str] = frozenset()
    risk_triggers: FrozenSet[str] = frozenset()
    unknown_risk_triggers: FrozenSet[str] = frozenset()
    normative_requirements: FrozenSet[str] = frozenset()
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
            "renewal_condition": set(),
            "special_feature": set(),
        }
        unknown_tags: set[str] = set()
        risk_triggers = set(_split_values(metadata.get("风险触发标签")))
        unknown_risk_triggers = risk_triggers.difference(_RISK_TRIGGER_TAGS)
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
            renewal_conditions=frozenset(grouped["renewal_condition"]),
            special_features=frozenset(grouped["special_feature"]),
            risk_triggers=frozenset(risk_triggers),
            unknown_risk_triggers=frozenset(unknown_risk_triggers),
            normative_requirements=frozenset(
                _split_values(metadata.get("检查目标标签"))
            ),
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
    inherited = (
        _SUBTYPE_ANCESTORS.get(actual, frozenset())
        if dimension == "subtype"
        else frozenset({"has_renewal"})
        if dimension == "renewal_condition"
        and actual in {"guaranteed_renewal", "non_guaranteed_renewal"}
        else frozenset()
    )
    inherited_matches = inherited.intersection(allowed)
    if inherited_matches:
        return (
            "matched",
            f"{dimension}: {actual} 通过上位关系命中 {sorted(inherited_matches)}",
        )
    return "excluded", f"{dimension}: {actual} 不在 {sorted(allowed)}"


def _renewal_condition(product_tags: ProductTags) -> Optional[str]:
    renewal_type = _known_enum_value(product_tags.renewal_type)
    if renewal_type is None:
        return None
    if renewal_type == "none":
        return "no_renewal"
    if renewal_type == "guaranteed":
        return "guaranteed_renewal"
    if renewal_type == "non_guaranteed":
        return "non_guaranteed_renewal"
    return "has_renewal"


def _risk_trigger_value(product_tags: ProductTags, trigger: str) -> Optional[bool]:
    if trigger == "guaranteed_renewal":
        renewal_type = _known_enum_value(product_tags.renewal_type)
        if renewal_type is None:
            return None
        return renewal_type == "guaranteed"
    if trigger == "accidental_medical_coverage":
        if "accidental_medical" in product_tags.coverage_components:
            return True
        return None
    field_name = _SPECIAL_PRODUCT_FIELDS.get(trigger)
    return getattr(product_tags, field_name) if field_name else None


def match_regulation_applicability(
    product_tags: ProductTags,
    regulation: RegulationApplicability,
) -> ApplicabilityResult:
    """按主体与风险旁路判断适用性；只有所有保留路径均明确失败才排除。"""
    dimensions = (
        ("line", regulation.lines, _known_enum_value(product_tags.line)),
        ("subtype", regulation.subtypes, _known_enum_value(product_tags.primary_subtype)),
        ("design_type", regulation.design_types, _known_enum_value(product_tags.design_type)),
        ("term_class", regulation.term_classes, _known_enum_value(product_tags.term_class)),
        ("customer_scope", regulation.customer_scopes, _known_enum_value(product_tags.customer_scope)),
        ("contract_role", regulation.contract_roles, _known_enum_value(product_tags.contract_role)),
        ("renewal_condition", regulation.renewal_conditions, _renewal_condition(product_tags)),
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

    if regulation.special_features:
        feature_values = tuple(
            (
                feature,
                getattr(product_tags, _SPECIAL_PRODUCT_FIELDS[feature]),
            )
            for feature in sorted(regulation.special_features)
        )
        for feature, actual in feature_values:
            reasons.append(
                f"special_feature.{feature}: "
                + (
                    "命中"
                    if actual is True
                    else "明确不满足"
                    if actual is False
                    else "产品标签未知"
                )
            )
        if any(actual is True for _, actual in feature_values):
            matched.append("special_feature")
            reasons.append("special_feature: 同维度多值按 OR，至少一个值命中")
        elif any(actual is None for _, actual in feature_values):
            indeterminate.append("special_feature")
            reasons.append("special_feature: 同维度没有已知命中且存在未知值，保守保留")
        else:
            excluded.append("special_feature")
            reasons.append("special_feature: 同维度所有允许值均明确不满足")

    subject_present = any((
        regulation.lines,
        regulation.subtypes,
        regulation.design_types,
        regulation.term_classes,
        regulation.customer_scopes,
        regulation.contract_roles,
        regulation.renewal_conditions,
        regulation.special_features,
        regulation.unknown_tags,
    ))
    subject_excluded = tuple(excluded)
    subject_indeterminate = tuple(indeterminate)
    risk_matched = False
    risk_unknown = False
    risk_explicitly_absent = False
    if regulation.risk_triggers:
        trigger_values = tuple(
            (trigger, _risk_trigger_value(product_tags, trigger))
            for trigger in sorted(regulation.risk_triggers)
        )
        risk_matched = any(value is True for _, value in trigger_values)
        risk_unknown = not risk_matched and any(
            value is None for _, value in trigger_values
        )
        reasons.extend(
            f"risk_trigger.{trigger}: "
            + (
                "命中，阻止常规标签冲突造成漏检"
                if value is True
                else "明确未命中"
                if value is False
                else "未识别风险触发标签，保守保留"
                if trigger in regulation.unknown_risk_triggers
                else "产品事实未知，保守保留"
            )
            for trigger, value in trigger_values
        )
        if risk_matched:
            matched.append("risk_trigger")
        elif risk_unknown:
            if subject_excluded or not subject_present:
                indeterminate.append("risk_trigger")
        else:
            risk_explicitly_absent = True
            if not subject_present:
                excluded.append("risk_trigger")

    if regulation.normative_requirements:
        reasons.append(
            "检查目标标签仅供审核判断，不参与适用性过滤: "
            f"{sorted(regulation.normative_requirements)}"
        )

    if regulation.unknown_tags and not risk_matched:
        indeterminate.append("unknown_regulation_tags")
        reasons.append(f"未识别法规标签 {sorted(regulation.unknown_tags)}，不据此排除")

    bypassed = subject_excluded if risk_matched or risk_unknown else ()
    if bypassed:
        reasons.append(
            "风险触发旁路保留，忽略常规冲突维度 "
            f"{list(bypassed)}"
        )
        excluded = [item for item in excluded if item not in subject_excluded]

    if risk_matched:
        indeterminate = [
            item for item in indeterminate
            if item not in subject_indeterminate
            and item != "unknown_regulation_tags"
        ]
    elif risk_unknown and not subject_excluded:
        reasons.append("常规主体路径未冲突，无需依赖未知的风险触发旁路")
    elif risk_explicitly_absent and not subject_excluded:
        reasons.append("风险触发明确未命中，但常规主体路径仍成立")

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
