import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    ProductClauseEvidence,
    ProductEvidenceCandidate,
    ProductEvidenceStrength,
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    RegulationEvidence,
    RegulationObligation,
    RegulationObligationAssessment,
    RegulationObligationStatus,
    RegulationTriggerSpec,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
    TriggerFactName,
    TriggerOperator,
)
from lib.common.product_tags import ProductTags
from lib.compliance import trigger_online_runner
from lib.compliance.trigger_online_measurement import (
    PreparedOnlineProbe,
    PreparedOnlineProbeGroup,
    RATE_SINGLE_UNIT_ID,
    RatePairStage,
    load_online_probe_plan,
    load_rate_pair_probe_plan,
)
from lib.llm.call_budget import (
    CallBudgetController,
    CallBudgetLimits,
    CallBudgetUsage,
)
from lib.llm.zhipu import ZhipuClient, ZhipuUsage


_ROOT = Path(__file__).resolve().parents[3]
_PLAN = (
    _ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-plan-v2.json"
)
_PAIR_PLAN = (
    _ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-rate-pair-v1.json"
)
_SINGLE_PLAN = (
    _ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-rate-single-v1.json"
)


class _NoCallClient:
    def __init__(self, budget: CallBudgetController) -> None:
        self.usage_records = ()
        self.call_budget = budget
        self.model = "glm-4-flash-250414"
        self.base_url = "https://open.bigmodel.cn/api/paas/v4"


def _decision(group_id: str, *, budget_exhausted: bool = False) -> RegulationAuditDecision:
    return RegulationAuditDecision(
        task_id=f"task-{group_id}",
        regulation_unit_id=f"unit-{group_id}",
        status=(
            RegulationDecisionStatus.MANUAL_REVIEW
            if budget_exhausted
            else RegulationDecisionStatus.COMPLIANT
        ),
        reasoning="预算测试",
        suggestion="",
        regulation_evidence=(),
        product_evidence=(),
        confidence=None if budget_exhausted else 0.95,
        incomplete=budget_exhausted,
        error_code="audit_budget_exhausted" if budget_exhausted else "",
    )


def _batch_failure_decision(group_id: str) -> RegulationAuditDecision:
    return replace(
        _decision(group_id),
        status=RegulationDecisionStatus.MANUAL_REVIEW,
        reasoning="批量模型调用未收到有效响应。",
        incomplete=True,
        error_code="batch_llm_call_failed",
    )


def _prepared(group_ids: tuple[str, ...]) -> PreparedOnlineProbe:
    plan = load_online_probe_plan(_PLAN)
    groups = tuple(
        PreparedOnlineProbeGroup(
            group_id=group_id,
            case_id=group_id,
            sample_id="real-001",
            arm="A",
            packages=(),
            full_document_fallback=False,
            prompt_chars=1,
            prompt_utf8_bytes=1,
            max_output_tokens=1,
            max_prompt_length=200_000,
            primary_segment_count=1,
        )
        for group_id in group_ids
    )
    return PreparedOnlineProbe(
        plan=plan,
        groups=groups,
        skipped_dynamic_canaries=(),
        product_manifest_path="manifest.json",
        kb_build_manifest_path="v5-build-manifest.json",
    )


def _budget() -> CallBudgetController:
    return CallBudgetController(CallBudgetLimits(
        deadline=time.monotonic() + 60,
        max_total_tokens=250_000,
        max_physical_calls=10,
    ))


def _single_budget() -> CallBudgetController:
    return CallBudgetController(CallBudgetLimits(
        deadline=time.monotonic() + 60,
        max_total_tokens=125_000,
        max_physical_calls=1,
    ))


def _pair_context(
    stage: str = "rate_dynamic_c",
) -> trigger_online_runner.RatePairRunContext:
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    if stage == "rate_dynamic_c":
        return trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_dynamic_c",
        )
    report_bytes, report_sha256, prepared_dynamic, gate = (
        _valid_prerequisite_report()
    )
    return trigger_online_runner.RatePairRunContext(
        pair_plan=pair,
        stage="rate_full_a",
        prerequisite_report_sha256=report_sha256,
        prerequisite_gate=gate,
        prerequisite_report_bytes=report_bytes,
        prerequisite_prepared_dynamic=prepared_dynamic,
    )


