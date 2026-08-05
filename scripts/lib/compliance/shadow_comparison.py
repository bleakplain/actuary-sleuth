"""新旧合规审核快照的离线影子对照。

该模块只读取已经序列化的结果，不导入审核链路或 LLM 客户端。差异指标始终可
计算；依赖人工真值的业务门槛只有在 ``compliance-audit-v1`` 完成精算签收后才
计算，避免把旧行为或草稿标注误当作正确性 oracle。

快照 schema ``1.0.0`` 的每个样例包含：

* ``candidate_regulation_unit_ids``：进入审核的法规单元；
* ``excluded_regulation_unit_ids``：被适用性判断明确排除的法规单元；
* ``submitted_clause_ids``：实际提交给法规审核单元的产品条款块；
* ``decisions``：法规级结论和证据；
* ``oracle``：与 manifest 标注版本一致的精算真值。

``oracle`` 同时存在于新旧快照是为了让每个快照可以独立归档。两份值不一致时
拒绝比较；manifest 未签收时即使快照含 oracle，也不会读取它计算业务指标。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


SNAPSHOT_SCHEMA_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0.0"
ACCEPTANCE_DATASET_ID = "compliance-audit-v1"
_ACCEPTED_ANNOTATION_FIELDS = frozenset(
    {
        "product_tags",
        "product_risk_facts",
        "regulation_applicability",
        "clause_routing",
        "audit_decisions",
    }
)
_DECISIVE_STATUSES = frozenset({"compliant", "non_compliant"})


class ShadowComparisonError(ValueError):
    """快照或 manifest 不满足可比较的数据合同。"""


@dataclass(frozen=True)
class DecisionSnapshot:
    regulation_unit_id: str
    status: str
    regulation_evidence_count: int
    product_evidence_count: int

    @property
    def evidence_complete(self) -> bool:
        if self.status in _DECISIVE_STATUSES:
            return self.regulation_evidence_count > 0 and self.product_evidence_count > 0
        return False


@dataclass(frozen=True)
class OracleSnapshot:
    applicable_regulation_unit_ids: Tuple[str, ...]
    not_applicable_regulation_unit_ids: Tuple[str, ...]
    core_clause_ids: Tuple[str, ...]


@dataclass(frozen=True)
class SampleSnapshot:
    sample_id: str
    candidate_regulation_unit_ids: Tuple[str, ...]
    excluded_regulation_unit_ids: Tuple[str, ...]
    submitted_clause_ids: Tuple[str, ...]
    decisions: Tuple[DecisionSnapshot, ...]
    context_chars: int
    degraded: bool
    oracle: OracleSnapshot


@dataclass(frozen=True)
class AuditSnapshot:
    schema_version: str
    run_id: str
    pipeline_version: str
    dataset_id: str
    annotation_version: str
    samples: Tuple[SampleSnapshot, ...]
    source_sha256: str


@dataclass(frozen=True)
class ManifestGate:
    accepted: bool
    reasons: Tuple[str, ...]
    dataset_id: str
    annotation_version: str


@dataclass(frozen=True)
class MetricValue:
    value: Optional[float]
    numerator: int
    denominator: int
    threshold: float
    passed: bool


@dataclass(frozen=True)
class BusinessMetrics:
    regulation_recall: MetricValue
    exclusion_accuracy: MetricValue
    clause_recall: MetricValue
    evidence_completeness: MetricValue

    @property
    def passed(self) -> bool:
        return all(
            metric.passed
            for metric in (
                self.regulation_recall,
                self.exclusion_accuracy,
                self.clause_recall,
                self.evidence_completeness,
            )
        )


@dataclass(frozen=True)
class SampleDifference:
    sample_id: str
    candidate_added: Tuple[str, ...]
    candidate_removed: Tuple[str, ...]
    exclusion_added: Tuple[str, ...]
    exclusion_removed: Tuple[str, ...]
    clause_added: Tuple[str, ...]
    clause_removed: Tuple[str, ...]
    decision_added: Tuple[str, ...]
    decision_removed: Tuple[str, ...]
    decision_status_changed: Tuple[str, ...]
    old_context_chars: int
    new_context_chars: int
    context_chars_delta: int
    old_degraded: bool
    new_degraded: bool


@dataclass(frozen=True)
class ShadowComparisonReport:
    schema_version: str
    generated_at: str
    report_id: str
    dataset_id: str
    annotation_version: str
    old_run_id: str
    old_pipeline_version: str
    old_snapshot_sha256: str
    new_run_id: str
    new_pipeline_version: str
    new_snapshot_sha256: str
    sample_count: int
    old_degraded_rate: float
    new_degraded_rate: float
    context_chars_delta_total: int
    differences: Tuple[SampleDifference, ...]
    manifest_gate: ManifestGate
    business_metrics: Optional[BusinessMetrics]
    business_metrics_status: str
    cutover_blocked: bool
    cutover_reasons: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """返回可直接写入版本化 JSON 的稳定结构。"""
        return asdict(self)


@dataclass(frozen=True)
class ShadowReportFiles:
    json_path: Path
    csv_path: Path


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ShadowComparisonError(f"{field_name} 必须是对象")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShadowComparisonError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _string_tuple(value: Any, field_name: str) -> Tuple[str, ...]:
    if not isinstance(value, list):
        raise ShadowComparisonError(f"{field_name} 必须是字符串数组")
    items = tuple(_require_string(item, field_name) for item in value)
    if len(items) != len(set(items)):
        raise ShadowComparisonError(f"{field_name} 不能包含重复 ID")
    return items


def _evidence_count(value: Any, field_name: str) -> int:
    if not isinstance(value, list):
        raise ShadowComparisonError(f"{field_name} 必须是数组")
    count = 0
    for index, item in enumerate(value):
        evidence = _require_mapping(item, f"{field_name}[{index}]")
        quote = evidence.get("quote")
        if isinstance(quote, str) and quote.strip():
            count += 1
    return count


def _parse_decisions(value: Any, field_name: str) -> Tuple[DecisionSnapshot, ...]:
    if not isinstance(value, list):
        raise ShadowComparisonError(f"{field_name} 必须是数组")
    decisions = []
    ids = set()
    for index, raw in enumerate(value):
        item_name = f"{field_name}[{index}]"
        item = _require_mapping(raw, item_name)
        regulation_unit_id = _require_string(
            item.get("regulation_unit_id"), f"{item_name}.regulation_unit_id",
        )
        if regulation_unit_id in ids:
            raise ShadowComparisonError(f"{field_name} 存在重复法规结论: {regulation_unit_id}")
        ids.add(regulation_unit_id)
        decisions.append(
            DecisionSnapshot(
                regulation_unit_id=regulation_unit_id,
                status=_require_string(item.get("status"), f"{item_name}.status"),
                regulation_evidence_count=_evidence_count(
                    item.get("regulation_evidence", []),
                    f"{item_name}.regulation_evidence",
                ),
                product_evidence_count=_evidence_count(
                    item.get("product_evidence", []),
                    f"{item_name}.product_evidence",
                ),
            )
        )
    return tuple(decisions)


def _parse_oracle(value: Any, field_name: str) -> OracleSnapshot:
    oracle = _require_mapping(value, field_name)
    applicable = _string_tuple(
        oracle.get("applicable_regulation_unit_ids", []),
        f"{field_name}.applicable_regulation_unit_ids",
    )
    not_applicable = _string_tuple(
        oracle.get("not_applicable_regulation_unit_ids", []),
        f"{field_name}.not_applicable_regulation_unit_ids",
    )
    overlap = set(applicable).intersection(not_applicable)
    if overlap:
        raise ShadowComparisonError(
            f"{field_name} 同一法规不能同时适用和不适用: {sorted(overlap)}"
        )
    return OracleSnapshot(
        applicable_regulation_unit_ids=applicable,
        not_applicable_regulation_unit_ids=not_applicable,
        core_clause_ids=_string_tuple(
            oracle.get("core_clause_ids", []),
            f"{field_name}.core_clause_ids",
        ),
    )


def _parse_sample(value: Any, index: int) -> SampleSnapshot:
    field_name = f"samples[{index}]"
    sample = _require_mapping(value, field_name)
    context_chars = sample.get("context_chars", 0)
    if isinstance(context_chars, bool) or not isinstance(context_chars, int) or context_chars < 0:
        raise ShadowComparisonError(f"{field_name}.context_chars 必须是非负整数")
    degraded = sample.get("degraded", False)
    if not isinstance(degraded, bool):
        raise ShadowComparisonError(f"{field_name}.degraded 必须是布尔值")
    candidates = _string_tuple(
        sample.get("candidate_regulation_unit_ids", []),
        f"{field_name}.candidate_regulation_unit_ids",
    )
    excluded = _string_tuple(
        sample.get("excluded_regulation_unit_ids", []),
        f"{field_name}.excluded_regulation_unit_ids",
    )
    overlap = set(candidates).intersection(excluded)
    if overlap:
        raise ShadowComparisonError(
            f"{field_name} 候选和排除法规重叠: {sorted(overlap)}"
        )
    return SampleSnapshot(
        sample_id=_require_string(sample.get("sample_id"), f"{field_name}.sample_id"),
        candidate_regulation_unit_ids=candidates,
        excluded_regulation_unit_ids=excluded,
        submitted_clause_ids=_string_tuple(
            sample.get("submitted_clause_ids", []),
            f"{field_name}.submitted_clause_ids",
        ),
        decisions=_parse_decisions(sample.get("decisions", []), f"{field_name}.decisions"),
        context_chars=context_chars,
        degraded=degraded,
        oracle=_parse_oracle(sample.get("oracle", {}), f"{field_name}.oracle"),
    )


def load_audit_snapshot(path: Path) -> AuditSnapshot:
    """读取一个离线审核快照并验证最小数据合同。"""
    payload_bytes = path.read_bytes()
    try:
        raw = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowComparisonError(f"无法读取快照 {path}: {exc}") from exc
    payload = _require_mapping(raw, str(path))
    schema_version = _require_string(payload.get("schema_version"), "schema_version")
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ShadowComparisonError(f"不支持的快照 schema: {schema_version}")
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise ShadowComparisonError("samples 必须是非空数组")
    samples = tuple(_parse_sample(value, index) for index, value in enumerate(raw_samples))
    sample_ids = tuple(sample.sample_id for sample in samples)
    if len(sample_ids) != len(set(sample_ids)):
        raise ShadowComparisonError("samples 不能包含重复 sample_id")
    return AuditSnapshot(
        schema_version=schema_version,
        run_id=_require_string(payload.get("run_id"), "run_id"),
        pipeline_version=_require_string(
            payload.get("pipeline_version"), "pipeline_version",
        ),
        dataset_id=_require_string(payload.get("dataset_id"), "dataset_id"),
        annotation_version=_require_string(
            payload.get("annotation_version"), "annotation_version",
        ),
        samples=samples,
        source_sha256=hashlib.sha256(payload_bytes).hexdigest(),
    )


def load_acceptance_manifest(path: Path) -> Mapping[str, Any]:
    """读取验收清单；签收状态由 :func:`evaluate_manifest_gate` 严格判断。"""
    try:
        return _require_mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except json.JSONDecodeError as exc:
        raise ShadowComparisonError(f"无法读取 manifest {path}: {exc}") from exc


def _accepted_sample_ids(manifest: Mapping[str, Any]) -> Tuple[str, ...]:
    accepted = []
    products = manifest.get("products", [])
    if isinstance(products, list):
        for raw in products:
            if isinstance(raw, Mapping) and raw.get("annotation_status") == "accepted":
                accepted.append(_require_string(raw.get("sample_id"), "products.sample_id"))
    synthetic = manifest.get("synthetic_boundary_samples", [])
    if isinstance(synthetic, list):
        for raw in synthetic:
            if isinstance(raw, Mapping) and raw.get("status") == "accepted":
                accepted.append(
                    _require_string(raw.get("sample_id"), "synthetic_boundary_samples.sample_id")
                )
    return tuple(accepted)


def evaluate_manifest_gate(
    manifest: Mapping[str, Any],
    old_snapshot: AuditSnapshot,
    new_snapshot: AuditSnapshot,
) -> ManifestGate:
    """仅在数据集、标注和精算复核均签收时开放业务指标。"""
    reasons = []
    dataset_id = str(manifest.get("dataset_id", ""))
    annotations = manifest.get("annotations")
    annotation_mapping = annotations if isinstance(annotations, Mapping) else {}
    annotation_version = str(annotation_mapping.get("version", ""))
    if dataset_id != ACCEPTANCE_DATASET_ID:
        reasons.append(f"dataset_id 不是 {ACCEPTANCE_DATASET_ID}")
    if manifest.get("dataset_status") != "accepted":
        reasons.append("验收集尚未 accepted")
    if annotation_mapping.get("status") != "accepted":
        reasons.append("人工标注尚未 accepted")
    fields = annotation_mapping.get("fields")
    field_mapping = fields if isinstance(fields, Mapping) else {}
    pending_fields = sorted(
        field
        for field in _ACCEPTED_ANNOTATION_FIELDS
        if field_mapping.get(field) != "accepted"
    )
    if pending_fields:
        reasons.append(f"人工标注字段尚未签收: {','.join(pending_fields)}")
    review = manifest.get("actuary_review")
    review_mapping = review if isinstance(review, Mapping) else {}
    if review_mapping.get("status") != "accepted":
        reasons.append("精算复核尚未 accepted")
    if not isinstance(review_mapping.get("reviewer"), str) or not review_mapping["reviewer"].strip():
        reasons.append("精算复核人为空")
    if (
        not isinstance(review_mapping.get("reviewed_at"), str)
        or not review_mapping["reviewed_at"].strip()
    ):
        reasons.append("精算复核时间为空")
    for label, snapshot in (("旧", old_snapshot), ("新", new_snapshot)):
        if snapshot.dataset_id != dataset_id:
            reasons.append(f"{label}快照 dataset_id 与 manifest 不一致")
        if snapshot.annotation_version != annotation_version:
            reasons.append(f"{label}快照标注版本与 manifest 不一致")
    accepted_sample_ids = set(_accepted_sample_ids(manifest))
    snapshot_sample_ids = {sample.sample_id for sample in new_snapshot.samples}
    if not accepted_sample_ids:
        reasons.append("manifest 没有已签收样例")
    elif snapshot_sample_ids != accepted_sample_ids:
        reasons.append("快照样例集合与 manifest 已签收样例集合不一致")
    return ManifestGate(
        accepted=not reasons,
        reasons=tuple(reasons),
        dataset_id=dataset_id,
        annotation_version=annotation_version,
    )


def _ordered_difference(left: Sequence[str], right: Iterable[str]) -> Tuple[str, ...]:
    right_set = set(right)
    return tuple(item for item in left if item not in right_set)


def _decision_statuses(sample: SampleSnapshot) -> Dict[str, str]:
    return {decision.regulation_unit_id: decision.status for decision in sample.decisions}


def _compare_sample(old: SampleSnapshot, new: SampleSnapshot) -> SampleDifference:
    old_decisions = _decision_statuses(old)
    new_decisions = _decision_statuses(new)
    shared_decisions = set(old_decisions).intersection(new_decisions)
    return SampleDifference(
        sample_id=old.sample_id,
        candidate_added=_ordered_difference(
            new.candidate_regulation_unit_ids, old.candidate_regulation_unit_ids,
        ),
        candidate_removed=_ordered_difference(
            old.candidate_regulation_unit_ids, new.candidate_regulation_unit_ids,
        ),
        exclusion_added=_ordered_difference(
            new.excluded_regulation_unit_ids, old.excluded_regulation_unit_ids,
        ),
        exclusion_removed=_ordered_difference(
            old.excluded_regulation_unit_ids, new.excluded_regulation_unit_ids,
        ),
        clause_added=_ordered_difference(new.submitted_clause_ids, old.submitted_clause_ids),
        clause_removed=_ordered_difference(old.submitted_clause_ids, new.submitted_clause_ids),
        decision_added=tuple(sorted(set(new_decisions).difference(old_decisions))),
        decision_removed=tuple(sorted(set(old_decisions).difference(new_decisions))),
        decision_status_changed=tuple(
            sorted(
                regulation_id
                for regulation_id in shared_decisions
                if old_decisions[regulation_id] != new_decisions[regulation_id]
            )
        ),
        old_context_chars=old.context_chars,
        new_context_chars=new.context_chars,
        context_chars_delta=new.context_chars - old.context_chars,
        old_degraded=old.degraded,
        new_degraded=new.degraded,
    )


def _metric(numerator: int, denominator: int, threshold: float = 1.0) -> MetricValue:
    value = numerator / denominator if denominator else None
    return MetricValue(
        value=value,
        numerator=numerator,
        denominator=denominator,
        threshold=threshold,
        passed=value is not None and value >= threshold,
    )


def _compute_business_metrics(samples: Sequence[SampleSnapshot]) -> BusinessMetrics:
    applicable_hits = applicable_total = 0
    correct_exclusions = actual_exclusions = 0
    clause_hits = core_clause_total = 0
    complete_decisions = decisive_decisions = 0
    for sample in samples:
        candidates = set(sample.candidate_regulation_unit_ids)
        excluded = set(sample.excluded_regulation_unit_ids)
        submitted = set(sample.submitted_clause_ids)
        applicable = set(sample.oracle.applicable_regulation_unit_ids)
        not_applicable = set(sample.oracle.not_applicable_regulation_unit_ids)
        core_clauses = set(sample.oracle.core_clause_ids)
        applicable_hits += len(candidates.intersection(applicable))
        applicable_total += len(applicable)
        correct_exclusions += len(excluded.intersection(not_applicable))
        actual_exclusions += len(excluded)
        clause_hits += len(submitted.intersection(core_clauses))
        core_clause_total += len(core_clauses)
        for decision in sample.decisions:
            if decision.status not in _DECISIVE_STATUSES:
                continue
            decisive_decisions += 1
            if decision.evidence_complete:
                complete_decisions += 1
    return BusinessMetrics(
        regulation_recall=_metric(applicable_hits, applicable_total),
        exclusion_accuracy=_metric(correct_exclusions, actual_exclusions),
        clause_recall=_metric(clause_hits, core_clause_total),
        evidence_completeness=_metric(complete_decisions, decisive_decisions),
    )


def compare_snapshots(
    old_snapshot: AuditSnapshot,
    new_snapshot: AuditSnapshot,
    manifest: Mapping[str, Any],
    *,
    generated_at: Optional[str] = None,
) -> ShadowComparisonReport:
    """比较两份快照，并按精算签收状态决定是否计算业务门槛。"""
    if old_snapshot.dataset_id != new_snapshot.dataset_id:
        raise ShadowComparisonError("新旧快照 dataset_id 不一致")
    if old_snapshot.annotation_version != new_snapshot.annotation_version:
        raise ShadowComparisonError("新旧快照 annotation_version 不一致")
    old_by_id = {sample.sample_id: sample for sample in old_snapshot.samples}
    new_by_id = {sample.sample_id: sample for sample in new_snapshot.samples}
    if set(old_by_id) != set(new_by_id):
        raise ShadowComparisonError("新旧快照 sample_id 集合不一致")
    for sample_id, old_sample in old_by_id.items():
        if old_sample.oracle != new_by_id[sample_id].oracle:
            raise ShadowComparisonError(f"样例 {sample_id} 的新旧 oracle 不一致")
    differences = tuple(
        _compare_sample(old_by_id[sample_id], new_by_id[sample_id])
        for sample_id in sorted(old_by_id)
    )
    gate = evaluate_manifest_gate(manifest, old_snapshot, new_snapshot)
    business_metrics = (
        _compute_business_metrics(new_snapshot.samples) if gate.accepted else None
    )
    reasons = list(gate.reasons)
    cutover_gate = manifest.get("cutover_gate")
    cutover_mapping = cutover_gate if isinstance(cutover_gate, Mapping) else {}
    manifest_cutover_open = cutover_mapping.get("status") == "open"
    if not manifest_cutover_open:
        reasons.append("manifest cutover_gate 尚未 open")
    if business_metrics is not None and not business_metrics.passed:
        reasons.append("一个或多个业务门槛未达到 100%")
    cutover_blocked = (
        business_metrics is None
        or not business_metrics.passed
        or not manifest_cutover_open
    )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    return ShadowComparisonReport(
        schema_version=REPORT_SCHEMA_VERSION,
        generated_at=timestamp,
        report_id=(
            f"shadow:{old_snapshot.run_id}:{new_snapshot.run_id}:"
            f"{old_snapshot.annotation_version}"
        ),
        dataset_id=old_snapshot.dataset_id,
        annotation_version=old_snapshot.annotation_version,
        old_run_id=old_snapshot.run_id,
        old_pipeline_version=old_snapshot.pipeline_version,
        old_snapshot_sha256=old_snapshot.source_sha256,
        new_run_id=new_snapshot.run_id,
        new_pipeline_version=new_snapshot.pipeline_version,
        new_snapshot_sha256=new_snapshot.source_sha256,
        sample_count=len(differences),
        old_degraded_rate=sum(item.old_degraded for item in differences) / len(differences),
        new_degraded_rate=sum(item.new_degraded for item in differences) / len(differences),
        context_chars_delta_total=sum(item.context_chars_delta for item in differences),
        differences=differences,
        manifest_gate=gate,
        business_metrics=business_metrics,
        business_metrics_status="calculated" if business_metrics else "not_calculated",
        cutover_blocked=cutover_blocked,
        cutover_reasons=tuple(reasons),
    )


def _safe_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return normalized or "comparison"


def _join(values: Sequence[str]) -> str:
    return ";".join(values)


def write_shadow_report(
    report: ShadowComparisonReport,
    output_dir: Path,
    *,
    stem: Optional[str] = None,
) -> ShadowReportFiles:
    """以相同版本标识写出 JSON 摘要和逐样例 CSV。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    file_stem = _safe_stem(
        stem
        or (
            f"compliance-shadow-{REPORT_SCHEMA_VERSION}-"
            f"{report.old_run_id}-vs-{report.new_run_id}"
        )
    )
    json_path = output_dir / f"{file_stem}.json"
    csv_path = output_dir / f"{file_stem}.csv"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fieldnames = [
        "schema_version",
        "dataset_id",
        "annotation_version",
        "old_run_id",
        "new_run_id",
        "cutover_blocked",
        "cutover_reasons",
        "business_metrics_status",
        "regulation_recall",
        "exclusion_accuracy",
        "clause_recall",
        "evidence_completeness",
        "sample_id",
        "candidate_added",
        "candidate_removed",
        "exclusion_added",
        "exclusion_removed",
        "clause_added",
        "clause_removed",
        "decision_added",
        "decision_removed",
        "decision_status_changed",
        "old_context_chars",
        "new_context_chars",
        "context_chars_delta",
        "old_degraded",
        "new_degraded",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        metrics = report.business_metrics
        for difference in report.differences:
            writer.writerow(
                {
                    "schema_version": report.schema_version,
                    "dataset_id": report.dataset_id,
                    "annotation_version": report.annotation_version,
                    "old_run_id": report.old_run_id,
                    "new_run_id": report.new_run_id,
                    "cutover_blocked": str(report.cutover_blocked).lower(),
                    "cutover_reasons": _join(report.cutover_reasons),
                    "business_metrics_status": report.business_metrics_status,
                    "regulation_recall": (
                        "" if metrics is None or metrics.regulation_recall.value is None
                        else metrics.regulation_recall.value
                    ),
                    "exclusion_accuracy": (
                        "" if metrics is None or metrics.exclusion_accuracy.value is None
                        else metrics.exclusion_accuracy.value
                    ),
                    "clause_recall": (
                        "" if metrics is None or metrics.clause_recall.value is None
                        else metrics.clause_recall.value
                    ),
                    "evidence_completeness": (
                        "" if metrics is None or metrics.evidence_completeness.value is None
                        else metrics.evidence_completeness.value
                    ),
                    "sample_id": difference.sample_id,
                    "candidate_added": _join(difference.candidate_added),
                    "candidate_removed": _join(difference.candidate_removed),
                    "exclusion_added": _join(difference.exclusion_added),
                    "exclusion_removed": _join(difference.exclusion_removed),
                    "clause_added": _join(difference.clause_added),
                    "clause_removed": _join(difference.clause_removed),
                    "decision_added": _join(difference.decision_added),
                    "decision_removed": _join(difference.decision_removed),
                    "decision_status_changed": _join(
                        difference.decision_status_changed
                    ),
                    "old_context_chars": difference.old_context_chars,
                    "new_context_chars": difference.new_context_chars,
                    "context_chars_delta": difference.context_chars_delta,
                    "old_degraded": str(difference.old_degraded).lower(),
                    "new_degraded": str(difference.new_degraded).lower(),
                }
            )
    return ShadowReportFiles(json_path=json_path, csv_path=csv_path)


def run_shadow_comparison(
    old_snapshot_path: Path,
    new_snapshot_path: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    generated_at: Optional[str] = None,
    stem: Optional[str] = None,
) -> Tuple[ShadowComparisonReport, ShadowReportFiles]:
    """运行完全离线的影子对照并写出版本化报告。"""
    old_snapshot = load_audit_snapshot(old_snapshot_path)
    new_snapshot = load_audit_snapshot(new_snapshot_path)
    manifest = load_acceptance_manifest(manifest_path)
    report = compare_snapshots(
        old_snapshot,
        new_snapshot,
        manifest,
        generated_at=generated_at,
    )
    return report, write_shadow_report(report, output_dir, stem=stem)
