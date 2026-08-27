"""Phase 2 单元测试：变异原语、宿主匹配、打包计划、变体构建。"""
from __future__ import annotations

import pytest

from lib.benchmark_mutation.host_planner import (
    HostProduct,
    HostPlanError,
    load_hosts,
    match_operators,
    plan_variants,
)
from lib.benchmark_mutation.operator_schema import parse_operator
from lib.benchmark_mutation.operators import (
    MutationApplicationError,
    apply_mutation,
)
from lib.benchmark_mutation.variant_builder import (
    VariantBuildError,
    build_variant,
)
from lib.common.compliance_audit import AuditClauseSnapshot

def _op(**overrides):
    raw = {
        "operator_id": "OP-T01",
        "rule_ref": "产品责任设计#原序号=22",
        "tier": "insertion",
        "host_tags": ["health"],
        "target_topics": ["policy.account_value"],
        "payload": {"insert_text": "本合同设立保单账户。"},
        "expected_decision": "violated",
        "description": "测试",
    }
    raw.update(overrides)
    return parse_operator(raw)

def _clause(clause_id="C1", text="保险责任内容。", topics=("coverage.responsibility",)):
    return AuditClauseSnapshot(
        clause_id=clause_id, number="3.1", title="保险责任",
        text=text, block_type="clause", topics=topics,
    )
class TestApplyMutation:
    def test_insertion_appends_sentence(self):
        diff = apply_mutation("C1", "保险责任内容。", _op())
        assert diff.mutated_text.endswith("本合同设立保单账户。")

    def test_numeric_replaces_first_occurrence(self):
        op = _op(
            operator_id="OP-T02", tier="numeric",
            host_tags=["long_term"], target_topics=["premium.payment"],
            payload={"from_value": "10年", "to_value": "2年"},
        )
        diff = apply_mutation("C2", "交费期间为10年，共10年期。", op)
        assert diff.mutated_text.startswith("交费期间为2年")

    def test_numeric_missing_value_raises(self):
        op = _op(
            operator_id="OP-T03", tier="numeric",
            host_tags=["long_term"], target_topics=["premium.payment"],
            payload={"from_value": "5年", "to_value": "2年"},
        )
        with pytest.raises(MutationApplicationError):
            apply_mutation("C2", "交费期间为10年。", op)

    def test_deletion_removes_anchor_sentence(self):
        op = _op(
            operator_id="OP-T04", tier="deletion",
            host_tags=["health"], target_topics=["contract.dispute"],
            payload={"anchor_text": "民事诉讼法"},
        )
        text = "争议处理参照民事诉讼法。其他争议协商解决。"
        diff = apply_mutation("C3", text, op)
        assert "民事诉讼法" not in diff.mutated_text
        assert "协商解决" in diff.mutated_text

    def test_rewrite_replaces_anchor(self):
        op = _op(
            operator_id="OP-T05", tier="rewrite",
            host_tags=["health"], target_topics=["coverage.preexisting"],
            payload={"anchor_text": "既往症", "replace_text": "既往症指生效前患过的疾病"},
        )
        diff = apply_mutation("C4", "既往症指本合同生效日之前被保险人已患且已知晓的疾病。", op)
        assert diff.mutated_text.startswith("既往症指生效前患过的疾病")
class TestHostPlanner:
    def test_loads_nine_hosts(self):
        hosts = load_hosts()
        assert len(hosts) == 9
        assert len({h.host_id for h in hosts}) == 9

    def test_match_requires_tag_subset(self):
        host = HostProduct("h", "f.doc", "显示", ("health", "medical"))
        ops = (
            _op(host_tags=["health", "medical"]),
            _op(operator_id="OP-X", host_tags=["participating"]),
        )
        matched = match_operators(host, ops)
        assert [op.operator_id for op in matched] == ["OP-T01"]

    def test_plan_starts_with_single_operator_variant(self):
        host = HostProduct("h", "f.doc", "显示", ("health",))
        ops = tuple(_op(operator_id=f"OP-{i:03d}") for i in range(1, 6))
        plans = plan_variants(host, ops)
        assert plans[0].operator_ids == ("OP-001",)

    def test_plan_groups_by_topic_exclusivity(self):
        host = HostProduct("h", "f.doc", "显示", ("health",))
        ops = (
            _op(target_topics=["coverage.responsibility"]),
            _op(operator_id="OP-A", target_topics=["coverage.responsibility", "coverage.survival"]),
            _op(operator_id="OP-B", target_topics=["claim.material"]),
        )
        plans = plan_variants(host, ops, single_operator_samples=0)
        packed = plans[0]
        assert "OP-T01" in packed.operator_ids
        assert "OP-B" in packed.operator_ids
        assert "OP-A" not in packed.operator_ids

    def test_no_matched_operators_raises(self):
        host = HostProduct("h", "f.doc", "显示", ("accident",))
        with pytest.raises(HostPlanError):
            plan_variants(host, (_op(),), single_operator_samples=0)
class TestVariantBuilder:
    def test_build_variant_mutates_located_clause(self):
        clause = _clause()
        op = _op(target_topics=["coverage.responsibility"])
        record = build_variant_simple(("OP-T01",), (op,), (clause,))
        assert record.diffs[0][0] == "OP-T01"
        mutated = {c.clause_id: c for c in record.clauses}
        assert "保单账户" in mutated["C1"].text

    def test_topic_miss_skips_operator(self):
        op = _op(
            tier="deletion", host_tags=["health"],
            target_topics=["contract.dispute"],
            payload={"anchor_text": "民事诉讼法"},
        )
        result = build_variant_full(("OP-T01",), (op,), (_clause(topics=("claim.payment",)),))
        assert result.skipped and not result.record.diffs

    def test_failed_operator_does_not_kill_variant(self):
        good = _op(operator_id="OP-GOOD", target_topics=["coverage.responsibility"])
        bad = _op(
            operator_id="OP-BAD", tier="deletion", host_tags=["health"],
            target_topics=["contract.dispute"],
            payload={"anchor_text": "民事诉讼法"},
        )
        result = build_variant_full(("OP-BAD", "OP-GOOD"), (bad, good), (_clause(),))
        assert result.record.diffs and result.record.diffs[0][0] == "OP-GOOD"
        assert result.skipped and result.skipped[0][0] == "OP-BAD"

    def test_insertion_falls_back_to_responsibility_block(self):
        record = build_variant_simple(
            ("OP-T01",), (_op(target_topics=["policy.account_value"]),), (_clause(),)
        )
        assert record.diffs and "保单账户" in record.clauses[0].text

    def test_anchor_miss_on_rewrite_skips_operator(self):
        op = _op(
            tier="rewrite", host_tags=["health"],
            target_topics=["coverage.responsibility"],
            payload={"anchor_text": "既往症", "replace_text": "改写"},
        )
        result = build_variant_full(("OP-T01",), (op,), (_clause(),))
        assert result.skipped and "锚文本" in result.skipped[0][1]

    def test_insertion_without_anchor_uses_topic_match(self):
        record = build_variant_simple(
            ("OP-T01",), (_op(target_topics=["coverage.responsibility"]),), (_clause(),)
        )
        assert record.diffs

def build_variant_full(operator_ids, operators, clauses):
    from lib.benchmark_mutation.host_planner import VariantPlan
    plan = VariantPlan(variant_id="VAR-T01", host_id="h", operator_ids=operator_ids)
    return build_variant(plan, tuple(clauses), {op.operator_id: op for op in operators})

def build_variant_simple(operator_ids, operators, clauses):
    return build_variant_full(operator_ids, operators, clauses).record
