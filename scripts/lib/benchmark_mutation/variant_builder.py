"""变体构建：定位目标条款块并应用变异。

v1 只实现条款块级轨（CLAUSE_BLOCK）：输入宿主解析出的 AuditClauseSnapshot
序列，输出变体条款快照 + 变异 diff。定位失败显式抛错——这可能暴露主题
路由覆盖不足，错误清单用于反哺主题注册表扩充（036 OPT-003）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple

from lib.benchmark_mutation.host_planner import VariantPlan
from lib.benchmark_mutation.operator_schema import MutationOperator, MutationTier
from lib.benchmark_mutation.operators import MutationApplicationError, apply_mutation
from lib.common.compliance_audit import AuditClauseSnapshot

class VariantBuildError(ValueError):
    """算子在宿主条款中定位失败。"""

@dataclass(frozen=True)
class VariantRecord:
    """一个变体的完整产物：变异后条款包 + 逐算子 diff。"""
    variant_id: str
    host_id: str
    clauses: Tuple[AuditClauseSnapshot, ...]
    diffs: Tuple[Tuple[str, str, str, str], ...]
    def diff_for(self, operator_id: str) -> Tuple[str, str, str, str]:
        for diff in self.diffs:
            if diff[0] == operator_id:
                return diff
        raise KeyError(operator_id)
def build_variant(
    plan: VariantPlan,
    clauses: Tuple[AuditClauseSnapshot, ...],
    operators_by_id,
) -> VariantRecord:
    """按计划对宿主条款应用算子，返回变体记录。

    ``operators_by_id`` 是 {operator_id: MutationOperator} 映射。同一变体
    内每个算子独立定位目标块；两个算子命中同一块时按顺序叠加，diff 记录
    的是相对上一算子输出后的增量改写。
    """
    mutated = {clause.clause_id: clause for clause in clauses}
    diffs: list[tuple[str, str, str, str]] = []
    for operator_id in plan.operator_ids:
        operator = operators_by_id[operator_id]
        clause = _locate_clause(operator, mutated)
        try:
            diff = apply_mutation(clause.clause_id, clause.text, operator)
        except MutationApplicationError as exc:
            raise VariantBuildError(str(exc)) from exc
        mutated[clause.clause_id] = replace(clause, text=diff.mutated_text)
        diffs.append((
            diff.operator_id,
            diff.clause_id,
            diff.original_text,
            diff.mutated_text,
        ))
    return VariantRecord(
        variant_id=plan.variant_id,
        host_id=plan.host_id,
        clauses=tuple(mutated.values()),
        diffs=tuple(diffs),
    )

def _locate_clause(operator: MutationOperator, mutated) -> AuditClauseSnapshot:
    """按 target_topics 定位块，再按 tier 验证锚文本/数值可命中。

    优先选择主题精确匹配且锚文本存在的块；找不到锚文本时对插入型算子
    放宽为主题匹配即可（插入不依赖现有文本）。
    """
    anchor = _anchor_of(operator)
    candidates = [
        clause for clause in mutated.values()
        if set(operator.target_topics) & set(clause.topics) and not clause.container_only
    ]
    if not candidates:
        raise VariantBuildError(
            f"{operator.operator_id}: 主题 {list(operator.target_topics)} "
            f"未命中任何条款块（宿主主题路由覆盖不足）"
        )
    if anchor:
        for clause in candidates:
            if anchor in clause.text:
                return clause
        if operator.tier is not MutationTier.INSERTION:
            raise VariantBuildError(
                f"{operator.operator_id}: 锚文本 {anchor!r} 在候选块中未出现"
            )
    return candidates[0]

def _anchor_of(operator: MutationOperator) -> str:
    if operator.tier is MutationTier.NUMERIC:
        return str(operator.payload.get("from_value", ""))
    if operator.tier in (MutationTier.DELETION, MutationTier.REWRITE):
        return str(operator.payload.get("anchor_text", ""))
    return ""