def _rate_prepared(arm: str = "C") -> PreparedOnlineProbe:
    plan = load_online_probe_plan(_PLAN)
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    packages = []
    for index, unit_id in enumerate(pair.required_unit_ids, start=1):
        clause = AuditClauseSnapshot(
            clause_id=f"clause-{index}",
            number=f"2.{index}",
            title="费率调整",
            text=f"第{index}条产品费率调整证据原文。",
            block_type="clause",
        )
        packages.append(RegulationAuditPackage(
            task_id=f"task-{index}",
            input_index=index,
            product_name="测试费率可调医疗保险",
            product_tags=ProductTags(),
            regulation=RegulationUnitSnapshot(
                regulation_unit_id=unit_id,
                kb_version="v5",
                law_name="测试法规",
                source_file="测试法规.md",
                article_number=f"第{index}条",
                section_path=f"第{index}条",
                topics=("premium.rate_adjustment",),
                chunks=(RegulationChunkSnapshot(
                    chunk_id=f"chunk-{index}",
                    content=f"第{index}条法规证据原文。",
                    chunk_index=0,
                ),),
                applicability_status="applicable",
                applicability_reasons=(),
            ),
            clauses=(RoutedClause(
                clause=clause,
                relation=RoutedClauseRelation.DIRECT,
                reasons=("测试",),
            ),),
            facts=(),
            product_evidence_candidates=(ProductEvidenceCandidate(
                clause_id=clause.clause_id,
                strength=ProductEvidenceStrength.STRONG,
                source_layers=("exact_topic",),
            ),),
        ))
    group_id = pair.dynamic_group_id if arm == "C" else pair.full_group_id
    return PreparedOnlineProbe(
        plan=plan,
        groups=(PreparedOnlineProbeGroup(
            group_id=group_id,
            case_id=pair.case_id,
            sample_id=pair.sample_id,
            arm=arm,
            packages=tuple(packages),
            full_document_fallback=False,
            prompt_chars=1,
            prompt_utf8_bytes=1,
            max_output_tokens=6144,
            max_prompt_length=200_000,
            primary_segment_count=1,
        ),),
        skipped_dynamic_canaries=(),
        product_manifest_path="manifest.json",
        kb_build_manifest_path="v5-build-manifest.json",
    )


def _single_prepared() -> PreparedOnlineProbe:
    base = load_online_probe_plan(_PLAN)
    single = load_rate_pair_probe_plan(_SINGLE_PLAN)
    target_clause_id = "clause_d2ff0389f54cb85e7d14a6aae5fd3d57"
    clauses = tuple(
        RoutedClause(
            clause=AuditClauseSnapshot(
                clause_id=(
                    target_clause_id if index == 14 else f"clause-{index:03d}"
                ),
                number="2.3" if index == 14 else f"9.{index}",
                title="费率调整" if index == 14 else f"测试条款{index}",
                text=(
                    "本产品费率可调，首次费率调整不早于销售后三年。"
                    if index == 14 else f"第{index}条产品原文。"
                ),
                block_type="clause",
                topics=("premium.rate_adjustment",) if index == 14 else (),
            ),
            relation=(
                RoutedClauseRelation.DIRECT
                if index == 14 else RoutedClauseRelation.UNKNOWN
            ),
            reasons=("费率调整主题",) if index == 14 else ("仅保留目录",),
            submitted=index == 14,
        )
        for index in range(1, 107)
    )
    package = RegulationAuditPackage(
        task_id=f"audit:{single.required_unit_ids[0]}",
        input_index=1,
        product_name="人保健康悠优保互联网医疗保险（费率可调）",
        product_tags=ProductTags(),
        regulation=RegulationUnitSnapshot(
            regulation_unit_id=single.required_unit_ids[0],
            kb_version="v5",
            law_name="对照负面清单检查",
            source_file="对照负面清单检查.md",
            article_number="第2条",
            section_path="第2条",
            topics=("premium.rate_adjustment",),
            chunks=(RegulationChunkSnapshot(
                chunk_id=(
                    "kb-chunk:bf776c0c207cd66e40ec94db664f9c2a"
                    "c7c57369cbd2d7764c55a7afa95b33a4"
                ),
                content="费率调整间隔和幅度应符合监管要求。",
                chunk_index=0,
            ),),
            applicability_status="applicable",
            applicability_reasons=("费率可调产品",),
        ),
        clauses=clauses,
        facts=(),
        product_evidence_candidates=(
            ProductEvidenceCandidate(
                clause_id=target_clause_id,
                strength=ProductEvidenceStrength.STRONG,
                source_layers=("trigger_fact", "exact_topic"),
            ),
            ProductEvidenceCandidate(
                clause_id=clauses[14].clause.clause_id,
                strength=ProductEvidenceStrength.WEAK,
                source_layers=("controlled_related_topic",),
            ),
        ),
    )
    group = PreparedOnlineProbeGroup(
        group_id=single.dynamic_group_id,
        case_id=single.case_id,
        sample_id=single.sample_id,
        arm="C",
        packages=(package,),
        full_document_fallback=False,
        prompt_chars=1,
        prompt_utf8_bytes=1,
        max_output_tokens=4096,
        max_prompt_length=200_000,
        primary_segment_count=1,
        http_timeout_cap_seconds=75,
    )
    return PreparedOnlineProbe(
        plan=replace(base, limits=single.limits_per_stage),
        groups=(group,),
        skipped_dynamic_canaries=(),
        product_manifest_path="manifest.json",
        kb_build_manifest_path="v5-build-manifest.json",
    )


def _single_context() -> trigger_online_runner.RatePairRunContext:
    return trigger_online_runner.RatePairRunContext(
        pair_plan=load_rate_pair_probe_plan(_SINGLE_PLAN),
        stage="rate_dynamic_c",
    )


