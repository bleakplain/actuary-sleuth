"""Run the frozen online probe with physical-call admission control."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

from lib.common.compliance_audit import (
    BatchAuditAttemptTrace,
    ProductEvidenceStrength,
    RegulationAuditDecision,
    RegulationAuditPackage,
)
from lib.compliance.auditor import (
    audit_regulation_package,
    audit_regulation_package_batch,
    build_audit_messages,
    build_batch_audit_messages,
)
from lib.compliance.trigger_online_measurement import (
    APPROVED_ONLINE_PLAN_SHA256,
    APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256,
    APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256,
    APPROVED_RATE_PAIR_PLAN_SHA256,
    APPROVED_RATE_SINGLE_PLAN_SHA256,
    PreparedOnlineProbe,
    PreparedOnlineProbeGroup,
    RATE_OBLIGATION_DUAL_UNIT_IDS,
    RATE_SINGLE_UNIT_ID,
    RatePairProbePlan,
    RatePairStage,
)
from lib.llm.base import BaseLLMClient
from lib.llm.call_budget import CallBudgetController, CallBudgetSnapshot
from lib.llm.zhipu import ZhipuClient, ZhipuUsage


_APPROVED_EVIDENCE_PROTOCOL_VERSION = "task-scoped-evidence-id-v1"
_RATE_PAIR_SCHEMA_VERSION = "trigger-online-rate-pair-v1"
_RATE_SINGLE_SCHEMA_VERSION = "trigger-online-rate-single-v1"
_RATE_OBLIGATION_DUAL_SCHEMA_VERSION = "trigger-online-rate-obligation-dual-v2"
_RATE_OBLIGATION_SINGLE_SCHEMA_VERSION = "trigger-online-rate-obligation-single-v2"
_SHA256_HEX_CHARACTERS = frozenset("0123456789abcdef")
_RATE_SINGLE_REGULATION_CHUNK_ID = (
    "kb-chunk:bf776c0c207cd66e40ec94db664f9c2ac7c57369cbd2d7764c55a7afa95b33a4"
)
_RATE_SINGLE_PRODUCT_CLAUSE_ID = (
    "clause_d2ff0389f54cb85e7d14a6aae5fd3d57"
)
_RATE_SINGLE_GROUP_PROMPT_CHARS = 42_924
_RATE_SINGLE_GROUP_PROMPT_UTF8_BYTES = 53_638
_RATE_SINGLE_EXTERNAL_PROMPT_CHARS = 42_768
_RATE_SINGLE_EXTERNAL_PROMPT_UTF8_BYTES = 53_398
_RATE_SINGLE_EXTERNAL_MESSAGES_SHA256 = (
    "acf31e96e7d442563feb0fb5ae5e79ab8cb9ef5347e19cf8e8f8133cf9be1ab5"
)
_RATE_OBLIGATION_DUAL_REGULATION_CHUNK_IDS = (
    _RATE_SINGLE_REGULATION_CHUNK_ID,
    "kb-chunk:43dbc6cf0206f7dfaffecb474fcee189431be2e00f5455947ee7723611130164",
)
_RATE_OBLIGATION_DUAL_GROUP_PROMPT_CHARS = 49_076
_RATE_OBLIGATION_DUAL_GROUP_PROMPT_UTF8_BYTES = 62_710
_RATE_OBLIGATION_DUAL_EXTERNAL_MESSAGES_SHA256 = (
    "ee4a7931618e94a44befc0e9e9e7784e7a9826cdd50967443a8969b734e7dec2"
)
_RATE_OBLIGATION_SINGLE_GROUP_PROMPT_CHARS = 44_350
_RATE_OBLIGATION_SINGLE_GROUP_PROMPT_UTF8_BYTES = 55_656
_RATE_OBLIGATION_SINGLE_EXTERNAL_PROMPT_CHARS = 44_194
_RATE_OBLIGATION_SINGLE_EXTERNAL_PROMPT_UTF8_BYTES = 55_416
_RATE_OBLIGATION_SINGLE_EXTERNAL_MESSAGES_SHA256 = (
    "ccd0b385f82160155e34bd1a45624dfadaaaa82f88425de2c53933b802c9b9e5"
)


@dataclass(frozen=True)
class OnlineProbeUsage:
    responses: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def to_dict(self) -> Mapping[str, int]:
        return {
            "responses": self.responses,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class OnlineProbeUnreportedCallTrace:
    """Account for provider calls whose token usage was not returned."""

    stage: str
    requested_unit_ids: Tuple[str, ...]
    error: str
    physical_calls: int
    provider_reported_tokens: int
    budget_accounted_tokens: int
    unreported_reserved_settlement: int
    budget_before: CallBudgetSnapshot
    budget_after: CallBudgetSnapshot

    def to_dict(self) -> Mapping[str, object]:
        return {
            "stage": self.stage,
            "requested_unit_ids": list(self.requested_unit_ids),
            "error": self.error,
            "physical_calls": self.physical_calls,
            "provider_reported_tokens": self.provider_reported_tokens,
            "budget_accounted_tokens": self.budget_accounted_tokens,
            "unreported_reserved_settlement": (
                self.unreported_reserved_settlement
            ),
            "budget_before": _budget_dict(self.budget_before),
            "budget_after": _budget_dict(self.budget_after),
        }


@dataclass(frozen=True)
class OnlineProbeGroupResult:
    group_id: str
    case_id: str
    sample_id: str
    arm: str
    status: str
    elapsed_seconds: float
    usage: OnlineProbeUsage
    decisions: Tuple[RegulationAuditDecision, ...]
    attempts: Tuple[BatchAuditAttemptTrace, ...]
    budget_before: CallBudgetSnapshot
    budget_after: CallBudgetSnapshot
    error: str = ""
    unreported_call_traces: Tuple[OnlineProbeUnreportedCallTrace, ...] = ()

    def to_dict(self) -> Mapping[str, object]:
        return {
            "group_id": self.group_id,
            "case_id": self.case_id,
            "sample_id": self.sample_id,
            "arm": self.arm,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "usage": dict(self.usage.to_dict()),
            "decisions": [_decision_dict(item) for item in self.decisions],
            "attempts": [_attempt_dict(item) for item in self.attempts],
            "budget_before": _budget_dict(self.budget_before),
            "budget_after": _budget_dict(self.budget_after),
            "error": self.error,
            "unreported_call_traces": [
                item.to_dict() for item in self.unreported_call_traces
            ],
        }


@dataclass(frozen=True)
class OnlineEvidenceGate:
    passed: bool
    validated_unit_ids: Tuple[str, ...]
    failures: Tuple[str, ...]
    validation_mode: str

    def to_dict(self) -> Mapping[str, object]:
        return {
            "passed": self.passed,
            "validated_unit_ids": list(self.validated_unit_ids),
            "failures": list(self.failures),
            "validation_mode": self.validation_mode,
        }


@dataclass(frozen=True)
class RatePairRunContext:
    pair_plan: RatePairProbePlan
    stage: RatePairStage
    prerequisite_report_sha256: str = ""
    prerequisite_gate: Optional[OnlineEvidenceGate] = None
    prerequisite_report_bytes: bytes = b""
    prerequisite_prepared_dynamic: Optional[PreparedOnlineProbe] = None

    def to_dict(self, evidence_gate: Optional[OnlineEvidenceGate]) -> Mapping[str, object]:
        pair_limits = self.pair_plan.pair_theoretical_limits
        return {
            "pair_plan_sha256": self.pair_plan.sha256,
            "evidence_protocol_version": (
                self.pair_plan.evidence_protocol_version
            ),
            "stage": self.stage,
            "selected_group_id": self.pair_plan.group_id_for(self.stage),
            "required_unit_ids": list(self.pair_plan.required_unit_ids),
            "prerequisite_report_sha256": self.prerequisite_report_sha256,
            "prerequisite_gate": (
                self.prerequisite_gate.to_dict()
                if self.prerequisite_gate is not None else None
            ),
            "evidence_gate": (
                evidence_gate.to_dict() if evidence_gate is not None else None
            ),
            "budget_scope": self.pair_plan.budget_scope,
            "pair_theoretical_limits": {
                "max_seconds": pair_limits.max_seconds,
                "outer_watchdog_seconds": pair_limits.outer_watchdog_seconds,
                "max_total_tokens": pair_limits.max_total_tokens,
                "max_physical_calls": pair_limits.max_physical_calls,
            },
        }


@dataclass(frozen=True)
class OnlineProbeRunReport:
    schema_version: str
    started_at: str
    updated_at: str
    elapsed_seconds: float
    status: str
    stopped_reason: str
    in_progress_group_id: str
    plan_summary: Mapping[str, object]
    groups: Tuple[OnlineProbeGroupResult, ...]
    budget: CallBudgetSnapshot
    external_scope_expanded: bool = False
    pair_context: Optional[RatePairRunContext] = None
    evidence_gate: Optional[OnlineEvidenceGate] = None

    def to_dict(self) -> Mapping[str, object]:
        usage = _sum_usage(tuple(group.usage for group in self.groups))
        budget_accounted_tokens = self.budget.consumed_tokens
        unreported_reserved_settlement = max(
            0, budget_accounted_tokens - usage.total_tokens,
        )
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "measurement_kind": (
                "online_rate_adjustment_paired_stage"
                if self.pair_context is not None
                else "online_full_vs_trigger_dynamic_probe"
            ),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status,
            "stopped_reason": self.stopped_reason,
            "in_progress_group_id": self.in_progress_group_id,
            "external_scope_expanded": self.external_scope_expanded,
            "plan": dict(self.plan_summary),
            "summary": {
                "recorded_group_count": len(self.groups),
                "completed_group_count": sum(
                    group.status in {"completed", "reused_identical_input"}
                    for group in self.groups
                ),
                "incomplete_group_count": sum(
                    group.status not in {"completed", "reused_identical_input"}
                    for group in self.groups
                ),
                "usage": dict(usage.to_dict()),
                "provider_reported_tokens": usage.total_tokens,
                "budget_accounted_tokens": budget_accounted_tokens,
                "unreported_reserved_settlement": (
                    unreported_reserved_settlement
                ),
                "budget": _budget_dict(self.budget),
            },
            "results": [group.to_dict() for group in self.groups],
        }
        if self.pair_context is not None:
            payload["pair"] = self.pair_context.to_dict(self.evidence_gate)
        return payload


def _budget_dict(snapshot: CallBudgetSnapshot) -> Mapping[str, object]:
    return {
        "deadline": snapshot.deadline,
        "observed_at": snapshot.observed_at,
        "remaining_seconds": snapshot.remaining_seconds,
        "max_total_tokens": snapshot.max_total_tokens,
        "consumed_tokens": snapshot.consumed_tokens,
        "reserved_tokens": snapshot.reserved_tokens,
        "remaining_tokens": snapshot.remaining_tokens,
        "max_physical_calls": snapshot.max_physical_calls,
        "physical_calls": snapshot.physical_calls,
        "active_leases": snapshot.active_leases,
    }


def _decision_dict(decision: RegulationAuditDecision) -> Mapping[str, object]:
    return {
        "task_id": decision.task_id,
        "unit_id": decision.regulation_unit_id,
        "status": decision.status.value,
        "reasoning": decision.reasoning,
        "suggestion": decision.suggestion,
        "regulation_evidence": [
            {"chunk_id": item.chunk_id, "quote": item.quote}
            for item in decision.regulation_evidence
        ],
        "product_evidence": [
            {
                "clause_id": item.clause_id,
                "quote": item.quote,
                "source_kind": item.source_kind,
            }
            for item in decision.product_evidence
        ],
        "applicability_dispute": decision.applicability_dispute,
        "confidence": decision.confidence,
        "incomplete": decision.incomplete,
        "error_code": decision.error_code,
        "obligation_assessments": [
            {
                "obligation_id": item.obligation_id,
                "requirement": item.requirement,
                "status": item.status.value,
                "reasoning": item.reasoning,
                "regulation_chunk_ids": list(item.regulation_chunk_ids),
                "product_clause_ids": list(item.product_clause_ids),
            }
            for item in decision.obligation_assessments
        ],
    }


def _attempt_dict(attempt: BatchAuditAttemptTrace) -> Mapping[str, object]:
    return {
        "attempt": attempt.attempt,
        "stage": attempt.stage,
        "requested_unit_ids": list(attempt.requested_unit_ids),
        "returned_unit_ids": list(attempt.returned_unit_ids),
        "validation_errors": list(attempt.validation_errors),
        "raw_response": attempt.raw_response,
        "usage": {
            "prompt_tokens": attempt.prompt_tokens,
            "completion_tokens": attempt.completion_tokens,
            "total_tokens": attempt.total_tokens,
        },
    }


def _mapping_value(value: object) -> Optional[Mapping[str, object]]:
    return value if isinstance(value, Mapping) else None


def _list_value(value: object) -> Optional[list[object]]:
    return value if isinstance(value, list) else None


def _validate_evidence_items(
    raw_items: object,
    sources: Mapping[str, str],
    label: str,
) -> Tuple[str, ...]:
    items = _list_value(raw_items)
    if not items:
        return (f"{label}证据为空",)
    failures = []
    for index, raw_item in enumerate(items):
        item = _mapping_value(raw_item)
        if item is None:
            failures.append(f"{label}证据[{index}]不是对象")
            continue
        source_id = item.get("chunk_id" if label == "法规" else "clause_id")
        quote = item.get("quote")
        if not isinstance(source_id, str) or source_id not in sources:
            failures.append(f"{label}证据[{index}] ID不属于当前任务")
            continue
        if not isinstance(quote, str) or quote != sources[source_id]:
            failures.append(f"{label}证据[{index}]原文未匹配当前任务")
        if label == "产品":
            expected_kind = (
                "product_name" if source_id == "product-name" else "clause_body"
            )
            if item.get("source_kind") != expected_kind:
                failures.append(f"{label}证据[{index}]来源类型与ID不一致")
    return tuple(failures)


def _validate_obligation_items(
    raw_items: object,
    package: RegulationAuditPackage,
    overall_status: object,
    regulation_ids: frozenset[str],
    product_ids: frozenset[str],
) -> Tuple[str, ...]:
    items = _list_value(raw_items)
    if not package.obligations:
        return () if not items else ("未配置逐项义务却返回了义务结果",)
    if items is None or len(items) != len(package.obligations):
        return ("逐项义务数量与冻结目录不一致",)
    failures = []
    statuses = []
    for index, obligation in enumerate(package.obligations):
        item = _mapping_value(items[index])
        if item is None:
            failures.append(f"义务[{index}]不是对象")
            continue
        if item.get("obligation_id") != obligation.obligation_id:
            failures.append(f"义务[{index}] ID或顺序不一致")
        if item.get("requirement") != obligation.requirement:
            failures.append(f"{obligation.obligation_id}: 要求正文被改写")
        status = item.get("status")
        if status not in {"satisfied", "violated", "insufficient_information"}:
            failures.append(f"{obligation.obligation_id}: 状态无效")
        reasoning = item.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            failures.append(f"{obligation.obligation_id}: 理由为空")
        regulation_chunk_ids = item.get("regulation_chunk_ids")
        product_clause_ids = item.get("product_clause_ids")
        if not isinstance(regulation_chunk_ids, list) or any(
            not isinstance(value, str) or value not in regulation_ids
            for value in regulation_chunk_ids
        ):
            failures.append(f"{obligation.obligation_id}: 法规证据不属于当前任务")
        if not isinstance(product_clause_ids, list) or any(
            not isinstance(value, str) or value not in product_ids
            for value in product_clause_ids
        ):
            failures.append(f"{obligation.obligation_id}: 产品证据不属于当前任务")
        if not obligation.automated_decision_allowed:
            if status != "insufficient_information":
                failures.append(
                    f"{obligation.obligation_id}: 未通过自动证据充分性验收"
                )
            if reasoning != obligation.insufficient_reason:
                failures.append(
                    f"{obligation.obligation_id}: 降级理由与冻结目录不一致"
                )
            if regulation_chunk_ids or product_clause_ids:
                failures.append(
                    f"{obligation.obligation_id}: 降级义务不得形成自动证据结论"
                )
            if status in {"satisfied", "violated", "insufficient_information"}:
                statuses.append("insufficient_information")
        elif status in {"satisfied", "violated"} and (
            not regulation_chunk_ids or not product_clause_ids
        ):
            failures.append(f"{obligation.obligation_id}: 明确结论缺少双域证据")
            statuses.append(status)
        elif status in {"satisfied", "violated", "insufficient_information"}:
            statuses.append(status)
    derived_status = (
        "non_compliant"
        if "violated" in statuses
        else "insufficient_information"
        if "insufficient_information" in statuses
        else "compliant"
    )
    if len(statuses) == len(package.obligations) and overall_status != derived_status:
        failures.append("总体结论与逐项义务状态不一致")
    return tuple(failures)


def validate_rate_pair_group_payload(
    group: PreparedOnlineProbeGroup,
    payload: Mapping[str, object],
) -> OnlineEvidenceGate:
    """Revalidate final, hydrated evidence at the runner boundary."""
    failures = []
    validated_unit_ids = []
    if payload.get("group_id") != group.group_id:
        failures.append("结果组ID与冻结阶段不一致")
    if payload.get("case_id") != group.case_id:
        failures.append("结果案例ID与冻结阶段不一致")
    if payload.get("sample_id") != group.sample_id:
        failures.append("结果产品ID与冻结阶段不一致")
    if payload.get("arm") != group.arm:
        failures.append("结果实验臂与冻结阶段不一致")
    if payload.get("status") != "completed":
        failures.append("结果组未完整完成")
    raw_decisions = _list_value(payload.get("decisions"))
    packages = {
        package.regulation.regulation_unit_id: package
        for package in group.packages
    }
    expected_unit_ids = tuple(packages)
    decision_items = tuple(raw_decisions or ())
    returned_unit_ids = tuple(
        item.get("unit_id")
        for raw_item in decision_items
        if (item := _mapping_value(raw_item)) is not None
        and isinstance(item.get("unit_id"), str)
    )
    if (
        len(decision_items) != len(expected_unit_ids)
        or len(returned_unit_ids) != len(expected_unit_ids)
        or len(set(returned_unit_ids)) != len(returned_unit_ids)
        or set(returned_unit_ids) != set(expected_unit_ids)
    ):
        failures.append(
            f"结果必须恰好包含{len(expected_unit_ids)}个冻结法规单元且不得重复"
        )
    for raw_item in decision_items:
        decision = _mapping_value(raw_item)
        if decision is None:
            failures.append("审核结论不是对象")
            continue
        unit_id = decision.get("unit_id")
        if not isinstance(unit_id, str) or unit_id not in packages:
            failures.append("审核结论引用了阶段外法规单元")
            continue
        package = packages[unit_id]
        unit_failures = []
        if decision.get("task_id") != package.task_id:
            unit_failures.append("task_id不匹配")
        allowed_statuses = (
            {"compliant", "non_compliant", "insufficient_information"}
            if package.obligations
            else {"compliant", "non_compliant"}
        )
        status = decision.get("status")
        if status not in allowed_statuses:
            unit_failures.append(
                "结论不属于当前逐项义务实验允许的状态"
                if package.obligations
                else "结论不是有效的明确合规/不合规状态"
            )
        if not isinstance(decision.get("reasoning"), str) or not str(
            decision.get("reasoning")
        ).strip():
            unit_failures.append("结论理由为空")
        if decision.get("applicability_dispute") is not False:
            unit_failures.append("结论包含未解决的适用性争议")
        confidence = decision.get("confidence")
        if status in {"compliant", "non_compliant"} and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.7 <= float(confidence) <= 1.0
        ):
            unit_failures.append("明确结论置信度低于自动判断门槛")
        if decision.get("incomplete") is not False:
            unit_failures.append("结论被标记为不完整")
        if decision.get("error_code") != "":
            unit_failures.append("结论包含错误码")
        regulation_sources = {
            chunk.chunk_id: chunk.content for chunk in package.regulation.chunks
        }
        strong_clause_ids = {
            candidate.clause_id
            for candidate in package.product_evidence_candidates
            if candidate.strength is ProductEvidenceStrength.STRONG
        }
        product_sources = {
            routed.clause.clause_id: routed.clause.text
            for routed in package.clauses
            if (
                routed.submitted
                and routed.clause.clause_id in strong_clause_ids
                and not routed.clause.container_only
                and bool(routed.clause.text.strip())
            )
        }
        product_name_relevant = (
            "contract.name" in package.regulation.topics
            or any(
                "contract.name" in spec.target_topics
                for spec in package.regulation.trigger_specs
            )
        )
        if product_name_relevant and package.product_name.strip():
            product_sources["product-name"] = package.product_name
        unit_failures.extend(_validate_evidence_items(
            decision.get("regulation_evidence"),
            regulation_sources,
            "法规",
        ))
        unit_failures.extend(_validate_evidence_items(
            decision.get("product_evidence"),
            product_sources,
            "产品",
        ))
        unit_failures.extend(_validate_obligation_items(
            decision.get("obligation_assessments"),
            package,
            decision.get("status"),
            frozenset(regulation_sources),
            frozenset(product_sources),
        ))
        if unit_failures:
            failures.extend(f"{unit_id}: {failure}" for failure in unit_failures)
        else:
            validated_unit_ids.append(unit_id)
    attempts = _list_value(payload.get("attempts")) or []
    recovered = any(
        (attempt := _mapping_value(raw_attempt)) is not None
        and attempt.get("stage") == "model_evidence_recovery"
        for raw_attempt in attempts
    )
    ordered_validated = tuple(
        unit_id for unit_id in expected_unit_ids if unit_id in validated_unit_ids
    )
    return OnlineEvidenceGate(
        passed=not failures and ordered_validated == expected_unit_ids,
        validated_unit_ids=ordered_validated,
        failures=tuple(failures),
        validation_mode="recovered" if recovered else "first_pass",
    )


def validate_rate_dynamic_prerequisite(
    report: Mapping[str, object],
    pair_plan: RatePairProbePlan,
    prepared_dynamic: PreparedOnlineProbe,
    expected_endpoint: str,
) -> OnlineEvidenceGate:
    """Validate the completed C report before admitting any A provider call."""
    failures = []
    if len(prepared_dynamic.groups) != 1:
        failures.append("当前C阶段准备结果不是唯一组")
        group = None
    else:
        group = prepared_dynamic.groups[0]
        if group.group_id != pair_plan.dynamic_group_id:
            failures.append("当前C阶段准备结果与pair计划不一致")
    if report.get("measurement_kind") != "online_rate_adjustment_paired_stage":
        failures.append("C报告类型不正确")
    if report.get("status") != "completed" or report.get("stopped_reason") != "":
        failures.append("C报告未成功完成")
    if report.get("external_scope_expanded") is not False:
        failures.append("C报告外发范围标记不安全")
    raw_plan = _mapping_value(report.get("plan"))
    expected_plan = prepared_dynamic.summary()
    locked_plan_fields = (
        "plan_sha256",
        "kb_version",
        "provider",
        "model",
        "product_manifest_sha256",
        "kb_build_manifest_sha256",
        "kb_catalog_sha256",
        "authorized_products",
        "limits",
    )
    if raw_plan is None:
        failures.append("C报告缺少冻结计划信息")
    else:
        for field_name in locked_plan_fields:
            if raw_plan.get(field_name) != expected_plan.get(field_name):
                failures.append(f"C报告计划字段不一致: {field_name}")
        raw_groups = _list_value(raw_plan.get("groups"))
        if (
            not raw_groups
            or len(raw_groups) != 1
            or not isinstance(raw_groups[0], Mapping)
            or raw_groups[0].get("group_id") != pair_plan.dynamic_group_id
            or raw_groups[0].get("unit_ids") != list(pair_plan.required_unit_ids)
        ):
            failures.append("C报告计划未唯一锁定动态组及3个法规单元")
        provider_endpoint = raw_plan.get("provider_endpoint")
        if (
            not isinstance(provider_endpoint, str)
            or provider_endpoint.rstrip("/") != expected_endpoint.rstrip("/")
        ):
            failures.append("C报告供应商端点与当前阶段不一致")
        else:
            endpoint = urlparse(provider_endpoint)
            if (
                endpoint.scheme != "https"
                or endpoint.hostname != pair_plan.allowed_endpoint_host
            ):
                failures.append("C报告不是冻结的官方HTTPS端点")
    raw_pair = _mapping_value(report.get("pair"))
    if raw_pair is None:
        failures.append("C报告缺少pair元数据")
    else:
        expected_pair_fields = {
            "pair_plan_sha256": pair_plan.sha256,
            "evidence_protocol_version": pair_plan.evidence_protocol_version,
            "stage": "rate_dynamic_c",
            "selected_group_id": pair_plan.dynamic_group_id,
            "required_unit_ids": list(pair_plan.required_unit_ids),
            "prerequisite_report_sha256": "",
            "budget_scope": pair_plan.budget_scope,
        }
        for field_name, expected_value in expected_pair_fields.items():
            if raw_pair.get(field_name) != expected_value:
                failures.append(f"C报告pair字段不一致: {field_name}")
        reported_gate = _mapping_value(raw_pair.get("evidence_gate"))
        if reported_gate is None or reported_gate.get("passed") is not True:
            failures.append("C报告未记录通过的证据门")
    raw_results = _list_value(report.get("results"))
    if group is None or raw_results is None or len(raw_results) != 1:
        group_gate = OnlineEvidenceGate(
            passed=False,
            validated_unit_ids=(),
            failures=("C报告必须恰好包含一个阶段结果",),
            validation_mode="first_pass",
        )
    else:
        raw_group = _mapping_value(raw_results[0])
        group_gate = (
            validate_rate_pair_group_payload(group, raw_group)
            if raw_group is not None
            else OnlineEvidenceGate(
                passed=False,
                validated_unit_ids=(),
                failures=("C报告阶段结果不是对象",),
                validation_mode="first_pass",
            )
        )
    failures.extend(group_gate.failures)
    raw_summary = _mapping_value(report.get("summary"))
    raw_budget = (
        _mapping_value(raw_summary.get("budget"))
        if raw_summary is not None else None
    )
    limits = pair_plan.limits_per_stage
    if raw_budget is None:
        failures.append("C报告缺少阶段预算结算")
    else:
        if raw_budget.get("max_total_tokens") != limits.max_total_tokens:
            failures.append("C报告token预算上限不一致")
        if raw_budget.get("max_physical_calls") != limits.max_physical_calls:
            failures.append("C报告物理调用上限不一致")
        consumed = raw_budget.get("consumed_tokens")
        physical_calls = raw_budget.get("physical_calls")
        if not isinstance(consumed, int) or consumed > limits.max_total_tokens:
            failures.append("C报告token结算超过阶段上限")
        if (
            not isinstance(physical_calls, int)
            or physical_calls > limits.max_physical_calls
        ):
            failures.append("C报告物理调用数超过阶段上限")
    return OnlineEvidenceGate(
        passed=not failures and group_gate.passed,
        validated_unit_ids=group_gate.validated_unit_ids,
        failures=tuple(failures),
        validation_mode=group_gate.validation_mode,
    )


def _sum_usage(records: Tuple[OnlineProbeUsage, ...]) -> OnlineProbeUsage:
    return OnlineProbeUsage(
        responses=sum(item.responses for item in records),
        prompt_tokens=sum(item.prompt_tokens for item in records),
        completion_tokens=sum(item.completion_tokens for item in records),
        total_tokens=sum(item.total_tokens for item in records),
    )


def _usage_delta(
    before: int,
    records: Tuple[ZhipuUsage, ...],
) -> OnlineProbeUsage:
    delta = records[before:]
    return OnlineProbeUsage(
        responses=len(delta),
        prompt_tokens=sum(item.prompt_tokens for item in delta),
        completion_tokens=sum(item.completion_tokens for item in delta),
        total_tokens=sum(item.total_tokens for item in delta),
    )


def _atomic_write_report(path: Path, report: OnlineProbeRunReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _group_status(decisions: Tuple[RegulationAuditDecision, ...]) -> str:
    if any(
        "audit_budget_exhausted" in item.error_code.split(",")
        for item in decisions
    ):
        return "budget_exhausted"
    if decisions and all(
        "batch_llm_call_failed" in item.error_code.split(",")
        for item in decisions
    ):
        return "technical_failure"
    if any(item.incomplete for item in decisions):
        return "completed_incomplete"
    return "completed"


def _unreported_call_stage(
    decisions: Tuple[RegulationAuditDecision, ...],
    attempts: Tuple[BatchAuditAttemptTrace, ...],
) -> str:
    if any(
        "model_evidence_recovery_failed" in item.error_code.split(",")
        for item in decisions
    ) and not any(item.stage == "model_evidence_recovery" for item in attempts):
        return "model_evidence_recovery"
    return "primary"


def _unreported_call_error(
    decisions: Tuple[RegulationAuditDecision, ...],
    error: str,
) -> str:
    if error:
        return error
    failures = tuple(dict.fromkeys(
        f"{item.error_code}: {item.reasoning}"
        for item in decisions
        if item.error_code
    ))
    if failures:
        return " | ".join(failures)
    return "供应商响应未提供可核对usage；预算按调用前预留结算。"


def _build_unreported_call_traces(
    group: PreparedOnlineProbeGroup,
    decisions: Tuple[RegulationAuditDecision, ...],
    attempts: Tuple[BatchAuditAttemptTrace, ...],
    usage: OnlineProbeUsage,
    budget_before: CallBudgetSnapshot,
    budget_after: CallBudgetSnapshot,
    error: str,
) -> Tuple[OnlineProbeUnreportedCallTrace, ...]:
    physical_calls = max(
        0, budget_after.physical_calls - budget_before.physical_calls,
    )
    unreported_calls = max(0, physical_calls - usage.responses)
    budget_accounted_tokens = max(
        0, budget_after.consumed_tokens - budget_before.consumed_tokens,
    )
    unreported_reserved_settlement = max(
        0, budget_accounted_tokens - usage.total_tokens,
    )
    if unreported_calls == 0 and unreported_reserved_settlement == 0:
        return ()
    return (OnlineProbeUnreportedCallTrace(
        stage=_unreported_call_stage(decisions, attempts),
        requested_unit_ids=tuple(
            package.regulation.regulation_unit_id for package in group.packages
        ),
        error=_unreported_call_error(decisions, error),
        physical_calls=unreported_calls,
        provider_reported_tokens=usage.total_tokens,
        budget_accounted_tokens=budget_accounted_tokens,
        unreported_reserved_settlement=unreported_reserved_settlement,
        budget_before=budget_before,
        budget_after=budget_after,
    ),)


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and all(character in _SHA256_HEX_CHARACTERS for character in value)
    )


def _validate_single_dynamic_external_scope(
    group: PreparedOnlineProbeGroup,
) -> None:
    """Rebuild the complete outbound prompt so direct callers cannot widen scope."""
    if (
        group.full_document_fallback
        or group.primary_segment_count != 1
        or group.prompt_chars != _RATE_SINGLE_GROUP_PROMPT_CHARS
        or group.prompt_utf8_bytes != _RATE_SINGLE_GROUP_PROMPT_UTF8_BYTES
        or group.max_output_tokens != 4096
        or group.max_prompt_length != 200_000
        or len(group.packages) != 1
    ):
        raise ValueError("单条运行组结构或预检尺寸偏离冻结范围")
    package = group.packages[0]
    chunks = package.regulation.chunks
    if (
        package.input_index != 1
        or len(chunks) != 1
        or chunks[0].chunk_id != _RATE_SINGLE_REGULATION_CHUNK_ID
        or len(package.clauses) != 106
    ):
        raise ValueError("单条运行包未锁定U0002、唯一法规chunk及106条目录")
    candidates = package.product_evidence_candidates
    strong_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.strength is ProductEvidenceStrength.STRONG
    )
    if (
        len(strong_candidates) != 1
        or strong_candidates[0].clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
    ):
        raise ValueError("单条运行包必须且只能有2.3条款这一项STRONG证据候选")
    submitted = tuple(routed for routed in package.clauses if routed.submitted)
    target = package.clauses[13]
    if (
        submitted != (target,)
        or target.clause.container_only
        or not target.clause.text.strip()
        or target.clause.clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
        or target.clause.number != "2.3"
        or target.clause.title != "费率调整"
    ):
        raise ValueError("单条运行包必须且只能提交P014/2.3费率调整正文")
    messages = build_audit_messages(
        package,
        allow_context_request=False,
    )
    prompt_chars = sum(len(message["content"]) for message in messages)
    prompt_utf8_bytes = sum(
        len(message["content"].encode("utf-8")) for message in messages
    )
    canonical = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if (
        prompt_chars != _RATE_SINGLE_EXTERNAL_PROMPT_CHARS
        or prompt_utf8_bytes != _RATE_SINGLE_EXTERNAL_PROMPT_UTF8_BYTES
        or hashlib.sha256(canonical).hexdigest()
        != _RATE_SINGLE_EXTERNAL_MESSAGES_SHA256
    ):
        raise ValueError("单条运行完整外发payload指纹与冻结版本不一致")


def _validate_obligation_dual_external_scope(
    group: PreparedOnlineProbeGroup,
) -> None:
    """Freeze both obligation tasks and their complete outbound batch payload."""
    if (
        group.full_document_fallback
        or group.evidence_repair_enabled
        or group.primary_segment_count != 1
        or group.prompt_chars != _RATE_OBLIGATION_DUAL_GROUP_PROMPT_CHARS
        or group.prompt_utf8_bytes != _RATE_OBLIGATION_DUAL_GROUP_PROMPT_UTF8_BYTES
        or group.max_output_tokens != 4096
        or group.max_prompt_length != 200_000
        or len(group.packages) != 2
    ):
        raise ValueError("双法规逐项义务运行组偏离冻结范围")
    for index, package in enumerate(group.packages):
        chunks = package.regulation.chunks
        strong_candidates = tuple(
            candidate for candidate in package.product_evidence_candidates
            if candidate.strength is ProductEvidenceStrength.STRONG
        )
        submitted = tuple(
            routed for routed in package.clauses if routed.submitted
        )
        target = package.clauses[13]
        expected_obligation_ids = tuple(
            f"OBL{number:03d}"
            for number in range(1, (6, 7)[index] + 1)
        )
        if (
            package.input_index != index + 1
            or package.regulation.regulation_unit_id
            != RATE_OBLIGATION_DUAL_UNIT_IDS[index]
            or len(chunks) != 1
            or chunks[0].chunk_id
            != _RATE_OBLIGATION_DUAL_REGULATION_CHUNK_IDS[index]
            or len(package.clauses) != 106
            or len(strong_candidates) != 1
            or strong_candidates[0].clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
            or submitted != (target,)
            or target.clause.clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
            or target.clause.number != "2.3"
            or target.clause.title != "费率调整"
            or tuple(item.obligation_id for item in package.obligations)
            != expected_obligation_ids
        ):
            raise ValueError("双法规逐项义务运行包未锁定法规、2.3正文及义务目录")
    messages = build_batch_audit_messages(group.packages)
    prompt_chars = sum(len(message["content"]) for message in messages)
    prompt_utf8_bytes = sum(
        len(message["content"].encode("utf-8")) for message in messages
    )
    canonical = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if (
        prompt_chars != _RATE_OBLIGATION_DUAL_GROUP_PROMPT_CHARS
        or prompt_utf8_bytes != _RATE_OBLIGATION_DUAL_GROUP_PROMPT_UTF8_BYTES
        or hashlib.sha256(canonical).hexdigest()
        != _RATE_OBLIGATION_DUAL_EXTERNAL_MESSAGES_SHA256
    ):
        raise ValueError("双法规逐项义务完整外发payload指纹与冻结版本不一致")


def _validate_obligation_single_external_scope(
    group: PreparedOnlineProbeGroup,
) -> None:
    """Freeze the single obligation task and its complete outbound payload."""
    if (
        group.full_document_fallback
        or group.evidence_repair_enabled
        or group.primary_segment_count != 1
        or group.prompt_chars != _RATE_OBLIGATION_SINGLE_GROUP_PROMPT_CHARS
        or group.prompt_utf8_bytes != _RATE_OBLIGATION_SINGLE_GROUP_PROMPT_UTF8_BYTES
        or group.max_output_tokens != 4096
        or group.max_prompt_length != 200_000
        or len(group.packages) != 1
    ):
        raise ValueError("单法规逐项义务运行组偏离冻结范围")
    package = group.packages[0]
    chunks = package.regulation.chunks
    strong_candidates = tuple(
        candidate for candidate in package.product_evidence_candidates
        if candidate.strength is ProductEvidenceStrength.STRONG
    )
    submitted = tuple(routed for routed in package.clauses if routed.submitted)
    target = package.clauses[13]
    if (
        package.input_index != 1
        or package.regulation.regulation_unit_id != RATE_SINGLE_UNIT_ID
        or len(chunks) != 1
        or chunks[0].chunk_id != _RATE_SINGLE_REGULATION_CHUNK_ID
        or len(package.clauses) != 106
        or len(strong_candidates) != 1
        or strong_candidates[0].clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
        or submitted != (target,)
        or target.clause.clause_id != _RATE_SINGLE_PRODUCT_CLAUSE_ID
        or target.clause.number != "2.3"
        or target.clause.title != "费率调整"
        or tuple(item.obligation_id for item in package.obligations)
        != tuple(f"OBL{number:03d}" for number in range(1, 7))
    ):
        raise ValueError("单法规逐项义务运行包未锁定法规、2.3正文及六项义务")
    messages = build_audit_messages(package, allow_context_request=False)
    prompt_chars = sum(len(message["content"]) for message in messages)
    prompt_utf8_bytes = sum(
        len(message["content"].encode("utf-8")) for message in messages
    )
    canonical = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if (
        prompt_chars != _RATE_OBLIGATION_SINGLE_EXTERNAL_PROMPT_CHARS
        or prompt_utf8_bytes != _RATE_OBLIGATION_SINGLE_EXTERNAL_PROMPT_UTF8_BYTES
        or hashlib.sha256(canonical).hexdigest()
        != _RATE_OBLIGATION_SINGLE_EXTERNAL_MESSAGES_SHA256
    ):
        raise ValueError("单法规逐项义务完整外发payload指纹与冻结版本不一致")


def _validate_rate_pair_run_context(
    prepared: PreparedOnlineProbe,
    pair_context: Optional[RatePairRunContext],
    expected_endpoint: str,
) -> RatePairRunContext:
    if pair_context is None:
        raise ValueError("在线探测必须提供冻结的两阶段运行上下文")
    pair_plan = pair_context.pair_plan
    if pair_plan.sha256 == APPROVED_RATE_PAIR_PLAN_SHA256:
        if (
            pair_plan.schema_version != _RATE_PAIR_SCHEMA_VERSION
            or pair_plan.allowed_stages != ("rate_dynamic_c", "rate_full_a")
            or len(pair_plan.required_unit_ids) != 3
            or len(set(pair_plan.required_unit_ids)) != 3
            or pair_plan.http_timeout_cap_seconds != 45
        ):
            raise ValueError("原三条pair运行上下文被放宽或篡改")
        expected_unit_count = 3
    elif pair_plan.sha256 == APPROVED_RATE_SINGLE_PLAN_SHA256:
        if (
            pair_plan.schema_version != _RATE_SINGLE_SCHEMA_VERSION
            or pair_plan.case_id != "rate-adjustment-real-001"
            or pair_plan.sample_id != "real-001"
            or pair_plan.required_unit_ids != (RATE_SINGLE_UNIT_ID,)
            or pair_plan.allowed_stages != ("rate_dynamic_c",)
            or pair_plan.full_group_id
            or pair_plan.http_timeout_cap_seconds != 75
            or pair_plan.limits_per_stage.max_total_tokens != 125_000
            or pair_plan.limits_per_stage.max_physical_calls != 1
            or pair_plan.limits_per_stage.max_seconds != 285
            or pair_plan.limits_per_stage.outer_watchdog_seconds != 300
            or pair_plan.limits_per_stage.max_batch_units != 1
        ):
            raise ValueError("单条运行上下文被放宽或篡改")
        expected_unit_count = 1
    elif pair_plan.sha256 == APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256:
        if (
            pair_plan.schema_version != _RATE_OBLIGATION_DUAL_SCHEMA_VERSION
            or pair_plan.case_id != "rate-adjustment-real-001"
            or pair_plan.sample_id != "real-001"
            or pair_plan.required_unit_ids != RATE_OBLIGATION_DUAL_UNIT_IDS
            or pair_plan.allowed_stages != ("rate_dynamic_c",)
            or pair_plan.full_group_id
            or pair_plan.http_timeout_cap_seconds != 75
            or pair_plan.limits_per_stage.max_total_tokens != 175_000
            or pair_plan.limits_per_stage.max_physical_calls != 1
            or pair_plan.limits_per_stage.max_seconds != 285
            or pair_plan.limits_per_stage.outer_watchdog_seconds != 300
            or pair_plan.limits_per_stage.max_batch_units != 2
        ):
            raise ValueError("双法规逐项义务运行上下文被放宽或篡改")
        expected_unit_count = 2
    elif pair_plan.sha256 == APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256:
        if (
            pair_plan.schema_version != _RATE_OBLIGATION_SINGLE_SCHEMA_VERSION
            or pair_plan.case_id != "rate-adjustment-real-001"
            or pair_plan.sample_id != "real-001"
            or pair_plan.required_unit_ids != (RATE_SINGLE_UNIT_ID,)
            or pair_plan.allowed_stages != ("rate_dynamic_c",)
            or pair_plan.full_group_id
            or pair_plan.http_timeout_cap_seconds != 75
            or pair_plan.limits_per_stage.max_total_tokens != 125_000
            or pair_plan.limits_per_stage.max_physical_calls != 1
            or pair_plan.limits_per_stage.max_seconds != 285
            or pair_plan.limits_per_stage.outer_watchdog_seconds != 300
            or pair_plan.limits_per_stage.max_batch_units != 1
        ):
            raise ValueError("单法规逐项义务运行上下文被放宽或篡改")
        expected_unit_count = 1
    else:
        raise ValueError("运行上下文不属于已批准的冻结overlay")
    if (
        pair_plan.evidence_protocol_version
        != _APPROVED_EVIDENCE_PROTOCOL_VERSION
    ):
        raise ValueError("两阶段运行证据协议不是已批准版本")
    if pair_context.stage not in pair_plan.allowed_stages:
        raise ValueError("运行阶段不在冻结overlay允许范围内")
    if (
        pair_plan.base_plan_sha256 != prepared.plan.sha256
        or len(prepared.groups) != 1
    ):
        raise ValueError("两阶段运行上下文与已准备阶段不一致")
    group = prepared.groups[0]
    expected_arm = "C" if pair_context.stage == "rate_dynamic_c" else "A"
    unit_ids = tuple(
        package.regulation.regulation_unit_id for package in group.packages
    )
    if (
        group.group_id != pair_plan.group_id_for(pair_context.stage)
        or group.case_id != pair_plan.case_id
        or group.sample_id != pair_plan.sample_id
        or group.arm != expected_arm
        or unit_ids != pair_plan.required_unit_ids
        or len(unit_ids) != expected_unit_count
        or len(set(unit_ids)) != expected_unit_count
        or group.reuses_group_id
        or group.http_timeout_cap_seconds
        != pair_plan.http_timeout_cap_seconds
    ):
        raise ValueError("运行目标组未锁定冻结产品及法规单元")
    expected_obligations = tuple(
        catalog.obligations for catalog in pair_plan.obligation_catalogs
    )
    actual_obligations = tuple(
        package.obligations for package in group.packages
    )
    if expected_obligations:
        if actual_obligations != expected_obligations:
            raise ValueError("运行包逐项义务及自动判断边界偏离冻结目录")
    elif any(actual_obligations):
        raise ValueError("未配置逐项义务的运行计划不得注入义务目录")
    if pair_plan.sha256 == APPROVED_RATE_SINGLE_PLAN_SHA256:
        _validate_single_dynamic_external_scope(group)
    elif pair_plan.sha256 == APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256:
        _validate_obligation_dual_external_scope(group)
    elif pair_plan.sha256 == APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256:
        _validate_obligation_single_external_scope(group)
    if pair_context.stage == "rate_dynamic_c":
        if (
            pair_context.prerequisite_report_sha256
            or pair_context.prerequisite_gate is not None
            or pair_context.prerequisite_report_bytes
            or pair_context.prerequisite_prepared_dynamic is not None
        ):
            raise ValueError("C阶段不得携带A阶段前置报告或证据门")
        return pair_context
    if not _is_sha256(pair_context.prerequisite_report_sha256):
        raise ValueError("A阶段必须绑定有效的C报告SHA-256")
    if (
        not pair_context.prerequisite_report_bytes
        or pair_context.prerequisite_prepared_dynamic is None
    ):
        raise ValueError("A阶段必须携带原始C报告及其冻结动态准备结果")
    if hashlib.sha256(pair_context.prerequisite_report_bytes).hexdigest() != (
        pair_context.prerequisite_report_sha256
    ):
        raise ValueError("A阶段原始C报告与绑定SHA-256不一致")
    try:
        raw_report = json.loads(pair_context.prerequisite_report_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("A阶段原始C报告不是有效JSON") from error
    if not isinstance(raw_report, Mapping):
        raise ValueError("A阶段原始C报告必须是JSON对象")
    prerequisite_gate = validate_rate_dynamic_prerequisite(
        raw_report,
        pair_plan,
        pair_context.prerequisite_prepared_dynamic,
        expected_endpoint,
    )
    if (
        not prerequisite_gate.passed
        or prerequisite_gate.failures
        or prerequisite_gate.validated_unit_ids != pair_plan.required_unit_ids
    ):
        raise ValueError("A阶段必须绑定通过且覆盖全部冻结法规单元的C证据门")
    if (
        pair_context.prerequisite_gate is not None
        and pair_context.prerequisite_gate != prerequisite_gate
    ):
        raise ValueError("A阶段调用方证据门与runner重验结果不一致")
    return replace(pair_context, prerequisite_gate=prerequisite_gate)


def _validate_online_client(
    prepared: PreparedOnlineProbe,
    client: ZhipuClient,
    budget: CallBudgetController,
    pair_context: Optional[RatePairRunContext] = None,
) -> RatePairRunContext:
    validated_context = _validate_rate_pair_run_context(
        prepared,
        pair_context,
        client.base_url,
    )
    if prepared.plan.sha256 != APPROVED_ONLINE_PLAN_SHA256:
        raise ValueError("在线探测准备结果不属于已批准计划")
    if client.call_budget is not budget:
        raise ValueError("在线探测客户端必须绑定本次运行的同一调用预算")
    if client.model != prepared.plan.model:
        raise ValueError("在线探测客户端模型与冻结计划不一致")
    endpoint = urlparse(client.base_url)
    if endpoint.scheme != "https" or endpoint.hostname != "open.bigmodel.cn":
        raise ValueError("在线探测只能向智谱官方HTTPS端点发送已授权内容")
    limits = budget.limits
    if (
        limits.max_total_tokens != prepared.plan.limits.max_total_tokens
        or limits.max_physical_calls != prepared.plan.limits.max_physical_calls
    ):
        raise ValueError("在线探测调用预算与冻结计划不一致")
    remaining_seconds = budget.snapshot().remaining_seconds
    if remaining_seconds > prepared.plan.limits.max_seconds + 0.1:
        raise ValueError("在线探测deadline超过冻结计划上限")
    previous_groups: dict[str, PreparedOnlineProbeGroup] = {}
    for group in prepared.groups:
        if group.reuses_group_id:
            source = previous_groups.get(group.reuses_group_id)
            if source is None or source.packages != group.packages:
                raise ValueError("复用组必须引用先前完全相同的审核输入")
        previous_groups[group.group_id] = group
    pair_plan = validated_context.pair_plan
    if endpoint.hostname != pair_plan.allowed_endpoint_host:
        raise ValueError("两阶段运行端点与冻结官方主机不一致")
    if pair_plan.limits_per_stage != prepared.plan.limits:
        raise ValueError("两阶段运行预算与冻结基础计划不一致")
    return validated_context


def _run_group(
    group: PreparedOnlineProbeGroup,
    llm: BaseLLMClient,
    remaining_seconds: float,
) -> Tuple[Tuple[RegulationAuditDecision, ...], Tuple[BatchAuditAttemptTrace, ...]]:
    if len(group.packages) > 1:
        attempts: List[BatchAuditAttemptTrace] = []
        usage_cursor = len(getattr(llm, "usage_records", ()))

        def record_attempt(trace: BatchAuditAttemptTrace) -> None:
            nonlocal usage_cursor
            records = tuple(getattr(llm, "usage_records", ()))[usage_cursor:]
            usage_cursor += len(records)
            attempts.append(replace(
                trace,
                prompt_tokens=sum(item.prompt_tokens for item in records),
                completion_tokens=sum(
                    item.completion_tokens for item in records
                ),
                total_tokens=sum(item.total_tokens for item in records),
            ))

        decisions = audit_regulation_package_batch(
            group.packages,
            llm,
            remaining_seconds,
            max_batch_size=len(group.packages),
            on_attempt=record_attempt,
            allow_full_repair=False,
            allow_evidence_repair=group.evidence_repair_enabled,
            request_timeout_cap_seconds=group.http_timeout_cap_seconds,
        )
        return decisions, tuple(attempts)
    package = group.packages[0]
    decision = audit_regulation_package(
        package,
        llm,
        remaining_seconds,
        max_prompt_length=group.max_prompt_length,
        allow_context_expansion=False,
        request_timeout_cap_seconds=group.http_timeout_cap_seconds,
    )
    return (decision,), ()


def run_online_probe(
    prepared: PreparedOnlineProbe,
    client: ZhipuClient,
    budget: CallBudgetController,
    output_path: Path,
    *,
    pair_context: Optional[RatePairRunContext],
    clock: Callable[[], float] = time.monotonic,
) -> OnlineProbeRunReport:
    pair_context = _validate_online_client(
        prepared,
        client,
        budget,
        pair_context,
    )
    started_monotonic = clock()
    started_at = datetime.now(timezone.utc).isoformat()
    report = OnlineProbeRunReport(
        schema_version="2.0.0",
        started_at=started_at,
        updated_at=started_at,
        elapsed_seconds=0.0,
        status="running",
        stopped_reason="",
        in_progress_group_id="",
        plan_summary={
            **prepared.summary(),
            "provider_endpoint": client.base_url,
            "scope_validation": "approved_plan_sha_and_authorized_product_sha_verified",
            "resume_supported": False,
            "watchdog_mid_group_usage_may_be_incomplete": True,
        },
        groups=(),
        budget=budget.snapshot(),
        pair_context=pair_context,
    )
    _atomic_write_report(output_path, report)
    results: List[OnlineProbeGroupResult] = []
    stopped_reason = ""
    for group in prepared.groups:
        before_budget = budget.snapshot()
        if before_budget.remaining_seconds <= 0:
            stopped_reason = "deadline_budget_exhausted"
            break
        report = replace(
            report,
            updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=round(clock() - started_monotonic, 3),
            in_progress_group_id=group.group_id,
            groups=tuple(results),
            budget=before_budget,
        )
        _atomic_write_report(output_path, report)
        reused = next(
            (
                item for item in results
                if item.group_id == group.reuses_group_id
            ),
            None,
        ) if group.reuses_group_id else None
        usage_start = len(client.usage_records)
        group_started = clock()
        error = ""
        decisions: Tuple[RegulationAuditDecision, ...]
        attempts: Tuple[BatchAuditAttemptTrace, ...]
        if reused is not None:
            decisions = reused.decisions
            attempts = ()
        else:
            try:
                decisions, attempts = _run_group(
                    group,
                    client,
                    before_budget.remaining_seconds,
                )
            except Exception as exc:
                decisions = ()
                attempts = ()
                error = f"{type(exc).__name__}: {exc}"
        usage = _usage_delta(usage_start, client.usage_records)
        after_budget = budget.snapshot()
        status = (
            "reused_identical_input" if reused is not None
            else "technical_failure" if error
            else _group_status(decisions)
        )
        result_error = error
        if status == "technical_failure" and not result_error:
            result_error = _unreported_call_error(decisions, "")
        unreported_call_traces = _build_unreported_call_traces(
            group,
            decisions,
            attempts,
            usage,
            before_budget,
            after_budget,
            result_error,
        )
        result = OnlineProbeGroupResult(
            group_id=group.group_id,
            case_id=group.case_id,
            sample_id=group.sample_id,
            arm=group.arm,
            status=status,
            elapsed_seconds=round(clock() - group_started, 3),
            usage=usage,
            decisions=decisions,
            attempts=attempts,
            budget_before=before_budget,
            budget_after=after_budget,
            error=result_error,
            unreported_call_traces=unreported_call_traces,
        )
        results.append(result)
        report = replace(
            report,
            updated_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=round(clock() - started_monotonic, 3),
            in_progress_group_id="",
            groups=tuple(results),
            budget=after_budget,
        )
        _atomic_write_report(output_path, report)
        if status == "budget_exhausted":
            stopped_reason = "call_budget_exhausted"
            break
        if status == "technical_failure":
            stopped_reason = "technical_failure"
            break
    completed = len(results) == len(prepared.groups) and not stopped_reason
    final = replace(
        report,
        updated_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=round(clock() - started_monotonic, 3),
        status="completed" if completed else "incomplete",
        stopped_reason=stopped_reason,
        in_progress_group_id="",
        groups=tuple(results),
        budget=budget.snapshot(),
    )
    if pair_context is not None:
        evidence_gate = (
            validate_rate_pair_group_payload(
                prepared.groups[0],
                results[0].to_dict(),
            )
            if len(prepared.groups) == 1 and len(results) == 1
            else OnlineEvidenceGate(
                passed=False,
                validated_unit_ids=(),
                failures=("阶段结果数量不符合冻结pair计划",),
                validation_mode="first_pass",
            )
        )
        final = replace(final, evidence_gate=evidence_gate)
        if not evidence_gate.passed:
            final = replace(
                final,
                status="incomplete",
                stopped_reason=(
                    final.stopped_reason or "evidence_gate_failed"
                ),
            )
    _atomic_write_report(output_path, final)
    return final
