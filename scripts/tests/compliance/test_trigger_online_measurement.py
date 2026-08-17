import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import measure_trigger_online_ab as online_cli
from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    ProductEvidenceCandidate,
    ProductEvidenceStrength,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
)
from lib.common.product_tags import ProductTags
from lib.compliance import trigger_online_measurement
from lib.compliance.auditor import build_audit_messages, build_batch_audit_messages
from lib.compliance.trigger_online_measurement import (
    APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256,
    APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256,
    APPROVED_RATE_PAIR_PLAN_SHA256,
    APPROVED_RATE_SINGLE_PLAN_SHA256,
    OnlineProbeCase,
    PreparedOnlineProbe,
    PreparedOnlineProbeGroup,
    RATE_OBLIGATION_DUAL_UNIT_IDS,
    RATE_SINGLE_UNIT_ID,
    load_online_probe_plan,
    load_rate_pair_probe_plan,
    select_rate_pair_stage,
)
from lib.compliance.trigger_online_runner import OnlineEvidenceGate
from measure_trigger_online_ab import (
    _run_with_watchdog,
    _validate_online_plan,
    _validate_output_path,
    _validate_zhipu_endpoint,
)


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
_OBLIGATION_DUAL_PLAN = (
    _ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-rate-obligation-dual-v2.json"
)
_OBLIGATION_SINGLE_PLAN = (
    _ROOT
    / ".Codex"
    / "specs"
    / "037-regulation-trigger-facts"
    / "trigger-online-rate-obligation-single-v2.json"
)


