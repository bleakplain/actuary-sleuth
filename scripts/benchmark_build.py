#!/usr/bin/env python3
"""构建 038 变异评测集：宿主解析 → 变体构建 → 确认清单生成。

用法：
    python3 scripts/benchmark_build.py --products-dir <产品目录> --output-dir <输出目录>
构建产物（JSON）：变体记录（含变异后条款与 diff）、金标草案、确认清单
CSV、冻结指纹。定位/执行失败的算子汇总在 build-errors.json，不中断整体
构建——错误清单用于反哺主题路由覆盖扩充。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.benchmark_mutation.golden_label import (  # noqa: E402
    build_golden_labels,
    freeze_dataset,
    write_confirmation_sheet,
)
from lib.benchmark_mutation.host_planner import (  # noqa: E402
    load_hosts,
    plan_variants,
)
from lib.benchmark_mutation.operator_schema import load_operators  # noqa: E402
from lib.benchmark_mutation.variant_builder import (  # noqa: E402
    VariantBuildError,
    build_variant,
)
from lib.common.compliance_audit import AuditClauseSnapshot  # noqa: E402

def execute(params: dict) -> dict:
    products_dir = Path(params["products_dir"])
    output_dir = Path(params["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    operators = load_operators()
    operators_by_id = {op.operator_id: op for op in operators}
    hosts_path = Path(params["hosts"]) if params.get("hosts") else None
    hosts = load_hosts(hosts_path)
    all_records, all_labels, build_errors = [], [], []
    for host in hosts:
        clauses = _load_host_clauses(products_dir / host.file_name)
        if clauses is None:
            build_errors.append({"host_id": host.host_id, "error": "解析失败或文件缺失"})
            continue
        for plan in plan_variants(host, operators):
            try:
                record = build_variant(plan, clauses, operators_by_id)
            except VariantBuildError as exc:
                build_errors.append({"variant_id": plan.variant_id, "error": str(exc)})
                continue
            all_records.append(record)
            all_labels.extend(build_golden_labels(record, operators_by_id))
    record_by_variant = {record.variant_id: record for record in all_records}
    write_confirmation_sheet(
        tuple(all_labels), record_by_variant, operators_by_id,
        output_dir / "confirmation.csv",
    )
    (output_dir / "variants.json").write_text(json.dumps(
        [dataclasses.asdict(record) for record in all_records],
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    (output_dir / "build-errors.json").write_text(json.dumps(
        build_errors, ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    fingerprint = freeze_dataset(
        tuple(all_labels),
        Path("lib/benchmark_mutation/data/operators.v1.json"),
        Path("lib/benchmark_mutation/data/hosts.v1.json"),
        output_dir / "benchmark-identity.json",
    )
    return {
        "success": True,
        "variant_count": len(all_records),
        "label_count": len(all_labels),
        "build_error_count": len(build_errors),
        "labels_sha256": fingerprint,
        "confirmation_sheet": str(output_dir / "confirmation.csv"),
    }

def _load_host_clauses(path: Path):
    if not path.is_file():
        return None
    from lib.doc_parser.pd.parser import parse_product_document
    document = parse_product_document(str(path))
    return tuple(
        AuditClauseSnapshot(
            clause_id=block.clause_id,
            number=block.number,
            title=block.title,
            text=block.content,
            block_type=block.block_type.value,
            topics=block.topics,
        )
        for block in document.audit_blocks
        if not block.container_only
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="构建 038 变异注入评测集")
    parser.add_argument("--products-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--hosts", help="宿主清单 JSON（默认 9 宿主全集；环境受限时可指定子集）")
    args = parser.parse_args()
    print(json.dumps(execute(vars(args)), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