def _approve_single_fixture(
    monkeypatch: pytest.MonkeyPatch,
    prepared: PreparedOnlineProbe,
) -> None:
    group = prepared.groups[0]
    package = group.packages[0]
    messages = trigger_online_runner.build_audit_messages(
        package,
        allow_context_request=False,
    )
    canonical = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    monkeypatch.setattr(
        trigger_online_runner,
        "_RATE_SINGLE_GROUP_PROMPT_CHARS",
        group.prompt_chars,
    )
    monkeypatch.setattr(
        trigger_online_runner,
        "_RATE_SINGLE_GROUP_PROMPT_UTF8_BYTES",
        group.prompt_utf8_bytes,
    )
    monkeypatch.setattr(
        trigger_online_runner,
        "_RATE_SINGLE_EXTERNAL_PROMPT_CHARS",
        sum(len(message["content"]) for message in messages),
    )
    monkeypatch.setattr(
        trigger_online_runner,
        "_RATE_SINGLE_EXTERNAL_PROMPT_UTF8_BYTES",
        sum(len(message["content"].encode("utf-8")) for message in messages),
    )
    monkeypatch.setattr(
        trigger_online_runner,
        "_RATE_SINGLE_EXTERNAL_MESSAGES_SHA256",
        hashlib.sha256(canonical).hexdigest(),
    )


def _valid_rate_decisions(
    prepared: PreparedOnlineProbe,
) -> tuple[RegulationAuditDecision, ...]:
    return tuple(
        RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.COMPLIANT,
            reasoning="证据充分。",
            suggestion="",
            regulation_evidence=(RegulationEvidence(
                package.regulation.chunks[0].chunk_id,
                package.regulation.chunks[0].content,
            ),),
            product_evidence=(ProductClauseEvidence(
                next(
                    routed for routed in package.clauses if routed.submitted
                ).clause.clause_id,
                next(
                    routed for routed in package.clauses if routed.submitted
                ).clause.text,
            ),),
            confidence=0.95,
        )
        for package in prepared.groups[0].packages
    )


def _valid_prerequisite_report() -> tuple[
    bytes,
    str,
    PreparedOnlineProbe,
    trigger_online_runner.OnlineEvidenceGate,
]:
    prepared = _rate_prepared("C")
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    group = prepared.groups[0]
    group_payload = {
        "group_id": group.group_id,
        "case_id": group.case_id,
        "sample_id": group.sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(item)
            for item in _valid_rate_decisions(prepared)
        ],
        "attempts": [],
    }
    gate = trigger_online_runner.validate_rate_pair_group_payload(
        group,
        group_payload,
    )
    report = {
        "schema_version": "2.0.0",
        "measurement_kind": "online_rate_adjustment_paired_stage",
        "status": "completed",
        "stopped_reason": "",
        "external_scope_expanded": False,
        "plan": {
            **prepared.summary(),
            "provider_endpoint": "https://open.bigmodel.cn/api/paas/v4",
        },
        "pair": trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_dynamic_c",
        ).to_dict(gate),
        "results": [group_payload],
        "summary": {
            "budget": {
                "max_total_tokens": pair.limits_per_stage.max_total_tokens,
                "max_physical_calls": pair.limits_per_stage.max_physical_calls,
                "consumed_tokens": 1,
                "physical_calls": 1,
            },
        },
    }
    report_bytes = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return (
        report_bytes,
        hashlib.sha256(report_bytes).hexdigest(),
        prepared,
        gate,
    )


def _assert_runner_rejects_before_call(
    tmp_path,
    monkeypatch,
    prepared: PreparedOnlineProbe,
    pair_context: trigger_online_runner.RatePairRunContext | None,
    expected_message: str,
) -> None:
    budget = _budget()
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda *_args: pytest.fail("非法运行上下文不得进入组执行"),
    )

    with pytest.raises(ValueError, match=expected_message):
        trigger_online_runner.run_online_probe(
            prepared,
            cast(ZhipuClient, _NoCallClient(budget)),
            budget,
            tmp_path / "must-not-exist.json",
            pair_context=pair_context,
        )

    assert budget.snapshot().physical_calls == 0
    assert not (tmp_path / "must-not-exist.json").exists()


def test_online_runner_checkpoints_completed_stage(tmp_path, monkeypatch) -> None:
    output = tmp_path / "probe.json"
    budget = _budget()
    prepared = _rate_prepared("C")
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (
            _valid_rate_decisions(prepared),
            (),
        ),
    )
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        output,
        pair_context=_pair_context(),
    )

    assert report.status == "completed"
    assert tuple(item.group_id for item in report.groups) == (
        _pair_context().pair_plan.dynamic_group_id,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["summary"]["completed_group_count"] == 1
    assert payload["external_scope_expanded"] is False


def test_single_runner_uses_one_call_budget_and_passes_evidence_gate(
    tmp_path,
    monkeypatch,
) -> None:
    output = tmp_path / "single.json"
    budget = _single_budget()
    prepared = _single_prepared()
    _approve_single_fixture(monkeypatch, prepared)
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (
            _valid_rate_decisions(prepared),
            (),
        ),
    )

    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        output,
        pair_context=_single_context(),
    )

    assert report.status == "completed"
    assert report.evidence_gate is not None
    assert report.evidence_gate.passed is True
    assert report.evidence_gate.validated_unit_ids == (RATE_SINGLE_UNIT_ID,)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["pair"]["budget_scope"] == "single_dynamic_stage"
    assert payload["pair"]["required_unit_ids"] == [RATE_SINGLE_UNIT_ID]
    assert payload["pair"]["pair_theoretical_limits"] == {
        "max_seconds": 285.0,
        "outer_watchdog_seconds": 300.0,
        "max_total_tokens": 125_000,
        "max_physical_calls": 1,
    }
    assert payload["summary"]["budget"]["max_total_tokens"] == 125_000
    assert payload["summary"]["budget"]["max_physical_calls"] == 1


