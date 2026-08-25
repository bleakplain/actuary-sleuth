"""宿主清单、算子-宿主匹配与打包计划。

宿主清单是 data/hosts.v1.json 声明式数据（文件名 + 预期标签 + 显示名），
research.md §4 的 9 宿主方案。匹配规则：算子 host_tags ⊆ 宿主预期标签。
打包约束：同一变体内算子的 target_topics 互不重叠，防止变异互相干扰。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from lib.benchmark_mutation.operator_schema import MutationOperator

MAX_OPERATORS_PER_VARIANT = 8

class HostPlanError(ValueError):
    """宿主清单非法或算子无法分配。"""

@dataclass(frozen=True)
class HostProduct:
    host_id: str
    file_name: str
    display_name: str
    tags: Tuple[str, ...]

@dataclass(frozen=True)
class VariantPlan:
    variant_id: str
    host_id: str
    operator_ids: Tuple[str, ...]

def load_hosts(path: Path | None = None) -> Tuple[HostProduct, ...]:
    """加载宿主清单并校验标签唯一性。"""
    source = path or Path(__file__).parent / "data" / "hosts.v1.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    entries = raw.get("hosts")
    if not isinstance(entries, list) or not entries:
        raise HostPlanError(f"{source}: hosts 必须是非空数组")
    hosts = tuple(
        HostProduct(
            host_id=str(item["host_id"]),
            file_name=str(item["file_name"]),
            display_name=str(item.get("display_name", item["host_id"])),
            tags=tuple(str(tag) for tag in item["tags"]),
        )
        for item in entries
    )
    ids = [host.host_id for host in hosts]
    if len(set(ids)) != len(ids):
        raise HostPlanError(f"{source}: host_id 重复")
    return hosts
def match_operators(host: HostProduct, operators: Tuple[MutationOperator, ...]) -> Tuple[MutationOperator, ...]:
    """返回宿主可承载的算子（host_tags ⊆ 宿主标签）。"""
    host_tag_set = set(host.tags)
    return tuple(
        op for op in operators
        if set(op.host_tags) <= host_tag_set
    )

def plan_variants(
    host: HostProduct,
    operators: Tuple[MutationOperator, ...],
    *,
    single_operator_samples: int = 1,
) -> Tuple[VariantPlan, ...]:
    """把宿主可承载的算子打包成变体计划。

    第一个变体为单算子样本（供漏检个案复现定位），其余按 target_topics
    互斥分组打包，每组不超过 MAX_OPERATORS_PER_VARIANT。无法定位的算子
    显式抛错而不是静默丢弃。
    """
    matched = match_operators(host, operators)
    if not matched:
        raise HostPlanError(f"{host.host_id}: 没有可承载的算子")
    remaining = list(matched)
    plans: list[VariantPlan] = []
    for _ in range(min(single_operator_samples, len(remaining))):
        op = remaining.pop(0)
        plans.append(VariantPlan(
            variant_id=f"VAR-{host.host_id}-{len(plans) + 1:02d}",
            host_id=host.host_id,
            operator_ids=(op.operator_id,),
        ))
    index = 0
    while remaining:
        group: list[MutationOperator] = []
        used_topics: set[str] = set()
        for op in list(remaining):
            if len(group) >= MAX_OPERATORS_PER_VARIANT:
                break
            if not (set(op.target_topics) & used_topics):
                group.append(op)
                used_topics.update(op.target_topics)
                remaining.remove(op)
        if not group:
            raise HostPlanError(f"{host.host_id}: 算子 {remaining[0].operator_id} 无法打包（主题冲突）")
        index += 1
        plans.append(VariantPlan(
            variant_id=f"VAR-{host.host_id}-{len(plans) + 1:02d}",
            host_id=host.host_id,
            operator_ids=tuple(op.operator_id for op in group),
        ))
    return tuple(plans)
