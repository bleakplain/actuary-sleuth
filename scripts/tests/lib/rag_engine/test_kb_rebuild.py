from __future__ import annotations

import json
from pathlib import Path

import pytest
from llama_index.core.schema import TextNode

from lib.rag_engine.kb_identity import sha256_file
from lib.rag_engine.kb_rebuild import (
    KnowledgeBaseRebuildError,
    StagedBuildResult,
    StagedValidation,
    StagingRequest,
    build_identity_payload,
    build_manifest_payload,
    promote_staged_knowledge_base,
    restore_knowledge_base_backup,
    stage_knowledge_base,
    validate_staged_build,
    validate_staged_catalog,
)
from lib.rag_engine.bm25_index import BM25Index
from lib.rag_engine.builder import KnowledgeBuilder
from lib.rag_engine.config import RAGConfig


def _catalog_row(
    chunk_id: str,
    chunk_index: int,
    source_file: str = "测试法规.md",
) -> dict:
    return {
        "id": chunk_id,
        "content": f"第{chunk_index}条正文",
        "source_file": source_file,
        "metadata": {
            "kb_version": "v5",
            "source_file": source_file,
            "source_path": f"00_保险法/{source_file}",
            "law_name": "测试法规",
            "article_number": f"第{chunk_index}条检核规则",
            "section_path": f"第{chunk_index}条检核规则",
            "chunk_id": chunk_index,
            "适用标签": "health",
        },
    }


def _legacy_catalog_row() -> dict:
    row = _catalog_row("legacy-random-id", 1)
    del row["metadata"]["kb_version"]
    del row["metadata"]["source_path"]
    return row


def _write_manifest(path: Path, marker: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "source_file": "fixture.xlsx",
            "source_sha256": marker,
            "documents": 1,
            "chunks": 1,
        }),
        encoding="utf-8",
    )
    return sha256_file(path)


def _fake_staged_result(stage_dir: Path) -> StagedBuildResult:
    return StagedBuildResult(
        stage_dir=stage_dir,
        references_dir=stage_dir / "references",
        version_dir=stage_dir / "v5",
        manifest_path=stage_dir / "references" / "v5-build-manifest.json",
        identity_path=stage_dir / "kb_build_identity.json",
        report_path=stage_dir / "stage-report.json",
        stats={"parsed": 1, "quality_passed": 1, "vector": 1, "bm25": 1},
        validation=StagedValidation(
            valid=True,
            version="v5",
            document_count=1,
            chunk_count=1,
            bm25_count=1,
            deterministic_id_count=1,
        ),
    )


def _prepare_switch_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    kb_root = tmp_path / "kb"
    references = kb_root / "references"
    live_version = kb_root / "v5"
    stage_dir = kb_root / ".staging" / "v5-test"
    identity_path = tmp_path / "repo" / "kb_build_identity.json"
    references.mkdir(parents=True)
    live_version.mkdir()
    (references / "old.md").write_text("old references", encoding="utf-8")
    (live_version / "old.index").write_text("old index", encoding="utf-8")
    old_manifest_sha = _write_manifest(
        references / "v5-build-manifest.json",
        "old",
    )
    identity_path.parent.mkdir()
    old_manifest = json.loads(
        (references / "v5-build-manifest.json").read_text(encoding="utf-8")
    )
    identity_path.write_text(
        json.dumps(build_identity_payload(
            version="v5",
            manifest=old_manifest,
            manifest_sha256=old_manifest_sha,
            catalog=(_legacy_catalog_row(),),
        )),
        encoding="utf-8",
    )

    (stage_dir / "references").mkdir(parents=True)
    (stage_dir / "v5").mkdir()
    (stage_dir / "references" / "new.md").write_text(
        "new references",
        encoding="utf-8",
    )
    _write_manifest(
        stage_dir / "references" / "v5-build-manifest.json",
        "new",
    )
    (stage_dir / "v5" / "new.index").write_text(
        "new index",
        encoding="utf-8",
    )
    (stage_dir / "kb_build_identity.json").write_text(
        "new identity",
        encoding="utf-8",
    )
    return kb_root, references, stage_dir, identity_path, old_manifest_sha


def _patch_backup_index_loaders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = (_legacy_catalog_row(),)
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.load_catalog_rows",
        lambda _: catalog,
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.load_bm25_node_rows",
        lambda _: (
            {
                "id": catalog[0]["id"],
                "content": catalog[0]["content"],
            },
        ),
    )