def test_single_group_uses_75_second_request_cap(monkeypatch) -> None:
    prepared = _single_prepared()
    observed = {}

    def audit_single(package, _client, timeout_seconds, **kwargs):
        observed["package"] = package
        observed["timeout_seconds"] = timeout_seconds
        observed.update(kwargs)
        return _valid_rate_decisions(prepared)[0]

    monkeypatch.setattr(
        trigger_online_runner,
        "audit_regulation_package",
        audit_single,
    )

    decisions, attempts = trigger_online_runner._run_group(
        prepared.groups[0],
        cast(ZhipuClient, _NoCallClient(_single_budget())),
        285,
    )

    assert len(decisions) == 1
    assert attempts == ()
    assert observed["allow_context_expansion"] is False
    assert observed["request_timeout_cap_seconds"] == 75


def test_online_runner_stops_after_budget_exhaustion(tmp_path, monkeypatch) -> None:
    called = []

    def run_group(group, _client, _remaining):
        called.append(group.group_id)
        return (_decision(group.group_id, budget_exhausted=True),), ()

    monkeypatch.setattr(trigger_online_runner, "_run_group", run_group)
    output = tmp_path / "probe.json"
    budget = _budget()
    prepared = _rate_prepared("C")
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        output,
        pair_context=_pair_context(),
    )

    assert called == [_pair_context().pair_plan.dynamic_group_id]
    assert report.status == "incomplete"
    assert report.stopped_reason == "call_budget_exhausted"
    assert report.groups[0].status == "budget_exhausted"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["in_progress_group_id"] == ""
    assert payload["results"][0]["decisions"][0]["error_code"] == (
        "audit_budget_exhausted"
    )


def test_last_group_budget_exhaustion_is_not_reported_completed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda group, _client, _remaining: (
            (_decision(group.group_id, budget_exhausted=True),),
            (),
        ),
    )

    budget = _budget()
    prepared = _rate_prepared("C")
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "probe.json",
        pair_context=_pair_context(),
    )

    assert report.status == "incomplete"
    assert report.stopped_reason == "call_budget_exhausted"


def test_runner_rejects_client_without_same_budget(tmp_path) -> None:
    budget = _budget()
    client = ZhipuClient(
        "test-key",
        model="glm-4-flash-250414",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    with pytest.raises(ValueError, match="同一调用预算"):
        trigger_online_runner.run_online_probe(
            _rate_prepared("C"),
            client,
            budget,
            tmp_path / "probe.json",
            pair_context=_pair_context(),
        )

    assert budget.snapshot().physical_calls == 0


def test_pair_runner_rejects_multiple_groups_without_call(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _prepared(("full", "dynamic"))
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda *_args: pytest.fail("非法pair不得进入组执行"),
    )
    budget = _budget()
    with pytest.raises(ValueError, match="已准备阶段不一致"):
        trigger_online_runner.run_online_probe(
            prepared,
            cast(ZhipuClient, _NoCallClient(budget)),
            budget,
            tmp_path / "probe.json",
            pair_context=_pair_context(),
        )

    assert budget.snapshot().physical_calls == 0


def test_group_status_detects_budget_code_after_segment_merge() -> None:
    mixed = replace(
        _decision("mixed", budget_exhausted=True),
        error_code="invalid_structured_output,audit_budget_exhausted",
    )

    assert trigger_online_runner._group_status((mixed,)) == "budget_exhausted"


def test_all_batch_call_failures_are_technical_and_stop_later_groups(
    tmp_path,
    monkeypatch,
) -> None:
    called = []

    def run_group(group, _client, _remaining):
        called.append(group.group_id)
        return (_batch_failure_decision(group.group_id),), ()

    monkeypatch.setattr(trigger_online_runner, "_run_group", run_group)
    budget = _budget()
    prepared = _rate_prepared("C")
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "probe.json",
        pair_context=_pair_context(),
    )

    assert called == [_pair_context().pair_plan.dynamic_group_id]
    assert report.status == "incomplete"
    assert report.stopped_reason == "technical_failure"
    assert report.groups[0].status == "technical_failure"
    assert "batch_llm_call_failed" in report.groups[0].error


def test_unreported_physical_call_has_accounting_trace_and_summary(
    tmp_path,
    monkeypatch,
) -> None:
    budget = _budget()

    def run_group(group, client, _remaining):
        successful = budget.reserve(
            [{"role": "user", "content": "successful"}], 20,
        )
        budget.settle(
            successful,
            CallBudgetUsage(prompt_tokens=5, completion_tokens=3),
        )
        client.usage_records = (ZhipuUsage(5, 3, 8),)
        timed_out = budget.reserve(
            [{"role": "user", "content": "timeout"}], 20,
        )
        budget.settle(timed_out)
        return (_batch_failure_decision(group.group_id),), ()

    monkeypatch.setattr(trigger_online_runner, "_run_group", run_group)
    output = tmp_path / "probe.json"
    prepared = _rate_prepared("C")
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        output,
        pair_context=_pair_context(),
    )

    trace = report.groups[0].unreported_call_traces[0]
    assert trace.stage == "primary"
    assert trace.physical_calls == 1
    assert trace.provider_reported_tokens == 8
    assert trace.budget_accounted_tokens == (
        8 + trace.unreported_reserved_settlement
    )
    assert trace.budget_after.physical_calls - trace.budget_before.physical_calls == 2
    assert "batch_llm_call_failed" in trace.error
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["results"][0]["unreported_call_traces"][0][
        "unreported_reserved_settlement"
    ] == trace.unreported_reserved_settlement
    assert payload["summary"]["provider_reported_tokens"] == 8
    assert payload["summary"]["budget_accounted_tokens"] == (
        trace.budget_accounted_tokens
    )
    assert payload["summary"]["unreported_reserved_settlement"] == (
        trace.unreported_reserved_settlement
    )
    assert "usage" in payload["summary"]