def _single_target_package() -> RegulationAuditPackage:
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
        )
        for index in range(1, 107)
    )
    return RegulationAuditPackage(
        task_id=f"audit:{RATE_SINGLE_UNIT_ID}",
        input_index=1,
        product_name="人保健康悠优保互联网医疗保险（费率可调）",
        product_tags=ProductTags(),
        regulation=RegulationUnitSnapshot(
            regulation_unit_id=RATE_SINGLE_UNIT_ID,
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
        complete_document=True,
        product_evidence_candidates=(ProductEvidenceCandidate(
            clause_id=target_clause_id,
            strength=ProductEvidenceStrength.STRONG,
            source_layers=("trigger_fact", "exact_topic"),
        ),),
    )


def _dual_third_target_package() -> RegulationAuditPackage:
    package = _single_target_package()
    return replace(
        package,
        task_id=f"audit:{RATE_OBLIGATION_DUAL_UNIT_IDS[1]}",
        input_index=2,
        regulation=replace(
            package.regulation,
            regulation_unit_id=RATE_OBLIGATION_DUAL_UNIT_IDS[1],
            article_number="第3条检核规则",
            section_path="第3条检核规则",
            chunks=(RegulationChunkSnapshot(
                chunk_id=(
                    "kb-chunk:43dbc6cf0206f7dfaffecb474fcee1894"
                    "31be2e00f5455947ee7723611130164"
                ),
                content="费率可调产品条款应完整披露调整规则。",
                chunk_index=0,
            ),),
        ),
    )


def _prepared_rate_source_group() -> PreparedOnlineProbe:
    base = load_online_probe_plan(_PLAN)
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    target = _single_target_package()
    packages = tuple(
        target
        if unit_id == RATE_SINGLE_UNIT_ID
        else _dual_third_target_package()
        if unit_id == RATE_OBLIGATION_DUAL_UNIT_IDS[1]
        else cast(RegulationAuditPackage, SimpleNamespace(
            regulation=SimpleNamespace(regulation_unit_id=unit_id),
        ))
        for unit_id in pair.required_unit_ids
    )
    return PreparedOnlineProbe(
        plan=base,
        groups=(PreparedOnlineProbeGroup(
            group_id=pair.dynamic_group_id,
            case_id=pair.case_id,
            sample_id=pair.sample_id,
            arm="C",
            packages=packages,
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


def test_frozen_online_plan_has_authorized_six_unit_scope() -> None:
    plan = load_online_probe_plan(_PLAN)

    assert plan.provider == "zhipu"
    assert plan.model == "glm-4-flash-250414"
    assert len(plan.authorized_products) == 3
    assert len(plan.unit_ids) == 6
    assert len(set(plan.unit_ids)) == 6
    assert plan.limits.max_total_tokens == 250_000
    assert plan.limits.max_seconds == 285
    assert plan.limits.outer_watchdog_seconds == 300
    assert plan.limits.max_physical_calls == 10
    assert sum(case.canary_dynamic_skip for case in plan.cases) == 1
    assert plan.sha256 == (
        "b93d46e2ea0efc916ff22404aa901b626a182aa494478fcc0015f088ad848d4d"
    )
    assert plan.kb_catalog_sha256 == (
        "8587c9bf7b7169229fc9ac4676338995aeb8629ce4f405ee956525686d92de34"
    )
    assert tuple(
        (item.sample_id, item.sha256) for item in plan.authorized_products
    ) == (
        ("real-001", "8b9a49e926a734ee8ec3ea32aaa805feeb65876ecec282d914be11b8b5d33ace"),
        ("real-015", "4d6f1b6597852a971268623a42e2b76f4380fcaf824f012175c7bfe4ccdacfcd"),
        ("real-019", "da5bf033921283a9c91ec4923b572e9ab904281d47368a5474ac77c256421bb7"),
    )
    assert plan.unit_ids == (
        "regulation-unit:016cee60953e13b743abf40e0f8f64b7eb4edceb509a400be03038e21bafc5a5",
        "regulation-unit:1eaabf6dcf068b4108d8268e9c317fcb4ff2dd7685be010dc21d7e179b1d32f1",
        "regulation-unit:2aeabccb65ebb8bf692709fb4de7e08ccef2880428ea0b931dbee600bdea917f",
        "regulation-unit:5c0dfefa6ceb7b210ec209098389b1b1aec0c08bb17021b3cee2e8f3a3789332",
        "regulation-unit:5003c66808cf0dfe694f3855c89bc7d0415ff246dcb0642ef78828992e108f6c",
        "regulation-unit:7a7e575629e47f10491cc70b49e5352ed6b27780b4ecbcbc5fb8a4544af9dbdd",
    )


def test_rate_pair_overlay_is_frozen_and_preserves_base_plan() -> None:
    base = load_online_probe_plan(_PLAN)
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)

    assert pair.sha256 == APPROVED_RATE_PAIR_PLAN_SHA256
    assert pair.base_plan_sha256 == base.sha256
    assert pair.evidence_protocol_version == "task-scoped-evidence-id-v1"
    assert pair.required_unit_ids == base.cases[0].unit_ids
    assert pair.limits_per_stage == base.limits
    assert pair.pair_theoretical_limits.max_total_tokens == 500_000
    assert pair.pair_theoretical_limits.max_physical_calls == 20


def test_rate_pair_overlay_rejects_any_modified_copy(tmp_path) -> None:
    raw = json.loads(_PAIR_PLAN.read_text(encoding="utf-8"))
    raw["evidence_protocol_version"] = "modified"
    modified = tmp_path / "modified-pair.json"
    modified.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="冻结版本"):
        load_rate_pair_probe_plan(modified)


def test_rate_single_overlay_is_frozen_and_dynamic_only() -> None:
    base = load_online_probe_plan(_PLAN)
    single = load_rate_pair_probe_plan(_SINGLE_PLAN)

    assert single.sha256 == APPROVED_RATE_SINGLE_PLAN_SHA256
    assert single.base_plan_sha256 == base.sha256
    assert single.required_unit_ids == (RATE_SINGLE_UNIT_ID,)
    assert single.allowed_stages == ("rate_dynamic_c",)
    assert single.full_group_id == ""
    assert single.single_dynamic_only is True
    assert single.budget_scope == "single_dynamic_stage"
    assert single.http_timeout_cap_seconds == 75
    assert single.limits_per_stage.max_total_tokens == 125_000
    assert single.limits_per_stage.max_physical_calls == 1
    assert single.limits_per_stage.max_batch_units == 1
    assert single.limits_per_stage.max_seconds == 285
    assert single.limits_per_stage.outer_watchdog_seconds == 300
    assert single.pair_theoretical_limits.max_total_tokens == 125_000
    assert single.pair_theoretical_limits.max_physical_calls == 1


def test_rate_single_overlay_rejects_any_modified_copy(tmp_path) -> None:
    raw = json.loads(_SINGLE_PLAN.read_text(encoding="utf-8"))
    raw["limits_per_stage"]["max_physical_calls"] = 2
    modified = tmp_path / "modified-single.json"
    modified.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="冻结版本"):
        load_rate_pair_probe_plan(modified)


def test_rate_obligation_dual_overlay_is_frozen_and_complete() -> None:
    dual = load_rate_pair_probe_plan(_OBLIGATION_DUAL_PLAN)

    assert dual.sha256 == APPROVED_RATE_OBLIGATION_DUAL_PLAN_SHA256
    assert dual.required_unit_ids == RATE_OBLIGATION_DUAL_UNIT_IDS
    assert dual.allowed_stages == ("rate_dynamic_c",)
    assert dual.obligation_dual_only
    assert not dual.single_dynamic_only
    assert dual.budget_scope == "obligation_dual_stage"
    assert dual.limits_per_stage.max_total_tokens == 175_000
    assert dual.limits_per_stage.max_physical_calls == 1
    assert dual.limits_per_stage.max_batch_units == 2
    assert [len(item.obligations) for item in dual.obligation_catalogs] == [6, 7]
    assert [
        item.automated_decision_allowed
        for item in dual.obligation_catalogs[0].obligations
    ] == [True, True, True, False, True, True]
    assert [
        item.automated_decision_allowed
        for item in dual.obligation_catalogs[1].obligations
    ] == [False, False, True, True, True, True, True]
    assert "产品定价政策" in dual.obligation_catalogs[0].obligations[3].insufficient_reason


def test_select_rate_obligation_dual_stage_keeps_one_body_and_all_obligations() -> None:
    dual = load_rate_pair_probe_plan(_OBLIGATION_DUAL_PLAN)
    selected = select_rate_pair_stage(
        _prepared_rate_source_group(),
        dual,
        "rate_dynamic_c",
    )

    group = selected.groups[0]
    assert tuple(
        package.regulation.regulation_unit_id for package in group.packages
    ) == RATE_OBLIGATION_DUAL_UNIT_IDS
    assert group.evidence_repair_enabled is False
    assert group.primary_segment_count == 1
    assert selected.planned_provider_response_floor == 1
    assert selected.planned_provider_response_ceiling == 1
    assert [len(package.obligations) for package in group.packages] == [6, 7]
    assert all(
        [routed.clause.number for routed in package.clauses if routed.submitted]
        == ["2.3"]
        for package in group.packages
    )
    messages = build_batch_audit_messages(group.packages)
    payload = json.loads(
        messages[1]["content"].split("审核包：\n", 1)[1]
    )
    assert [
        len(task["regulation_unit"]["obligations"])
        for task in payload["regulation_tasks"]
    ] == [6, 7]


def test_rate_obligation_single_overlay_is_frozen_and_complete() -> None:
    single = load_rate_pair_probe_plan(_OBLIGATION_SINGLE_PLAN)

    assert single.sha256 == APPROVED_RATE_OBLIGATION_SINGLE_PLAN_SHA256
    assert single.required_unit_ids == (RATE_SINGLE_UNIT_ID,)
    assert single.allowed_stages == ("rate_dynamic_c",)
    assert single.obligation_single_only
    assert single.obligation_experiment
    assert single.budget_scope == "obligation_single_stage"
    assert single.limits_per_stage.max_total_tokens == 125_000
    assert single.limits_per_stage.max_physical_calls == 1
    assert single.limits_per_stage.max_batch_units == 1
    assert len(single.obligation_catalogs) == 1
    assert len(single.obligation_catalogs[0].obligations) == 6
    assert [
        item.automated_decision_allowed
        for item in single.obligation_catalogs[0].obligations
    ] == [True, True, True, False, True, True]


def test_obligation_overlay_requires_explicit_automation_boundary(
    tmp_path,
) -> None:
    raw = json.loads(_OBLIGATION_SINGLE_PLAN.read_text(encoding="utf-8"))
    raw["obligation_catalogs"][0]["obligations"][0].pop(
        "automated_decision_allowed"
    )
    modified = tmp_path / "missing-obligation-boundary.json"
    modified.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="automated_decision_allowed"):
        load_rate_pair_probe_plan(modified)