def test_manifest_and_identity_are_derived_from_catalog():
    catalog = [
        _catalog_row("kb-chunk:first", 1),
        _catalog_row("kb-chunk:second", 2, "第二法规.md"),
    ]

    manifest = build_manifest_payload(
        source_file="fixture.xlsx",
        source_sha256="source-sha",
        converted_at="2026-07-28T00:00:00+00:00",
        catalog=catalog,
    )
    identity = build_identity_payload(
        version="v5",
        manifest=manifest,
        manifest_sha256="manifest-sha",
        catalog=catalog,
    )

    assert manifest["documents"] == 2
    assert manifest["chunks"] == 2
    assert manifest["metadata_coverage"]["适用标签"] == 2
    assert identity["kb_version"] == "v5"
    assert identity["catalog_sha256"]


def test_staged_validation_rejects_duplicate_or_random_ids():
    catalog = [
        _catalog_row("random-id", 1),
        _catalog_row("random-id", 2),
    ]

    result = validate_staged_catalog(
        version="v5",
        catalog=catalog,
        bm25_nodes=catalog,
        stats={
            "parsed": 1,
            "quality_passed": 1,
            "vector": 2,
            "bm25": 2,
        },
        expected_documents=1,
        expected_chunks=2,
    )

    assert not result.valid
    assert any("重复" in error for error in result.errors)
    assert any("非确定性" in error for error in result.errors)


def test_staged_validation_still_rejects_legacy_metadata():
    catalog = [_legacy_catalog_row()]

    result = validate_staged_catalog(
        version="v5",
        catalog=catalog,
        bm25_nodes=catalog,
        stats={
            "parsed": 1,
            "quality_passed": 1,
            "vector": 1,
            "bm25": 1,
        },
        expected_documents=1,
        expected_chunks=1,
    )

    assert not result.valid
    assert any("非确定性" in error for error in result.errors)
    assert any("版本不一致" in error for error in result.errors)
    assert any("稳定来源路径" in error for error in result.errors)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("id", "kb-chunk:replacement"),
        ("content", "同数量但被替换的正文"),
    ],
)
def test_staged_validation_rejects_same_count_bm25_node_substitution(
    field: str,
    replacement: str,
):
    catalog = [
        _catalog_row("kb-chunk:first", 1),
        _catalog_row("kb-chunk:second", 2),
    ]
    bm25_nodes = [
        {"id": row["id"], "content": row["content"]}
        for row in catalog
    ]
    bm25_nodes[1][field] = replacement

    result = validate_staged_catalog(
        version="v5",
        catalog=catalog,
        bm25_nodes=bm25_nodes,
        stats={
            "parsed": 1,
            "quality_passed": 1,
            "vector": 2,
            "bm25": 2,
        },
        expected_documents=1,
        expected_chunks=2,
    )

    assert result.bm25_count == result.chunk_count == 2
    assert not result.valid
    assert any("节点 ID 或正文不一致" in error for error in result.errors)


def test_staged_revalidation_rejects_same_count_bm25_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    stage_dir = tmp_path / "kb" / ".staging" / "v5-test"
    references = stage_dir / "references"
    version_dir = stage_dir / "v5"
    references.mkdir(parents=True)
    version_dir.mkdir()
    excel = references / "fixture.xlsx"
    excel.write_text("source", encoding="utf-8")
    catalog = [
        _catalog_row("kb-chunk:first", 1),
        _catalog_row("kb-chunk:second", 2),
    ]
    original_nodes = [
        TextNode(id_=row["id"], text=row["content"])
        for row in catalog
    ]
    bm25_path = version_dir / "bm25_index.pkl"
    BM25Index.build(original_nodes, bm25_path)
    original_bm25 = [
        {"id": node.node_id, "content": node.text}
        for node in original_nodes
    ]
    stats = {
        "parsed": 1,
        "quality_passed": 1,
        "vector": 2,
        "bm25": 2,
    }
    validation = validate_staged_catalog(
        version="v5",
        catalog=catalog,
        bm25_nodes=original_bm25,
        stats=stats,
        expected_documents=1,
        expected_chunks=2,
    )
    manifest = build_manifest_payload(
        source_file=excel.name,
        source_sha256=sha256_file(excel),
        converted_at="2026-07-28T00:00:00+00:00",
        catalog=catalog,
    )
    manifest_path = references / "v5-build-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    identity = build_identity_payload(
        version="v5",
        manifest=manifest,
        manifest_sha256=sha256_file(manifest_path),
        catalog=catalog,
    )
    identity_path = stage_dir / "kb_build_identity.json"
    identity_path.write_text(
        json.dumps(identity, ensure_ascii=False),
        encoding="utf-8",
    )
    report = {
        "schema_version": "2",
        "version": "v5",
        "source_excel": excel.name,
        "source_sha256": sha256_file(excel),
        "expected_documents": 1,
        "expected_chunks": 2,
        "stats": stats,
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
    (stage_dir / "stage-report.json").write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.load_catalog_rows",
        lambda _: tuple(catalog),
    )

    tampered_nodes = [
        TextNode(id_="kb-chunk:first", text="第1条正文"),
        TextNode(id_="kb-chunk:second", text="同数量但被替换的正文"),
    ]
    BM25Index.build(tampered_nodes, bm25_path)
    result = validate_staged_build(stage_dir, "v5")

    assert result.validation.bm25_count == result.validation.chunk_count == 2
    assert not result.validation.valid
    assert any(
        "节点 ID 或正文不一致" in error
        for error in result.validation.errors
    )
    assert any(
        "指纹与 staging 验收记录不一致" in error
        for error in result.validation.errors
    )


