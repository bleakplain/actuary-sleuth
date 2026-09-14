#!/usr/bin/env python3
"""回放断点：重建 unit→规则映射并重算评测指标（不调用审核 LLM）。"""
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
    VariantRunResult,
    _file_stem,
    _load_ordinal_map,
)
from lib.rag_engine import init_engine  # noqa: E402

def execute(params: dict) -> dict:
    dataset_dir = Path(params["dataset_dir"])
    init_engine()
    from lib.compliance.audit_pipeline import _default_retriever
    from lib.compliance.regulation_retrieval import build_regulation_retrieval_query
    from lib.common.product_tags import ProductTags

    variants = {v["variant_id"]: v for v in json.loads((dataset_dir / "variants.json").read_text(encoding="utf-8"))}
    confirmations = load_confirmations(dataset_dir / "confirmation.xlsx")
    operators_by_id = {op.operator_id: op for op in load_operators()}
    ordinal_map = _load_ordinal_map()
    unit_refs: dict[str, str] = {}
    run_results = []
    # 每个宿主只需检索一次（同宿主变体共享法规候选集合）
    host_queries: dict[str, dict[str, str]] = {}
    for line in (dataset_dir / "run-checkpoint.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        host_id = entry["variant_id"].rsplit("-", 1)[0]
        raw = variants.get(entry["variant_id"])
        if raw is None:
            continue
        labels = tuple(apply_confirmations(
            build_golden_labels(_restore_record(raw), operators_by_id), confirmations,
        ))
        if host_id not in host_queries:
            clauses_text = "\n".join(c["text"] for c in raw["clauses"])
            query = build_regulation_retrieval_query(raw["host_id"], clauses_text, ProductTags())
            outcome = _default_retriever(query, None, ProductTags(), (), 12)
            host_queries[host_id] = {
                unit.regulation_unit_id: ordinal_map.get(
                    f"{_file_stem(unit.source_file)}#{unit.section_path}", ""
                )
                for unit in outcome.regulations
            }
            unit_refs.update(host_queries[host_id])
        run_results.append(VariantRunResult(
            variant_id=entry["variant_id"],
            labels=labels,
            decisions=tuple(tuple(d) for d in entry["decisions"]),
            false_positive_refs=tuple(entry.get("false_positive_refs", ())),
        ))
    resolved = {u: r for u, r in unit_refs.items() if r}
    print(f"unit→规则映射: {len(resolved)} 条（覆盖 {len(host_queries)} 个宿主的候选集）", flush=True)
    from lib.benchmark_mutation.runner import collect_outcomes
    outcomes = collect_outcomes(tuple(run_results), resolved)
    from collections import Counter
    status_stat = Counter(s for o in outcomes for s in o.statuses)
    print("目标规则判定分布:", dict(status_stat), flush=True)
    report = evaluate_labels(
        outcomes,
        false_positive_refs=tuple(
            ref for run in run_results for ref in run.false_positive_refs
        ),
    )
    header = (
        f"- 生成时间: {datetime.datetime.now().isoformat()}\n"
        f"- 已确认金标: {sum(len(r.labels) for r in run_results)}"
    )
    (dataset_dir / "benchmark-report.md").write_text(format_report(report, header), encoding="utf-8")
    return {
        "success": True,
        "label_count": report.label_count,
        "detection_rate": report.detection_rate,
        "loose_miss_rate": report.loose_miss_rate,
        "strict_miss_rate": report.strict_miss_rate,
        "report": str(dataset_dir / "benchmark-report.md"),
    }

def _restore_record(raw: dict):
    from lib.common.compliance_audit import AuditClauseSnapshot
    from lib.benchmark_mutation.variant_builder import VariantRecord
    clauses = tuple(AuditClauseSnapshot(
        clause_id=c["clause_id"], number=c["number"], title=c["title"],
        text=c["text"], block_type=c["block_type"], topics=tuple(c["topics"]),
    ) for c in raw["clauses"])
    diffs = tuple((d[0], d[1], d[2], d[3]) for d in raw["diffs"])
    return VariantRecord(
        variant_id=raw["variant_id"], host_id=raw["host_id"],
        clauses=clauses, diffs=diffs,
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="回放断点重算指标（不调用审核 LLM）")
    parser.add_argument("--dataset-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(vars(args)), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