def test_select_rate_obligation_single_stage_keeps_one_body_and_six_obligations() -> None:
    single = load_rate_pair_probe_plan(_OBLIGATION_SINGLE_PLAN)
    selected = select_rate_pair_stage(
        _prepared_rate_source_group(),
        single,
        "rate_dynamic_c",
    )

    group = selected.groups[0]
    assert tuple(
        package.regulation.regulation_unit_id for package in group.packages
    ) == (RATE_SINGLE_UNIT_ID,)
    assert group.evidence_repair_enabled is False
    assert group.primary_segment_count == 1
    assert selected.planned_provider_response_floor == 1
    assert selected.planned_provider_response_ceiling == 1
    package = group.packages[0]
    assert len(package.obligations) == 6
    assert [
        routed.clause.number for routed in package.clauses if routed.submitted
    ] == ["2.3"]
    messages = build_audit_messages(package, allow_context_request=False)
    payload = json.loads(messages[1]["content"].split("审核包：\n", 1)[1])
    assert len(payload["regulation_unit"]["obligations"]) == 6


def test_select_rate_single_stage_keeps_only_strong_2_3_body() -> None:
    single = load_rate_pair_probe_plan(_SINGLE_PLAN)
    selected = select_rate_pair_stage(
        _prepared_rate_source_group(),
        single,
        "rate_dynamic_c",
    )

    assert len(selected.groups) == 1
    group = selected.groups[0]
    assert group.group_id == single.dynamic_group_id
    assert group.arm == "C"
    assert group.full_document_fallback is False
    assert group.http_timeout_cap_seconds == 75
    assert len(group.packages) == 1
    package = group.packages[0]
    assert package.input_index == 1
    assert package.regulation.regulation_unit_id == RATE_SINGLE_UNIT_ID
    assert len(package.clauses) == 106
    submitted = tuple(
        routed for routed in package.clauses if routed.submitted
    )
    assert len(submitted) == 1
    assert submitted[0].clause.clause_id == (
        "clause_d2ff0389f54cb85e7d14a6aae5fd3d57"
    )
    assert submitted[0].clause.number == "2.3"
    assert submitted[0].clause.title == "费率调整"
    assert selected.plan.limits.max_total_tokens == 125_000
    assert selected.plan.limits.max_physical_calls == 1
    assert selected.planned_provider_response_floor == 1
    assert selected.planned_provider_response_ceiling == 1
    assert selected.summary()["fixed_unit_count"] == 1

    messages = build_audit_messages(package, allow_context_request=False)
    payload = json.loads(
        messages[1]["content"].split("\n审核包：\n", 1)[1]
    )
    assert len(payload["product"]["clause_outline"]) == 106
    assert payload["product"]["clauses"] == [{
        "context_ref": "C014",
        "clause_id": "clause_d2ff0389f54cb85e7d14a6aae5fd3d57",
        "number": "2.3",
        "title": "费率调整",
        "text": "本产品费率可调，首次费率调整不早于销售后三年。",
        "topics": ["premium.rate_adjustment"],
        "hierarchy_level": 0,
        "parent_number": None,
        "ancestor_numbers": [],
        "hierarchy_path": "",
        "container_only": False,
        "relation": "direct",
        "routing_reasons": ["费率调整主题"],
    }]
    assert [
        item["evidence_id"]
        for item in payload["product"]["product_evidence_catalog"]
    ] == ["U0002-P014"]
    assert [
        item["evidence_id"]
        for item in payload["regulation_unit"]["chunks"]
    ] == ["U0002-R001"]
    assert sum(
        item["body_submitted"]
        for item in payload["product"]["clause_outline"]
    ) == 1

    with pytest.raises(ValueError, match="不允许运行阶段"):
        select_rate_pair_stage(
            _prepared_rate_source_group(),
            single,
            "rate_full_a",
        )


