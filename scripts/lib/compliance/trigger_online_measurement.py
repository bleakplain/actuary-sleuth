"""Prepare and execute the frozen online trigger-context probe."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Literal, Mapping, Optional, Sequence, Tuple

from lib.common.compliance_audit import (
    ProductEvidenceStrength,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationDecisionStatus,
    RegulationObligation,
    RegulationTriggerSpec,
    RoutedClause,
    TriggerStatus,
)
from lib.compliance.audit_pipeline import AuditPipelineRequest, run_audit_pipeline
from lib.compliance.auditor import (
    build_audit_messages,
    build_batch_audit_messages,
    split_audit_package,
)
from lib.compliance.package_measurement import (
    build_audit_clause_snapshots,
    list_applicable_regulation_units,
)
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalCoverage,
    RegulationRetrievalOutcome,
)
from lib.compliance.regulation_trigger_metadata import (
    parse_regulation_trigger_metadata,
)
from lib.compliance.regulation_units import RegulationUnit
from lib.doc_parser import parse_product_document
from lib.rag_engine.kb_rebuild import load_catalog_rows
from lib.rag_engine.kb_identity import stable_catalog_sha256


ProbeArm = Literal["A", "C"]
RatePairStage = Literal["rate_dynamic_c", "rate_full_a"]
APPROVED_ONLINE_PLAN_SHA256 = (
    "b93d46e2ea0efc916ff22404aa901b626a182aa494478fcc0015f088ad848d4d"
)
APPROVED_RATE_PAIR_PLAN_SHA256 = (
    "ec1efcb5d36b6c7c863340961f1a191b5d05377e7bf9c22e6e65b66f77f1449f"
)
APPROVED_RATE_SINGLE_PLAN_SHA256 = (
    "12db60aafdd9cb12ee8b23f2edff32f308ac860cbf48f71dce170168b3867605"
)
APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256 = (
    "2a502198e55d9087b1aab9667f5da3e070bc6f8857bbba200d12b609257ac65e"
)
APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256 = (
    "b0037337e33e555edcb73cac8286af405cc18e52622f56cac0d7cd0f70e088df"
)
RATE_SINGLE_UNIT_ID = (
    "regulation-unit:1eaabf6dcf068b4108d8268e9c317fcb4ff2dd7685be010dc21d7e179b1d32f1"
)
RATE_OBLIGATION_DUAL_UNIT_IDS = (
    RATE_SINGLE_UNIT_ID,
    "regulation-unit:2aeabccb65ebb8bf692709fb4de7e08ccef2880428ea0b931dbee600bdea917f",
)
_RATE_SINGLE_REGULATION_CHUNK_ID = (
    "kb-chunk:bf776c0c207cd66e40ec94db664f9c2ac7c57369cbd2d7764c55a7afa95b33a4"
)
_RATE_OBLIGATION_DUAL_REGULATION_CHUNK_IDS = (
    _RATE_SINGLE_REGULATION_CHUNK_ID,
    "kb-chunk:43dbc6cf0206f7dfaffecb474fcee189431be2e00f5455947ee7723611130164",
)
_RATE_SINGLE_PRODUCT_CLAUSE_ID = (
    "clause_d2ff0389f54cb85e7d14a6aae5fd3d57"
)
_RATE_PAIR_SCHEMA_VERSION = "trigger-online-rate-pair-v1"
_RATE_SINGLE_SCHEMA_VERSION = "trigger-online-rate-single-v1"
_RATE_OBLIGATION_DUAL_SCHEMA_VERSION = "trigger-online-rate-obligation-dual-v2"
_RATE_OBLIGATION_SINGLE_SCHEMA_VERSION = "trigger-online-rate-obligation-single-v2"
_FULL_DOCUMENT_SEGMENT_LIMIT = 80_000


@dataclass(frozen=True)
class OnlineProbeLimits:
    max_seconds: float
    outer_watchdog_seconds: float
    max_total_tokens: int
    max_physical_calls: int
    max_batch_units: int


@dataclass(frozen=True)
class AuthorizedProbeProduct:
    sample_id: str
    sha256: str


@dataclass(frozen=True)
class ProbeTriggerMetadata:
    unit_id: str
    specs: Tuple[RegulationTriggerSpec, ...]


@dataclass(frozen=True)
class OnlineProbeCase:
    case_id: str
    sample_id: str
    unit_ids: Tuple[str, ...]
    trigger_metadata: Tuple[ProbeTriggerMetadata, ...]
    canary_dynamic_skip: bool = False

    def specs_for(self, unit_id: str) -> Optional[Tuple[RegulationTriggerSpec, ...]]:
        return next(
            (item.specs for item in self.trigger_metadata if item.unit_id == unit_id),
            None,
        )


@dataclass(frozen=True)
class OnlineProbePlan:
    schema_version: str
    sha256: str
    kb_version: str
    product_manifest_sha256: str
    kb_build_manifest_sha256: str
    kb_catalog_sha256: str
    provider: str
    model: str
    limits: OnlineProbeLimits
    authorized_products: Tuple[AuthorizedProbeProduct, ...]
    cases: Tuple[OnlineProbeCase, ...]

    @property
    def unit_ids(self) -> Tuple[str, ...]:
        return tuple(unit_id for case in self.cases for unit_id in case.unit_ids)


@dataclass(frozen=True)
class RatePairTheoreticalLimits:
    max_seconds: float
    outer_watchdog_seconds: float
    max_total_tokens: int
    max_physical_calls: int


@dataclass(frozen=True)
class ProbeObligationCatalog:
    unit_id: str
    obligations: Tuple[RegulationObligation, ...]


@dataclass(frozen=True)
class RatePairProbePlan:
    """Freeze the smaller C-then-A experiment without changing its base plan."""

    schema_version: str
    sha256: str
    base_plan_sha256: str
    evidence_protocol_version: str
    case_id: str
    sample_id: str
    required_unit_ids: Tuple[str, ...]
    dynamic_group_id: str
    full_group_id: str
    allowed_stages: Tuple[RatePairStage, ...]
    allowed_endpoint_host: str
    http_timeout_cap_seconds: float
    limits_per_stage: OnlineProbeLimits
    pair_theoretical_limits: RatePairTheoreticalLimits
    obligation_catalogs: Tuple[ProbeObligationCatalog, ...] = ()

    def group_id_for(self, stage: RatePairStage) -> str:
        if stage not in self.allowed_stages:
            raise ValueError(f"冻结overlay不允许运行阶段: {stage}")
        return (
            self.dynamic_group_id
            if stage == "rate_dynamic_c"
            else self.full_group_id
        )

    @property
    def single_dynamic_only(self) -> bool:
        return self.schema_version == _RATE_SINGLE_SCHEMA_VERSION

    @property
    def obligation_dual_only(self) -> bool:
        return self.schema_version == _RATE_OBLIGATION_DUAL_SCHEMA_VERSION

    @property
    def obligation_single_only(self) -> bool:
        return self.schema_version == _RATE_OBLIGATION_SINGLE_SCHEMA_VERSION

    @property
    def obligation_experiment(self) -> bool:
        return self.obligation_dual_only or self.obligation_single_only

    @property
    def budget_scope(self) -> str:
        return (
            "single_dynamic_stage"
            if self.single_dynamic_only
            else "obligation_dual_stage"
            if self.obligation_dual_only
            else "obligation_single_stage"
            if self.obligation_single_only
            else "independent_per_stage"
        )


@dataclass(frozen=True)
class OnlineProbeSegmentEstimate:
    source_segment_index: int
    execution_order: int
    segment_index: int
    prompt_chars: int
    prompt_utf8_bytes: int
    max_output_tokens: int


@dataclass(frozen=True)
class PreparedOnlineProbeGroup:
    group_id: str
    case_id: str
    sample_id: str
    arm: ProbeArm
    packages: Tuple[RegulationAuditPackage, ...]
    full_document_fallback: bool
    prompt_chars: int
    prompt_utf8_bytes: int
    max_output_tokens: int
    max_prompt_length: int
    primary_segment_count: int
    reuses_group_id: str = ""
    primary_segments: Tuple[OnlineProbeSegmentEstimate, ...] = ()
    http_timeout_cap_seconds: float = 45.0
    evidence_repair_enabled: bool = True


@dataclass(frozen=True)
class SkippedDynamicCanary:
    case_id: str
    sample_id: str
    unit_id: str
    trigger_status: str
    trigger_reasons: Tuple[str, ...]


@dataclass(frozen=True)
class PreparedOnlineProbe:
    plan: OnlineProbePlan
    groups: Tuple[PreparedOnlineProbeGroup, ...]
    skipped_dynamic_canaries: Tuple[SkippedDynamicCanary, ...]
    product_manifest_path: str
    kb_build_manifest_path: str

    @property
    def planned_provider_response_floor(self) -> int:
        return sum(group.primary_segment_count for group in self.groups)

    @property
    def planned_provider_response_ceiling(self) -> int:
        return self.planned_provider_response_floor + sum(
            len(group.packages) > 1
            and not group.reuses_group_id
            and group.evidence_repair_enabled
            for group in self.groups
        )

    def summary(self) -> Mapping[str, object]:
        selected_unit_ids = tuple(dict.fromkeys(
            package.regulation.regulation_unit_id
            for group in self.groups
            for package in group.packages
        ))
        return {
            "schema_version": self.plan.schema_version,
            "plan_sha256": self.plan.sha256,
            "kb_version": self.plan.kb_version,
            "provider": self.plan.provider,
            "model": self.plan.model,
            "product_manifest_sha256": self.plan.product_manifest_sha256,
            "kb_build_manifest_sha256": self.plan.kb_build_manifest_sha256,
            "kb_catalog_sha256": self.plan.kb_catalog_sha256,
            "product_manifest_path": self.product_manifest_path,
            "kb_build_manifest_path": self.kb_build_manifest_path,
            "authorized_products": [
                {"sample_id": item.sample_id, "sha256": item.sha256}
                for item in self.plan.authorized_products
            ],
            "limits": {
                "max_seconds": self.plan.limits.max_seconds,
                "outer_watchdog_seconds": self.plan.limits.outer_watchdog_seconds,
                "max_total_tokens": self.plan.limits.max_total_tokens,
                "max_physical_calls": self.plan.limits.max_physical_calls,
                "max_batch_units": self.plan.limits.max_batch_units,
            },
            "fixed_unit_count": len(selected_unit_ids),
            "planned_group_count": len(self.groups),
            "planned_provider_response_floor": (
                self.planned_provider_response_floor
            ),
            "planned_provider_response_ceiling": (
                self.planned_provider_response_ceiling
            ),
            "context_expansion_enabled": False,
            "full_document_repair_enabled": False,
            "skipped_dynamic_canary_count": len(self.skipped_dynamic_canaries),
            "groups": [
                {
                    "group_id": group.group_id,
                    "sample_id": group.sample_id,
                    "arm": group.arm,
                    "unit_ids": [
                        package.regulation.regulation_unit_id
                        for package in group.packages
                    ],
                    "full_document_fallback": group.full_document_fallback,
                    "evidence_repair_enabled": group.evidence_repair_enabled,
                    "prompt_chars": group.prompt_chars,
                    "prompt_utf8_bytes": group.prompt_utf8_bytes,
                    "max_output_tokens": group.max_output_tokens,
                    "max_prompt_length": group.max_prompt_length,
                    "http_timeout_cap_seconds": (
                        group.http_timeout_cap_seconds
                    ),
                    "primary_segment_count": group.primary_segment_count,
                    "reuses_group_id": group.reuses_group_id,
                    "actual_external_prompt_chars_planned": (
                        0 if group.reuses_group_id else group.prompt_chars
                    ),
                    "actual_external_prompt_utf8_bytes_planned": (
                        0 if group.reuses_group_id else group.prompt_utf8_bytes
                    ),
                    "submitted_body_clause_count": sum(
                        routed.submitted and _has_body(routed)
                        for routed in (
                            group.packages[0].clauses if group.packages else ()
                        )
                    ),
                    "submitted_body_chars": sum(
                        len(routed.clause.text)
                        for routed in (
                            group.packages[0].clauses if group.packages else ()
                        )
                        if routed.submitted and _has_body(routed)
                    ),
                    "regulation_units": [
                        {
                            "unit_id": package.regulation.regulation_unit_id,
                            "law_name": package.regulation.law_name,
                            "article_number": package.regulation.article_number,
                            "source_file": package.regulation.source_file,
                            "chunk_ids": [
                                chunk.chunk_id
                                for chunk in package.regulation.chunks
                            ],
                        }
                        for package in group.packages
                    ],
                    "primary_segments": [
                        {
                            "segment_index": segment.segment_index,
                            "source_segment_index": segment.source_segment_index,
                            "execution_order": segment.execution_order,
                            "prompt_chars": segment.prompt_chars,
                            "prompt_utf8_bytes": segment.prompt_utf8_bytes,
                            "max_output_tokens": segment.max_output_tokens,
                        }
                        for segment in group.primary_segments
                    ],
                }
                for group in self.groups
            ],
            "skipped_dynamic_canaries": [
                {
                    "case_id": item.case_id,
                    "sample_id": item.sample_id,
                    "unit_id": item.unit_id,
                    "trigger_status": item.trigger_status,
                    "trigger_reasons": list(item.trigger_reasons),
                }
                for item in self.skipped_dynamic_canaries
            ],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")
    return value.strip()


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} 必须是正整数")
    return value


def _positive_float(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} 必须是正数")
    return float(value)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label}必须是布尔值")
    return value


def _parse_obligation(value: Mapping[str, object]) -> RegulationObligation:
    automated_decision_allowed = _boolean(
        value.get("automated_decision_allowed"),
        "obligation automated_decision_allowed",
    )
    raw_reason = value.get("insufficient_reason")
    if not isinstance(raw_reason, str):
        raise ValueError("obligation insufficient_reason必须是字符串")
    insufficient_reason = raw_reason.strip()
    if not automated_decision_allowed and not insufficient_reason:
        raise ValueError("禁止自动判断的义务必须配置降级理由")
    return RegulationObligation(
        obligation_id=_text(value.get("obligation_id"), "obligation_id"),
        requirement=_text(value.get("requirement"), "obligation requirement"),
        automated_decision_allowed=automated_decision_allowed,
        insufficient_reason=insufficient_reason,
    )


def load_online_probe_plan(path: Path) -> OnlineProbePlan:
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), "在线计划")
    raw_limits = _mapping(raw.get("limits"), "limits")
    limits = OnlineProbeLimits(
        max_seconds=_positive_float(raw_limits.get("max_seconds"), "max_seconds"),
        outer_watchdog_seconds=_positive_float(
            raw_limits.get("outer_watchdog_seconds"),
            "outer_watchdog_seconds",
        ),
        max_total_tokens=_positive_int(
            raw_limits.get("max_total_tokens"),
            "max_total_tokens",
        ),
        max_physical_calls=_positive_int(
            raw_limits.get("max_physical_calls"),
            "max_physical_calls",
        ),
        max_batch_units=_positive_int(
            raw_limits.get("max_batch_units"),
            "max_batch_units",
        ),
    )
    if limits.max_seconds >= limits.outer_watchdog_seconds:
        raise ValueError("内部模型预算必须小于外部进程 watchdog")
    authorized = tuple(
        AuthorizedProbeProduct(
            sample_id=_text(
                _mapping(item, "authorized_products item").get("sample_id"),
                "authorized sample_id",
            ),
            sha256=_text(
                _mapping(item, "authorized_products item").get("sha256"),
                "authorized sha256",
            ),
        )
        for item in _sequence(raw.get("authorized_products"), "authorized_products")
    )
    cases = []
    for raw_case in _sequence(raw.get("cases"), "cases"):
        case = _mapping(raw_case, "case")
        unit_ids = tuple(
            _text(item, "unit_id") for item in _sequence(case.get("unit_ids"), "unit_ids")
        )
        metadata = []
        for raw_item in _sequence(case.get("trigger_metadata", []), "trigger_metadata"):
            item = _mapping(raw_item, "trigger_metadata item")
            metadata.append(ProbeTriggerMetadata(
                unit_id=_text(item.get("unit_id"), "trigger unit_id"),
                specs=parse_regulation_trigger_metadata(
                    _mapping(item.get("draft_metadata", {}), "draft_metadata")
                ),
            ))
        cases.append(OnlineProbeCase(
            case_id=_text(case.get("case_id"), "case_id"),
            sample_id=_text(case.get("sample_id"), "case sample_id"),
            unit_ids=unit_ids,
            trigger_metadata=tuple(metadata),
            canary_dynamic_skip=case.get("canary_dynamic_skip") is True,
        ))
    plan = OnlineProbePlan(
        schema_version=_text(raw.get("schema_version"), "schema_version"),
        sha256=_sha256(path),
        kb_version=_text(raw.get("kb_version"), "kb_version"),
        product_manifest_sha256=_text(
            raw.get("product_manifest_sha256"),
            "product_manifest_sha256",
        ),
        kb_build_manifest_sha256=_text(
            raw.get("kb_build_manifest_sha256"),
            "kb_build_manifest_sha256",
        ),
        kb_catalog_sha256=_text(
            raw.get("kb_catalog_sha256"),
            "kb_catalog_sha256",
        ),
        provider=_text(raw.get("provider"), "provider"),
        model=_text(raw.get("model"), "model"),
        limits=limits,
        authorized_products=authorized,
        cases=tuple(cases),
    )
    _validate_plan(plan)
    return plan


def load_rate_pair_probe_plan(path: Path) -> RatePairProbePlan:
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), "两阶段在线计划")
    schema_version = _text(raw.get("schema_version"), "schema_version")
    raw_stages = _mapping(raw.get("stages"), "stages")
    raw_limits = _mapping(raw.get("limits_per_stage"), "limits_per_stage")
    limits = OnlineProbeLimits(
        max_seconds=_positive_float(raw_limits.get("max_seconds"), "max_seconds"),
        outer_watchdog_seconds=_positive_float(
            raw_limits.get("outer_watchdog_seconds"),
            "outer_watchdog_seconds",
        ),
        max_total_tokens=_positive_int(
            raw_limits.get("max_total_tokens"),
            "max_total_tokens",
        ),
        max_physical_calls=_positive_int(
            raw_limits.get("max_physical_calls"),
            "max_physical_calls",
        ),
        max_batch_units=_positive_int(
            raw_limits.get("max_batch_units"),
            "max_batch_units",
        ),
    )
    raw_pair_limits = _mapping(
        raw.get("pair_theoretical_limits"),
        "pair_theoretical_limits",
    )
    pair_limits = RatePairTheoreticalLimits(
        max_seconds=_positive_float(
            raw_pair_limits.get("max_seconds"),
            "pair max_seconds",
        ),
        outer_watchdog_seconds=_positive_float(
            raw_pair_limits.get("outer_watchdog_seconds"),
            "pair outer_watchdog_seconds",
        ),
        max_total_tokens=_positive_int(
            raw_pair_limits.get("max_total_tokens"),
            "pair max_total_tokens",
        ),
        max_physical_calls=_positive_int(
            raw_pair_limits.get("max_physical_calls"),
            "pair max_physical_calls",
        ),
    )
    obligation_catalogs = tuple(
        ProbeObligationCatalog(
            unit_id=_text(
                catalog.get("unit_id"),
                "obligation_catalog unit_id",
            ),
            obligations=tuple(
                _parse_obligation(obligation)
                for raw_obligation in _sequence(
                    catalog.get("obligations"),
                    "obligation_catalog obligations",
                )
                for obligation in (
                    _mapping(raw_obligation, "obligation item"),
                )
            ),
        )
        for raw_catalog in _sequence(
            raw.get("obligation_catalogs", []),
            "obligation_catalogs",
        )
        for catalog in (_mapping(raw_catalog, "obligation catalog"),)
    )
    plan = RatePairProbePlan(
        schema_version=schema_version,
        sha256=_sha256(path),
        base_plan_sha256=_text(
            raw.get("base_plan_sha256"),
            "base_plan_sha256",
        ),
        evidence_protocol_version=_text(
            raw.get("evidence_protocol_version"),
            "evidence_protocol_version",
        ),
        case_id=_text(raw.get("case_id"), "case_id"),
        sample_id=_text(raw.get("sample_id"), "sample_id"),
        required_unit_ids=tuple(
            _text(item, "required_unit_id")
            for item in _sequence(raw.get("required_unit_ids"), "required_unit_ids")
        ),
        dynamic_group_id=_text(
            raw_stages.get("rate_dynamic_c"),
            "rate_dynamic_c group_id",
        ),
        full_group_id=(
            ""
            if schema_version in {
                _RATE_SINGLE_SCHEMA_VERSION,
                _RATE_OBLIGATION_DUAL_SCHEMA_VERSION,
                _RATE_OBLIGATION_SINGLE_SCHEMA_VERSION,
            }
            else _text(
                raw_stages.get("rate_full_a"),
                "rate_full_a group_id",
            )
        ),
        allowed_stages=(
            ("rate_dynamic_c",)
            if schema_version in {
                _RATE_SINGLE_SCHEMA_VERSION,
                _RATE_OBLIGATION_DUAL_SCHEMA_VERSION,
                _RATE_OBLIGATION_SINGLE_SCHEMA_VERSION,
            }
            else ("rate_dynamic_c", "rate_full_a")
        ),
        allowed_endpoint_host=_text(
            raw.get("allowed_endpoint_host"),
            "allowed_endpoint_host",
        ),
        http_timeout_cap_seconds=_positive_float(
            raw.get("http_timeout_cap_seconds", 45),
            "http_timeout_cap_seconds",
        ),
        limits_per_stage=limits,
        pair_theoretical_limits=pair_limits,
        obligation_catalogs=obligation_catalogs,
    )
    _validate_rate_pair_plan(plan)
    return plan


def _validate_rate_pair_plan(plan: RatePairProbePlan) -> None:
    if plan.schema_version == _RATE_PAIR_SCHEMA_VERSION:
        if plan.sha256 != APPROVED_RATE_PAIR_PLAN_SHA256:
            raise ValueError("两阶段在线计划不属于已审核冻结版本")
        if len(plan.required_unit_ids) != 3 or len(set(plan.required_unit_ids)) != 3:
            raise ValueError("两阶段在线计划必须冻结3个不重复法规单元")
        if plan.dynamic_group_id == plan.full_group_id:
            raise ValueError("两阶段在线计划的C组和A组不得相同")
        if not plan.full_group_id.endswith(":A"):
            raise ValueError("两阶段在线计划的全文组必须是A组")
        if plan.allowed_stages != ("rate_dynamic_c", "rate_full_a"):
            raise ValueError("两阶段在线计划必须同时冻结C和A")
        if plan.http_timeout_cap_seconds != 45:
            raise ValueError("原三条pair必须保持45秒HTTP timeout cap")
        if plan.obligation_catalogs:
            raise ValueError("原三条pair不得携带逐项义务实验目录")
        expected_stage_multiplier = 2
    elif plan.schema_version == _RATE_SINGLE_SCHEMA_VERSION:
        if plan.sha256 != APPROVED_RATE_SINGLE_PLAN_SHA256:
            raise ValueError("单条在线计划不属于已审核冻结版本")
        if (
            plan.case_id != "rate-adjustment-real-001"
            or plan.sample_id != "real-001"
            or plan.required_unit_ids != (RATE_SINGLE_UNIT_ID,)
            or plan.full_group_id
            or plan.allowed_stages != ("rate_dynamic_c",)
            or plan.http_timeout_cap_seconds != 75
        ):
            raise ValueError("单条在线计划只能冻结real-001费率调整第2条动态C")
        limits = plan.limits_per_stage
        if (
            limits.max_seconds != 285
            or limits.outer_watchdog_seconds != 300
            or limits.max_total_tokens != 125_000
            or limits.max_physical_calls != 1
            or limits.max_batch_units != 1
        ):
            raise ValueError("单条在线计划预算必须冻结为125k/1call/285s+300s")
        if plan.obligation_catalogs:
            raise ValueError("原单条在线计划不得携带逐项义务实验目录")
        expected_stage_multiplier = 1
    elif plan.schema_version == _RATE_OBLIGATION_DUAL_SCHEMA_VERSION:
        if plan.sha256 != APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256:
            raise ValueError("双法规逐项义务计划不属于已审核冻结版本")
        if (
            plan.case_id != "rate-adjustment-real-001"
            or plan.sample_id != "real-001"
            or plan.required_unit_ids != RATE_OBLIGATION_DUAL_UNIT_IDS
            or plan.full_group_id
            or plan.allowed_stages != ("rate_dynamic_c",)
            or plan.http_timeout_cap_seconds != 75
        ):
            raise ValueError("双法规计划只能冻结real-001费率调整第2、3条动态C")
        limits = plan.limits_per_stage
        if (
            limits.max_seconds != 285
            or limits.outer_watchdog_seconds != 300
            or limits.max_total_tokens != 175_000
            or limits.max_physical_calls != 1
            or limits.max_batch_units != 2
        ):
            raise ValueError("双法规逐项义务预算必须冻结为175k/1call/285s+300s")
        catalog_ids = tuple(item.unit_id for item in plan.obligation_catalogs)
        if catalog_ids != plan.required_unit_ids:
            raise ValueError("双法规逐项义务目录必须按法规顺序完整配置")
        for catalog in plan.obligation_catalogs:
            obligation_ids = tuple(
                item.obligation_id for item in catalog.obligations
            )
            if not obligation_ids or len(set(obligation_ids)) != len(obligation_ids):
                raise ValueError("逐项义务目录不能为空或包含重复ID")
        expected_stage_multiplier = 1
    elif plan.schema_version == _RATE_OBLIGATION_SINGLE_SCHEMA_VERSION:
        if plan.sha256 != APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256:
            raise ValueError("单法规逐项义务计划不属于已审核冻结版本")
        if (
            plan.case_id != "rate-adjustment-real-001"
            or plan.sample_id != "real-001"
            or plan.required_unit_ids != (RATE_SINGLE_UNIT_ID,)
            or plan.full_group_id
            or plan.allowed_stages != ("rate_dynamic_c",)
            or plan.http_timeout_cap_seconds != 75
        ):
            raise ValueError("单法规逐项义务计划只能冻结real-001费率调整第2条动态C")
        limits = plan.limits_per_stage
        if (
            limits.max_seconds != 285
            or limits.outer_watchdog_seconds != 300
            or limits.max_total_tokens != 125_000
            or limits.max_physical_calls != 1
            or limits.max_batch_units != 1
        ):
            raise ValueError("单法规逐项义务预算必须冻结为125k/1call/285s+300s")
        if (
            len(plan.obligation_catalogs) != 1
            or plan.obligation_catalogs[0].unit_id != RATE_SINGLE_UNIT_ID
            or tuple(item.obligation_id for item in plan.obligation_catalogs[0].obligations)
            != tuple(f"OBL{index:03d}" for index in range(1, 7))
        ):
            raise ValueError("单法规逐项义务目录必须完整冻结第2条六项义务")
        expected_stage_multiplier = 1
    else:
        raise ValueError("法规在线overlay schema未获批准")
    if plan.base_plan_sha256 != APPROVED_ONLINE_PLAN_SHA256:
        raise ValueError("法规在线overlay引用了未批准的基础计划")
    if not plan.dynamic_group_id.endswith(":C"):
        raise ValueError("法规在线overlay的动态组必须是C组")
    if plan.allowed_endpoint_host != "open.bigmodel.cn":
        raise ValueError("法规在线overlay必须冻结智谱官方主机")
    if plan.limits_per_stage.max_seconds >= (
        plan.limits_per_stage.outer_watchdog_seconds
    ):
        raise ValueError("内部模型预算必须小于外部watchdog")
    pair_limits = plan.pair_theoretical_limits
    limits = plan.limits_per_stage
    if (
        pair_limits.max_seconds
        != limits.max_seconds * expected_stage_multiplier
        or pair_limits.outer_watchdog_seconds
        != limits.outer_watchdog_seconds * expected_stage_multiplier
        or pair_limits.max_total_tokens
        != limits.max_total_tokens * expected_stage_multiplier
        or pair_limits.max_physical_calls
        != limits.max_physical_calls * expected_stage_multiplier
    ):
        raise ValueError("overlay理论上限与允许阶段数不一致")


def _validate_plan(plan: OnlineProbePlan) -> None:
    authorized_ids = tuple(item.sample_id for item in plan.authorized_products)
    if len(set(authorized_ids)) != len(authorized_ids):
        raise ValueError("授权产品 sample_id 重复")
    case_ids = tuple(item.case_id for item in plan.cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("在线案例 case_id 重复")
    if any(case.sample_id not in authorized_ids for case in plan.cases):
        raise ValueError("在线案例包含未授权产品")
    if len(plan.unit_ids) != 6 or len(set(plan.unit_ids)) != 6:
        raise ValueError("在线计划必须恰好冻结6个不重复法规单元")
    if sum(case.canary_dynamic_skip for case in plan.cases) != 1:
        raise ValueError("在线计划必须恰好包含1个动态跳过canary")
    for case in plan.cases:
        if not case.unit_ids:
            raise ValueError(f"{case.case_id} 未配置法规单元")
        if len(case.unit_ids) > plan.limits.max_batch_units:
            raise ValueError(f"{case.case_id} 超过单批法规上限")
        metadata_ids = tuple(item.unit_id for item in case.trigger_metadata)
        if len(set(metadata_ids)) != len(metadata_ids):
            raise ValueError(f"{case.case_id} 触发metadata重复")
        if any(unit_id not in case.unit_ids for unit_id in metadata_ids):
            raise ValueError(f"{case.case_id} 触发metadata引用案例外法规")


def _offline_auditor(
    packages: Iterable[RegulationAuditPackage],
    max_concurrency: int,
    deadline_seconds: float,
    on_decision: Optional[Callable[[RegulationAuditDecision, int, int], None]],
) -> Tuple[RegulationAuditDecision, ...]:
    del max_concurrency, deadline_seconds
    ordered = tuple(packages)
    decisions = tuple(
        RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.INSUFFICIENT_INFORMATION,
            reasoning="在线探测准备阶段占位，不代表法规结论。",
            suggestion="",
            regulation_evidence=(),
            product_evidence=(),
        )
        for package in ordered
    )
    if on_decision is not None:
        for completed, decision in enumerate(decisions, start=1):
            on_decision(decision, completed, len(decisions))
    return decisions


def _coverage(unit_count: int) -> RegulationRetrievalCoverage:
    return RegulationRetrievalCoverage(
        rag_available=False,
        catalog_available=True,
        semantic_available=False,
        registered_available=False,
        category_resolution="frozen_online_probe",
        complete_candidate_freeze=True,
        catalog_candidate_count=unit_count,
    )


def _inject_case_specs(
    units: Tuple[RegulationUnit, ...],
    case: OnlineProbeCase,
) -> Tuple[RegulationUnit, ...]:
    return tuple(
        replace(
            unit,
            trigger_specs=case.specs_for(unit.unit_id) or (),
            chunks=tuple(
                replace(
                    chunk,
                    trigger_specs=case.specs_for(unit.unit_id) or (),
                )
                for chunk in unit.chunks
            ),
        )
        for unit in units
    )


def _has_body(routed: RoutedClause) -> bool:
    return not routed.clause.container_only and bool(routed.clause.text.strip())


def _harmonize_submitted_clauses(
    packages: Tuple[RegulationAuditPackage, ...],
    selected_clause_ids: Sequence[str],
) -> Tuple[RegulationAuditPackage, ...]:
    selected = frozenset(selected_clause_ids)
    return tuple(
        replace(
            package,
            clauses=tuple(
                replace(
                    routed,
                    submitted=(
                        routed.clause.clause_id in selected
                        if _has_body(routed)
                        else False
                    ),
                )
                for routed in package.clauses
            ),
        )
        for package in packages
    )


def _build_group(
    case: OnlineProbeCase,
    arm: ProbeArm,
    packages: Tuple[RegulationAuditPackage, ...],
    full_document_fallback: bool,
    reuses_group_id: str = "",
    http_timeout_cap_seconds: float = 45.0,
    evidence_repair_enabled: bool = True,
) -> PreparedOnlineProbeGroup:
    initial_messages = (
        build_batch_audit_messages(packages)
        if len(packages) > 1
        else build_audit_messages(packages[0])
    )
    initial_prompt_chars = sum(
        len(message["content"]) for message in initial_messages
    )
    max_prompt_length = (
        _FULL_DOCUMENT_SEGMENT_LIMIT
        if len(packages) == 1 and arm == "A" and initial_prompt_chars > 60_000
        else 200_000
    )
    primary_packages = (
        split_audit_package(packages[0], max_prompt_length=max_prompt_length)
        if len(packages) == 1 else packages
    )
    indexed_primary_messages = (
        tuple(sorted(
            (
                (source_index, build_audit_messages(package))
                for source_index, package in enumerate(primary_packages, start=1)
            ),
            key=lambda item: sum(
                len(message["content"].encode("utf-8"))
                for message in item[1]
            ),
            reverse=True,
        ))
        if len(packages) == 1
        else ((1, build_batch_audit_messages(packages)),)
    )
    primary_messages = tuple(
        messages for _source_index, messages in indexed_primary_messages
    )
    prompt_chars = sum(
        len(message["content"])
        for request_messages in primary_messages
        for message in request_messages
    )
    prompt_utf8_bytes = sum(
        len(message["content"].encode("utf-8"))
        for request_messages in primary_messages
        for message in request_messages
    )
    primary_segment_count = (
        0 if reuses_group_id
        else len(primary_packages) if len(packages) == 1
        else 1
    )
    output_tokens_per_call = (
        4096 if len(packages) == 1
        else min(16_384, max(4096, len(packages) * 2048))
    )
    segment_estimates = tuple(
        OnlineProbeSegmentEstimate(
            source_segment_index=source_index,
            execution_order=execution_order,
            # Preserve the v2 report's execution-order meaning for compatibility.
            segment_index=execution_order,
            prompt_chars=sum(len(message["content"]) for message in messages),
            prompt_utf8_bytes=sum(
                len(message["content"].encode("utf-8")) for message in messages
            ),
            max_output_tokens=output_tokens_per_call,
        )
        for execution_order, (source_index, messages) in enumerate(
            indexed_primary_messages,
            start=1,
        )
    )
    return PreparedOnlineProbeGroup(
        group_id=f"{case.case_id}:{arm}",
        case_id=case.case_id,
        sample_id=case.sample_id,
        arm=arm,
        packages=packages,
        full_document_fallback=full_document_fallback,
        prompt_chars=prompt_chars,
        prompt_utf8_bytes=prompt_utf8_bytes,
        max_output_tokens=output_tokens_per_call * primary_segment_count,
        max_prompt_length=max_prompt_length,
        primary_segment_count=primary_segment_count,
        reuses_group_id=reuses_group_id,
        primary_segments=() if reuses_group_id else segment_estimates,
        http_timeout_cap_seconds=http_timeout_cap_seconds,
        evidence_repair_enabled=evidence_repair_enabled,
    )


def _manifest_products(path: Path) -> Mapping[str, Mapping[str, object]]:
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), "产品manifest")
    products = {}
    for item in _sequence(raw.get("products"), "manifest products"):
        product = _mapping(item, "manifest product")
        sample_id = _text(product.get("sample_id"), "manifest sample_id")
        if sample_id in products:
            raise ValueError(f"产品manifest sample_id重复: {sample_id}")
        products[sample_id] = product
    return products


def prepare_online_probe(
    plan_path: Path,
    product_manifest_path: Path,
    products_dir: Path,
    kb_dir: Path,
    *,
    loaded_plan: Optional[OnlineProbePlan] = None,
) -> PreparedOnlineProbe:
    plan = loaded_plan or load_online_probe_plan(plan_path)
    if loaded_plan is not None and _sha256(plan_path) != loaded_plan.sha256:
        raise ValueError("在线计划在校验后发生变化，拒绝继续")
    if _sha256(product_manifest_path) != plan.product_manifest_sha256:
        raise ValueError("产品manifest指纹不一致")
    kb_build_manifest_path = kb_dir / "references" / "v5-build-manifest.json"
    if _sha256(kb_build_manifest_path) != plan.kb_build_manifest_sha256:
        raise ValueError("KB构建manifest指纹不一致")
    manifest = _manifest_products(product_manifest_path)
    authorized = {item.sample_id: item.sha256 for item in plan.authorized_products}
    for sample_id, expected_sha256 in authorized.items():
        product = manifest.get(sample_id)
        if product is None:
            raise ValueError(f"授权产品不在manifest: {sample_id}")
        manifest_sha256 = _text(product.get("sha256"), f"{sample_id} sha256")
        if manifest_sha256 != expected_sha256:
            raise ValueError(f"授权产品manifest指纹不一致: {sample_id}")

    catalog = load_catalog_rows(kb_dir / plan.kb_version / "lancedb")
    if stable_catalog_sha256(catalog) != plan.kb_catalog_sha256:
        raise ValueError("KB实时法规目录指纹与已授权计划不一致")
    parsed_products: dict[str, tuple[AuditPipelineRequest, Tuple[RegulationUnit, ...]]] = {}
    groups = []
    skipped_canaries = []
    for case in plan.cases:
        if case.sample_id not in parsed_products:
            product = manifest[case.sample_id]
            file_name = _text(product.get("file_name"), f"{case.sample_id} file_name")
            source = products_dir / file_name
            if _sha256(source) != authorized[case.sample_id]:
                raise ValueError(f"产品文件指纹不一致: {case.sample_id}")
            document = parse_product_document(str(source))
            request = AuditPipelineRequest(
                product_name=document.product_name or file_name,
                document_content=document.canonical_text,
                product_tags=document.product_tags,
                clauses=build_audit_clause_snapshots(document),
                document_fingerprint=document.document_fingerprint,
                audit_input_fingerprint=document.audit_input_fingerprint,
                product_name_source=document.product_name_source,
                parse_warnings=tuple(document.warnings),
                coverage_attested=document.coverage_attested,
                coverage_attested_facts=document.coverage_attested_facts,
            )
            units = list_applicable_regulation_units(
                catalog,
                document.product_tags,
                plan.kb_version,
            )
            parsed_products[case.sample_id] = (request, units)
        request, applicable_units = parsed_products[case.sample_id]
        unit_map = {unit.unit_id: unit for unit in applicable_units}
        missing = tuple(unit_id for unit_id in case.unit_ids if unit_id not in unit_map)
        if missing:
            raise ValueError(
                f"{case.case_id} 法规不在当前产品适用候选: " + "、".join(missing)
            )
        units = _inject_case_specs(
            tuple(unit_map[unit_id] for unit_id in case.unit_ids),
            case,
        )
        if len({unit.source_file for unit in units}) != 1:
            raise ValueError(f"{case.case_id} 不能跨法规文件合批")
        outcome = RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=units,
            coverage=_coverage(len(units)),
            candidate_count=len(units),
        )
        pipeline = run_audit_pipeline(
            request,
            retriever=lambda *_args, _outcome=outcome: _outcome,
            package_auditor=_offline_auditor,
        )
        records = tuple(pipeline.records)
        if tuple(
            record.package.regulation.regulation_unit_id for record in records
        ) != case.unit_ids:
            raise ValueError(f"{case.case_id} 法规单元顺序或数量不一致")
        full_packages = tuple(record.package for record in records)
        dynamic_skip = all(
            record.package.trigger_evaluation is not None
            and record.package.trigger_evaluation.status is TriggerStatus.NOT_TRIGGERED
            for record in records
        )
        if case.canary_dynamic_skip:
            if not dynamic_skip:
                raise ValueError(f"{case.case_id} canary未形成安全not_triggered")
            for record in records:
                evaluation = record.package.trigger_evaluation
                if evaluation is None:
                    raise ValueError(f"{case.case_id} canary缺少触发trace")
                skipped_canaries.append(SkippedDynamicCanary(
                    case_id=case.case_id,
                    sample_id=case.sample_id,
                    unit_id=record.package.regulation.regulation_unit_id,
                    trigger_status=evaluation.status.value,
                    trigger_reasons=evaluation.reasons,
                ))
            groups.append(_build_group(case, "A", full_packages, False))
        elif dynamic_skip:
            raise ValueError(f"{case.case_id} 非canary法规被意外排除")
        else:
            selections = tuple(record.evidence_selection for record in records)
            config_valid = all(
                selection is not None and selection.config_valid
                for selection in selections
            )
            selected_ids = tuple(dict.fromkeys(
                clause_id
                for selection in selections
                if selection is not None
                for clause_id in selection.selected_clause_ids
            ))
            selected_body_ids = frozenset(
                routed.clause.clause_id
                for package in full_packages
                for routed in package.clauses
                if _has_body(routed) and routed.clause.clause_id in selected_ids
            )
            fallback = not config_valid or not selected_body_ids
            dynamic_packages = (
                full_packages
                if fallback
                else _harmonize_submitted_clauses(
                    full_packages,
                    tuple(selected_body_ids),
                )
            )
            # 先运行同案例中更大的全文臂，使保守的调用前预留不会因为
            # 动态臂已经消耗少量实际 token 而永久拒绝全文对照。
            full_group = _build_group(case, "A", full_packages, False)
            groups.append(full_group)
            groups.append(_build_group(
                case,
                "C",
                dynamic_packages,
                fallback,
                reuses_group_id=(
                    full_group.group_id
                    if fallback and dynamic_packages == full_packages else ""
                ),
            ))
    prepared = PreparedOnlineProbe(
        plan=plan,
        groups=tuple(groups),
        skipped_dynamic_canaries=tuple(skipped_canaries),
        product_manifest_path=str(product_manifest_path),
        kb_build_manifest_path=str(kb_build_manifest_path),
    )
    if (
        prepared.planned_provider_response_ceiling
        > plan.limits.max_physical_calls
    ):
        raise ValueError("在线计划最坏物理调用数超过冻结上限")
    return prepared


def _project_rate_single_dynamic_package(
    package: RegulationAuditPackage,
) -> RegulationAuditPackage:
    """Keep the full outline but submit only this task's audited strong clause."""
    if (
        package.input_index != 1
        or package.regulation.regulation_unit_id != RATE_SINGLE_UNIT_ID
        or len(package.regulation.chunks) != 1
        or package.regulation.chunks[0].chunk_id
        != _RATE_SINGLE_REGULATION_CHUNK_ID
    ):
        raise ValueError("单条动态C必须保持input_index=1及唯一法规chunk")
    strong_clause_ids = tuple(
        candidate.clause_id
        for candidate in package.product_evidence_candidates
        if candidate.strength is ProductEvidenceStrength.STRONG
    )
    if len(strong_clause_ids) != 1:
        raise ValueError("单条动态C必须恰好有一个STRONG产品证据候选")
    strong_clause_id = strong_clause_ids[0]
    matches = tuple(
        (index, routed)
        for index, routed in enumerate(package.clauses, start=1)
        if routed.clause.clause_id == strong_clause_id
    )
    if (
        len(matches) != 1
        or strong_clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
        or matches[0][0] != 14
        or matches[0][1].clause.number != "2.3"
        or matches[0][1].clause.title != "费率调整"
        or not _has_body(matches[0][1])
    ):
        raise ValueError("单条动态C的STRONG证据必须精确锁定2.3费率调整/P014")
    projected = replace(
        package,
        clauses=tuple(
            replace(
                routed,
                submitted=(routed.clause.clause_id == strong_clause_id),
            )
            for routed in package.clauses
        ),
    )
    submitted_body = tuple(
        routed for routed in projected.clauses
        if routed.submitted and _has_body(routed)
    )
    if len(submitted_body) != 1:
        raise ValueError("单条动态C必须且只能提交一个产品正文块")
    return projected


