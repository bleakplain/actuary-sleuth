#!/usr/bin/env python3
"""离线测量真实产品的法规触发准备度与动态条款证据体量。"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from lib.common.compliance_audit import (
    RegulationAuditDecision,
    RegulationDecisionStatus,
    TriggerStatus,
)
from lib.compliance.audit_pipeline import AuditPipelineRequest, run_audit_pipeline
from lib.compliance.package_measurement import (
    build_audit_clause_snapshots,
    list_applicable_regulation_units,
)
from lib.compliance.regulation_retrieval import RegulationRetrievalOutcome
from lib.config import get_kb_version_dir
from lib.doc_parser import parse_product_document
from lib.rag_engine.kb_rebuild import load_catalog_rows


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    return ordered[max(0, math.ceil(len(ordered) * percentile) - 1)]


def _offline_auditor(packages, concurrency, deadline, callback):
    return tuple(
        RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.COMPLIANT,
            reasoning="离线体量测量占位，不代表精算或模型审核结论。",
            suggestion="",
            regulation_evidence=(),
            product_evidence=(),
        )
        for package in packages
    )


def measure(product: Path, kb_version: str) -> dict[str, object]:
    kb_root = Path(get_kb_version_dir())
    document = parse_product_document(str(product))
    clauses = build_audit_clause_snapshots(document)
    catalog = load_catalog_rows(kb_root / kb_version / "lancedb")
    units = list_applicable_regulation_units(
        catalog,
        document.product_tags,
        kb_version,
    )
    request = AuditPipelineRequest(
        product_name=document.product_name or product.name,
        document_content=document.canonical_text,
        product_tags=document.product_tags,
        clauses=clauses,
        document_fingerprint=document.document_fingerprint,
        audit_input_fingerprint=document.audit_input_fingerprint,
        product_name_source=document.product_name_source,
        parse_warnings=tuple(document.warnings),
        coverage_attested=document.coverage_attested,
    )
    outcome = RegulationRetrievalOutcome(
        regulations=(),
        regulation_units=units,
        candidate_count=len(units),
    )
    result = run_audit_pipeline(
        request,
        retriever=lambda *args: outcome,
        package_auditor=_offline_auditor,
    )
    clause_chars = {
        clause.clause_id: len(clause.title) + len(clause.text)
        for clause in clauses
    }
    outline_chars = sum(
        len(clause.number)
        + len(clause.title)
        + len(clause.hierarchy_path)
        for clause in clauses
    )
    selected_counts = []
    dynamic_chars = 0
    zero_selection_units = []
    for record in result.records:
        selection = record.evidence_selection
        selected_ids = selection.selected_clause_ids if selection is not None else ()
        selected_counts.append(len(selected_ids))
        if not selected_ids:
            zero_selection_units.append({
                "regulation_unit_id": (
                    record.package.regulation.regulation_unit_id
                ),
                "law_name": record.package.regulation.law_name,
                "article_number": record.package.regulation.article_number,
                "topics": list(record.package.regulation.topics),
            })
        dynamic_chars += outline_chars + sum(
            clause_chars[clause_id]
            for clause_id in selected_ids
            if clause_id in clause_chars
        )
    full_chars = sum(clause_chars.values()) * len(result.records)
    configured_units = sum(bool(unit.trigger_specs) for unit in units)
    trigger_status_counts = {
        status.value: sum(
            record.evaluation.status is status
            for record in result.trigger_records
        )
        for status in TriggerStatus
    }
    limitations = [
        "离线 auditor 只生成占位状态，不代表法规判断准确率。",
        "动态证据仍处于影子模式，正式 LLM 输入保持完整产品条款。",
        "法规触发规格须由精算在 Excel 验收后才能用于生产排除。",
    ]
    if configured_units == 0:
        limitations.append(
            "当前知识库没有触发规格，因此未调用产品事实补充模型，"
            "也不能测量第二轮法规过滤收益。"
        )
    return {
        "schema_version": "1.0.0",
        "measurement_kind": "offline_trigger_and_dynamic_evidence_shadow",
        "formal_audit_result": False,
        "input": {
            "product": str(product),
            "product_name": request.product_name,
            "kb_version": kb_version,
            "coverage_attested": request.coverage_attested,
            "parsed_clause_count": len(clauses),
            "candidate_regulation_unit_count": len(units),
        },
        "trigger_readiness": {
            "configured_regulation_unit_count": configured_units,
            "unconfigured_regulation_unit_count": len(units) - configured_units,
            "status_counts": trigger_status_counts,
            "product_fact_count": len(result.product_facts),
            "note": (
                "未配置触发规格的法规按 triggered 保守保留；"
                "configured=0 时只能验证链路，不能验证额外法规过滤收益。"
            ),
        },
        "dynamic_evidence": {
            "formal_submission_mode": "full_document",
            "shadow_record_count": len(result.records),
            "selected_clauses_per_unit_mean": (
                round(sum(selected_counts) / len(selected_counts), 2)
                if selected_counts
                else 0
            ),
            "selected_clauses_per_unit_p95": _percentile(selected_counts, 0.95),
            "selected_clauses_per_unit_max": max(selected_counts, default=0),
            "zero_selection_unit_count": sum(count == 0 for count in selected_counts),
            "zero_selection_units": zero_selection_units,
            "full_product_context_chars": full_chars,
            "dynamic_outline_and_body_chars": dynamic_chars,
            "context_reduction_percent": (
                round((1 - dynamic_chars / full_chars) * 100, 2)
                if full_chars
                else 0
            ),
            "shadow_warning_count": len(result.shadow_warnings),
        },
        "limitations": limitations,
    }


def render_markdown(report: dict[str, object]) -> str:
    inputs = report["input"]
    trigger = report["trigger_readiness"]
    evidence = report["dynamic_evidence"]
    assert isinstance(inputs, dict)
    assert isinstance(trigger, dict)
    assert isinstance(evidence, dict)
    lines = [
        "# 法规触发与动态条款证据离线测量",
        "",
        f"- 产品：{inputs['product_name']}",
        f"- KB：{inputs['kb_version']}",
        f"- 解析完整性证明：{inputs['coverage_attested']}",
        f"- 产品条款块：{inputs['parsed_clause_count']}",
        f"- 候选法规单元：{inputs['candidate_regulation_unit_count']}",
        f"- 已配置触发规格：{trigger['configured_regulation_unit_count']}",
        f"- 未配置触发规格：{trigger['unconfigured_regulation_unit_count']}",
        f"- 触发状态：{json.dumps(trigger['status_counts'], ensure_ascii=False)}",
        f"- 每法规影子证据块均值 / P95 / 最大："
        f"{evidence['selected_clauses_per_unit_mean']} / "
        f"{evidence['selected_clauses_per_unit_p95']} / "
        f"{evidence['selected_clauses_per_unit_max']}",
        f"- 影子上下文字符减少：{evidence['context_reduction_percent']}%",
    ]
    zero_selection_units = evidence.get("zero_selection_units")
    if isinstance(zero_selection_units, list) and zero_selection_units:
        labels = []
        for item in zero_selection_units:
            if not isinstance(item, dict):
                continue
            law_name = str(item.get("law_name", "")).strip()
            article_number = str(item.get("article_number", "")).strip()
            labels.append(f"{law_name}{article_number}")
        lines.append(
            f"- 无第一轮证据的法规单元：{len(zero_selection_units)}"
            + (f"（{'、'.join(labels)}）" if labels else "")
        )
    lines.extend((
        "",
        "> 本报告不包含 LLM 合规结论；正式提交仍为完整条款。",
    ))
    limitations = report.get("limitations")
    if isinstance(limitations, list):
        lines.extend(f"> {item}" for item in limitations if isinstance(item, str))
    lines.append("")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    kb_root = Path(get_kb_version_dir())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product",
        type=Path,
        default=(
            kb_root.parent
            / "products"
            / "《人保健康附加出境人员团体意外医疗保险》条款v2-无标记.docx"
        ),
    )
    parser.add_argument("--kb-version", default="v5")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = measure(args.product, args.kb_version)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