def test_rate_dynamic_stage_passes_gate_and_can_be_prerequisite(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _rate_prepared("C")
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (
            _valid_rate_decisions(prepared),
            (),
        ),
    )
    budget = _budget()
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "dynamic.json",
        pair_context=trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_dynamic_c",
        ),
    )

    assert report.status == "completed"
    assert report.evidence_gate is not None
    assert report.evidence_gate.passed is True
    payload = report.to_dict()
    assert payload["measurement_kind"] == "online_rate_adjustment_paired_stage"
    assert payload["pair"]["stage"] == "rate_dynamic_c"
    assert payload["pair"]["evidence_gate"]["passed"] is True
    prerequisite_gate = (
        trigger_online_runner.validate_rate_dynamic_prerequisite(
            payload,
            pair,
            prepared,
            "https://open.bigmodel.cn/api/paas/v4",
        )
    )
    assert prerequisite_gate.passed is True
    assert prerequisite_gate.validated_unit_ids == pair.required_unit_ids


@pytest.mark.parametrize(
    ("change", "expected_failure"),
    (
        (
            lambda decision: replace(
                decision,
                status=RegulationDecisionStatus.MANUAL_REVIEW,
            ),
            "明确合规/不合规",
        ),
        (
            lambda decision: replace(decision, incomplete=True),
            "不完整",
        ),
        (
            lambda decision: replace(decision, error_code="bad_output"),
            "错误码",
        ),
        (
            lambda decision: replace(decision, reasoning=""),
            "理由为空",
        ),
        (
            lambda decision: replace(decision, applicability_dispute=True),
            "适用性争议",
        ),
        (
            lambda decision: replace(decision, confidence=0.1),
            "置信度低于",
        ),
        (
            lambda decision: replace(decision, confidence=float("nan")),
            "置信度低于",
        ),
        (
            lambda decision: replace(decision, confidence=1.1),
            "置信度低于",
        ),
        (
            lambda decision: replace(decision, regulation_evidence=()),
            "法规证据为空",
        ),
        (
            lambda decision: replace(decision, product_evidence=()),
            "产品证据为空",
        ),
        (
            lambda decision: replace(
                decision,
                regulation_evidence=(replace(
                    decision.regulation_evidence[0],
                    quote=decision.regulation_evidence[0].quote[:-1],
                ),),
            ),
            "原文未匹配",
        ),
        (
            lambda decision: replace(
                decision,
                product_evidence=(replace(
                    decision.product_evidence[0],
                    quote=decision.product_evidence[0].quote[:-1],
                ),),
            ),
            "原文未匹配",
        ),
        (
            lambda decision: replace(
                decision,
                product_evidence=(ProductClauseEvidence(
                    "clause-2",
                    "第2条产品费率调整证据原文。",
                ),),
            ),
            "ID不属于当前任务",
        ),
    ),
)
def test_rate_pair_gate_rejects_unsafe_final_decision(
    change,
    expected_failure,
) -> None:
    prepared = _rate_prepared("C")
    decisions = _valid_rate_decisions(prepared)
    payload = {
        "group_id": prepared.groups[0].group_id,
        "case_id": prepared.groups[0].case_id,
        "sample_id": prepared.groups[0].sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(
                change(decisions[0]) if index == 0 else decision
            )
            for index, decision in enumerate(decisions)
        ],
        "attempts": [],
    }

    gate = trigger_online_runner.validate_rate_pair_group_payload(
        prepared.groups[0],
        payload,
    )

    assert gate.passed is False
    assert expected_failure in "；".join(gate.failures)


def test_rate_pair_gate_validates_obligation_items_and_derived_status() -> None:
    prepared = _rate_prepared("C")
    group = prepared.groups[0]
    first = group.packages[0]
    obligation = RegulationObligation(
        "OBL001",
        "费率调整间隔不得短于1年",
        automated_decision_allowed=True,
        insufficient_reason="",
    )
    first = replace(first, obligations=(obligation,))
    group = replace(group, packages=(first, *group.packages[1:]))
    decisions = list(_valid_rate_decisions(replace(prepared, groups=(group,))))
    decisions[0] = replace(
        decisions[0],
        obligation_assessments=(RegulationObligationAssessment(
            obligation_id="OBL001",
            requirement=obligation.requirement,
            status=RegulationObligationStatus.SATISFIED,
            reasoning="条款明确约定间隔不少于1年。",
            regulation_chunk_ids=(first.regulation.chunks[0].chunk_id,),
            product_clause_ids=(first.clauses[0].clause.clause_id,),
        ),),
    )
    payload = {
        "group_id": group.group_id,
        "case_id": group.case_id,
        "sample_id": group.sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(item) for item in decisions
        ],
        "attempts": [],
    }

    gate = trigger_online_runner.validate_rate_pair_group_payload(group, payload)

    assert gate.passed
    payload["decisions"][0]["obligation_assessments"][0]["status"] = (
        "insufficient_information"
    )
    rejected = trigger_online_runner.validate_rate_pair_group_payload(
        group,
        payload,
    )
    assert not rejected.passed
    assert "总体结论与逐项义务状态不一致" in "；".join(rejected.failures)