def test_builder_propagates_version_and_relative_source_path(
    tmp_path: Path,
):
    references = tmp_path / "references"
    regulation = references / "00_保险法" / "测试法规.md"
    regulation.parent.mkdir(parents=True)
    regulation.write_text(
        """---
regulation: 测试法规
---

# 测试法规

## 第1条检核规则

测试正文。
""",
        encoding="utf-8",
    )
    builder = KnowledgeBuilder(
        RAGConfig.create(
            regulations_dir=str(references),
            vector_db_path=str(tmp_path / "v5" / "lancedb"),
        ),
    )

    first = builder.chunk(builder.parse())
    second = builder.chunk(builder.parse())

    assert first[0].node_id == second[0].node_id
    assert first[0].metadata["kb_version"] == "v5"
    assert first[0].metadata["source_path"] == "00_保险法/测试法规.md"


def test_staging_failure_never_changes_live_v5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root = tmp_path / "kb"
    references = kb_root / "references"
    live_version = kb_root / "v5"
    references.mkdir(parents=True)
    live_version.mkdir()
    excel = references / "fixture.xlsx"
    excel.write_text("source", encoding="utf-8")
    live_rule = references / "00_保险法" / "rule.md"
    live_rule.parent.mkdir()
    live_rule.write_text("live rule", encoding="utf-8")
    live_index = live_version / "index.sentinel"
    live_index.write_text("live index", encoding="utf-8")
    _write_manifest(references / "v5-build-manifest.json", "old")

    def fail_conversion(*args, **kwargs):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(
        "lib.doc_parser.kb.converter.convert_excel_to_markdown",
        fail_conversion,
    )

    stage_dir = kb_root / ".staging" / "failed"
    with pytest.raises(KnowledgeBaseRebuildError, match="生产 v5 未修改"):
        stage_knowledge_base(StagingRequest(
            source_excel=excel,
            production_references_dir=references,
            kb_root=kb_root,
            stage_dir=stage_dir,
        ))

    assert live_rule.read_text(encoding="utf-8") == "live rule"
    assert live_index.read_text(encoding="utf-8") == "live index"
    assert (stage_dir / "FAILED.json").is_file()


def test_stage_dir_must_be_below_reserved_staging_root(
    tmp_path: Path,
):
    kb_root = tmp_path / "kb"
    references = kb_root / "references"
    references.mkdir(parents=True)
    excel = tmp_path / "fixture.xlsx"
    excel.write_text("source", encoding="utf-8")

    with pytest.raises(KnowledgeBaseRebuildError, match=r"\.staging"):
        stage_knowledge_base(StagingRequest(
            source_excel=excel,
            production_references_dir=references,
            kb_root=kb_root,
            stage_dir=kb_root / "v5" / "unsafe-stage",
        ))

    assert not (kb_root / "v5").exists()


