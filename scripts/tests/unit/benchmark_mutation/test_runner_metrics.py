"""Phase 4 单元测试：指标计算与 runner 编排（模型桩）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from lib.benchmark_mutation.golden_label import GoldenLabel
from lib.benchmark_mutation.metrics import RuleOutcome, evaluate_labels, format_report
from lib.benchmark_mutation.runner import collect_outcomes, run_variant_benchmark
from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)
from lib.common.product_tags import ProductTags

RULE = "产品责任设计#原序号=22"

def _outcome(rule_ref=RULE, statuses=("non_compliant",)):
    return RuleOutcome(rule_ref=rule_ref, variant_id="VAR-T01", statuses=statuses)

class TestRuleOutcome:
    def test_detected(self):
        assert _outcome().detected

    def test_loose_miss_on_compliant(self):
        outcome = _outcome(statuses=("compliant",))
        assert outcome.loose_missed and outcome.strict_missed

    def test_strict_only_miss_on_manual_review(self):
        outcome = _outcome(statuses=("manual_review",))
        assert outcome.strict_missed and not outcome.loose_missed and outcome.undetermined

    def test_empty_statuses_not_missed(self):
        outcome = _outcome(statuses=())
        assert not outcome.detected and not outcome.loose_missed

class TestEvaluateLabels:
    def test_aggregates_counts_and_rates(self):
        outcomes = (
            _outcome(statuses=("non_compliant",)),
            _outcome(statuses=("compliant",)),
            _outcome(statuses=("insufficient_information",)),
        )
        report = evaluate_labels(outcomes, false_positive_refs=("其他法规#1",))
        assert report.label_count == 3
        assert report.detected_count == 1
        assert report.loose_miss_count == 1
        assert report.strict_miss_count == 2
        assert report.detection_rate > 0
        assert report.false_positive_count == 1

    def test_per_rule_grouping(self):
        outcomes = (
            _outcome(statuses=("non_compliant",)),
            _outcome(rule_ref="产品条款表述#原序号=10", statuses=("compliant",)),
        )
        report = evaluate_labels(outcomes)
        assert ("产品条款表述#原序号=10", 0, 1, 1) in report.per_rule

    def test_format_report_includes_dual_miss_rates(self):
        report = evaluate_labels((_outcome(statuses=("compliant",)),))
        text = format_report(report)
        assert "宽松漏检" in text and "严格漏检" in text

class TestRunner:
    def test_pipeline_stub_collects_target_and_false_positive(self):
        labels = (GoldenLabel("VAR-T01", RULE, "violated", "C1", "OP-T01"),)
        decisions = (
            ("RU-TARGET", "non_compliant"),
            ("RU-OTHER", "non_compliant"),
            ("RU-IGNORED", "compliant"),
        )
        run = run_variant_benchmark(
            "VAR-T01", _request(), labels, _pipeline_stub(decisions),
            unit_refs={"RU-TARGET": RULE, "RU-OTHER": "产品条款表述#原序号=9"},
        )
        assert run.false_positive_refs == ("RU-OTHER",)
        unit_refs = {"RU-TARGET": RULE, "RU-OTHER": "产品条款表述#原序号=9"}
        outcomes = collect_outcomes((run,), unit_refs)
        assert len(outcomes) == 1
        assert outcomes[0].detected

    def test_target_missed_records_loose_miss(self):
        labels = (GoldenLabel("VAR-T01", RULE, "violated", "C1", "OP-T01"),)
        decisions = (("RU-TARGET", "compliant"),)
        run = run_variant_benchmark(
            "VAR-T01", _request(), labels, _pipeline_stub(decisions),
            unit_refs={"RU-TARGET": RULE},
        )
        outcomes = collect_outcomes((run,), {"RU-TARGET": RULE})
        assert outcomes[0].loose_missed

def _request():
    return _StubRequest()

@dataclass(frozen=True)
class _StubRequest:
    clauses: Tuple[AuditClauseSnapshot, ...] = ()

@dataclass(frozen=True)
class _StubResult:
    records: Tuple = ()
    @staticmethod
    def with_decisions(decisions):
        records = tuple(
            _StubRecord(RegulationAuditDecision(
                task_id=f"T-{i}", regulation_unit_id=unit_id,
                status=RegulationDecisionStatus(status), reasoning="", suggestion="",
                regulation_evidence=(), product_evidence=(),
            ))
            for i, (unit_id, status) in enumerate(decisions)
        )
        return _StubResult(records)

@dataclass(frozen=True)
class _StubRecord:
    decision: RegulationAuditDecision
    package: object = None

def _pipeline_stub(decisions):
    result = _StubResult.with_decisions(decisions)
    return lambda request: result
