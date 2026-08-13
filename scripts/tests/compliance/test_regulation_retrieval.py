import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lib.common.product_tags import ProductLine, ProductTags
from lib.compliance.regulation_retrieval import (
    _kb_trigger_manifest_identity,
    _stable_catalog_sha256,
    _validate_candidate_identity_conservation,
    _validate_catalog_identity,
    retrieve_regulation_candidates,
)
from lib.config import get_kb_version_dir
from lib.rag_engine.layered_retrieval import layer_regulation_candidates


def _candidate(chunk_id: str, article: str, tags: str) -> dict:
    return {
        "id": chunk_id,
        "law_name": "测试法规",
        "article_number": article,
        "source_file": "测试法规.md",
        "content": f"{article}正文",
        "metadata": {
            "kb_version": "v5",
            "source_file": "测试法规.md",
            "section_path": article,
            "chunk_id": int(chunk_id.rsplit("-", 1)[1]),
            "适用标签": tags,
            "条款主题": "renewal.general",
        },
    }


def _write_controlled_identity(
    tmp_path: Path,
    catalog: list[dict],
) -> tuple[SimpleNamespace, Path]:
    manifest = {
        "source_file": "fixture.xlsx",
        "source_sha256": "fixture-source-sha",
        "documents": len({
            candidate["metadata"]["source_file"]
            for candidate in catalog
        }),
        "chunks": len(catalog),
    }
    references = tmp_path / "v5" / "references"
    lancedb = tmp_path / "v5" / "lancedb"
    references.mkdir(parents=True)
    lancedb.mkdir()
    manifest_path = references / "v5-build-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    identity = {
        "schema_version": "1",
        "kb_version": "v5",
        "build_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        **manifest,
        "catalog_sha256": _stable_catalog_sha256(catalog),
    }
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps(identity, ensure_ascii=False),
        encoding="utf-8",
    )
    engine = SimpleNamespace(
        config=SimpleNamespace(vector_db_path=str(lancedb))
    )
    return engine, identity_path


def test_catalog_identity_detects_applicability_tag_tampering(
    tmp_path: Path,
) -> None:
    catalog = [_candidate("chunk-1", "第一条", "health")]
    engine, identity_path = _write_controlled_identity(tmp_path, catalog)
    tampered = [dict(catalog[0])]
    tampered[0]["metadata"] = {
        **catalog[0]["metadata"],
        "适用标签": "life",
    }

    errors = _validate_catalog_identity(
        engine,
        tuple(tampered),
        "v5",
        identity_path,
    )

    assert "知识库目录内容指纹与受控 v5 不一致" in errors


def test_trigger_manifest_identity_reads_schema_and_source_hash(
    tmp_path: Path,
) -> None:
    lancedb = tmp_path / "v5" / "lancedb"
    references = tmp_path / "references"
    lancedb.mkdir(parents=True)
    references.mkdir()
    (references / "v5-build-manifest.json").write_text(
        json.dumps({
            "regulation_trigger_schema_version": "1.0.0",
            "source_sha256": "source-sha",
        }),
        encoding="utf-8",
    )
    engine = SimpleNamespace(
        config=SimpleNamespace(vector_db_path=str(lancedb))
    )

    assert _kb_trigger_manifest_identity(engine, "v5") == (
        "1.0.0",
        "source-sha",
    )


def test_catalog_hash_normalizes_arrow_pandas_nullable_integer_drift() -> None:
    arrow_candidate = _candidate("chunk-1", "第一条", "health")
    arrow_candidate["metadata"].update({
        "prev_chunk_id": None,
        "next_chunk_id": 2,
    })
    pandas_candidate = _candidate("chunk-1", "第一条", "health")
    pandas_candidate["metadata"].update({
        "prev_chunk_id": math.nan,
        "next_chunk_id": 2.0,
    })

    assert _stable_catalog_sha256([arrow_candidate]) == _stable_catalog_sha256(
        [pandas_candidate]
    )