@pytest.mark.parametrize("mutation", ("satisfied", "wrong_reason", "evidence"))
def test_rate_pair_gate_enforces_obligation_automation_boundary(
    mutation: str,
) -> None:
    prepared = _rate_prepared("C")
    group = prepared.groups[0]
    first = group.packages[0]
    obligation = RegulationObligation(
        "OBL001",
        "分组方式应与产品定价政策一致",
        automated_decision_allowed=False,
        insufficient_reason="审核包未包含产品定价政策。",
    )
    first = replace(first, obligations=(obligation,))
    group = replace(group, packages=(first, *group.packages[1:]))
    decisions = list(_valid_rate_decisions(replace(prepared, groups=(group,))))
    assessment = RegulationObligationAssessment(
        obligation_id=obligation.obligation_id,
        requirement=obligation.requirement,
        status=RegulationObligationStatus.INSUFFICIENT_INFORMATION,
        reasoning=obligation.insufficient_reason,
    )
    if mutation == "satisfied":
        assessment = replace(
            assessment,
            status=RegulationObligationStatus.SATISFIED,
        )
    elif mutation == "wrong_reason":
        assessment = replace(assessment, reasoning="模型声称证据充分。")
    else:
        assessment = replace(
            assessment,
            regulation_chunk_ids=(first.regulation.chunks[0].chunk_id,),
            product_clause_ids=(first.clauses[0].clause.clause_id,),
        )
    decisions[0] = replace(
        decisions[0],
        status=RegulationDecisionStatus.INSUFFICIENT_INFORMATION,
        obligation_assessments=(assessment,),
    )
    payload = {
        "group_id": group.group_id,
        "case_id": group.case_id,
        "sample_id": group.sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(item) for item in decisions
        ],
        "attempts": [],
    }

    gate = trigger_online_runner.validate_rate_pair_group_payload(group, payload)

    assert not gate.passed
    assert "OBL001" in "；".join(gate.failures)


def test_rate_pair_gate_rejects_submitted_weak_product_evidence() -> None:
    prepared = _rate_prepared("C")
    group = prepared.groups[0]
    first = group.packages[0]
    weak_clause = replace(
        first.clauses[0],
        clause=replace(
            first.clauses[0].clause,
            clause_id="weak-clause",
            text="仅供上下文阅读的弱召回条款。",
        ),
    )
    first = replace(
        first,
        clauses=(*first.clauses, weak_clause),
        product_evidence_candidates=(
            *first.product_evidence_candidates,
            ProductEvidenceCandidate(
                clause_id="weak-clause",
                strength=ProductEvidenceStrength.WEAK,
                source_layers=("bm25",),
            ),
        ),
    )
    group = replace(group, packages=(first, *group.packages[1:]))
    decisions = list(_valid_rate_decisions(replace(prepared, groups=(group,))))
    decisions[0] = replace(
        decisions[0],
        product_evidence=(ProductClauseEvidence(
            clause_id="weak-clause",
            quote="仅供上下文阅读的弱召回条款。",
        ),),
    )
    payload = {
        "group_id": group.group_id,
        "case_id": group.case_id,
        "sample_id": group.sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(item) for item in decisions
        ],
        "attempts": [],
    }

    gate = trigger_online_runner.validate_rate_pair_group_payload(group, payload)

    assert not gate.passed
    assert "ID不属于当前任务" in "；".join(gate.failures)


def test_rate_pair_gate_accepts_product_name_from_trigger_target_topic() -> None:
    prepared = _rate_prepared("C")
    group = prepared.groups[0]
    first = group.packages[0]
    name_trigger = RegulationTriggerSpec(
        fact_name=TriggerFactName.IS_RATE_ADJUSTABLE,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("contract.name",),
    )
    first = replace(
        first,
        regulation=replace(
            first.regulation,
            topics=(),
            trigger_specs=(name_trigger,),
        ),
    )
    prepared = replace(
        prepared,
        groups=(replace(group, packages=(first, *group.packages[1:])),),
    )
    decisions = _valid_rate_decisions(prepared)
    decisions = (
        replace(
            decisions[0],
            product_evidence=(ProductClauseEvidence(
                "product-name",
                first.product_name,
                "product_name",
            ),),
        ),
        *decisions[1:],
    )
    payload = {
        "group_id": prepared.groups[0].group_id,
        "case_id": prepared.groups[0].case_id,
        "sample_id": prepared.groups[0].sample_id,
        "arm": "C",
        "status": "completed",
        "decisions": [
            trigger_online_runner._decision_dict(decision)
            for decision in decisions
        ],
        "attempts": [],
    }

    gate = trigger_online_runner.validate_rate_pair_group_payload(
        prepared.groups[0],
        payload,
    )

    assert gate.passed is True
    assert gate.validated_unit_ids == _pair_context().pair_plan.required_unit_ids