def test_select_rate_pair_stage_keeps_exact_single_group() -> None:
    base = load_online_probe_plan(_PLAN)
    pair = load_rate_pair_probe_plan(_PAIR_PLAN)
    packages = tuple(
        cast(RegulationAuditPackage, SimpleNamespace(
            regulation=SimpleNamespace(regulation_unit_id=unit_id),
        ))
        for unit_id in pair.required_unit_ids
    )
    common = {
        "case_id": pair.case_id,
        "sample_id": pair.sample_id,
        "packages": packages,
        "full_document_fallback": False,
        "prompt_chars": 1,
        "prompt_utf8_bytes": 1,
        "max_output_tokens": 1,
        "max_prompt_length": 200_000,
        "primary_segment_count": 1,
    }
    prepared = PreparedOnlineProbe(
        plan=base,
        groups=(
            PreparedOnlineProbeGroup(
                group_id=pair.full_group_id,
                arm="A",
                **common,
            ),
            PreparedOnlineProbeGroup(
                group_id=pair.dynamic_group_id,
                arm="C",
                **common,
            ),
        ),
        skipped_dynamic_canaries=(),
        product_manifest_path="manifest.json",
        kb_build_manifest_path="v5-build-manifest.json",
    )

    selected_c = select_rate_pair_stage(prepared, pair, "rate_dynamic_c")
    selected_a = select_rate_pair_stage(prepared, pair, "rate_full_a")

    assert tuple(group.group_id for group in selected_c.groups) == (
        pair.dynamic_group_id,
    )
    assert tuple(group.group_id for group in selected_a.groups) == (
        pair.full_group_id,
    )
    assert selected_c.planned_provider_response_floor == 1
    assert selected_c.planned_provider_response_ceiling == 2