def test_real_v5_catalog_matches_controlled_identity() -> None:
    vector_path = Path(get_kb_version_dir()) / "v5" / "lancedb"
    manifest_path = vector_path.parent.parent / "references" / "v5-build-manifest.json"
    if not vector_path.exists() or not manifest_path.exists():
        pytest.skip("真实 v5 知识库不可用")

    import lancedb

    rows = []
    table = lancedb.connect(str(vector_path)).open_table("regulations_vectors")
    for row in table.to_pandas().to_dict(orient="records"):
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        rows.append({
            "id": row.get("id", ""),
            "law_name": metadata.get("law_name", ""),
            "article_number": metadata.get("article_number", ""),
            "category": metadata.get("category", ""),
            "content": row.get("text", ""),
            "source_file": metadata.get("source_file", ""),
            "hierarchy_path": metadata.get("hierarchy_path", ""),
            "doc_number": metadata.get("doc_number", ""),
            "effective_date": metadata.get("effective_date", ""),
            "issuing_authority": metadata.get("issuing_authority", ""),
            "metadata": dict(metadata),
        })
    engine = SimpleNamespace(
        config=SimpleNamespace(vector_db_path=str(vector_path))
    )

    assert _validate_catalog_identity(engine, tuple(rows), "v5") == ()


def test_catalog_identity_rejects_duplicate_global_ids(tmp_path: Path) -> None:
    first = _candidate("chunk-1", "第一条", "health")
    duplicate = _candidate("chunk-2", "第二条", "health")
    duplicate["id"] = first["id"]
    catalog = [first, duplicate]
    engine, identity_path = _write_controlled_identity(tmp_path, catalog)

    errors = _validate_catalog_identity(
        engine,
        tuple(catalog),
        "v5",
        identity_path,
    )

    assert any("重复全局 id" in error for error in errors)


def test_catalog_identity_rejects_explicit_mixed_chunk_version(
    tmp_path: Path,
) -> None:
    first = _candidate("chunk-1", "第一条", "health")
    second = _candidate("chunk-2", "第二条", "health")
    second["metadata"]["kb_version"] = "v4"
    catalog = [first, second]
    engine, identity_path = _write_controlled_identity(tmp_path, catalog)

    errors = _validate_catalog_identity(
        engine,
        tuple(catalog),
        "v5",
        identity_path,
    )

    assert any("显式版本与受控版本不一致" in error for error in errors)


def test_candidate_identity_conservation_detects_merge_data_loss() -> None:
    catalog = [
        _candidate("chunk-1", "第一条", "health"),
        _candidate("chunk-2", "第二条", "health"),
    ]
    merged = catalog[:1]
    layered = layer_regulation_candidates(
        merged,
        ProductTags(line=ProductLine.HEALTH),
        top_k=None,
    )

    errors = _validate_candidate_identity_conservation(
        catalog,
        merged,
        layered,
    )

    assert any("merge 后不守恒" in error for error in errors)


@patch(
    "lib.compliance.regulation_retrieval._validate_catalog_identity",
    return_value=(),
)
@patch("lib.compliance.regulation_retrieval.get_engine")
def test_full_catalog_is_not_truncated_by_semantic_top_k(
    mock_engine,
    _mock_identity,
) -> None:
    catalog = [
        _candidate("chunk-1", "第一条", "health"),
        _candidate("chunk-2", "第二条", "health"),
        _candidate("chunk-3", "第三条", "life"),
    ]
    engine = MagicMock()
    engine.search_by_metadata.return_value = catalog
    engine.search_candidates.return_value = [catalog[0]]
    mock_engine.return_value = engine

    outcome = retrieve_regulation_candidates(
        "续保",
        "健康险",
        ProductTags(line=ProductLine.HEALTH),
        ("renewal.general",),
        semantic_top_k=1,
    )

    assert [item.chunk_id for item in outcome.regulations] == [
        "chunk-1",
        "chunk-2",
    ]
    assert len(outcome.regulation_units) == 2
    assert outcome.candidate_count == 2
    assert outcome.excluded_count == 1
    assert outcome.excluded_regulation_units[0].law_name == "测试法规"
    assert outcome.excluded_regulation_units[0].excluded_by == ("line",)
    assert outcome.coverage is not None
    assert outcome.coverage.complete_candidate_freeze
    assert outcome.kb_catalog_sha256 == _stable_catalog_sha256(catalog)
    assert engine.search_by_metadata.call_count == 1


