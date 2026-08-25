"""评测执行编排：变体 → 审核管线 → 金标比对。

runner 不直接调用 run_audit_pipeline，而是接受可注入的 pipeline 函数
（签名与 run_audit_pipeline 一致），单测用模型桩替换。规则匹配：决策的
法规来源（source_file 词干 + 原序号命中 section_path/article_number）对齐
金标 rule_ref；匹配不到目标规则的 non_compliant 决策计为非目标误报，
其余判定变化交由宿主基线漂移分析（v2）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Tuple

from lib.benchmark_mutation.golden_label import GoldenLabel
from lib.benchmark_mutation.metrics import RuleOutcome
from lib.common.compliance_audit import RegulationDecisionStatus
from lib.compliance.audit_pipeline import AuditPipelineRequest, AuditPipelineResult

PipelineFn = Callable[[AuditPipelineRequest], AuditPipelineResult]

@dataclass(frozen=True)
class VariantRunResult:
    variant_id: str
    labels: Tuple[GoldenLabel, ...]
    decisions: Tuple[Tuple[str, str], ...]
    false_positive_refs: Tuple[str, ...]

def run_variant_benchmark(
    variant_id: str,
    request: AuditPipelineRequest,
    labels: Tuple[GoldenLabel, ...],
    pipeline: PipelineFn,
    unit_refs: Mapping[str, str] | None = None,
) -> VariantRunResult:
    """对一个变体执行审核管线并按金标归集结果。

    ``unit_refs`` 为空时用 resolve_rule_refs 从管线结果推导；非目标规则
    （不在金标 rule_ref 集合内）的 non_compliant 决策计为非目标误报。
    """
    result = pipeline(request)
    resolved = unit_refs if unit_refs is not None else resolve_rule_refs(result)
    decisions = tuple(
        (decision.regulation_unit_id, decision.status.value)
        for record in result.records
        for decision in (record.decision,)
    )
    target_refs = {label.rule_ref for label in labels}
    false_positives = tuple(
        unit_id for unit_id, status in decisions
        if status == RegulationDecisionStatus.NON_COMPLIANT.value
        and resolved.get(unit_id) not in target_refs
    )
    return VariantRunResult(
        variant_id=variant_id,
        labels=labels,
        decisions=decisions,
        false_positive_refs=false_positives,
    )

def collect_outcomes(
    run_results: Tuple[VariantRunResult, ...],
    unit_refs,
) -> Tuple[RuleOutcome, ...]:
    """把运行结果转为逐金标的 RuleOutcome。

    ``unit_refs`` 提供 regulation_unit_id → 负面清单 rule_ref 的映射
    （由 KB 检索层构建，runner 不重复解析法规文本）。
    """
    outcomes = []
    for run in run_results:
        for label in run.labels:
            statuses = tuple(
                status for unit_id, status in run.decisions
                if unit_refs.get(unit_id) == label.rule_ref
            )
            outcomes.append(RuleOutcome(
                rule_ref=label.rule_ref,
                variant_id=run.variant_id,
                statuses=statuses,
            ))
    return tuple(outcomes)

def resolve_rule_refs(result: AuditPipelineResult) -> Mapping[str, str]:
    """从管线结果构建 regulation_unit_id → rule_ref 映射。

    规则：source_file 词干等于负面清单文件名且 section_path 中含
    "原序号=N" 的单元，映射为 "<词干>#原序号=N"。
    """
    mapping = {}
    for record in result.records:
        snapshot = record.package.regulation
        file_stem = _file_stem(snapshot.source_file)
        for match in re.finditer(r"原序号=\d+", snapshot.section_path):
            mapping[record.decision.regulation_unit_id] = f"{file_stem}#{match.group()}"
            break
    return mapping

def _file_stem(source_file: str) -> str:
    name = source_file.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name