def test_online_mode_rejects_modified_plan_or_non_zhipu_endpoint() -> None:
    plan = load_online_probe_plan(_PLAN)
    _validate_online_plan(plan)

    with pytest.raises(ValueError, match="已审核"):
        _validate_online_plan(replace(plan, sha256="b" * 64))
    _validate_zhipu_endpoint("https://open.bigmodel.cn/api/paas/v4/")
    with pytest.raises(ValueError, match="智谱官方"):
        _validate_zhipu_endpoint("https://example.com/api/paas/v4/")


def test_segment_preflight_preserves_source_index_and_execution_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_package = cast(RegulationAuditPackage, SimpleNamespace(
        regulation=SimpleNamespace(
            regulation_unit_id="unit",
            law_name="测试法规",
            article_number="第1条",
            source_file="测试法规.md",
            chunks=(),
        ),
        clauses=(),
    ))
    source_segments = ("source-1", "source-2")
    monkeypatch.setattr(
        trigger_online_measurement,
        "build_batch_audit_messages",
        lambda _packages: [{"role": "user", "content": "initial"}],
    )
    monkeypatch.setattr(
        trigger_online_measurement,
        "split_audit_package",
        lambda _package, **_kwargs: source_segments,
    )
    monkeypatch.setattr(
        trigger_online_measurement,
        "build_audit_messages",
        lambda segment: [{
            "role": "user",
            "content": "小段" if segment == "source-1" else "较大的分段" * 10,
        }],
    )
    case = OnlineProbeCase("case", "sample", ("unit",), ())

    group = trigger_online_measurement._build_group(
        case,
        "A",
        (source_package,),
        False,
    )

    assert tuple(
        (
            segment.source_segment_index,
            segment.execution_order,
            segment.segment_index,
        )
        for segment in group.primary_segments
    ) == ((2, 1, 1), (1, 2, 2))
    serialized = trigger_online_measurement.PreparedOnlineProbe(
        plan=load_online_probe_plan(_PLAN),
        groups=(group,),
        skipped_dynamic_canaries=(),
        product_manifest_path="manifest.json",
        kb_build_manifest_path="v5-build-manifest.json",
    ).summary()["groups"]
    assert isinstance(serialized, list)
    assert serialized[0]["primary_segments"] == [
        {
            "segment_index": 1,
            "source_segment_index": 2,
            "execution_order": 1,
            "prompt_chars": len("较大的分段" * 10),
            "prompt_utf8_bytes": len(("较大的分段" * 10).encode("utf-8")),
            "max_output_tokens": 4096,
        },
        {
            "segment_index": 2,
            "source_segment_index": 1,
            "execution_order": 2,
            "prompt_chars": len("小段"),
            "prompt_utf8_bytes": len("小段".encode("utf-8")),
            "max_output_tokens": 4096,
        },
    ]


