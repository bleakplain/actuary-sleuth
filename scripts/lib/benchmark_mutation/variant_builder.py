"""变体构建：定位目标条款块并应用变异。

v1 只实现条款块级轨（CLAUSE_BLOCK）：输入宿主解析出的 AuditClauseSnapshot
序列，输出变体条款快照 + 变异 diff。定位失败显式抛错——这可能暴露主题
路由覆盖不足，错误清单用于反哺主题注册表扩充（036 OPT-003）。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
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

@dataclass(frozen=True)
class _VariantBuildResult:
    """构建产物：成功的变体记录 + 被跳过的算子及原因。"""
    record: VariantRecord
    skipped: Tuple[Tuple[str, str], ...] = ()
def build_variant(
    plan: VariantPlan,
    clauses: Tuple[AuditClauseSnapshot, ...],
    operators_by_id,
):
    """按计划对宿主条款应用算子，返回变体记录。

    定位/执行失败的算子跳过并记入 skipped，不废弃整个变体——变体是
    多算子打包的，单个算子在特定宿主上不适配是常态（宿主缺对应条款），
    连坐丢弃会让产出率减半。其余算子照常应用。
    """
    mutated = {clause.clause_id: clause for clause in clauses}
    diffs: list[tuple[str, str, str, str]] = []
    skipped: list[tuple[str, str]] = []
    for operator_id in plan.operator_ids:
        operator = operators_by_id[operator_id]
        try:
            clause = _locate_clause(operator, mutated)
            diff = apply_mutation(clause.clause_id, clause.text, operator)
        except (VariantBuildError, MutationApplicationError) as exc:
            skipped.append((operator_id, str(exc)))
            continue
        mutated[clause.clause_id] = replace(clause, text=diff.mutated_text)
        diffs.append((
            diff.operator_id,
            diff.clause_id,
            diff.original_text,
            diff.mutated_text,
        ))
    return _VariantBuildResult(
        record=VariantRecord(
            variant_id=plan.variant_id,
            host_id=plan.host_id,
            clauses=tuple(mutated.values()),
            diffs=tuple(diffs),
        ),
        skipped=tuple(skipped),
    )

def _locate_clause(operator: MutationOperator, mutated) -> AuditClauseSnapshot:
    """按 target_topics 定位块，主题未命中时用注册表关键词兜底。

    兜底是必要的：当前真实产品约七成条款块无主题标签（036 OPT-003），
    若只认主题，多数算子无法定位。关键词来自 doc_parser 主题注册表
    （Library-First），语义与主题一致。找到候选后按 tier 验证锚文本；
    插入型不依赖现有文本。定位彻底失败才显式报错。
    """
    anchor = _anchor_of(operator)
    candidates = [
        clause for clause in mutated.values()
        if set(operator.target_topics) & set(clause.topics) and not clause.container_only
    ]
    if not candidates:
        candidates = _keyword_fallback(operator, mutated)
    if not candidates and operator.tier is MutationTier.INSERTION:
        candidates = _responsibility_fallback(mutated)
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

def _keyword_fallback(operator: MutationOperator, mutated):
    """主题未命中时，按主题关键词在条款标题/正文全文搜索候选块。"""
    keywords = _topic_keywords()
    terms = [kw for topic in operator.target_topics for kw in keywords.get(topic, ())]
    if not terms:
        return []
    return [
        clause for clause in mutated.values()
        if not clause.container_only
        and any(term in clause.text or term in clause.title for term in terms)
    ]

def _responsibility_fallback(mutated):
    """插入型算子的最终兜底：落到"保险责任"段，退而取最长文本块。

    插入不依赖宿主现有文本（违规概念是外加的），宿主没有对应主题
    块时插进保险责任段在语义上仍然成立——审核系统应当扫到它。
    """
    blocks = [c for c in mutated.values() if not c.container_only and c.text.strip()]
    titled = [c for c in blocks if "保险责任" in c.title or "责任" in c.title]
    if titled:
        return titled
    return [max(blocks, key=lambda c: len(c.text))] if blocks else []

def _topic_keywords():
    """惰性加载主题关键词：doc_parser 注册表 + 本模块补充表。

    注册表只覆盖 27/59 主题，补充表填变异算子需要但注册表缺失的
    主题（如 coverage.death、policy.account_value），两层合并使用。
    """
    global _TOPIC_KEYWORDS
    if _TOPIC_KEYWORDS is None:
        import json
        from lib.doc_parser.pd.clause_topics import (
            load_clause_topic_keywords,
            load_clause_topic_registry,
        )
        keywords = dict(load_clause_topic_keywords(load_clause_topic_registry()))
        supplement = json.loads(
            (Path(__file__).parent / "data" / "mutation_topic_keywords.json")
            .read_text(encoding="utf-8")
        )["keywords"]
        for topic, terms in supplement.items():
            keywords.setdefault(topic, tuple(terms))
        _TOPIC_KEYWORDS = keywords
    return _TOPIC_KEYWORDS

_TOPIC_KEYWORDS = None

def _anchor_of(operator: MutationOperator) -> str:
    if operator.tier is MutationTier.NUMERIC:
        candidates = operator.payload.get("from_values") or [operator.payload.get("from_value")]
        return str(candidates[0])
    if operator.tier in (MutationTier.DELETION, MutationTier.REWRITE):
        return str(operator.payload.get("anchor_text", ""))
    return ""
