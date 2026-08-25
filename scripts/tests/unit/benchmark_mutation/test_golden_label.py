"""Phase 3 单元测试：金标生成、确认工作流、冻结指纹。"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from lib.benchmark_mutation.golden_label import (
    GoldenLabel,
    apply_confirmations,
    build_golden_labels,
    freeze_dataset,
    load_confirmations,
    write_confirmation_sheet,
)
from lib.benchmark_mutation.operator_schema import parse_operator
from lib.benchmark_mutation.host_planner import VariantPlan
from lib.benchmark_mutation.variant_builder import build_variant
from lib.common.compliance_audit import AuditClauseSnapshot

def _operator():
    return parse_operator({
        "operator_id": "OP-T01",
        "rule_ref": "产品责任设计#原序号=22",
        "tier": "insertion",
        "host_tags": ["health"],
        "target_topics": ["coverage.responsibility"],
        "payload": {"insert_text": "本合同设立保单账户。"},
        "expected_decision": "violated",
        "description": "测试算子",
    })

def _record():
    clause = AuditClauseSnapshot(
        clause_id="C1", number="3.1", title="保险责任",
        text="保险责任内容。", block_type="clause",
        topics=("coverage.responsibility",),
    )
    plan = VariantPlan(variant_id="VAR-T01", host_id="host-01", operator_ids=("OP-T01",))
    return build_variant(plan, (clause,), {"OP-T01": _operator()})
class TestGoldenLabels:
    def test_builds_draft_labels_from_diffs(self):
        record = _record()
        labels = build_golden_labels(record, {"OP-T01": _operator()})
        assert len(labels) == 1
        label = labels[0]
        assert label.variant_id == "VAR-T01"
        assert label.expected == "violated"
        assert label.evidence_clause_id == "C1"
        assert not label.is_confirmed

class TestConfirmationWorkflow:
    def test_sheet_roundtrip_preserves_entries(self, tmp_path: Path):
        record = _record()
        operator = _operator()
        labels = build_golden_labels(record, {"OP-T01": operator})
        sheet = tmp_path / "confirm.csv"
        write_confirmation_sheet(labels, {record.variant_id: record}, {"OP-T01": operator}, sheet)
        loaded = load_confirmations(sheet)
        assert ("VAR-T01", "OP-T01") in loaded

    def test_sheet_contains_original_and_mutated_text(self, tmp_path: Path):
        record = _record()
        operator = _operator()
        labels = build_golden_labels(record, {"OP-T01": operator})
        sheet = tmp_path / "confirm.csv"
        write_confirmation_sheet(labels, {record.variant_id: record}, {"OP-T01": operator}, sheet)
        rows = list(csv.DictReader(sheet.open(encoding="utf-8-sig")))
        assert rows[0]["original_text"] == "保险责任内容。"
        assert "保单账户" in rows[0]["mutated_text"]

    def test_yes_confirmation_activates_label(self):
        labels = (GoldenLabel("VAR-T01", "规则#1", "violated", "C1", "OP-T01"),)
        confirmations = {("VAR-T01", "OP-T01"): ("yes", "审核人", "2026-08-25")}
        activated = apply_confirmations(labels, confirmations)
        assert len(activated) == 1
        assert activated[0].is_confirmed
        assert activated[0].confirmed_by == "审核人"

    def test_no_and_blank_confirmations_are_dropped(self):
        labels = (
            GoldenLabel("V1", "规则#1", "violated", "C1", "OP-A"),
            GoldenLabel("V2", "规则#2", "violated", "C2", "OP-B"),
        )
        confirmations = {
            ("V1", "OP-A"): ("no", "审核人", "2026-08-25"),
            ("V2", "OP-B"): ("", "", ""),
        }
        assert apply_confirmations(labels, confirmations) == ()

class TestFreeze:
    def test_freeze_produces_stable_identity(self, tmp_path: Path):
        operators_path = tmp_path / "operators.json"
        hosts_path = tmp_path / "hosts.json"
        operators_path.write_text("{}", encoding="utf-8")
        hosts_path.write_text("{}", encoding="utf-8")
        labels = (GoldenLabel("V1", "规则#1", "violated", "C1", "OP-A"),)
        fingerprint_a = freeze_dataset(labels, operators_path, hosts_path, tmp_path / "identity.json")
        fingerprint_b = freeze_dataset(labels, operators_path, hosts_path, tmp_path / "identity2.json")
        assert fingerprint_a == fingerprint_b
        identity = json.loads((tmp_path / "identity.json").read_text(encoding="utf-8"))
        assert identity["label_count"] == 1
        assert len(identity["operators_sha256"]) == 64

    def test_freeze_changes_when_labels_change(self, tmp_path: Path):
        operators_path = tmp_path / "operators.json"
        hosts_path = tmp_path / "hosts.json"
        operators_path.write_text("{}", encoding="utf-8")
        hosts_path.write_text("{}", encoding="utf-8")
        labels_a = (GoldenLabel("V1", "规则#1", "violated", "C1", "OP-A"),)
        labels_b = (GoldenLabel("V1", "规则#2", "violated", "C1", "OP-A"),)
        fa = freeze_dataset(labels_a, operators_path, hosts_path, tmp_path / "a.json")
        fb = freeze_dataset(labels_b, operators_path, hosts_path, tmp_path / "b.json")
        assert fa != fb
