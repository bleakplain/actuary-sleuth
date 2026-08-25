#!/usr/bin/env python3
"""执行 038 评测：已确认变体 → 审核管线 → 漏检率报告。

用法：
    python3 scripts/benchmark_run.py --dataset-dir <构建输出目录> [--report-dir <报告目录>]
前提：confirmation.csv 已人工确认（confirmed=yes）。调用真实云端管线，
需要 .env 配置；报告头记录时间与金标指纹保证可复现。
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.benchmark_mutation.golden_label import (  # noqa: E402
    apply_confirmations,
    build_golden_labels,
    load_confirmations,
)
from lib.benchmark_mutation.metrics import evaluate_labels, format_report  # noqa: E402
from lib.benchmark_mutation.operator_schema import load_operators  # noqa: E402
from lib.benchmark_mutation.runner import (  # noqa: E402
    collect_outcomes,
    resolve_rule_refs,
    run_variant_benchmark,
)
from lib.benchmark_mutation.variant_builder import VariantRecord  # noqa: E402
from lib.common.compliance_audit import AuditClauseSnapshot  # noqa: E402
from lib.compliance.audit_pipeline import AuditPipelineRequest, run_audit_pipeline  # noqa: E402

def execute(params: dict) -> dict:
    dataset_dir = Path(params["dataset_dir"])
    report_dir = Path(params.get("report_dir") or dataset_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    variants = json.loads((dataset_dir / "variants.json").read_text(encoding="utf-8"))
    confirmations = load_confirmations(dataset_dir / "confirmation.csv")
    operators_by_id = {op.operator_id: op for op in load_operators()}
    labels_by_variant: dict[str, list] = {}
    records = []
    for raw in variants:
        record = _restore_record(raw)
        records.append(record)
        labels_by_variant[record.variant_id] = list(
            build_golden_labels(record, operators_by_id)
        )
    confirmed = apply_confirmations(
        tuple(label for labels in labels_by_variant.values() for label in labels),
        confirmations,
    )
    if not confirmed:
        return {"success": False, "error": "没有已确认的金标条目（先完成 confirmation.csv）"}
    confirmed_by_variant: dict[str, list] = {}
    for label in confirmed:
        confirmed_by_variant.setdefault(label.variant_id, []).append(label)
    unit_refs: dict[str, str] = {}
    run_results = []
    for record in records:
        labels = tuple(confirmed_by_variant.get(record.variant_id, ()))
        if not labels:
            continue
        request = _build_request(record)
        result = run_audit_pipeline(request)
        unit_refs.update(resolve_rule_refs(result))
        run_results.append(run_variant_benchmark(
            record.variant_id, request, labels, lambda req: result, unit_refs,
        ))
    outcomes = collect_outcomes(tuple(run_results), unit_refs)
    report = evaluate_labels(
        outcomes,
        false_positive_refs=tuple(
            ref for run in run_results for ref in run.false_positive_refs
        ),
    )
    header = (
        f"- 生成时间: {datetime.datetime.now().isoformat()}\n"
        f"- 已确认金标: {len(confirmed)}"
    )
    (report_dir / "benchmark-report.md").write_text(
        format_report(report, header), encoding="utf-8"
    )
    return {
        "success": True,
        "label_count": report.label_count,
        "detection_rate": report.detection_rate,
        "loose_miss_rate": report.loose_miss_rate,
        "strict_miss_rate": report.strict_miss_rate,
        "report": str(report_dir / "benchmark-report.md"),
    }

def _restore_record(raw: dict) -> VariantRecord:
    clauses = tuple(AuditClauseSnapshot(
        clause_id=c["clause_id"], number=c["number"], title=c["title"],
        text=c["text"], block_type=c["block_type"], topics=tuple(c["topics"]),
    ) for c in raw["clauses"])
    diffs = tuple((d[0], d[1], d[2], d[3]) for d in raw["diffs"])
    return VariantRecord(
        variant_id=raw["variant_id"], host_id=raw["host_id"],
        clauses=clauses, diffs=diffs,
    )

def _build_request(record: VariantRecord) -> AuditPipelineRequest:
    from lib.common.product_tags import ProductTags
    return AuditPipelineRequest(
        product_name=record.host_id,
        document_content="\n".join(c.text for c in record.clauses),
        product_tags=ProductTags(),
        clauses=record.clauses,
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="执行 038 变异注入评测")
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--report-dir")
    args = parser.parse_args()
    print(json.dumps(execute(vars(args)), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