def test_stage_dir_cannot_overlap_live_references(
    tmp_path: Path,
):
    kb_root = tmp_path / "kb"
    references = kb_root / ".staging"
    references.mkdir(parents=True)
    excel = tmp_path / "fixture.xlsx"
    excel.write_text("source", encoding="utf-8")

    with pytest.raises(KnowledgeBaseRebuildError, match="祖先或后代重叠"):
        stage_knowledge_base(StagingRequest(
            source_excel=excel,
            production_references_dir=references,
            kb_root=kb_root,
            stage_dir=references / "v5-test",
        ))

    assert not (references / "v5-test").exists()


def test_index_build_failure_never_drops_live_v5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root = tmp_path / "kb"
    references = kb_root / "references"
    live_version = kb_root / "v5"
    references.mkdir(parents=True)
    live_version.mkdir()
    excel = references / "fixture.xlsx"
    excel.write_text("source", encoding="utf-8")
    live_rule = references / "00_保险法" / "rule.md"
    live_rule.parent.mkdir()
    live_rule.write_text("live rule", encoding="utf-8")
    live_index = live_version / "index.sentinel"
    live_index.write_text("live index", encoding="utf-8")
    _write_manifest(references / "v5-build-manifest.json", "old")
    monkeypatch.setattr(
        "lib.doc_parser.kb.converter.convert_excel_to_markdown",
        lambda *args, **kwargs: None,
    )

    def fail_build(*args, **kwargs):
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(KnowledgeBuilder, "build", fail_build)

    with pytest.raises(KnowledgeBaseRebuildError, match="生产 v5 未修改"):
        stage_knowledge_base(StagingRequest(
            source_excel=excel,
            production_references_dir=references,
            kb_root=kb_root,
            stage_dir=kb_root / ".staging" / "failed-build",
        ))

    assert live_rule.read_text(encoding="utf-8") == "live rule"
    assert live_index.read_text(encoding="utf-8") == "live index"


def test_legacy_backup_without_current_metadata_can_be_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda *args, **kwargs: _fake_staged_result(stage_dir),
    )
    _patch_backup_index_loaders(monkeypatch)

    promoted = promote_staged_knowledge_base(
        stage_dir=stage_dir,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        expected_live_manifest_sha256=old_sha,
        service_stopped=True,
    )

    assert (references / "new.md").is_file()
    assert (kb_root / "v5" / "new.index").is_file()
    assert (promoted.backup_dir / "references" / "old.md").is_file()
    assert (promoted.backup_dir / "v5" / "old.index").is_file()
    assert identity_path.read_text(encoding="utf-8") == "new identity"

    restored = restore_knowledge_base_backup(
        backup_dir=promoted.backup_dir,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        service_stopped=True,
    )

    assert (references / "old.md").is_file()
    assert (kb_root / "v5" / "old.index").is_file()
    assert (
        promoted.backup_dir / "replaced-build" / "references" / "new.md"
    ).is_file()
    assert restored.promoted_manifest_sha256 == old_sha
    assert json.loads(
        identity_path.read_text(encoding="utf-8")
    )["source_sha256"] == "old"


def test_failed_promote_restores_live_v5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda *args, **kwargs: _fake_staged_result(stage_dir),
    )
    from lib.rag_engine import kb_rebuild

    real_replace = kb_rebuild._replace_path
    calls = {"count": 0}

    def fail_fourth_replace(source: Path, target: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 4:
            raise OSError("simulated switch failure")
        real_replace(source, target)

    monkeypatch.setattr(kb_rebuild, "_replace_path", fail_fourth_replace)

    with pytest.raises(KnowledgeBaseRebuildError, match="原 v5 已恢复"):
        promote_staged_knowledge_base(
            stage_dir=stage_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            expected_live_manifest_sha256=old_sha,
            service_stopped=True,
        )

    assert (references / "old.md").is_file()
    assert (kb_root / "v5" / "old.index").is_file()
    assert json.loads(
        identity_path.read_text(encoding="utf-8")
    )["source_sha256"] == "old"


def test_failed_rollback_preserves_current_build_and_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda *args, **kwargs: _fake_staged_result(stage_dir),
    )
    _patch_backup_index_loaders(monkeypatch)
    promoted = promote_staged_knowledge_base(
        stage_dir=stage_dir,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        expected_live_manifest_sha256=old_sha,
        service_stopped=True,
    )
    from lib.rag_engine import kb_rebuild

    real_replace = kb_rebuild._replace_path
    calls = {"count": 0}

    def fail_fourth_replace(source: Path, target: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 4:
            raise OSError("simulated restore failure")
        real_replace(source, target)

    monkeypatch.setattr(kb_rebuild, "_replace_path", fail_fourth_replace)

    with pytest.raises(KnowledgeBaseRebuildError, match="切换前状态已恢复"):
        restore_knowledge_base_backup(
            backup_dir=promoted.backup_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            service_stopped=True,
        )

    assert (references / "new.md").is_file()
    assert (kb_root / "v5" / "new.index").is_file()
    assert (promoted.backup_dir / "references" / "old.md").is_file()
    assert (promoted.backup_dir / "v5" / "old.index").is_file()
    assert identity_path.read_text(encoding="utf-8") == "new identity"


def test_promote_requires_explicit_service_stop_confirmation(
    tmp_path: Path,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )

    with pytest.raises(KnowledgeBaseRebuildError, match="停止"):
        promote_staged_knowledge_base(
            stage_dir=stage_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            expected_live_manifest_sha256=old_sha,
        )


def test_promote_rejects_backup_root_outside_reserved_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda *args, **kwargs: _fake_staged_result(stage_dir),
    )
    unsafe_backup_root = kb_root / "v5" / "backups"

    with pytest.raises(KnowledgeBaseRebuildError, match="备份根目录 必须位于"):
        promote_staged_knowledge_base(
            stage_dir=stage_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            expected_live_manifest_sha256=old_sha,
            backup_root=unsafe_backup_root,
            service_stopped=True,
        )

    assert (references / "old.md").is_file()
    assert not unsafe_backup_root.exists()


