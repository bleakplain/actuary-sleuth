from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from lib.compliance.shadow_comparison import (
    REPORT_SCHEMA_VERSION,
    ShadowComparisonError,
    compare_snapshots,
    evaluate_manifest_gate,
    load_acceptance_manifest,
    load_audit_snapshot,
    run_shadow_comparison,
)


def _oracle() -> Dict[str, Any]:
    return {
        "applicable_regulation_unit_ids": ["reg-applicable"],
        "not_applicable_regulation_unit_ids": ["reg-not-applicable"],
        "core_clause_ids": ["clause-core"],
    }


def _decision(
    regulation_unit_id: str,
    status: str,
    *,
    regulation_evidence: bool = True,
    product_evidence: bool = False,
) -> Dict[str, Any]:
    return {
        "regulation_unit_id": regulation_unit_id,
        "status": status,
        "regulation_evidence": (
            [{"chunk_id": "chunk-1", "quote": "法规证据"}]
            if regulation_evidence
            else []
        ),
        "product_evidence": (
            [{"clause_id": "clause-core", "quote": "条款证据"}]
            if product_evidence
            else []
        ),
    }


def _snapshot(
    run_id: str,
    *,
    candidates: list[str],
    excluded: list[str],
    clauses: list[str],
    decisions: list[Dict[str, Any]],
    context_chars: int,
    degraded: bool = False,
    oracle: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "pipeline_version": f"{run_id}-pipeline-v1",
        "dataset_id": "compliance-audit-v1",
        "annotation_version": "annotations-v1",
        "samples": [
            {
                "sample_id": "sample-1",
                "candidate_regulation_unit_ids": candidates,
                "excluded_regulation_unit_ids": excluded,
                "submitted_clause_ids": clauses,
                "decisions": decisions,
                "context_chars": context_chars,
                "degraded": degraded,
                "oracle": oracle or _oracle(),
            }
        ],
    }


