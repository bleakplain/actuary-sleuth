"""金标草案生成与评测集冻结。

金标 = 变体 × 目标规则的预期 violated 判定 + 证据条款引用。目标规则的
金标来自算子声明；非目标规则不生成硬金标（变异可能合法引发连锁判定
变化，作为"漂移"单列，见 metrics.py）。
冻结采用 KB 构建清单同款 SHA-256 指纹做法：算子文件、宿主清单、变体
产物三者哈希写入数据文件，保证评测可复现、论文可引用。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from lib.benchmark_mutation.host_planner import VariantPlan
from lib.benchmark_mutation.operator_schema import MutationOperator
from lib.benchmark_mutation.variant_builder import VariantRecord

@dataclass(frozen=True)
class GoldenLabel:
    """单条金标：一个变体上目标规则的预期判定。"""
    variant_id: str
    rule_ref: str
    expected: str
    evidence_clause_id: str
    operator_id: str
    confirmed_by: str = ""
    confirmed_at: str = ""
    @property
    def is_confirmed(self) -> bool:
        return bool(self.confirmed_by.strip())

def build_golden_labels(
    record: VariantRecord,
    operators_by_id,
) -> Tuple[GoldenLabel, ...]:
    """从变体记录生成金标草案（未确认状态）。"""
    labels = []
    for operator_id, clause_id, _original, _mutated in record.diffs:
        operator: MutationOperator = operators_by_id[operator_id]
        labels.append(GoldenLabel(
            variant_id=record.variant_id,
            rule_ref=operator.rule_ref,
            expected=operator.expected_decision,
            evidence_clause_id=clause_id,
            operator_id=operator_id,
        ))
    return tuple(labels)

def write_confirmation_sheet(
    labels: Tuple[GoldenLabel, ...],
    record_by_variant,
    operator_by_id,
    path: Path,
) -> None:
    """生成确认清单 CSV：规则、原文→变异后、确认人/时间/结论字段。"""
    import csv
    columns = [
        "variant_id", "operator_id", "rule_ref", "description",
        "original_text", "mutated_text", "confirmed", "confirmed_by", "confirmed_at",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for label in labels:
            record = record_by_variant[label.variant_id]
            diff = record.diff_for(label.operator_id)
            writer.writerow({
                "variant_id": label.variant_id,
                "operator_id": label.operator_id,
                "rule_ref": label.rule_ref,
                "description": operator_by_id[label.operator_id].description,
                "original_text": diff[2],
                "mutated_text": diff[3],
                "confirmed": "",
                "confirmed_by": "",
                "confirmed_at": "",
            })

def load_confirmations(path: Path) -> dict[tuple[str, str], tuple[str, str, str]]:
    """读回确认结果：{(variant_id, operator_id): (confirmed, by, at)}。"""
    import csv
    results = {}
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (row["variant_id"], row["operator_id"])
            results[key] = (row.get("confirmed", ""), row.get("confirmed_by", ""), row.get("confirmed_at", ""))
    return results

def apply_confirmations(
    labels: Tuple[GoldenLabel, ...],
    confirmations,
) -> Tuple[GoldenLabel, ...]:
    """把确认结果写回金标；未确认/否决的条目剔除。

    confirmed 字段填 yes 视为金标生效；其他值（空、no）一律剔除——
    否决说明变异不构成真实违规，留在评测集会污染金标。
    """
    confirmed = []
    for label in labels:
        entry = confirmations.get((label.variant_id, label.operator_id))
        if entry and entry[0].strip().lower() == "yes":
            confirmed.append(GoldenLabel(
                variant_id=label.variant_id,
                rule_ref=label.rule_ref,
                expected=label.expected,
                evidence_clause_id=label.evidence_clause_id,
                operator_id=label.operator_id,
                confirmed_by=entry[1].strip(),
                confirmed_at=entry[2].strip(),
            ))
    return tuple(confirmed)

def freeze_dataset(
    labels: Tuple[GoldenLabel, ...],
    operators_path: Path,
    hosts_path: Path,
    output_path: Path,
    *,
    version: str = "v1",
) -> str:
    """冻结评测集：算子/宿主文件与金标的 SHA-256 清单写入数据文件。"""
    identity = {
        "schema_version": "1.0.0",
        "version": version,
        "operators_sha256": _sha256(operators_path),
        "hosts_sha256": _sha256(hosts_path),
        "labels_sha256": _sha256_text(json.dumps(
            [label.__dict__ for label in labels], ensure_ascii=False, sort_keys=True
        )),
        "label_count": len(labels),
    }
    output_path.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return identity["labels_sha256"]

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