def test_rollback_rejects_tampered_backup_index_before_live_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, stage_dir, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda *args, **kwargs: _fake_staged_result(stage_dir),
    )
    promoted = promote_staged_knowledge_base(
        stage_dir=stage_dir,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        expected_live_manifest_sha256=old_sha,
        service_stopped=True,
    )
    catalog = (_legacy_catalog_row(),)
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.load_catalog_rows",
        lambda _: catalog,
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.load_bm25_node_rows",
        lambda _: (
            {
                "id": catalog[0]["id"],
                "content": "被篡改的正文",
            },
        ),
    )

    with pytest.raises(
        KnowledgeBaseRebuildError,
        match="节点 ID 或正文不一致",
    ):
        restore_knowledge_base_backup(
            backup_dir=promoted.backup_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            service_stopped=True,
        )

    assert (references / "new.md").is_file()
    assert (kb_root / "v5" / "new.index").is_file()
    assert not (promoted.backup_dir / "replaced-build").exists()


def test_old_backup_cannot_overwrite_a_later_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    kb_root, references, first_stage, identity_path, old_sha = (
        _prepare_switch_fixture(tmp_path)
    )
    monkeypatch.setattr(
        "lib.rag_engine.kb_rebuild.validate_staged_build",
        lambda stage_dir, *args, **kwargs: _fake_staged_result(
            Path(stage_dir)
        ),
    )
    _patch_backup_index_loaders(monkeypatch)
    first = promote_staged_knowledge_base(
        stage_dir=first_stage,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        expected_live_manifest_sha256=old_sha,
        service_stopped=True,
    )

    second_stage = kb_root / ".staging" / "v5-test-2"
    (second_stage / "references").mkdir(parents=True)
    (second_stage / "v5").mkdir()
    (second_stage / "references" / "newer.md").write_text(
        "newer references",
        encoding="utf-8",
    )
    _write_manifest(
        second_stage / "references" / "v5-build-manifest.json",
        "newer",
    )
    (second_stage / "v5" / "newer.index").write_text(
        "newer index",
        encoding="utf-8",
    )
    (second_stage / "kb_build_identity.json").write_text(
        "newer identity",
        encoding="utf-8",
    )
    promote_staged_knowledge_base(
        stage_dir=second_stage,
        kb_root=kb_root,
        production_references_dir=references,
        identity_path=identity_path,
        expected_live_manifest_sha256=first.promoted_manifest_sha256,
        service_stopped=True,
    )

    with pytest.raises(
        KnowledgeBaseRebuildError,
        match="拒绝使用旧备份",
    ):
        restore_knowledge_base_backup(
            backup_dir=first.backup_dir,
            kb_root=kb_root,
            production_references_dir=references,
            identity_path=identity_path,
            service_stopped=True,
        )

    assert (references / "newer.md").is_file()
    assert (kb_root / "v5" / "newer.index").is_file()
    assert not (first.backup_dir / "replaced-build").exists()