def test_runner_requires_pair_context_before_call(tmp_path, monkeypatch) -> None:
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("C"),
        None,
        "必须提供冻结的两阶段运行上下文",
    )


def test_runner_rejects_a_without_prerequisite_before_call(
    tmp_path,
    monkeypatch,
) -> None:
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("A"),
        trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_full_a",
        ),
        "必须绑定有效的C报告SHA-256",
    )


def test_runner_rejects_a_gate_without_exact_units_before_call(
    tmp_path,
    monkeypatch,
) -> None:
    valid_context = _pair_context("rate_full_a")
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("A"),
        replace(
            valid_context,
            prerequisite_gate=trigger_online_runner.OnlineEvidenceGate(
                passed=True,
                validated_unit_ids=(RATE_SINGLE_UNIT_ID,),
                failures=(),
                validation_mode="first_pass",
            ),
        ),
        "调用方证据门与runner重验结果不一致",
    )


def test_runner_rejects_synthetic_a_gate_without_raw_report(
    tmp_path,
    monkeypatch,
) -> None:
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("A"),
        trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_full_a",
            prerequisite_report_sha256="c" * 64,
            prerequisite_gate=trigger_online_runner.OnlineEvidenceGate(
                passed=True,
                validated_unit_ids=pair.required_unit_ids,
                failures=(),
                validation_mode="first_pass",
            ),
        ),
        "必须携带原始C报告",
    )


def test_runner_rejects_a_when_raw_report_sha_is_tampered(
    tmp_path,
    monkeypatch,
) -> None:
    context = _pair_context("rate_full_a")
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("A"),
        replace(context, prerequisite_report_bytes=b"{}"),
        "原始C报告与绑定SHA-256不一致",
    )


def test_runner_rejects_c_with_prerequisite_before_call(
    tmp_path,
    monkeypatch,
) -> None:
    full_context = _pair_context("rate_full_a")
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("C"),
        replace(full_context, stage="rate_dynamic_c"),
        "C阶段不得携带",
    )


def test_single_runner_rejects_a_before_call(tmp_path, monkeypatch) -> None:
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _single_prepared(),
        replace(
            _single_context(),
            stage=cast(RatePairStage, "rate_full_a"),
        ),
        "不在冻结overlay允许范围",
    )


def test_single_runner_rejects_any_prerequisite_before_call(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _single_prepared()
    _approve_single_fixture(monkeypatch, prepared)
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        prepared,
        replace(
            _single_context(),
            prerequisite_report_sha256="c" * 64,
            prerequisite_gate=trigger_online_runner.OnlineEvidenceGate(
                passed=True,
                validated_unit_ids=(RATE_SINGLE_UNIT_ID,),
                failures=(),
                validation_mode="first_pass",
            ),
        ),
        "C阶段不得携带",
    )


