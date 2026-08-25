"""漏检率、误报率与漂移计算（纯函数）。

判定语义映射：引擎输出 non_compliant 视为检出违规；compliant 视为漏检
（宽松口径），indeterminate 家族（insufficient_information / manual_review /
incomplete / error）在严格口径下也计漏检——双口径差值即三值保守判定的
人工审核代价，是 038 评测的核心输出。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

from lib.common.compliance_audit import RegulationDecisionStatus

_DETECTABLE = {RegulationDecisionStatus.NON_COMPLIANT}
_LOOSE_MISS = {RegulationDecisionStatus.COMPLIANT}
_STRICT_MISS = {
    RegulationDecisionStatus.INSUFFICIENT_INFORMATION,
    RegulationDecisionStatus.MANUAL_REVIEW,
}

@dataclass(frozen=True)
class RuleOutcome:
    """一条目标规则在一个变体上的引擎判定聚合。"""
    rule_ref: str
    variant_id: str
    statuses: Tuple[str, ...]
    @property
    def detected(self) -> bool:
        return any(status in _DETECTABLE for status in self.statuses)
    @property
    def loose_missed(self) -> bool:
        return bool(self.statuses) and not self.detected and any(
            status in _LOOSE_MISS for status in self.statuses
        )
    @property
    def strict_missed(self) -> bool:
        return bool(self.statuses) and not self.detected and any(
            status in _LOOSE_MISS or status in _STRICT_MISS for status in self.statuses
        )
    @property
    def undetermined(self) -> bool:
        return bool(self.statuses) and not self.detected and any(
            status in _STRICT_MISS for status in self.statuses
        )

@dataclass(frozen=True)
class BenchmarkReport:
    """整个评测集的指标汇总。"""
    label_count: int
    detected_count: int
    loose_miss_count: int
    strict_miss_count: int
    undetermined_count: int
    false_positive_count: int
    false_positive_refs: Tuple[str, ...]
    per_rule: Tuple[Tuple[str, int, int, int], ...]
    @property
    def detection_rate(self) -> float:
        return self.detected_count / self.label_count if self.label_count else 0.0
    @property
    def loose_miss_rate(self) -> float:
        return self.loose_miss_count / self.label_count if self.label_count else 0.0
    @property
    def strict_miss_rate(self) -> float:
        return self.strict_miss_count / self.label_count if self.label_count else 0.0

def evaluate_labels(
    outcomes: Tuple[RuleOutcome, ...],
    false_positive_refs: Tuple[str, ...] = (),
) -> BenchmarkReport:
    """汇总全部金标的结果。outcomes 与金标一一对应（由 runner 保证）。"""
    detected = sum(1 for o in outcomes if o.detected)
    loose = sum(1 for o in outcomes if o.loose_missed)
    strict = sum(1 for o in outcomes if o.strict_missed)
    undetermined = sum(1 for o in outcomes if o.undetermined)
    per_rule: dict[str, list[int]] = {}
    for outcome in outcomes:
        counts = per_rule.setdefault(outcome.rule_ref, [0, 0, 0])
        counts[0] += 1 if outcome.detected else 0
        counts[1] += 1 if outcome.loose_missed else 0
        counts[2] += 1 if outcome.strict_missed else 0
    return BenchmarkReport(
        label_count=len(outcomes),
        detected_count=detected,
        loose_miss_count=loose,
        strict_miss_count=strict,
        undetermined_count=undetermined,
        false_positive_count=len(false_positive_refs),
        false_positive_refs=tuple(sorted(false_positive_refs)),
        per_rule=tuple(
            (rule, counts[0], counts[1], counts[2])
            for rule, counts in sorted(per_rule.items())
        ),
    )

def format_report(report: BenchmarkReport, header: str = "") -> str:
    """渲染 markdown 报告（报告头由 runner 补充指纹与模型参数）。"""
    lines = [
        "# 038 变异注入违规评测报告",
        header,
        "",
        f"- 金标条目: {report.label_count}",
        f"- 检出（non_compliant）: {report.detected_count}（{report.detection_rate:.1%}）",
        f"- 宽松漏检（compliant）: {report.loose_miss_count}（{report.loose_miss_rate:.1%}）",
        f"- 严格漏检（含未决）: {report.strict_miss_count}（{report.strict_miss_rate:.1%}）",
        f"- 未决（insufficient/manual）: {report.undetermined_count}",
        f"- 非目标规则误报: {report.false_positive_count}",
        "",
        "| 规则 | 检出 | 宽松漏检 | 严格漏检 |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {rule} | {detected} | {loose} | {strict} |"
        for rule, detected, loose, strict in report.per_rule
    )
    if report.false_positive_refs:
        lines.extend(["", "## 非目标规则误报明细", ""])
        lines.extend(f"- {ref}" for ref in report.false_positive_refs)
    return "\n".join(lines)