def _project_rate_obligation_dual_packages(
    packages: Mapping[str, RegulationAuditPackage],
    pair_plan: RatePairProbePlan,
) -> Tuple[RegulationAuditPackage, ...]:
    catalog_by_unit = {
        item.unit_id: item.obligations for item in pair_plan.obligation_catalogs
    }
    projected = []
    for index, unit_id in enumerate(pair_plan.required_unit_ids):
        package = packages.get(unit_id)
        if package is None:
            raise ValueError("双法规逐项义务计划缺少冻结法规单元")
        if (
            len(package.regulation.chunks) != 1
            or package.regulation.chunks[0].chunk_id
            != _RATE_OBLIGATION_DUAL_REGULATION_CHUNK_IDS[index]
        ):
            raise ValueError("双法规逐项义务计划的法规chunk不匹配")
        strong_clause_ids = tuple(
            candidate.clause_id
            for candidate in package.product_evidence_candidates
            if candidate.strength is ProductEvidenceStrength.STRONG
        )
        if strong_clause_ids != (_RATE_SINGLE_PRODUCT_CLAUSE_ID,):
            raise ValueError("双法规逐项义务计划必须只引用2.3费率调整强证据")
        clauses = tuple(
            replace(
                routed,
                submitted=(
                    routed.clause.clause_id == _RATE_SINGLE_PRODUCT_CLAUSE_ID
                ),
            )
            for routed in package.clauses
        )
        submitted = tuple(
            routed for routed in clauses if routed.submitted and _has_body(routed)
        )
        if (
            len(submitted) != 1
            or submitted[0].clause.clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
            or submitted[0].clause.number != "2.3"
            or submitted[0].clause.title != "费率调整"
        ):
            raise ValueError("双法规逐项义务计划必须只提交2.3费率调整正文")
        projected.append(replace(
            package,
            clauses=clauses,
            obligations=catalog_by_unit[unit_id],
        ))
    return tuple(projected)