def test_single_runner_rejects_widened_call_budget_before_call(
    tmp_path,
    monkeypatch,
) -> None:
    context = _single_context()
    widened_limits = replace(
        context.pair_plan.limits_per_stage,
        max_physical_calls=2,
    )
    forged = replace(
        context,
        pair_plan=replace(
            context.pair_plan,
            limits_per_stage=widened_limits,
        ),
    )

    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _single_prepared(),
        forged,
        "单条运行上下文被放宽或篡改",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_chunk_id",
        "changed_regulation_content",
        "wrong_target_clause_id",
        "changed_target_clause_content",
        "extra_clause",
        "extra_submitted_body",
        "weak_candidate",
        "extra_strong_candidate",
        "fallback",
        "multiple_segments",
        "changed_outline_title",
        "changed_product_name",
    ),
)
def test_single_runner_revalidates_complete_external_scope_before_call(
    tmp_path,
    monkeypatch,
    mutation,
) -> None:
    prepared = _single_prepared()
    _approve_single_fixture(monkeypatch, prepared)
    group = prepared.groups[0]
    package = group.packages[0]
    clauses = package.clauses
    candidates = package.product_evidence_candidates
    if mutation == "wrong_chunk_id":
        chunk = replace(
            package.regulation.chunks[0],
            chunk_id="kb-chunk:forged",
        )
        package = replace(
            package,
            regulation=replace(package.regulation, chunks=(chunk,)),
        )
    elif mutation == "changed_regulation_content":
        chunk = replace(
            package.regulation.chunks[0],
            content="被替换的法规正文。",
        )
        package = replace(
            package,
            regulation=replace(package.regulation, chunks=(chunk,)),
        )
    elif mutation == "wrong_target_clause_id":
        target = replace(
            clauses[13],
            clause=replace(clauses[13].clause, clause_id="forged-clause"),
        )
        package = replace(package, clauses=(*clauses[:13], target, *clauses[14:]))
    elif mutation == "changed_target_clause_content":
        target = replace(
            clauses[13],
            clause=replace(clauses[13].clause, text="被替换的产品条款正文。"),
        )
        package = replace(package, clauses=(*clauses[:13], target, *clauses[14:]))
    elif mutation == "extra_clause":
        package = replace(package, clauses=(*clauses, clauses[-1]))
    elif mutation == "extra_submitted_body":
        first = replace(clauses[0], submitted=True)
        package = replace(package, clauses=(first, *clauses[1:]))
    elif mutation == "weak_candidate":
        package = replace(
            package,
            product_evidence_candidates=(replace(
                candidates[0],
                strength=ProductEvidenceStrength.WEAK,
            ),),
        )
    elif mutation == "extra_strong_candidate":
        package = replace(
            package,
            product_evidence_candidates=(
                *candidates,
                ProductEvidenceCandidate(
                    clause_id=clauses[0].clause.clause_id,
                    strength=ProductEvidenceStrength.STRONG,
                    source_layers=("forged",),
                ),
            ),
        )
    elif mutation == "changed_outline_title":
        first = replace(
            clauses[0],
            clause=replace(clauses[0].clause, title="被替换的目录标题"),
        )
        package = replace(package, clauses=(first, *clauses[1:]))
    elif mutation == "changed_product_name":
        package = replace(package, product_name="被替换的产品名称")
    elif mutation == "fallback":
        group = replace(group, full_document_fallback=True)
    elif mutation == "multiple_segments":
        group = replace(group, primary_segment_count=2)
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    group = replace(group, packages=(package,))
    mutated = replace(prepared, groups=(group,))

    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        mutated,
        _single_context(),
        "单条运行",
    )


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "expected_message"),
    (
        ("sha256", "f" * 64, "不属于已批准的冻结overlay"),
        (
            "evidence_protocol_version",
            "forged-protocol-v1",
            "证据协议不是已批准版本",
        ),
    ),
)
def test_runner_rejects_forged_pair_before_call(
    tmp_path,
    monkeypatch,
    changed_field,
    changed_value,
    expected_message,
) -> None:
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    forged_pair = replace(pair, **{changed_field: changed_value})
    _assert_runner_rejects_before_call(
        tmp_path,
        monkeypatch,
        _rate_prepared("C"),
        trigger_online_runner.RatePairRunContext(
            pair_plan=forged_pair,
            stage="rate_dynamic_c",
        ),
        expected_message,
    )


def test_rate_dynamic_gate_failure_marks_top_level_incomplete(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _rate_prepared("C")
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    unsafe = tuple(
        replace(decision, product_evidence=())
        for decision in _valid_rate_decisions(prepared)
    )
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (unsafe, ()),
    )
    budget = _budget()

    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "dynamic-failed.json",
        pair_context=trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_dynamic_c",
        ),
    )

    assert report.status == "incomplete"
    assert report.stopped_reason == "evidence_gate_failed"
    assert report.evidence_gate is not None
    assert report.evidence_gate.passed is False


def test_prerequisite_rejects_changed_protocol_and_endpoint(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _rate_prepared("C")
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (
            _valid_rate_decisions(prepared),
            (),
        ),
    )
    budget = _budget()
    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "dynamic.json",
        pair_context=trigger_online_runner.RatePairRunContext(
            pair_plan=pair,
            stage="rate_dynamic_c",
        ),
    ).to_dict()
    changed_pair = dict(cast(dict, report["pair"]))
    changed_pair["evidence_protocol_version"] = "changed"
    changed_report = {**report, "pair": changed_pair}

    protocol_gate = trigger_online_runner.validate_rate_dynamic_prerequisite(
        changed_report,
        pair,
        prepared,
        "https://open.bigmodel.cn/api/paas/v4",
    )
    endpoint_gate = trigger_online_runner.validate_rate_dynamic_prerequisite(
        report,
        pair,
        prepared,
        "https://open.bigmodel.cn/another-endpoint",
    )

    assert protocol_gate.passed is False
    assert "evidence_protocol_version" in "；".join(protocol_gate.failures)
    assert endpoint_gate.passed is False
    assert "供应商端点" in "；".join(endpoint_gate.failures)


def test_full_stage_records_prerequisite_sha_and_separate_pair_budget(
    tmp_path,
    monkeypatch,
) -> None:
    prepared = _rate_prepared("A")
    pair_context = _pair_context("rate_full_a")
    monkeypatch.setattr(
        trigger_online_runner,
        "_run_group",
        lambda _group, _client, _remaining: (
            _valid_rate_decisions(prepared),
            (),
        ),
    )
    budget = _budget()

    report = trigger_online_runner.run_online_probe(
        prepared,
        cast(ZhipuClient, _NoCallClient(budget)),
        budget,
        tmp_path / "full.json",
        pair_context=pair_context,
    ).to_dict()

    assert report["status"] == "completed"
    assert report["pair"]["stage"] == "rate_full_a"
    assert report["pair"]["prerequisite_report_sha256"] == (
        pair_context.prerequisite_report_sha256
    )
    assert report["pair"]["prerequisite_gate"]["passed"] is True
    assert report["pair"]["pair_theoretical_limits"] == {
        "max_seconds": 570.0,
        "outer_watchdog_seconds": 600.0,
        "max_total_tokens": 500_000,
        "max_physical_calls": 20,
    }
    assert report["summary"]["budget"]["max_total_tokens"] == 250_000
    assert report["summary"]["budget"]["max_physical_calls"] == 10
