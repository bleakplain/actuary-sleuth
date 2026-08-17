"""法规触发过滤与动态条款证据的离线 A/B/C 体量测量。"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple

from lib.common.compliance_audit import (
    RegulationAuditDecision,
    RegulationAuditPackage,
    RegulationDecisionStatus,
    RegulationTriggerSpec,
    RoutedClause,
    TriggerStatus,
)
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    build_regulation_audit_packages,
    run_audit_pipeline,
)
from lib.compliance.auditor import build_audit_messages, split_audit_package
from lib.compliance.package_measurement import (
    build_audit_clause_snapshots,
    list_applicable_regulation_units,
)
from lib.compliance.regulation_retrieval import (
    RegulationRetrievalCoverage,
    RegulationRetrievalOutcome,
)
from lib.compliance.regulation_trigger_metadata import (
    parse_regulation_trigger_metadata,
)
from lib.compliance.regulation_units import (
    RegulationUnit,
    aggregate_regulation_units,
)
from lib.doc_parser import parse_product_document
from lib.rag_engine.kb_rebuild import load_catalog_rows


@dataclass(frozen=True)
class PilotTriggerRule:
    rule_id: str
    regulation_unit_id: str
    specs: Tuple[RegulationTriggerSpec, ...]


@dataclass(frozen=True)
class PilotTriggerCatalog:
    schema_version: str
    sha256: str
    rules: Tuple[PilotTriggerRule, ...]

    @property
    def unit_ids(self) -> Tuple[str, ...]:
        return tuple(rule.regulation_unit_id for rule in self.rules)

    def specs_for(
        self,
        regulation_unit_id: str,
    ) -> Optional[Tuple[RegulationTriggerSpec, ...]]:
        return next(
            (
                rule.specs
                for rule in self.rules
                if rule.regulation_unit_id == regulation_unit_id
            ),
            None,
        )


@dataclass(frozen=True)
class ArmMeasurement:
    candidate_regulation_count: int
    submitted_body_clause_occurrence_count: int
    submitted_body_chars: int
    outline_clause_occurrence_count: int
    llm_call_count: int
    prompt_chars_total: int
    prompt_chars_mean: int
    prompt_chars_p95: int
    prompt_chars_max: int
    full_document_fallback_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_regulation_count": self.candidate_regulation_count,
            "submitted_body_clause_occurrence_count": (
                self.submitted_body_clause_occurrence_count
            ),
            "submitted_body_chars": self.submitted_body_chars,
            "outline_clause_occurrence_count": (
                self.outline_clause_occurrence_count
            ),
            "llm_call_count": self.llm_call_count,
            "prompt_chars_total": self.prompt_chars_total,
            "prompt_chars_mean": self.prompt_chars_mean,
            "prompt_chars_p95": self.prompt_chars_p95,
            "prompt_chars_max": self.prompt_chars_max,
            "full_document_fallback_count": self.full_document_fallback_count,
        }


@dataclass(frozen=True)
class ProductTriggerABMeasurement:
    sample_id: str
    file_name: str
    product_name: str
    parsed_clause_count: int
    parsed_clause_chars: int
    pilot_candidate_count: int
    trigger_status_counts: Mapping[str, int]
    simulated_safe_exclusion_unit_ids: Tuple[str, ...]
    arm_a: ArmMeasurement
    arm_b: ArmMeasurement
    arm_c: ArmMeasurement
    dynamic_evidence_warning_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "file_name": self.file_name,
            "product_name": self.product_name,
            "parsed_clause_count": self.parsed_clause_count,
            "parsed_clause_chars": self.parsed_clause_chars,
            "pilot_candidate_count": self.pilot_candidate_count,
            "trigger_status_counts": dict(self.trigger_status_counts),
            "simulated_safe_exclusion_count": len(
                self.simulated_safe_exclusion_unit_ids
            ),
            "simulated_safe_exclusion_unit_ids": list(
                self.simulated_safe_exclusion_unit_ids
            ),
            "dynamic_evidence_warning_count": (
                self.dynamic_evidence_warning_count
            ),
            "arm_a_current_full_document": self.arm_a.to_dict(),
            "arm_b_trigger_filter_full_document": self.arm_b.to_dict(),
            "arm_c_trigger_filter_dynamic_evidence": self.arm_c.to_dict(),
            "deltas": {
                "candidate_reduction_b_vs_a": (
                    self.arm_a.candidate_regulation_count
                    - self.arm_b.candidate_regulation_count
                ),
                "prompt_reduction_percent_b_vs_a": _reduction_percent(
                    self.arm_a.prompt_chars_total,
                    self.arm_b.prompt_chars_total,
                ),
                "prompt_reduction_percent_c_vs_a": _reduction_percent(
                    self.arm_a.prompt_chars_total,
                    self.arm_c.prompt_chars_total,
                ),
                "body_char_reduction_percent_c_vs_b": _reduction_percent(
                    self.arm_b.submitted_body_chars,
                    self.arm_c.submitted_body_chars,
                ),
            },
        }


@dataclass(frozen=True)
class TriggerABMeasurementReport:
    schema_version: str
    generated_at: str
    inputs: Mapping[str, object]
    summary: Mapping[str, object]
    products: Tuple[ProductTriggerABMeasurement, ...]
    limitations: Tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "measurement_kind": "offline_trigger_ab_context_volume",
            "formal_audit_result": False,
            "generated_at": self.generated_at,
            "inputs": dict(self.inputs),
            "summary": dict(self.summary),
            "products": [product.to_dict() for product in self.products],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class _MeasuredPackages:
    measurement: ArmMeasurement
    prompt_chars: Tuple[int, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空字符串")
    return value.strip()


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} 必须是整数")
    return value


def load_pilot_trigger_catalog(path: Path) -> PilotTriggerCatalog:
    raw = _mapping(json.loads(path.read_text(encoding="utf-8")), "试点配置")
    raw_rules = _sequence(raw.get("rules"), "试点配置 rules")
    rules = []
    seen_unit_ids = set()
    for index, raw_rule in enumerate(raw_rules):
        rule = _mapping(raw_rule, f"rules[{index}]")
        unit_id = _required_text(
            rule.get("unit_id") or rule.get("regulation_unit_id"),
            f"rules[{index}].unit_id",
        )
        if unit_id in seen_unit_ids:
            raise ValueError(f"试点法规单元重复: {unit_id}")
        seen_unit_ids.add(unit_id)
        draft_metadata = _mapping(
            rule.get("draft_metadata", {}),
            f"rules[{index}].draft_metadata",
        )
        rules.append(PilotTriggerRule(
            rule_id=str(rule.get("rule_id") or f"pilot-{index + 1}"),
            regulation_unit_id=unit_id,
            specs=parse_regulation_trigger_metadata(draft_metadata),
        ))
    if not rules:
        raise ValueError("试点配置至少需要一个法规单元")
    return PilotTriggerCatalog(
        schema_version=str(raw.get("schema_version") or "unversioned"),
        sha256=_sha256(path),
        rules=tuple(rules),
    )


def inject_pilot_trigger_specs(
    units: Iterable[RegulationUnit],
    pilot: PilotTriggerCatalog,
) -> Tuple[RegulationUnit, ...]:
    injected = []
    for unit in units:
        specs = pilot.specs_for(unit.unit_id)
        if specs is None:
            injected.append(unit)
            continue
        injected.append(replace(
            unit,
            trigger_specs=specs,
            chunks=tuple(
                replace(chunk, trigger_specs=specs) for chunk in unit.chunks
            ),
        ))
    return tuple(injected)


def validate_pilot_units_exist(
    pilot: PilotTriggerCatalog,
    units: Iterable[RegulationUnit],
) -> None:
    catalog_unit_ids = frozenset(unit.unit_id for unit in units)
    missing_pilot_units = tuple(
        unit_id for unit_id in pilot.unit_ids if unit_id not in catalog_unit_ids
    )
    if missing_pilot_units:
        raise ValueError(
            "试点法规单元不在当前知识库目录: "
            + "、".join(missing_pilot_units)
        )


def _offline_auditor(
    packages: Iterable[RegulationAuditPackage],
    max_concurrency: int,
    deadline_seconds: float,
    on_decision: Optional[
        Callable[[RegulationAuditDecision, int, int], None]
    ],
) -> Tuple[RegulationAuditDecision, ...]:
    del max_concurrency, deadline_seconds
    ordered = tuple(packages)
    decisions = tuple(
        RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.COMPLIANT,
            reasoning="离线体量占位，不代表法规审核结论。",
            suggestion="",
            regulation_evidence=(),
            product_evidence=(),
        )
        for package in ordered
    )
    if on_decision is not None:
        total = len(decisions)
        for completed, decision in enumerate(decisions, start=1):
            on_decision(decision, completed, total)
    return decisions


def _percentile(values: Iterable[int], percentile: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    rank = max(1, math.ceil(len(ordered) * percentile))
    return ordered[rank - 1]


def _has_body(routed: RoutedClause) -> bool:
    return not routed.clause.container_only and bool(routed.clause.text.strip())


def _prompt_chars(package: RegulationAuditPackage) -> int:
    return sum(len(message["content"]) for message in build_audit_messages(package))


def _measure_packages(
    packages: Iterable[RegulationAuditPackage],
    *,
    full_document_fallback_count: int = 0,
) -> _MeasuredPackages:
    ordered = tuple(packages)
    segments = tuple(
        segment
        for package in ordered
        for segment in split_audit_package(package)
    )
    prompt_chars = tuple(_prompt_chars(segment) for segment in segments)
    submitted = tuple(
        routed
        for package in ordered
        for routed in package.clauses
        if routed.submitted and _has_body(routed)
    )
    total = sum(prompt_chars)
    return _MeasuredPackages(
        measurement=ArmMeasurement(
            candidate_regulation_count=len(ordered),
            submitted_body_clause_occurrence_count=len(submitted),
            submitted_body_chars=sum(
                len(routed.clause.title) + len(routed.clause.text)
                for routed in submitted
            ),
            outline_clause_occurrence_count=sum(
                len(package.clauses) for package in ordered
            ),
            llm_call_count=len(segments),
            prompt_chars_total=total,
            prompt_chars_mean=(round(total / len(segments)) if segments else 0),
            prompt_chars_p95=_percentile(prompt_chars, 0.95),
            prompt_chars_max=max(prompt_chars, default=0),
            full_document_fallback_count=full_document_fallback_count,
        ),
        prompt_chars=prompt_chars,
    )


def _dynamic_package(
    package: RegulationAuditPackage,
    selected_clause_ids: Sequence[str],
    *,
    config_valid: bool,
) -> Tuple[RegulationAuditPackage, bool]:
    selected = frozenset(selected_clause_ids)
    selected_body_ids = frozenset(
        routed.clause.clause_id
        for routed in package.clauses
        if _has_body(routed) and routed.clause.clause_id in selected
    )
    if not config_valid or not selected_body_ids:
        return package, True
    return replace(
        package,
        clauses=tuple(
            replace(
                routed,
                submitted=(
                    routed.clause.clause_id in selected_body_ids
                    if _has_body(routed)
                    else False
                ),
            )
            for routed in package.clauses
        ),
    ), False


def _complete_coverage(unit_count: int) -> RegulationRetrievalCoverage:
    return RegulationRetrievalCoverage(
        rag_available=False,
        catalog_available=True,
        semantic_available=False,
        registered_available=False,
        category_resolution="offline_catalog",
        complete_candidate_freeze=True,
        catalog_candidate_count=unit_count,
    )


def _reduction_percent(baseline: int, comparison: int) -> float:
    return round((1 - comparison / baseline) * 100, 2) if baseline else 0.0


def _change_label(reduction_percent: float) -> str:
    if reduction_percent < 0:
        return f"增加 {abs(reduction_percent)}%"
    return f"减少 {reduction_percent}%"


def measure_product_trigger_ab(
    sample_id: str,
    file_name: str,
    request: AuditPipelineRequest,
    units: Tuple[RegulationUnit, ...],
    pilot: PilotTriggerCatalog,
) -> Tuple[ProductTriggerABMeasurement, Mapping[str, Tuple[int, ...]]]:
    arm_a_packages, _, _ = build_regulation_audit_packages(request, units)
    arm_a = _measure_packages(arm_a_packages)

    pilot_units = inject_pilot_trigger_specs(units, pilot)
    outcome = RegulationRetrievalOutcome(
        regulations=(),
        regulation_units=pilot_units,
        coverage=_complete_coverage(len(pilot_units)),
        candidate_count=len(pilot_units),
    )
    result = run_audit_pipeline(
        request,
        retriever=lambda *args: outcome,
        package_auditor=_offline_auditor,
    )
    retained_records = tuple(
        record
        for record in result.records
        if (
            record.package.regulation.regulation_unit_id not in pilot.unit_ids
            or record.package.trigger_evaluation is None
            or record.package.trigger_evaluation.status
            is not TriggerStatus.NOT_TRIGGERED
        )
    )
    excluded_unit_ids = tuple(
        record.package.regulation.regulation_unit_id
        for record in result.records
        if (
            record.package.regulation.regulation_unit_id in pilot.unit_ids
            and record.package.trigger_evaluation is not None
            and record.package.trigger_evaluation.status
            is TriggerStatus.NOT_TRIGGERED
        )
    )
    arm_b_packages = tuple(record.package for record in retained_records)
    arm_b = _measure_packages(arm_b_packages)

    dynamic_packages = []
    fallback_count = 0
    dynamic_warning_count = 0
    for record in retained_records:
        selection = record.evidence_selection
        dynamic_warning_count += len(selection.warnings) if selection else 1
        package, fell_back = _dynamic_package(
            record.package,
            selection.selected_clause_ids if selection is not None else (),
            config_valid=(
                selection.config_valid if selection is not None else False
            ),
        )
        dynamic_packages.append(package)
        fallback_count += fell_back
    arm_c = _measure_packages(
        dynamic_packages,
        full_document_fallback_count=fallback_count,
    )

    statuses = {
        status.value: sum(
            record.package.trigger_evaluation is not None
            and record.package.trigger_evaluation.status is status
            for record in result.records
            if record.package.regulation.regulation_unit_id in pilot.unit_ids
        )
        for status in TriggerStatus
    }
    measurement = ProductTriggerABMeasurement(
        sample_id=sample_id,
        file_name=file_name,
        product_name=request.product_name,
        parsed_clause_count=len(request.clauses),
        parsed_clause_chars=sum(
            len(clause.title) + len(clause.text) for clause in request.clauses
        ),
        pilot_candidate_count=sum(
            unit.unit_id in pilot.unit_ids for unit in units
        ),
        trigger_status_counts=statuses,
        simulated_safe_exclusion_unit_ids=excluded_unit_ids,
        arm_a=arm_a.measurement,
        arm_b=arm_b.measurement,
        arm_c=arm_c.measurement,
        dynamic_evidence_warning_count=dynamic_warning_count,
    )
    return measurement, {
        "A": arm_a.prompt_chars,
        "B": arm_b.prompt_chars,
        "C": arm_c.prompt_chars,
    }


def _arm_summary(
    products: Sequence[ProductTriggerABMeasurement],
    arm_name: str,
    prompt_chars: Sequence[int],
) -> dict[str, object]:
    arms = tuple(
        {
            "A": product.arm_a,
            "B": product.arm_b,
            "C": product.arm_c,
        }[arm_name]
        for product in products
    )
    total_prompt_chars = sum(item.prompt_chars_total for item in arms)
    return {
        "candidate_regulation_count": sum(
            item.candidate_regulation_count for item in arms
        ),
        "submitted_body_clause_occurrence_count": sum(
            item.submitted_body_clause_occurrence_count for item in arms
        ),
        "submitted_body_chars": sum(item.submitted_body_chars for item in arms),
        "outline_clause_occurrence_count": sum(
            item.outline_clause_occurrence_count for item in arms
        ),
        "llm_call_count": sum(item.llm_call_count for item in arms),
        "prompt_chars_total": total_prompt_chars,
        "prompt_chars_mean": (
            round(total_prompt_chars / len(prompt_chars)) if prompt_chars else 0
        ),
        "prompt_chars_p95": _percentile(prompt_chars, 0.95),
        "prompt_chars_max": max(prompt_chars, default=0),
        "full_document_fallback_count": sum(
            item.full_document_fallback_count for item in arms
        ),
    }


def run_trigger_ab_measurement(
    manifest_path: Path,
    products_dir: Path,
    kb_dir: Path,
    pilot_json_path: Path,
) -> TriggerABMeasurementReport:
    manifest = _mapping(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        "产品验收清单",
    )
    kb = _mapping(manifest.get("kb"), "知识库身份")
    kb_version = _required_text(kb.get("version"), "知识库版本")
    raw_products = _sequence(manifest.get("products"), "产品验收清单 products")
    pilot = load_pilot_trigger_catalog(pilot_json_path)
    catalog = load_catalog_rows(kb_dir / kb_version / "lancedb")
    validate_pilot_units_exist(
        pilot,
        aggregate_regulation_units(catalog, kb_version).units,
    )
    products = []
    prompt_chars: dict[str, list[int]] = {"A": [], "B": [], "C": []}
    for index, raw_product in enumerate(raw_products):
        product = _mapping(raw_product, f"products[{index}]")
        sample_id = _required_text(
            product.get("sample_id"),
            f"products[{index}].sample_id",
        )
        file_name = _required_text(
            product.get("file_name"),
            f"products[{index}].file_name",
        )
        source = products_dir / file_name
        expected_sha256 = _required_text(
            product.get("sha256"),
            f"products[{index}].sha256",
        )
        if _sha256(source) != expected_sha256:
            raise ValueError(f"产品文件指纹不一致: {file_name}")
        document = parse_product_document(str(source))
        clauses = build_audit_clause_snapshots(document)
        units = list_applicable_regulation_units(
            catalog,
            document.product_tags,
            kb_version,
        )
        request = AuditPipelineRequest(
            product_name=document.product_name or file_name,
            document_content=document.canonical_text,
            product_tags=document.product_tags,
            clauses=clauses,
            document_fingerprint=document.document_fingerprint,
            audit_input_fingerprint=document.audit_input_fingerprint,
            product_name_source=document.product_name_source,
            parse_warnings=tuple(document.warnings),
            coverage_attested=document.coverage_attested,
            coverage_attested_facts=document.coverage_attested_facts,
        )
        measurement, product_prompts = measure_product_trigger_ab(
            sample_id,
            file_name,
            request,
            units,
            pilot,
        )
        products.append(measurement)
        for arm_name, values in product_prompts.items():
            prompt_chars[arm_name].extend(values)

    ordered = tuple(products)
    arm_summaries = {
        arm_name: _arm_summary(ordered, arm_name, prompt_chars[arm_name])
        for arm_name in ("A", "B", "C")
    }
    arm_a_prompt = _integer(
        arm_summaries["A"]["prompt_chars_total"],
        "A.prompt_chars_total",
    )
    arm_b_prompt = _integer(
        arm_summaries["B"]["prompt_chars_total"],
        "B.prompt_chars_total",
    )
    arm_c_prompt = _integer(
        arm_summaries["C"]["prompt_chars_total"],
        "C.prompt_chars_total",
    )
    summary: dict[str, object] = {
        "product_count": len(ordered),
        "pilot_rule_count": len(pilot.rules),
        "configured_pilot_rule_count": sum(bool(rule.specs) for rule in pilot.rules),
        "simulated_safe_exclusion_count": sum(
            len(product.simulated_safe_exclusion_unit_ids)
            for product in ordered
        ),
        "arms": arm_summaries,
        "candidate_reduction_b_vs_a": (
            _integer(
                arm_summaries["A"]["candidate_regulation_count"],
                "A.candidate_regulation_count",
            )
            - _integer(
                arm_summaries["B"]["candidate_regulation_count"],
                "B.candidate_regulation_count",
            )
        ),
        "prompt_reduction_percent_b_vs_a": _reduction_percent(
            arm_a_prompt,
            arm_b_prompt,
        ),
        "prompt_reduction_percent_c_vs_a": _reduction_percent(
            arm_a_prompt,
            arm_c_prompt,
        ),
    }
    return TriggerABMeasurementReport(
        schema_version="1.0.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        inputs={
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "products_dir": str(products_dir),
            "kb_version": kb_version,
            "kb_catalog_row_count": len(catalog),
            "pilot_json_path": str(pilot_json_path),
            "pilot_json_sha256": pilot.sha256,
            "pilot_schema_version": pilot.schema_version,
            "temporary_in_memory_injection": True,
            "excel_modified": False,
            "knowledge_base_modified": False,
            "llm_called": False,
        },
        summary=summary,
        products=ordered,
        limitations=(
            "本报告只测量候选数量和模型输入体量，不代表法规审核准确率。",
            "B 仅模拟求值器已证明安全的 not_triggered；indeterminate 全部保留。",
            "C 保留完整条款目录；动态证据为空或配置异常时回退完整正文。",
            "prompt 字符按当前逐法规单元调用模式跨包累计；不代表按法规文件合批后的实际 token。",
            "未调用模型，字符数不能替代供应商 token usage。",
        ),
    )


def render_trigger_ab_markdown(report: TriggerABMeasurementReport) -> str:
    summary = report.summary
    raw_arms = _mapping(summary.get("arms"), "汇总 arms")
    arms = {
        name: _mapping(raw_arms.get(name), f"汇总 arms.{name}")
        for name in ("A", "B", "C")
    }
    arm_a_prompt = _integer(
        arms["A"].get("prompt_chars_total"),
        "A.prompt_chars_total",
    )
    arm_b_prompt = _integer(
        arms["B"].get("prompt_chars_total"),
        "B.prompt_chars_total",
    )
    arm_c_prompt = _integer(
        arms["C"].get("prompt_chars_total"),
        "C.prompt_chars_total",
    )
    lines = [
        "# 法规触发与动态条款证据 A/B/C 离线体量对照",
        "",
        f"- 产品：{summary['product_count']} 份",
        f"- 试点法规：{summary['pilot_rule_count']} 条",
        f"- 安全 not_triggered 模拟排除：{summary['simulated_safe_exclusion_count']} 个组合",
        "- B 对 A prompt 字符变化："
        + _change_label(_reduction_percent(arm_a_prompt, arm_b_prompt)),
        "- C 对 A prompt 字符变化："
        + _change_label(_reduction_percent(arm_a_prompt, arm_c_prompt)),
        "- 本次未调用 LLM，未修改 Excel、KB 或生产开关。",
        "- 提交正文块与目录条目均按跨法规包累计出现次数统计，不是产品唯一条款块数。",
        "",
        "| 方案 | 法规候选 | LLM调用 | 提交正文块出现次数 | 提交正文字符 | prompt字符 | P95单包 | 全文回退 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "A": "A 当前：标签过滤+全文",
        "B": "B：触发过滤+全文",
        "C": "C：触发过滤+动态证据",
    }
    for name in ("A", "B", "C"):
        arm = arms[name]
        lines.append(
            "| {label} | {candidates} | {calls} | {clauses} | {body_chars} | "
            "{prompt_chars} | {p95} | {fallbacks} |".format(
                label=labels[name],
                candidates=arm["candidate_regulation_count"],
                calls=arm["llm_call_count"],
                clauses=arm["submitted_body_clause_occurrence_count"],
                body_chars=arm["submitted_body_chars"],
                prompt_chars=arm["prompt_chars_total"],
                p95=arm["prompt_chars_p95"],
                fallbacks=arm["full_document_fallback_count"],
            )
        )
    lines.extend((
        "",
        "| 样本 | A候选 | B候选 | 安全排除 | A prompt字符 | B prompt字符 | C prompt字符 | C对A减少 | C全文回退 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for product in report.products:
        lines.append(
            "| {sample} | {a_candidates} | {b_candidates} | {excluded} | "
            "{a_prompt} | {b_prompt} | {c_prompt} | {reduction}% | {fallbacks} |".format(
                sample=product.sample_id,
                a_candidates=product.arm_a.candidate_regulation_count,
                b_candidates=product.arm_b.candidate_regulation_count,
                excluded=len(product.simulated_safe_exclusion_unit_ids),
                a_prompt=product.arm_a.prompt_chars_total,
                b_prompt=product.arm_b.prompt_chars_total,
                c_prompt=product.arm_c.prompt_chars_total,
                reduction=_reduction_percent(
                    product.arm_a.prompt_chars_total,
                    product.arm_c.prompt_chars_total,
                ),
                fallbacks=product.arm_c.full_document_fallback_count,
            )
        )
    lines.extend(("", "> 限制："))
    lines.extend(f"> - {limitation}" for limitation in report.limitations)
    lines.append("")
    return "\n".join(lines)