def test_online_output_guard_rejects_input_directories(tmp_path) -> None:
    products = tmp_path / "products"
    kb = tmp_path / "kb"
    products.mkdir()
    kb.mkdir()

    with pytest.raises(ValueError, match="产品条款目录"):
        _validate_output_path(products / "result.json", products, kb)
    with pytest.raises(ValueError, match="知识库目录"):
        _validate_output_path(kb / "result.json", products, kb)
    with pytest.raises(ValueError, match=".json"):
        _validate_output_path(tmp_path / "result.xlsx", products, kb)

    assert _validate_output_path(
        tmp_path / "outputs" / "result.json",
        products,
        kb,
    ) == (tmp_path / "outputs" / "result.json").resolve()


def test_outer_watchdog_terminates_child_and_checkpoints_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    class TimedOutProcess:
        def __init__(self) -> None:
            self.wait_count = 0
            self.terminated = False

        def wait(self, timeout=None) -> int:
            self.wait_count += 1
            if self.wait_count == 1:
                raise subprocess.TimeoutExpired("probe", timeout)
            return -15

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            pytest.fail("SIGTERM后已退出，不应升级SIGKILL")

    process = TimedOutProcess()
    child_environment = {}

    def start_process(*_args, **kwargs):
        child_environment.update(kwargs["env"])
        return process

    monkeypatch.setattr(subprocess, "Popen", start_process)
    args = argparse.Namespace(
        plan=_PLAN,
        pair_plan=_PAIR_PLAN,
        stage="rate_dynamic_c",
        prerequisite_json=None,
        single_unit=False,
        manifest=tmp_path / "manifest.json",
        products_dir=tmp_path / "products",
        kb_dir=tmp_path / "kb",
        output_json=tmp_path / "result.json",
    )

    exit_code = _run_with_watchdog(
        args,
        args.output_json,
        timeout_seconds=0.01,
        plan_sha256="a" * 64,
        overlay_sha256="b" * 64,
        stage="rate_dynamic_c",
        model="glm-4-flash-250414",
    )

    payload = json.loads(args.output_json.read_text(encoding="utf-8"))
    assert exit_code == 124
    assert process.terminated is True
    assert payload["status"] == "incomplete"
    assert payload["stopped_reason"] == "outer_watchdog_exceeded"
    assert payload["pair"] == {
        "pair_plan_sha256": "b" * 64,
        "stage": "rate_dynamic_c",
    }
    assert child_environment["ACTUARY_ONLINE_WATCHDOG_PLAN_SHA"] == "a" * 64
    assert child_environment["ACTUARY_ONLINE_WATCHDOG_OVERLAY_SHA"] == "b" * 64
    assert child_environment["ACTUARY_ONLINE_WATCHDOG_STAGE"] == (
        "rate_dynamic_c"
    )