def select_rate_pair_stage(
    prepared: PreparedOnlineProbe,
    pair_plan: RatePairProbePlan,
    stage: RatePairStage,
) -> PreparedOnlineProbe:
    """Narrow a fully validated base probe to one immutable pair stage."""
    approved_overlay_sha256 = (
        APPROVED_RATE_SINGLE_PLAN_SHA256
        if pair_plan.single_dynamic_only
        else APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256
        if pair_plan.obligation_single_only
        else APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256
        if pair_plan.obligation_dual_only
        else APPROVED_RATE_PAIR_PLAN_SHA256
    )
    if pair_plan.sha256 != approved_overlay_sha256:
        raise ValueError("法规在线overlay不属于已审核冻结版本")
    if prepared.plan.sha256 != pair_plan.base_plan_sha256:
        raise ValueError("法规在线overlay与已准备的基础计划不一致")
    if (
        not pair_plan.single_dynamic_only
        and not pair_plan.obligation_experiment
        and prepared.plan.limits != pair_plan.limits_per_stage
    ):
        raise ValueError("两阶段在线计划预算与基础计划不一致")
    expected_group_id = pair_plan.group_id_for(stage)
    case = next(
        (item for item in prepared.plan.cases if item.case_id == pair_plan.case_id),
        None,
    )
    if (
        case is None
        or case.sample_id != pair_plan.sample_id
    ):
        raise ValueError("法规在线overlay的案例或产品与基础计划不一致")
    if pair_plan.single_dynamic_only or pair_plan.obligation_experiment:
        if (
            stage != "rate_dynamic_c"
            or not set(pair_plan.required_unit_ids).issubset(case.unit_ids)
        ):
            raise ValueError("动态子集计划只能选择冻结费率调整法规")
    elif case.unit_ids != pair_plan.required_unit_ids:
        raise ValueError("两阶段在线计划的法规单元与基础计划不一致")
    matches = tuple(
        group for group in prepared.groups if group.group_id == expected_group_id
    )
    if len(matches) != 1:
        raise ValueError(f"两阶段在线计划未唯一找到目标组: {expected_group_id}")
    group = matches[0]
    source_unit_ids = tuple(
        package.regulation.regulation_unit_id for package in group.packages
    )
    expected_arm: ProbeArm = "C" if stage == "rate_dynamic_c" else "A"
    if (
        group.case_id != pair_plan.case_id
        or group.sample_id != pair_plan.sample_id
        or group.arm != expected_arm
        or source_unit_ids != case.unit_ids
        or group.reuses_group_id
    ):
        raise ValueError("法规在线overlay的来源组不符合冻结范围")
    if pair_plan.single_dynamic_only or pair_plan.obligation_experiment:
        if group.full_document_fallback:
            raise ValueError("冻结动态C不得使用全文回退")
        package_map = {
            package.regulation.regulation_unit_id: package
            for package in group.packages
        }
        packages = (
            tuple(
                _project_rate_single_dynamic_package(package_map[unit_id])
                for unit_id in pair_plan.required_unit_ids
            )
            if pair_plan.single_dynamic_only
            else _project_rate_obligation_dual_packages(package_map, pair_plan)
        )
        single_case = replace(
            case,
            unit_ids=pair_plan.required_unit_ids,
            trigger_metadata=tuple(
                item for item in case.trigger_metadata
                if item.unit_id in pair_plan.required_unit_ids
            ),
        )
        group = _build_group(
            single_case,
            "C",
            packages,
            False,
            http_timeout_cap_seconds=pair_plan.http_timeout_cap_seconds,
            evidence_repair_enabled=not pair_plan.obligation_experiment,
        )
    else:
        unit_ids = tuple(
            package.regulation.regulation_unit_id for package in group.packages
        )
        if unit_ids != pair_plan.required_unit_ids:
            raise ValueError("两阶段在线计划的目标组内容不符合冻结范围")
    selected_plan = (
        replace(prepared.plan, limits=pair_plan.limits_per_stage)
        if pair_plan.single_dynamic_only or pair_plan.obligation_experiment
        else prepared.plan
    )
    selected = replace(
        prepared,
        plan=selected_plan,
        groups=(group,),
        skipped_dynamic_canaries=(),
    )
    if (
        selected.planned_provider_response_ceiling
        > pair_plan.limits_per_stage.max_physical_calls
    ):
        raise ValueError("两阶段在线计划单阶段最坏物理调用数超过上限")
    if (
        (pair_plan.single_dynamic_only or pair_plan.obligation_experiment)
        and (
            selected.planned_provider_response_floor != 1
            or selected.planned_provider_response_ceiling != 1
        )
    ):
        raise ValueError("单条动态C必须恰好规划一次供应商响应")
    return selected
