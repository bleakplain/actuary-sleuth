"""完整条款法规审核包的离线体量测量。"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

from lib.common.compliance_audit import RegulationAuditPackage
from lib.compliance.auditor import build_audit_messages, split_audit_package


def _prompt_chars(package: RegulationAuditPackage) -> int:
    return sum(len(message["content"]) for message in build_audit_messages(package))


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    rank = max(1, math.ceil(len(ordered) * percentile))
    return ordered[rank - 1]


@dataclass(frozen=True)
class ProductPackageMeasurement:
    sample_id: str
    file_name: str
    clause_count: int
    clause_chars: int
    applicable_units: int
    indeterminate_units: int
    audit_unit_count: int
    oversized_unit_count: int
    llm_call_count: int
    package_prompt_chars_total: int
    package_prompt_chars_mean: int
    package_prompt_chars_p95: int
    package_prompt_chars_max: int
    segment_prompt_chars_max: int
    max_average_call_seconds_for_300s: float

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "file_name": self.file_name,
            "clause_count": self.clause_count,
            "clause_chars": self.clause_chars,
            "applicable_units": self.applicable_units,
            "indeterminate_units": self.indeterminate_units,
            "audit_unit_count": self.audit_unit_count,
            "oversized_unit_count": self.oversized_unit_count,
            "llm_call_count": self.llm_call_count,
            "package_prompt_chars_total": self.package_prompt_chars_total,
            "package_prompt_chars_mean": self.package_prompt_chars_mean,
            "package_prompt_chars_p95": self.package_prompt_chars_p95,
            "package_prompt_chars_max": self.package_prompt_chars_max,
            "segment_prompt_chars_max": self.segment_prompt_chars_max,
            "max_average_call_seconds_for_300s": self.max_average_call_seconds_for_300s,
        }


@dataclass(frozen=True)
class FullDocumentMeasurementReport:
    schema_version: str
    kb_version: str
    max_concurrency: int
    deadline_seconds: int
    inputs: Mapping[str, object]
    products: Tuple[ProductPackageMeasurement, ...]
    summary: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kb_version": self.kb_version,
            "input_mode": "full_document",
            "token_measurement": "pending_online_provider_usage",
            "max_concurrency": self.max_concurrency,
            "deadline_seconds": self.deadline_seconds,
            "inputs": dict(self.inputs),
            "summary": dict(self.summary),
            "products": [product.to_dict() for product in self.products],
        }


def measure_product_packages(
    sample_id: str,
    file_name: str,
    clause_count: int,
    clause_chars: int,
    packages: Tuple[RegulationAuditPackage, ...],
    *,
    max_concurrency: int,
    deadline_seconds: int,
) -> ProductPackageMeasurement:
    package_chars = tuple(_prompt_chars(package) for package in packages)
    segments = tuple(split_audit_package(package) for package in packages)
    segment_chars = tuple(
        _prompt_chars(segment)
        for package_segments in segments
        for segment in package_segments
    )
    calls = len(segment_chars)
    waves = math.ceil(calls / max_concurrency) if calls else 0
    return ProductPackageMeasurement(
        sample_id=sample_id,
        file_name=file_name,
        clause_count=clause_count,
        clause_chars=clause_chars,
        applicable_units=sum(
            package.regulation.applicability_status == "applicable"
            for package in packages
        ),
        indeterminate_units=sum(
            package.regulation.applicability_status == "indeterminate"
            for package in packages
        ),
        audit_unit_count=len(packages),
        oversized_unit_count=sum(len(items) > 1 for items in segments),
        llm_call_count=calls,
        package_prompt_chars_total=sum(package_chars),
        package_prompt_chars_mean=(
            round(sum(package_chars) / len(package_chars)) if package_chars else 0
        ),
        package_prompt_chars_p95=_percentile(package_chars, 0.95),
        package_prompt_chars_max=max(package_chars, default=0),
        segment_prompt_chars_max=max(segment_chars, default=0),
        max_average_call_seconds_for_300s=(
            round(deadline_seconds / waves, 2) if waves else float(deadline_seconds)
        ),
    )


def build_measurement_report(
    products: Iterable[ProductPackageMeasurement],
    *,
    kb_version: str,
    max_concurrency: int,
    deadline_seconds: int,
    inputs: Mapping[str, object],
) -> FullDocumentMeasurementReport:
    ordered = tuple(products)
    calls = tuple(product.llm_call_count for product in ordered)
    audit_units = sum(product.audit_unit_count for product in ordered)
    prompt_chars_total = sum(
        product.package_prompt_chars_total for product in ordered
    )
    summary: dict[str, object] = {
        "product_count": len(ordered),
        "audit_unit_count": audit_units,
        "llm_call_count": sum(calls),
        "llm_calls_per_product_mean": (
            round(sum(calls) / len(calls), 2) if calls else 0
        ),
        "llm_calls_per_product_p95": _percentile(calls, 0.95),
        "llm_calls_per_product_max": max(calls, default=0),
        "oversized_unit_count": sum(
            product.oversized_unit_count for product in ordered
        ),
        "package_prompt_chars_total": prompt_chars_total,
        "package_prompt_chars_mean": (
            round(prompt_chars_total / audit_units) if audit_units else 0
        ),
        "max_product_package_prompt_chars_p95": max(
            (product.package_prompt_chars_p95 for product in ordered),
            default=0,
        ),
        "max_package_prompt_chars": max(
            (product.package_prompt_chars_max for product in ordered),
            default=0,
        ),
        "min_300s_call_budget_seconds": min(
            (
                product.max_average_call_seconds_for_300s
                for product in ordered
            ),
            default=float(deadline_seconds),
        ),
    }
    return FullDocumentMeasurementReport(
        schema_version="1",
        kb_version=kb_version,
        max_concurrency=max_concurrency,
        deadline_seconds=deadline_seconds,
        inputs=dict(inputs),
        products=ordered,
        summary=summary,
    )


def render_measurement_markdown(report: FullDocumentMeasurementReport) -> str:
    summary = report.summary
    lines = [
        "# 完整产品条款 LLM 审核包离线体量报告",
        "",
        f"- 知识库：{report.kb_version}",
        f"- 产品清单 SHA-256：{report.inputs['product_manifest_sha256']}",
        f"- KB 构建清单 SHA-256：{report.inputs['kb_build_manifest_sha256']}",
        f"- 法规 chunk 数：{report.inputs['catalog_chunk_count']}",
        f"- 产品数：{summary['product_count']}",
        f"- 法规审核单元总数：{summary['audit_unit_count']}",
        f"- 预计 LLM 调用总数：{summary['llm_call_count']}",
        f"- 单产品调用数 P95 / 最大：{summary['llm_calls_per_product_p95']} / {summary['llm_calls_per_product_max']}",
        f"- 超长并分段的法规单元：{summary['oversized_unit_count']}",
        f"- 全部法规包平均 prompt 字符数：{summary['package_prompt_chars_mean']}",
        f"- 各产品 P95 prompt 字符数的最大值：{summary['max_product_package_prompt_chars_p95']}",
        f"- 最大单包 prompt 字符数：{summary['max_package_prompt_chars']}",
        f"- 300秒内完成时最严格的单次平均耗时上限：{summary['min_300s_call_budget_seconds']}秒",
        "- token：待在线供应商 usage 实测，本报告不做字符/token猜测。",
        "",
        "| 样本 | 审核块 | applicable | indeterminate | 法规单元 | LLM调用 | 超长单元 | 平均prompt字符 | P95 prompt字符 | 300秒单次耗时上限 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        "| {sample} | {clauses} | {applicable} | {indeterminate} | {units} | "
        "{calls} | {oversized} | {mean_chars} | {p95_chars} | {budget:.2f}s |".format(
            sample=product.sample_id,
            clauses=product.clause_count,
            applicable=product.applicable_units,
            indeterminate=product.indeterminate_units,
            units=product.audit_unit_count,
            calls=product.llm_call_count,
            oversized=product.oversized_unit_count,
            mean_chars=product.package_prompt_chars_mean,
            p95_chars=product.package_prompt_chars_p95,
            budget=product.max_average_call_seconds_for_300s,
        )
        for product in report.products
    )
    return "\n".join(lines) + "\n"