def test_full_stage_rejects_failed_dynamic_gate_before_client_creation(
    tmp_path,
    monkeypatch,
) -> None:
    plan = load_online_probe_plan(_PLAN)
    prerequisite = tmp_path / "dynamic.json"
    prerequisite.write_text("{}", encoding="utf-8")
    prepared = SimpleNamespace(
        plan=plan,
        summary=lambda: {"plan_sha256": plan.sha256},
    )
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_CHILD", "1")
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_NONCE", "nonce")
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_PLAN_SHA", plan.sha256)
    monkeypatch.setenv(
        "ACTUARY_ONLINE_WATCHDOG_OVERLAY_SHA",
        load_rate_pair_probe_plan(_PAIR_PLAN).sha256,
    )
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_STAGE", "rate_full_a")
    monkeypatch.setattr(online_cli.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(online_cli.signal, "alarm", lambda *_args: None)
    monkeypatch.setattr(
        online_cli,
        "prepare_online_probe",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        online_cli,
        "select_rate_pair_stage",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        online_cli,
        "get_audit_llm_config",
        lambda: SimpleNamespace(
            provider="zhipu",
            api_key="test-key",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            timeout=30,
        ),
    )
    monkeypatch.setattr(
        online_cli,
        "validate_rate_dynamic_prerequisite",
        lambda *_args, **_kwargs: OnlineEvidenceGate(
            passed=False,
            validated_unit_ids=(),
            failures=("证据未通过",),
            validation_mode="first_pass",
        ),
    )
    monkeypatch.setattr(
        online_cli,
        "ZhipuClient",
        lambda *_args, **_kwargs: pytest.fail("不得创建A阶段模型客户端"),
    )

    output = tmp_path / "full.json"
    exit_code = online_cli.main([
        "--plan", str(_PLAN),
        "--pair-plan", str(_PAIR_PLAN),
        "--stage", "rate_full_a",
        "--prerequisite-json", str(prerequisite),
        "--manifest", str(tmp_path / "manifest.json"),
        "--products-dir", str(tmp_path / "products"),
        "--kb-dir", str(tmp_path / "kb"),
        "--output-json", str(output),
        "--online",
        "--online-child",
        "--watchdog-nonce", "nonce",
    ])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["stopped_reason"] == "prerequisite_evidence_gate_failed"
    assert payload["llm_called"] is False
    assert payload["pair"]["prerequisite_gate"]["passed"] is False


def test_watchdog_child_preserves_pair_stage_and_prerequisite(tmp_path) -> None:
    prerequisite = tmp_path / "dynamic.json"
    args = argparse.Namespace(
        plan=_PLAN,
        pair_plan=_PAIR_PLAN,
        stage="rate_full_a",
        prerequisite_json=prerequisite,
        single_unit=False,
        manifest=tmp_path / "manifest.json",
        products_dir=tmp_path / "products",
        kb_dir=tmp_path / "kb",
        output_json=tmp_path / "full.json",
    )

    command = online_cli._watchdog_command(args, "nonce")

    assert command[command.index("--stage") + 1] == "rate_full_a"
    assert command[command.index("--pair-plan") + 1] == str(
        _PAIR_PLAN.resolve()
    )
    assert command[command.index("--prerequisite-json") + 1] == str(
        prerequisite.resolve()
    )


def test_watchdog_child_binds_single_overlay_and_explicit_flag(tmp_path) -> None:
    args = argparse.Namespace(
        plan=_PLAN,
        pair_plan=_SINGLE_PLAN,
        stage="rate_dynamic_c",
        prerequisite_json=None,
        single_unit=True,
        manifest=tmp_path / "manifest.json",
        products_dir=tmp_path / "products",
        kb_dir=tmp_path / "kb",
        output_json=tmp_path / "single.json",
    )

    command = online_cli._watchdog_command(args, "nonce")

    assert command[command.index("--stage") + 1] == "rate_dynamic_c"
    assert command[command.index("--pair-plan") + 1] == str(
        _SINGLE_PLAN.resolve()
    )
    assert "--single-unit" in command


def test_watchdog_child_binds_obligation_dual_overlay_and_flag(tmp_path) -> None:
    args = argparse.Namespace(
        plan=_PLAN,
        pair_plan=_OBLIGATION_DUAL_PLAN,
        stage="rate_dynamic_c",
        prerequisite_json=None,
        single_unit=False,
        obligation_dual=True,
        manifest=tmp_path / "manifest.json",
        products_dir=tmp_path / "products",
        kb_dir=tmp_path / "kb",
        output_json=tmp_path / "dual.json",
    )

    command = online_cli._watchdog_command(args, "nonce")

    assert command[command.index("--pair-plan") + 1] == str(
        _OBLIGATION_DUAL_PLAN.resolve()
    )
    assert "--obligation-dual" in command


@pytest.mark.parametrize(
    "argv",
    (
        (
            "--pair-plan", str(_OBLIGATION_DUAL_PLAN),
            "--stage", "rate_dynamic_c",
        ),
        (
            "--pair-plan", str(_PAIR_PLAN),
            "--stage", "rate_dynamic_c",
            "--obligation-dual",
        ),
    ),
)
def test_obligation_dual_overlay_and_flag_must_be_selected_together(
    tmp_path,
    argv,
) -> None:
    with pytest.raises(ValueError, match="--obligation-dual"):
        online_cli.main([
            "--plan", str(_PLAN),
            *argv,
            "--manifest", str(tmp_path / "manifest.json"),
            "--products-dir", str(tmp_path / "products"),
            "--kb-dir", str(tmp_path / "kb"),
            "--output-json", str(tmp_path / "result.json"),
        ])


@pytest.mark.parametrize(
    "argv",
    (
        (
            "--pair-plan", str(_SINGLE_PLAN),
            "--stage", "rate_dynamic_c",
        ),
        (
            "--pair-plan", str(_PAIR_PLAN),
            "--stage", "rate_dynamic_c",
            "--single-unit",
        ),
    ),
)
def test_single_overlay_and_flag_must_be_selected_together(
    tmp_path,
    argv,
) -> None:
    with pytest.raises(ValueError, match="--single-unit"):
        online_cli.main([
            "--plan", str(_PLAN),
            *argv,
            "--manifest", str(tmp_path / "manifest.json"),
            "--products-dir", str(tmp_path / "products"),
            "--kb-dir", str(tmp_path / "kb"),
            "--output-json", str(tmp_path / "result.json"),
        ])


def test_online_stage_has_no_implicit_three_unit_overlay(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        online_cli,
        "prepare_online_probe",
        lambda *_args, **_kwargs: pytest.fail("缺少显式overlay不得进入预检"),
    )

    with pytest.raises(ValueError, match="显式指定 --pair-plan"):
        online_cli.main([
            "--plan", str(_PLAN),
            "--stage", "rate_dynamic_c",
            "--manifest", str(tmp_path / "manifest.json"),
            "--products-dir", str(tmp_path / "products"),
            "--kb-dir", str(tmp_path / "kb"),
            "--output-json", str(tmp_path / "result.json"),
            "--online",
        ])


def test_single_overlay_rejects_a_and_prerequisite_before_prepare(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        online_cli,
        "prepare_online_probe",
        lambda *_args, **_kwargs: pytest.fail("非法单条阶段不得进入完整预检"),
    )

    with pytest.raises(ValueError, match="不在冻结overlay允许范围"):
        online_cli.main([
            "--plan", str(_PLAN),
            "--pair-plan", str(_SINGLE_PLAN),
            "--stage", "rate_full_a",
            "--single-unit",
            "--prerequisite-json", str(tmp_path / "prerequisite.json"),
            "--manifest", str(tmp_path / "manifest.json"),
            "--products-dir", str(tmp_path / "products"),
            "--kb-dir", str(tmp_path / "kb"),
            "--output-json", str(tmp_path / "result.json"),
            "--online",
        ])


@pytest.mark.parametrize(
    ("overlay_sha", "stage"),
    (
        ("f" * 64, "rate_dynamic_c"),
        (APPROVED_RATE_SINGLE_PLAN_SHA256, "rate_full_a"),
    ),
)
def test_single_watchdog_child_rejects_overlay_or_stage_mismatch_before_prepare(
    tmp_path,
    monkeypatch,
    overlay_sha,
    stage,
) -> None:
    plan = load_online_probe_plan(_PLAN)
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_CHILD", "1")
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_NONCE", "nonce")
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_PLAN_SHA", plan.sha256)
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_OVERLAY_SHA", overlay_sha)
    monkeypatch.setenv("ACTUARY_ONLINE_WATCHDOG_STAGE", stage)
    monkeypatch.setattr(
        online_cli,
        "prepare_online_probe",
        lambda *_args, **_kwargs: pytest.fail("watchdog绑定失败不得进入预检"),
    )

    with pytest.raises(ValueError, match="受控 watchdog"):
        online_cli.main([
            "--plan", str(_PLAN),
            "--pair-plan", str(_SINGLE_PLAN),
            "--stage", "rate_dynamic_c",
            "--single-unit",
            "--manifest", str(tmp_path / "manifest.json"),
            "--products-dir", str(tmp_path / "products"),
            "--kb-dir", str(tmp_path / "kb"),
            "--output-json", str(tmp_path / "result.json"),
            "--online",
            "--online-child",
            "--watchdog-nonce", "nonce",
        ])
