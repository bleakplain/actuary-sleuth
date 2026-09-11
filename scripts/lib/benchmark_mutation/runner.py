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

    法规单元以"第N条检核规则"标识负面清单条目，而金标 rule_ref 用 KB
    元数据的"原序号=M"。两者映射从 KB 参考文件读取（第N条块内含原序号），
    由 unit 的 source_file 定位文件。
    """
    ordinal_map = _load_ordinal_map()
    mapping = {}
    for record in result.records:
        snapshot = record.package.regulation
        file_stem = _file_stem(snapshot.source_file)
        section_ref = f"{file_stem}#{snapshot.section_path}"
        rule_ref = ordinal_map.get(section_ref)
        if rule_ref is None and snapshot.section_path.startswith("第"):
            # 元数据式 section_path 缺失时退化为 article_number 兜底
            rule_ref = ordinal_map.get(f"{file_stem}#{snapshot.article_number}")
        if rule_ref:
            mapping[record.decision.regulation_unit_id] = rule_ref
    return mapping

_ORDINAL_MAP: dict[str, str] | None = None

def _load_ordinal_map() -> Mapping[str, str]:
    """构建 {文件#第N条检核规则: 文件#原序号=M}，从 KB 参考文件惰性加载。"""
    global _ORDINAL_MAP
    if _ORDINAL_MAP is None:
        import os
        import re
        from pathlib import Path
        refs_dir = Path(os.environ.get("DATA_PATHS_REGULATIONS_DIR", ""))
        if not refs_dir.is_dir():
            refs_dir = Path(__file__).resolve().parents[3] / "kb" / "references"
        mapping: dict[str, str] = {}
        if refs_dir.is_dir():
            negative_dir = refs_dir / "01_负面清单检查"
            for rule_file in (negative_dir.glob("*.md") if negative_dir.is_dir() else []):
                for block in rule_file.read_text(encoding="utf-8").split("## 第")[1:]:
                    section = re.match(r"(\d+条检核规则)", block)
                    ordinal = re.search(r"原序号=(\d+)", block)
                    if section and ordinal:
                        mapping[f"{rule_file.stem}#{section.group(1)}"] = (
                            f"{rule_file.stem}#原序号={ordinal.group(1)}"
                        )
        _ORDINAL_MAP = mapping
    return _ORDINAL_MAP

def _file_stem(source_file: str) -> str:
    name = source_file.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name