@patch(
    "lib.compliance.regulation_retrieval._validate_catalog_identity",
    return_value=("知识库目录内容指纹与受控 v5 不一致",),
)
@patch("lib.compliance.regulation_retrieval.get_engine")
def test_catalog_identity_mismatch_makes_candidate_freeze_incomplete(
    mock_engine,
    _mock_identity,
) -> None:
    catalog = [_candidate("chunk-1", "第一条", "health")]
    engine = MagicMock()
    engine.search_by_metadata.return_value = catalog
    engine.search_candidates.return_value = catalog
    mock_engine.return_value = engine

    outcome = retrieve_regulation_candidates(
        "等待期",
        "健康险",
        ProductTags(line=ProductLine.HEALTH),
    )

    assert outcome.coverage is not None
    assert not outcome.coverage.complete_candidate_freeze
    assert "kb_build_identity" in outcome.coverage.uncovered_scopes


@patch(
    "lib.compliance.regulation_retrieval._validate_catalog_identity",
    return_value=(),
)
@patch("lib.compliance.regulation_retrieval.get_engine")
def test_mixed_chunk_applicability_keeps_complete_regulation_unit(
    mock_engine,
    _mock_identity,
) -> None:
    health = _candidate("chunk-1", "第一条", "health")
    life = _candidate("chunk-2", "第一条", "life")
    engine = MagicMock()
    engine.search_by_metadata.return_value = [health, life]
    engine.search_candidates.return_value = [health]
    mock_engine.return_value = engine

    outcome = retrieve_regulation_candidates(
        "等待期",
        "健康险",
        ProductTags(line=ProductLine.HEALTH),
    )

    assert len(outcome.regulation_units) == 1
    assert outcome.regulation_units[0].chunk_ids == ("chunk-1", "chunk-2")
    assert outcome.regulation_units[0].applicability_status == "indeterminate"
    assert outcome.excluded_count == 0


@patch(
    "lib.compliance.regulation_retrieval._validate_catalog_identity",
    return_value=(),
)
@patch("lib.compliance.regulation_retrieval.get_engine")
def test_excluded_chunk_missing_stable_identity_blocks_complete_freeze(
    mock_engine,
    _mock_identity,
) -> None:
    invalid = _candidate("chunk-1", "", "life")
    invalid["source_file"] = ""
    invalid["metadata"]["source_file"] = ""
    invalid["metadata"]["section_path"] = ""
    engine = MagicMock()
    engine.search_by_metadata.return_value = [invalid]
    engine.search_candidates.return_value = []
    mock_engine.return_value = engine

    outcome = retrieve_regulation_candidates(
        "query",
        "健康险",
        ProductTags(line=ProductLine.HEALTH),
    )

    assert outcome.excluded_count == 1
    assert outcome.coverage is not None
    assert not outcome.coverage.complete_candidate_freeze
    assert "regulation_unit_identity" in outcome.coverage.uncovered_scopes


@patch("lib.compliance.regulation_retrieval.get_engine", return_value=None)
def test_missing_engine_is_explicitly_degraded(_mock_engine) -> None:
    outcome = retrieve_regulation_candidates(
        "query",
        "健康险",
        ProductTags(),
    )

    assert outcome.regulations == ()
    assert outcome.regulation_units == ()
    assert outcome.kb_catalog_sha256 == ""
    assert outcome.degraded
    assert outcome.coverage is not None
    assert not outcome.coverage.complete_candidate_freeze
    assert "regulation_catalog" in outcome.coverage.uncovered_scopes
