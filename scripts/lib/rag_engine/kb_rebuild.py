"""法规知识库的可验证 staging 重建与可恢复切换。

生产 references 和版本索引在 staging 构建完成前始终保持只读。切换阶段要求
调用方先停止 API/worker；多个目录无法组成单个文件系统事务，因此使用同盘
``os.replace`` 加补偿回滚实现离线原子切换。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from lib.common.constants import ComplianceConstants

from .kb_identity import (
    sha256_file,
    stable_catalog_sha256,
    stable_node_content_sha256,
)

_MANIFEST_COVERAGE_FIELDS = (
    "条款主体",
    "条款主题",
    "适用标签",
    "涉及标签",
    "风险触发标签",
    "检查目标标签",
    "触发事实",
    "触发运算符",
    "触发期望值",
    "目标条款主题",
    "所需事实",
    "证明策略",
    "检索必含词组",
    "检索任一词组",
    "触发条件说明",
    "触发排除验收状态",
    "特殊属性",
    "规则逻辑",
    "团体个人",
    "备注",
)


class KnowledgeBaseRebuildError(RuntimeError):
    """知识库 staging、校验或切换失败。"""


@dataclass(frozen=True)
class StagingRequest:
    source_excel: Path
    production_references_dir: Path
    kb_root: Path
    stage_dir: Path
    version: str = "v5"
    expected_documents: Optional[int] = None
    expected_chunks: Optional[int] = None


@dataclass(frozen=True)
class StagedValidation:
    valid: bool
    version: str
    document_count: int
    chunk_count: int
    bm25_count: int
    deterministic_id_count: int
    lancedb_node_content_sha256: str = ""
    bm25_node_content_sha256: str = ""
    errors: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "version": self.version,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "bm25_count": self.bm25_count,
            "deterministic_id_count": self.deterministic_id_count,
            "lancedb_node_content_sha256": self.lancedb_node_content_sha256,
            "bm25_node_content_sha256": self.bm25_node_content_sha256,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class StagedBuildResult:
    stage_dir: Path
    references_dir: Path
    version_dir: Path
    manifest_path: Path
    identity_path: Path
    report_path: Path
    stats: Mapping[str, int]
    validation: StagedValidation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_dir": str(self.stage_dir),
            "references_dir": str(self.references_dir),
            "version_dir": str(self.version_dir),
            "manifest_path": str(self.manifest_path),
            "identity_path": str(self.identity_path),
            "report_path": str(self.report_path),
            "stats": dict(self.stats),
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class PromotionResult:
    version: str
    backup_dir: Path
    previous_manifest_sha256: str
    promoted_manifest_sha256: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "version": self.version,
            "backup_dir": str(self.backup_dir),
            "previous_manifest_sha256": self.previous_manifest_sha256,
            "promoted_manifest_sha256": self.promoted_manifest_sha256,
        }


@dataclass(frozen=True)
class _RollbackValidation:
    previous_manifest_sha256: str
    promoted_manifest_sha256: str


def default_stage_dir(kb_root: Path, version: str) -> Path:
    """返回同文件系统内的唯一 staging 目录。"""
    _validate_version(version)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return kb_root / ".staging" / f"{version}-{stamp}-{uuid.uuid4().hex[:8]}"


def _validate_version(version: str) -> None:
    if not re.fullmatch(r"v[1-9]\d*", version):
        raise KnowledgeBaseRebuildError(f"非法知识库版本: {version}")


def _require_child(path: Path, parent: Path, label: str) -> Path:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path == resolved_parent:
        raise KnowledgeBaseRebuildError(f"{label} 不能等于父目录: {path}")
    try:
        resolved_path.relative_to(resolved_parent)
    except ValueError as exc:
        raise KnowledgeBaseRebuildError(
            f"{label} 必须位于 {resolved_parent} 内: {resolved_path}"
        ) from exc
    return resolved_path


def _require_at_or_below(path: Path, root: Path, label: str) -> Path:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise KnowledgeBaseRebuildError(
            f"{label} 必须位于 {resolved_root} 内: {resolved_path}"
        ) from exc
    return resolved_path


def _require_disjoint(
    path: Path,
    protected_path: Path,
    label: str,
) -> None:
    resolved_path = path.resolve()
    resolved_protected = protected_path.resolve()
    overlaps = False
    try:
        resolved_path.relative_to(resolved_protected)
        overlaps = True
    except ValueError:
        pass
    try:
        resolved_protected.relative_to(resolved_path)
        overlaps = True
    except ValueError:
        pass
    if overlaps:
        raise KnowledgeBaseRebuildError(
            f"{label} 不得与 {resolved_protected} 存在祖先或后代重叠"
        )


def _metadata(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _metadata_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if value in (None, ""):
        value = _metadata(row).get(key)
    return str(value).strip() if value not in (None, "") else ""


def _has_manifest_metadata_field(
    metadata: Mapping[str, Any],
    field: str,
) -> bool:
    if str(metadata.get(field, "") or "").strip():
        return True
    if not field.startswith(("触发", "目标条款", "所需事实", "证明策略", "检索")):
        return False
    pattern = re.compile(rf"^{re.escape(field)}[1-9]\d*$")
    return any(
        isinstance(key, str)
        and pattern.fullmatch(key)
        and str(value or "").strip()
        for key, value in metadata.items()
    )


def build_manifest_payload(
    source_file: str,
    source_sha256: str,
    converted_at: str,
    catalog: Iterable[Mapping[str, Any]],
    failed_documents: Iterable[str] = (),
) -> Dict[str, Any]:
    """从已构建目录生成与审核端兼容的构建清单。"""
    rows = tuple(catalog)
    source_files = {
        _metadata_text(row, "source_file")
        for row in rows
        if _metadata_text(row, "source_file")
    }
    coverage: Dict[str, int] = {}
    for field in _MANIFEST_COVERAGE_FIELDS:
        count = sum(
            1
            for row in rows
            if _has_manifest_metadata_field(_metadata(row), field)
        )
        if count:
            coverage[field] = count
    return {
        "source_file": source_file,
        "source_sha256": source_sha256,
        "converted_at": converted_at,
        "documents": len(source_files),
        "chunks": len(rows),
        "failed_documents": list(failed_documents),
        "metadata_coverage": coverage,
        "regulation_trigger_schema_version": (
            ComplianceConstants.REGULATION_TRIGGER_SCHEMA_VERSION
        ),
    }


def build_identity_payload(
    version: str,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    catalog: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """生成运行时受控知识库身份。"""
    _validate_version(version)
    return {
        "schema_version": "1",
        "kb_version": version,
        "build_manifest_sha256": manifest_sha256,
        "source_file": manifest.get("source_file", ""),
        "source_sha256": manifest.get("source_sha256", ""),
        "documents": manifest.get("documents"),
        "chunks": manifest.get("chunks"),
        "catalog_sha256": stable_catalog_sha256(catalog),
    }


def validate_staged_catalog(
    version: str,
    catalog: Iterable[Mapping[str, Any]],
    bm25_nodes: Iterable[Mapping[str, Any]],
    stats: Mapping[str, int],
    expected_documents: Optional[int] = None,
    expected_chunks: Optional[int] = None,
) -> StagedValidation:
    """纯函数校验 staging 中两个索引与确定性身份是否一致。"""
    _validate_version(version)
    rows = tuple(catalog)
    bm25_rows = tuple(bm25_nodes)
    chunk_ids = tuple(str(row.get("id", "")).strip() for row in rows)
    bm25_ids = tuple(str(row.get("id", "")).strip() for row in bm25_rows)
    lancedb_fingerprint = stable_node_content_sha256(rows)
    bm25_fingerprint = stable_node_content_sha256(bm25_rows)
    source_files = {
        _metadata_text(row, "source_file")
        for row in rows
        if _metadata_text(row, "source_file")
    }
    errors = []
    if not rows:
        errors.append("LanceDB 目录为空")
    if any(not chunk_id for chunk_id in chunk_ids):
        errors.append("LanceDB 存在缺失顶层 ID 的 chunk")
    if len(set(chunk_ids)) != len(chunk_ids):
        errors.append("LanceDB 存在重复顶层 chunk ID")
    deterministic_count = sum(
        chunk_id.startswith("kb-chunk:")
        for chunk_id in chunk_ids
    )
    if deterministic_count != len(rows):
        errors.append(
            "LanceDB 存在非确定性 chunk ID: "
            f"{deterministic_count}/{len(rows)}"
        )
    wrong_versions = [
        index
        for index, row in enumerate(rows)
        if _metadata_text(row, "kb_version") != version
    ]
    if wrong_versions:
        errors.append(
            f"chunk 显式版本不一致: rows={wrong_versions[:5]}"
        )
    missing_source_paths = [
        index
        for index, row in enumerate(rows)
        if not _metadata_text(row, "source_path")
    ]
    if missing_source_paths:
        errors.append(
            f"chunk 缺少稳定来源路径: rows={missing_source_paths[:5]}"
        )
    if any(not chunk_id for chunk_id in bm25_ids):
        errors.append("BM25 存在缺失节点 ID 的 chunk")
    if len(set(bm25_ids)) != len(bm25_ids):
        errors.append("BM25 存在重复节点 ID")
    if len(bm25_rows) != len(rows):
        errors.append(
            "BM25/LanceDB 数量不一致: "
            f"bm25={len(bm25_rows)}, lance={len(rows)}"
        )
    if bm25_fingerprint != lancedb_fingerprint:
        errors.append("BM25/LanceDB 节点 ID 或正文不一致")
    for key in ("vector", "bm25"):
        if int(stats.get(key, 0)) != len(rows):
            errors.append(
                f"构建统计 {key} 不一致: "
                f"stats={stats.get(key, 0)}, actual={len(rows)}"
            )
    parsed = int(stats.get("parsed", 0))
    quality_passed = int(stats.get("quality_passed", 0))
    if parsed != quality_passed:
        errors.append(
            f"存在未通过质量检查的文档: parsed={parsed}, passed={quality_passed}"
        )
    if parsed != len(source_files):
        errors.append(
            f"构建文档数与目录不一致: parsed={parsed}, actual={len(source_files)}"
        )
    if expected_documents is not None and len(source_files) != expected_documents:
        errors.append(
            "文档数偏离受控基线: "
            f"actual={len(source_files)}, expected={expected_documents}"
        )
    if expected_chunks is not None and len(rows) != expected_chunks:
        errors.append(
            "chunk 数偏离受控基线: "
            f"actual={len(rows)}, expected={expected_chunks}"
        )
    # 构建阶段必须阻止不完整或越过受控枚举的触发配置。运行时仍会再次
    # 校验，以防外部或旧索引绕过标准 staging 流程。
    from lib.compliance.regulation_trigger_metadata import (
        RegulationTriggerMetadataError,
        parse_regulation_trigger_metadata,
    )
    for index, row in enumerate(rows):
        try:
            parse_regulation_trigger_metadata(_metadata(row))
        except RegulationTriggerMetadataError as exc:
            errors.append(f"法规触发规格非法: row={index}: {exc}")
    from lib.compliance.regulation_units import aggregate_regulation_units
    unit_validation = aggregate_regulation_units(rows, version)
    errors.extend(
        f"法规单元聚合校验失败: {error}"
        for error in unit_validation.errors
    )
    return StagedValidation(
        valid=not errors,
        version=version,
        document_count=len(source_files),
        chunk_count=len(rows),
        bm25_count=len(bm25_rows),
        deterministic_id_count=deterministic_count,
        lancedb_node_content_sha256=lancedb_fingerprint,
        bm25_node_content_sha256=bm25_fingerprint,
        errors=tuple(errors),
    )


def _validate_backup_catalog(
    version: str,
    catalog: Iterable[Mapping[str, Any]],
    bm25_nodes: Iterable[Mapping[str, Any]],
    expected_documents: Optional[int],
    expected_chunks: Optional[int],
) -> StagedValidation:
    """校验历史备份自洽性，不追溯要求旧数据具备新元数据。"""
    rows = tuple(catalog)
    bm25_rows = tuple(bm25_nodes)
    chunk_ids = tuple(str(row.get("id", "")).strip() for row in rows)
    bm25_ids = tuple(str(row.get("id", "")).strip() for row in bm25_rows)
    lancedb_fingerprint = stable_node_content_sha256(rows)
    bm25_fingerprint = stable_node_content_sha256(bm25_rows)
    source_files = {
        _metadata_text(row, "source_file")
        for row in rows
        if _metadata_text(row, "source_file")
    }
    errors = []
    if not rows:
        errors.append("备份 LanceDB 目录为空")
    if any(not chunk_id for chunk_id in chunk_ids):
        errors.append("备份 LanceDB 存在缺失顶层 ID 的 chunk")
    if len(set(chunk_ids)) != len(chunk_ids):
        errors.append("备份 LanceDB 存在重复顶层 chunk ID")
    if any(not chunk_id for chunk_id in bm25_ids):
        errors.append("备份 BM25 存在缺失节点 ID 的 chunk")
    if len(set(bm25_ids)) != len(bm25_ids):
        errors.append("备份 BM25 存在重复节点 ID")
    if len(bm25_rows) != len(rows):
        errors.append(
            "备份 BM25/LanceDB 数量不一致: "
            f"bm25={len(bm25_rows)}, lance={len(rows)}"
        )
    if bm25_fingerprint != lancedb_fingerprint:
        errors.append("备份 BM25/LanceDB 节点 ID 或正文不一致")
    if (
        expected_documents is not None
        and len(source_files) != expected_documents
    ):
        errors.append(
            "备份文档数与 manifest 不一致: "
            f"actual={len(source_files)}, expected={expected_documents}"
        )
    if expected_chunks is not None and len(rows) != expected_chunks:
        errors.append(
            "备份 chunk 数与 manifest 不一致: "
            f"actual={len(rows)}, expected={expected_chunks}"
        )
    deterministic_count = sum(
        chunk_id.startswith("kb-chunk:")
        for chunk_id in chunk_ids
    )
    return StagedValidation(
        valid=not errors,
        version=version,
        document_count=len(source_files),
        chunk_count=len(rows),
        bm25_count=len(bm25_rows),
        deterministic_id_count=deterministic_count,
        lancedb_node_content_sha256=lancedb_fingerprint,
        bm25_node_content_sha256=bm25_fingerprint,
        errors=tuple(errors),
    )


def load_catalog_rows(lancedb_dir: Path) -> Tuple[Dict[str, Any], ...]:
    """读取 LanceDB，并转换为受控身份使用的目录行。"""
    import lancedb  # type: ignore[import-untyped]

    database = lancedb.connect(str(lancedb_dir))
    table = database.open_table("regulations_vectors")
    rows = []
    for raw in table.to_arrow().to_pylist():
        metadata = raw.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, Mapping):
            metadata = {}
        rows.append({
            "id": raw.get("id", ""),
            "law_name": metadata.get("law_name", ""),
            "article_number": metadata.get("article_number", ""),
            "category": metadata.get("category", ""),
            "content": raw.get("text", ""),
            "source_file": metadata.get("source_file", ""),
            "source_path": metadata.get("source_path", ""),
            "section_path": metadata.get("section_path", ""),
            "hierarchy_path": metadata.get("hierarchy_path", ""),
            "metadata": dict(metadata),
        })
    return tuple(rows)


def load_bm25_node_rows(
    index_path: Path,
) -> Tuple[Dict[str, str], ...]:
    """读取 BM25 中用于与 LanceDB 对账的节点身份和正文。"""
    from .bm25_index import BM25Index

    index = BM25Index.load(index_path)
    if index is None:
        raise KnowledgeBaseRebuildError(f"BM25 索引不可读取: {index_path}")
    return index.list_identity_rows()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_live_expectations(
    references_dir: Path,
    version: str,
) -> Tuple[Optional[int], Optional[int]]:
    manifest_path = references_dir / f"{version}-build-manifest.json"
    if not manifest_path.is_file():
        return None, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    documents = manifest.get("documents")
    chunks = manifest.get("chunks")
    return (
        documents if isinstance(documents, int) else None,
        chunks if isinstance(chunks, int) else None,
    )


def stage_knowledge_base(request: StagingRequest) -> StagedBuildResult:
    """在独立目录完成 Excel 转换、索引构建、身份生成和验收。"""
    _validate_version(request.version)
    source_excel = request.source_excel.resolve()
    references = request.production_references_dir.resolve()
    kb_root = request.kb_root.resolve()
    live_version = kb_root / request.version
    stage_dir = _require_child(
        request.stage_dir,
        kb_root / ".staging",
        "staging 目录",
    )
    _require_disjoint(stage_dir, references, "staging 目录")
    _require_disjoint(stage_dir, live_version, "staging 目录")
    if not source_excel.is_file():
        raise KnowledgeBaseRebuildError(f"Excel 不存在: {source_excel}")
    if not references.is_dir():
        raise KnowledgeBaseRebuildError(f"references 不存在: {references}")
    if stage_dir.exists():
        raise KnowledgeBaseRebuildError(f"staging 目录已存在: {stage_dir}")
    expected_documents = request.expected_documents
    expected_chunks = request.expected_chunks
    if expected_documents is None or expected_chunks is None:
        live_documents, live_chunks = _read_live_expectations(
            references,
            request.version,
        )
        expected_documents = (
            expected_documents
            if expected_documents is not None
            else live_documents
        )
        expected_chunks = (
            expected_chunks
            if expected_chunks is not None
            else live_chunks
        )

    staged_references = stage_dir / "references"
    staged_version = stage_dir / request.version
    manifest_path = staged_references / f"{request.version}-build-manifest.json"
    identity_path = stage_dir / "kb_build_identity.json"
    report_path = stage_dir / "stage-report.json"
    try:
        stage_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(references, staged_references)
        staged_excel = staged_references / source_excel.name
        if source_excel != staged_excel.resolve():
            shutil.copy2(source_excel, staged_excel)

        from lib.doc_parser.kb.converter import convert_excel_to_markdown

        convert_excel_to_markdown(
            excel_path=str(staged_excel),
            output_dir=str(staged_references),
            skip_ocr=True,
            skip_name_llm=True,
        )

        from .builder import KnowledgeBuilder
        from .config import RAGConfig

        config = RAGConfig.create(
            regulations_dir=str(staged_references),
            vector_db_path=str(staged_version / "lancedb"),
        )
        stats = KnowledgeBuilder(
            config,
            kb_version=request.version,
        ).build(force_rebuild=True)
        catalog = load_catalog_rows(staged_version / "lancedb")
        bm25_nodes = load_bm25_node_rows(staged_version / "bm25_index.pkl")
        validation = validate_staged_catalog(
            version=request.version,
            catalog=catalog,
            bm25_nodes=bm25_nodes,
            stats=stats,
            expected_documents=expected_documents,
            expected_chunks=expected_chunks,
        )
        manifest = build_manifest_payload(
            source_file=source_excel.name,
            source_sha256=sha256_file(source_excel),
            converted_at=datetime.now(timezone.utc).isoformat(),
            catalog=catalog,
        )
        _write_json_atomic(manifest_path, manifest)
        identity = build_identity_payload(
            version=request.version,
            manifest=manifest,
            manifest_sha256=sha256_file(manifest_path),
            catalog=catalog,
        )
        _write_json_atomic(identity_path, identity)
        report = {
            "schema_version": "2",
            "version": request.version,
            "source_excel": source_excel.name,
            "source_sha256": sha256_file(source_excel),
            "expected_documents": expected_documents,
            "expected_chunks": expected_chunks,
            "stats": dict(stats),
            "validation": validation.to_dict(),
            "index_fingerprints": {
                "lancedb_node_content_sha256": (
                    validation.lancedb_node_content_sha256
                ),
                "bm25_node_content_sha256": (
                    validation.bm25_node_content_sha256
                ),
            },
            "manifest_sha256": sha256_file(manifest_path),
            "identity_sha256": sha256_file(identity_path),
        }
        _write_json_atomic(report_path, report)
        return StagedBuildResult(
            stage_dir=stage_dir,
            references_dir=staged_references,
            version_dir=staged_version,
            manifest_path=manifest_path,
            identity_path=identity_path,
            report_path=report_path,
            stats=dict(stats),
            validation=validation,
        )
    except Exception as exc:
        if stage_dir.exists():
            _write_json_atomic(
                stage_dir / "FAILED.json",
                {
                    "schema_version": "1",
                    "version": request.version,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        if isinstance(exc, KnowledgeBaseRebuildError):
            raise
        raise KnowledgeBaseRebuildError(
            f"staging 构建失败，生产 v5 未修改: {exc}"
        ) from exc


def validate_staged_build(
    stage_dir: Path,
    version: str,
) -> StagedBuildResult:
    """重新读取 staging 产物，防止构建后到切换前被修改。"""
    _validate_version(version)
    stage_dir = stage_dir.resolve()
    report_path = stage_dir / "stage-report.json"
    manifest_path = stage_dir / "references" / f"{version}-build-manifest.json"
    identity_path = stage_dir / "kb_build_identity.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeBaseRebuildError(f"staging 控制文件不可读取: {exc}") from exc
    if report.get("version") != version:
        raise KnowledgeBaseRebuildError("staging report 版本不一致")
    catalog = load_catalog_rows(stage_dir / version / "lancedb")
    bm25_nodes = load_bm25_node_rows(
        stage_dir / version / "bm25_index.pkl"
    )
    stats = report.get("stats")
    if not isinstance(stats, Mapping):
        raise KnowledgeBaseRebuildError("staging report 缺少构建统计")
    validation = validate_staged_catalog(
        version=version,
        catalog=catalog,
        bm25_nodes=bm25_nodes,
        stats={
            str(key): int(value)
            for key, value in stats.items()
            if isinstance(value, int)
        },
        expected_documents=report.get("expected_documents"),
        expected_chunks=report.get("expected_chunks"),
    )
    integrity_errors = list(validation.errors)
    recorded_fingerprints = report.get("index_fingerprints")
    actual_fingerprints = {
        "lancedb_node_content_sha256": (
            validation.lancedb_node_content_sha256
        ),
        "bm25_node_content_sha256": validation.bm25_node_content_sha256,
    }
    if recorded_fingerprints != actual_fingerprints:
        integrity_errors.append("索引节点指纹与 staging 验收记录不一致")
    manifest_sha = sha256_file(manifest_path)
    if report.get("manifest_sha256") != manifest_sha:
        integrity_errors.append("manifest 在 staging 验收后发生变化")
    if report.get("identity_sha256") != sha256_file(identity_path):
        integrity_errors.append("identity 在 staging 验收后发生变化")
    staged_excel = stage_dir / "references" / str(
        report.get("source_excel", "")
    )
    if not staged_excel.is_file():
        integrity_errors.append("staging 缺少构建所用 Excel")
    else:
        actual_source_sha = sha256_file(staged_excel)
        if report.get("source_sha256") != actual_source_sha:
            integrity_errors.append("Excel 在 staging 验收后发生变化")
        if manifest.get("source_sha256") != actual_source_sha:
            integrity_errors.append("manifest 的 Excel 指纹不一致")
    expected_identity = build_identity_payload(
        version=version,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        catalog=catalog,
    )
    if identity != expected_identity:
        integrity_errors.append("identity 与 staging 目录实际内容不一致")
    if manifest.get("documents") != validation.document_count:
        integrity_errors.append("manifest 文档数与 staging 目录不一致")
    if manifest.get("chunks") != validation.chunk_count:
        integrity_errors.append("manifest chunk 数与 staging 目录不一致")
    validation = StagedValidation(
        valid=not integrity_errors,
        version=validation.version,
        document_count=validation.document_count,
        chunk_count=validation.chunk_count,
        bm25_count=validation.bm25_count,
        deterministic_id_count=validation.deterministic_id_count,
        lancedb_node_content_sha256=(
            validation.lancedb_node_content_sha256
        ),
        bm25_node_content_sha256=validation.bm25_node_content_sha256,
        errors=tuple(dict.fromkeys(integrity_errors)),
    )
    return StagedBuildResult(
        stage_dir=stage_dir,
        references_dir=stage_dir / "references",
        version_dir=stage_dir / version,
        manifest_path=manifest_path,
        identity_path=identity_path,
        report_path=report_path,
        stats=dict(stats),
        validation=validation,
    )


def _replace_path(source: Path, target: Path) -> None:
    os.replace(source, target)


def _atomic_copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def _read_json_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeBaseRebuildError(f"{label}不可读取: {exc}") from exc
    if not isinstance(value, Mapping):
        raise KnowledgeBaseRebuildError(f"{label}必须是 JSON 对象")
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise KnowledgeBaseRebuildError(f"{label}缺失或格式错误")
    return text


def _validate_backup_for_restore(
    backup_dir: Path,
    version: str,
) -> _RollbackValidation:
    """验证备份来源及两套索引，防止恢复损坏或错代数据。"""
    backup_references = backup_dir / "references"
    backup_version = backup_dir / version
    manifest_path = backup_references / f"{version}-build-manifest.json"
    identity_path = backup_dir / "kb_build_identity.json"
    promotion_path = backup_dir / "promotion.json"
    if (
        not backup_references.is_dir()
        or not backup_version.is_dir()
        or not identity_path.is_file()
        or not manifest_path.is_file()
        or not promotion_path.is_file()
    ):
        raise KnowledgeBaseRebuildError("备份不完整、来源不明或已经恢复")

    promotion = _read_json_object(promotion_path, "promotion 记录")
    manifest = _read_json_object(manifest_path, "备份 manifest")
    identity = _read_json_object(identity_path, "备份 identity")
    if promotion.get("version") != version:
        raise KnowledgeBaseRebuildError("promotion 记录的知识库版本不一致")
    previous_manifest_sha = _require_sha256(
        promotion.get("previous_manifest_sha256"),
        "promotion.previous_manifest_sha256",
    )
    promoted_manifest_sha = _require_sha256(
        promotion.get("promoted_manifest_sha256"),
        "promotion.promoted_manifest_sha256",
    )
    actual_manifest_sha = sha256_file(manifest_path)
    errors = []
    if actual_manifest_sha != previous_manifest_sha:
        errors.append("备份 manifest 与 promotion 记录不一致")

    try:
        catalog = load_catalog_rows(backup_version / "lancedb")
        bm25_nodes = load_bm25_node_rows(
            backup_version / "bm25_index.pkl"
        )
    except Exception as exc:
        raise KnowledgeBaseRebuildError(
            f"备份索引不可读取: {exc}"
        ) from exc
    document_count = manifest.get("documents")
    chunk_count = manifest.get("chunks")
    if not isinstance(document_count, int) or document_count < 0:
        errors.append("备份 manifest 的 documents 无效")
        document_count = None
    if not isinstance(chunk_count, int) or chunk_count < 0:
        errors.append("备份 manifest 的 chunks 无效")
        chunk_count = None
    validation = _validate_backup_catalog(
        version=version,
        catalog=catalog,
        bm25_nodes=bm25_nodes,
        expected_documents=document_count,
        expected_chunks=chunk_count,
    )
    errors.extend(validation.errors)
    expected_identity = build_identity_payload(
        version=version,
        manifest=manifest,
        manifest_sha256=actual_manifest_sha,
        catalog=catalog,
    )
    if identity != expected_identity:
        errors.append("备份 identity 与 manifest/LanceDB 实际内容不一致")
    if errors:
        raise KnowledgeBaseRebuildError(
            f"备份验收失败: {list(dict.fromkeys(errors))}"
        )
    return _RollbackValidation(
        previous_manifest_sha256=previous_manifest_sha,
        promoted_manifest_sha256=promoted_manifest_sha,
    )


def promote_staged_knowledge_base(
    stage_dir: Path,
    kb_root: Path,
    production_references_dir: Path,
    identity_path: Path,
    expected_live_manifest_sha256: str,
    version: str = "v5",
    backup_root: Optional[Path] = None,
    service_stopped: bool = False,
) -> PromotionResult:
    """切换已验收 staging；任一步失败都会补偿恢复原 v5。"""
    if not service_stopped:
        raise KnowledgeBaseRebuildError(
            "切换前必须停止所有 API/worker，并显式确认 service_stopped"
        )
    _validate_version(version)
    kb_root = kb_root.resolve()
    stage_dir = _require_child(
        stage_dir,
        kb_root / ".staging",
        "staging 目录",
    )
    live_references = _require_child(
        production_references_dir,
        kb_root,
        "生产 references 目录",
    )
    live_version = kb_root / version
    _require_disjoint(stage_dir, live_references, "staging 目录")
    _require_disjoint(stage_dir, live_version, "staging 目录")
    staged = validate_staged_build(stage_dir, version)
    if not staged.validation.valid:
        raise KnowledgeBaseRebuildError(
            f"staging 验收失败: {list(staged.validation.errors)}"
        )
    live_identity = identity_path.resolve()
    if not live_references.is_dir() or not live_version.is_dir():
        raise KnowledgeBaseRebuildError("生产 references 或版本目录不存在")
    live_manifest = live_references / f"{version}-build-manifest.json"
    actual_live_manifest_sha = sha256_file(live_manifest)
    if actual_live_manifest_sha != expected_live_manifest_sha256:
        raise KnowledgeBaseRebuildError(
            "生产 manifest 已变化，拒绝基于过期基线切换"
        )
    if not live_identity.is_file():
        raise KnowledgeBaseRebuildError(
            f"生产受控 identity 不存在: {live_identity}"
        )
    backups = _require_at_or_below(
        backup_root or kb_root / "backups",
        kb_root / "backups",
        "备份根目录",
    )
    _require_disjoint(backups, live_references, "备份根目录")
    _require_disjoint(backups, live_version, "备份根目录")
    _require_disjoint(backups, stage_dir, "备份根目录")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backups / f"{version}-before-rebuild-{stamp}-{uuid.uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_references = backup_dir / "references"
    backup_version = backup_dir / version
    backup_identity = backup_dir / "kb_build_identity.json"
    shutil.copy2(live_identity, backup_identity)

    references_backed_up = False
    version_backed_up = False
    staged_references_installed = False
    staged_version_installed = False
    try:
        _replace_path(live_references, backup_references)
        references_backed_up = True
        _replace_path(live_version, backup_version)
        version_backed_up = True
        _replace_path(staged.references_dir, live_references)
        staged_references_installed = True
        _replace_path(staged.version_dir, live_version)
        staged_version_installed = True
        _atomic_copy_file(staged.identity_path, live_identity)
        promoted_manifest_sha = sha256_file(
            live_references / f"{version}-build-manifest.json"
        )
        _write_json_atomic(
            backup_dir / "promotion.json",
            {
                "schema_version": "1",
                "version": version,
                "previous_manifest_sha256": actual_live_manifest_sha,
                "promoted_manifest_sha256": promoted_manifest_sha,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return PromotionResult(
            version=version,
            backup_dir=backup_dir,
            previous_manifest_sha256=actual_live_manifest_sha,
            promoted_manifest_sha256=promoted_manifest_sha,
        )
    except Exception as exc:
        try:
            if staged_version_installed and live_version.exists():
                _replace_path(live_version, staged.version_dir)
            if staged_references_installed and live_references.exists():
                _replace_path(live_references, staged.references_dir)
            if version_backed_up and backup_version.exists():
                _replace_path(backup_version, live_version)
            if references_backed_up and backup_references.exists():
                _replace_path(backup_references, live_references)
            _atomic_copy_file(backup_identity, live_identity)
        except Exception as rollback_exc:
            raise KnowledgeBaseRebuildError(
                "切换失败且自动恢复失败；不要启动服务。"
                f" switch={exc}; rollback={rollback_exc}; backup={backup_dir}"
            ) from rollback_exc
        raise KnowledgeBaseRebuildError(
            f"切换失败，原 v5 已恢复: {exc}"
        ) from exc


def restore_knowledge_base_backup(
    backup_dir: Path,
    kb_root: Path,
    production_references_dir: Path,
    identity_path: Path,
    version: str = "v5",
    service_stopped: bool = False,
) -> PromotionResult:
    """一次性恢复 promote 产生的备份，同时保留被替换的新版本。"""
    if not service_stopped:
        raise KnowledgeBaseRebuildError(
            "恢复前必须停止所有 API/worker，并显式确认 service_stopped"
        )
    _validate_version(version)
    kb_root = kb_root.resolve()
    backup_dir = _require_child(
        backup_dir,
        kb_root / "backups",
        "备份目录",
    )
    backup_references = backup_dir / "references"
    backup_version = backup_dir / version
    backup_identity = backup_dir / "kb_build_identity.json"
    live_references = _require_child(
        production_references_dir,
        kb_root,
        "生产 references 目录",
    )
    live_version = kb_root / version
    live_identity = identity_path.resolve()
    _require_disjoint(backup_dir, live_references, "备份目录")
    _require_disjoint(backup_dir, live_version, "备份目录")
    if (
        not live_references.is_dir()
        or not live_version.is_dir()
        or not live_identity.is_file()
    ):
        raise KnowledgeBaseRebuildError("当前生产知识库不完整")
    validated_backup = _validate_backup_for_restore(backup_dir, version)
    live_manifest = live_references / f"{version}-build-manifest.json"
    if not live_manifest.is_file():
        raise KnowledgeBaseRebuildError("当前生产知识库缺少 manifest")
    current_sha = sha256_file(live_manifest)
    if current_sha != validated_backup.promoted_manifest_sha256:
        raise KnowledgeBaseRebuildError(
            "当前生产 manifest 已不是该次 promotion 的发布结果，"
            "拒绝使用旧备份覆盖更新后的知识库"
        )
    failed_live = backup_dir / "replaced-build"
    failed_live.mkdir(exist_ok=False)
    displaced_references = failed_live / "references"
    displaced_version = failed_live / version
    references_displaced = False
    version_displaced = False
    backup_references_installed = False
    backup_version_installed = False
    try:
        _replace_path(live_references, displaced_references)
        references_displaced = True
        _replace_path(live_version, displaced_version)
        version_displaced = True
        _replace_path(backup_references, live_references)
        backup_references_installed = True
        _replace_path(backup_version, live_version)
        backup_version_installed = True
        _atomic_copy_file(backup_identity, live_identity)
    except Exception as exc:
        try:
            if backup_version_installed and live_version.exists():
                _replace_path(live_version, backup_version)
            if backup_references_installed and live_references.exists():
                _replace_path(live_references, backup_references)
            if version_displaced and displaced_version.exists():
                _replace_path(displaced_version, live_version)
            if references_displaced and displaced_references.exists():
                _replace_path(displaced_references, live_references)
            failed_live.rmdir()
        except Exception as rollback_exc:
            raise KnowledgeBaseRebuildError(
                "备份恢复失败且补偿失败；不要启动服务。"
                f" restore={exc}; rollback={rollback_exc}; backup={backup_dir}"
            ) from rollback_exc
        raise KnowledgeBaseRebuildError(
            f"备份恢复失败，切换前状态已恢复: {exc}"
        ) from exc
    return PromotionResult(
        version=version,
        backup_dir=backup_dir,
        previous_manifest_sha256=current_sha,
        promoted_manifest_sha256=(
            validated_backup.previous_manifest_sha256
        ),
    )