def _manifest(*, accepted: bool) -> Dict[str, Any]:
    status = "accepted" if accepted else "pending"
    return {
        "schema_version": "1",
        "dataset_id": "compliance-audit-v1",
        "dataset_status": status,
        "annotations": {
            "version": "annotations-v1",
            "status": status,
            "fields": {
                "product_tags": status,
                "product_risk_facts": status,
                "regulation_applicability": status,
                "clause_routing": status,
                "audit_decisions": status,
            },
        },
        "actuary_review": {
            "status": status,
            "reviewer": "张精算师" if accepted else None,
            "reviewed_at": "2026-07-28T10:00:00+08:00" if accepted else None,
            "comment": "已核对法规原文" if accepted else "待审核",
        },
        "cutover_gate": {
            "status": "open" if accepted else "blocked",
            "reason": "精算已签收" if accepted else "精算尚未签收",
        },
        "products": [
            {
                "sample_id": "sample-1",
                "annotation_status": status,
            }
        ],
        "synthetic_boundary_samples": [],
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _load_pair(
    tmp_path: Path,
    *,
    old: Dict[str, Any] | None = None,
    new: Dict[str, Any] | None = None,
) -> tuple:
    old_payload = old or _snapshot(
        "old",
        candidates=["reg-old-only"],
        excluded=[],
        clauses=["clause-old"],
        decisions=[_decision("reg-old-only", "non_compliant", product_evidence=True)],
        context_chars=900,
        degraded=True,
    )
    new_payload = new or _snapshot(
        "new",
        candidates=["reg-applicable"],
        excluded=["reg-not-applicable"],
        clauses=["clause-core"],
        decisions=[
            _decision(
                "reg-applicable",
                "compliant",
                product_evidence=True,
            )
        ],
        context_chars=400,
    )
    return (
        load_audit_snapshot(_write_json(tmp_path / "old.json", old_payload)),
        load_audit_snapshot(_write_json(tmp_path / "new.json", new_payload)),
    )


def test_pending_manifest_outputs_differences_but_never_business_metrics(
    tmp_path: Path,
) -> None:
    old, new = _load_pair(tmp_path)

    report = compare_snapshots(
        old,
        new,
        _manifest(accepted=False),
        generated_at="2026-07-28T00:00:00+00:00",
    )

    assert report.business_metrics is None
    assert report.business_metrics_status == "not_calculated"
    assert report.cutover_blocked is True
    assert "验收集尚未 accepted" in report.cutover_reasons
    assert report.context_chars_delta_total == -500
    difference = report.differences[0]
    assert difference.candidate_added == ("reg-applicable",)
    assert difference.candidate_removed == ("reg-old-only",)
    assert difference.clause_added == ("clause-core",)
    assert difference.decision_added == ("reg-applicable",)
    assert difference.decision_removed == ("reg-old-only",)


def test_pending_product_risk_facts_keep_signed_manifest_blocked(
    tmp_path: Path,
) -> None:
    old, new = _load_pair(tmp_path)
    manifest = _manifest(accepted=True)
    manifest["annotations"]["fields"]["product_risk_facts"] = "pending"

    gate = evaluate_manifest_gate(manifest, old, new)

    assert gate.accepted is False
    assert "人工标注字段尚未签收: product_risk_facts" in gate.reasons


def test_signed_manifest_calculates_all_four_business_metrics(
    tmp_path: Path,
) -> None:
    old, new = _load_pair(tmp_path)

    report = compare_snapshots(old, new, _manifest(accepted=True))

    assert report.manifest_gate.accepted is True
    assert report.business_metrics_status == "calculated"
    assert report.cutover_blocked is False
    assert report.business_metrics is not None
    metrics = report.business_metrics
    assert metrics.regulation_recall.value == 1.0
    assert metrics.exclusion_accuracy.value == 1.0
    assert metrics.clause_recall.value == 1.0
    assert metrics.evidence_completeness.value == 1.0
    assert metrics.passed is True


def test_signed_manifest_keeps_cutover_blocked_when_thresholds_fail(
    tmp_path: Path,
) -> None:
    failing_new = _snapshot(
        "new",
        candidates=[],
        excluded=["reg-not-applicable", "reg-wrongly-excluded"],
        clauses=[],
        decisions=[_decision("reg-applicable", "compliant", regulation_evidence=False)],
        context_chars=100,
    )
    old, new = _load_pair(tmp_path, new=failing_new)

    report = compare_snapshots(old, new, _manifest(accepted=True))

    assert report.business_metrics is not None
    assert report.business_metrics.regulation_recall.value == 0.0
    assert report.business_metrics.exclusion_accuracy.value == 0.5
    assert report.business_metrics.clause_recall.value == 0.0
    assert report.business_metrics.evidence_completeness.value == 0.0
    assert report.cutover_blocked is True
    assert report.cutover_reasons == ("一个或多个业务门槛未达到 100%",)


def test_signed_manifest_requires_product_evidence_for_compliant_decision(
    tmp_path: Path,
) -> None:
    new_payload = _snapshot(
        "new",
        candidates=["reg-applicable"],
        excluded=["reg-not-applicable"],
        clauses=["clause-core"],
        decisions=[_decision("reg-applicable", "compliant")],
        context_chars=400,
    )
    old, new = _load_pair(tmp_path, new=new_payload)

    report = compare_snapshots(old, new, _manifest(accepted=True))

    assert report.business_metrics is not None
    assert report.business_metrics.evidence_completeness.value == 0.0
    assert report.cutover_blocked is True


def test_zero_denominator_is_unknown_not_fake_one_hundred_percent(
    tmp_path: Path,
) -> None:
    empty_oracle = {
        "applicable_regulation_unit_ids": [],
        "not_applicable_regulation_unit_ids": [],
        "core_clause_ids": [],
    }
    old_payload = _snapshot(
        "old",
        candidates=[],
        excluded=[],
        clauses=[],
        decisions=[],
        context_chars=0,
        oracle=empty_oracle,
    )
    new_payload = _snapshot(
        "new",
        candidates=[],
        excluded=[],
        clauses=[],
        decisions=[],
        context_chars=0,
        oracle=empty_oracle,
    )
    old, new = _load_pair(tmp_path, old=old_payload, new=new_payload)

    report = compare_snapshots(old, new, _manifest(accepted=True))

    assert report.business_metrics is not None
    assert report.business_metrics.regulation_recall.value is None
    assert report.business_metrics.exclusion_accuracy.value is None
    assert report.business_metrics.clause_recall.value is None
    assert report.business_metrics.evidence_completeness.value is None
    assert report.cutover_blocked is True


def test_oracle_mismatch_is_rejected_even_before_gate_evaluation(
    tmp_path: Path,
) -> None:
    changed_oracle = _oracle()
    changed_oracle["core_clause_ids"] = ["different-clause"]
    new_payload = _snapshot(
        "new",
        candidates=["reg-applicable"],
        excluded=["reg-not-applicable"],
        clauses=["different-clause"],
        decisions=[_decision("reg-applicable", "compliant")],
        context_chars=400,
        oracle=changed_oracle,
    )
    old, new = _load_pair(tmp_path, new=new_payload)

    with pytest.raises(ShadowComparisonError, match="oracle 不一致"):
        compare_snapshots(old, new, _manifest(accepted=True))


def test_runner_writes_versioned_json_and_csv_without_online_dependencies(
    tmp_path: Path,
) -> None:
    old_path = _write_json(
        tmp_path / "old.json",
        _snapshot(
            "old",
            candidates=["reg-old-only"],
            excluded=[],
            clauses=["clause-old"],
            decisions=[],
            context_chars=900,
        ),
    )
    new_path = _write_json(
        tmp_path / "new.json",
        _snapshot(
            "new",
            candidates=["reg-applicable"],
            excluded=["reg-not-applicable"],
            clauses=["clause-core"],
            decisions=[_decision("reg-applicable", "compliant")],
            context_chars=400,
        ),
    )
    manifest_path = _write_json(tmp_path / "manifest.json", _manifest(accepted=False))

    report, files = run_shadow_comparison(
        old_path,
        new_path,
        manifest_path,
        tmp_path / "reports",
        generated_at="2026-07-28T00:00:00+00:00",
    )

    json_report = json.loads(files.json_path.read_text(encoding="utf-8"))
    with files.csv_path.open(encoding="utf-8", newline="") as source:
        csv_rows = list(csv.DictReader(source))
    assert report.schema_version == REPORT_SCHEMA_VERSION
    assert REPORT_SCHEMA_VERSION in files.json_path.name
    assert json_report["schema_version"] == REPORT_SCHEMA_VERSION
    assert json_report["cutover_blocked"] is True
    assert csv_rows[0]["schema_version"] == REPORT_SCHEMA_VERSION
    assert csv_rows[0]["sample_id"] == "sample-1"
    assert csv_rows[0]["regulation_recall"] == ""


def test_manifest_snapshot_version_mismatch_blocks_instead_of_calculating(
    tmp_path: Path,
) -> None:
    old, new = _load_pair(tmp_path)
    manifest = _manifest(accepted=True)
    manifest["annotations"]["version"] = "different-version"

    gate = evaluate_manifest_gate(manifest, old, new)

    assert gate.accepted is False
    assert "旧快照标注版本与 manifest 不一致" in gate.reasons
    assert "新快照标注版本与 manifest 不一致" in gate.reasons


def test_signed_oracle_can_be_measured_while_explicit_cutover_gate_stays_blocked(
    tmp_path: Path,
) -> None:
    old, new = _load_pair(tmp_path)
    manifest = _manifest(accepted=True)
    manifest["cutover_gate"] = {
        "status": "blocked",
        "reason": "等待业务门槛报告",
    }

    report = compare_snapshots(old, new, manifest)

    assert report.business_metrics_status == "calculated"
    assert report.business_metrics is not None
    assert report.business_metrics.passed is True
    assert report.cutover_blocked is True
    assert report.cutover_reasons == ("manifest cutover_gate 尚未 open",)


def test_current_pending_acceptance_manifest_cannot_open_cutover(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).parents[3]
    manifest_path = (
        project_root
        / "scripts"
        / "tests"
        / "fixtures"
        / "compliance_audit"
        / "v1"
        / "manifest.json"
    )
    old, new = _load_pair(tmp_path)
    # 当前冻结清单的 annotation_version 与合成快照不同；这本身也是阻断原因。
    gate = evaluate_manifest_gate(load_acceptance_manifest(manifest_path), old, new)

    assert gate.accepted is False
    assert any("尚未 accepted" in reason for reason in gate.reasons)


def test_shadow_runner_source_has_no_llm_or_legacy_rule_engine_import() -> None:
    project_root = Path(__file__).parents[3]
    files = (
        project_root / "scripts" / "lib" / "compliance" / "shadow_comparison.py",
        project_root / "scripts" / "compare_compliance_snapshots.py",
    )
    imported_modules = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert not any(module.startswith("lib.llm") for module in imported_modules)
    assert "lib.compliance.rule_engine" not in imported_modules
