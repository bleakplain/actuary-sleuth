from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.compliance.regulation_retrieval import _validate_catalog_identity

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "compliance_audit" / "v1"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
SCHEMA_PATH = FIXTURE_DIR / "manifest.schema.json"
BASELINE_TEST_REPORT_PATH = FIXTURE_DIR / "baseline-test-report.json"
PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products")
KB_MANIFEST_PATH = Path("/Users/plain/work/actuary-assets/kb/references/v5-build-manifest.json")
KB_LANCEDB_PATH = Path("/Users/plain/work/actuary-assets/kb/v5/lancedb")


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def test_manifest_has_versioned_pending_cutover_gate() -> None:
    manifest = _load_json(MANIFEST_PATH)
    schema = _load_json(SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert manifest["schema_version"] == "1"
    assert manifest["dataset_id"] == "compliance-audit-v1"
    assert manifest["dataset_status"] == "pending"
    assert manifest["kb"]["version"] == "v5"
    assert manifest["annotations"]["version"] == "compliance-audit-v1-annotations-draft.1"
    assert manifest["annotations"]["status"] == "pending"
    assert set(manifest["annotations"]["fields"].values()) == {"pending"}
    assert manifest["actuary_review"]["status"] == "pending"
    assert manifest["actuary_review"]["reviewer"] is None
    assert manifest["actuary_review"]["reviewed_at"] is None
    assert manifest["cutover_gate"]["status"] == "blocked"


def test_manifest_freezes_all_23_real_product_fingerprints() -> None:
    products = _load_json(MANIFEST_PATH)["products"]

    assert len(products) == 23
    assert Counter(product["format"] for product in products) == {
        "doc": 9,
        "docx": 11,
        "pdf": 3,
    }
    assert len({product["sample_id"] for product in products}) == 23
    assert len({product["file_name"] for product in products}) == 23
    assert all(product["source_kind"] == "real" for product in products)
    assert all(product["annotation_status"] == "pending" for product in products)
    assert all(len(product["sha256"]) == 64 for product in products)


def test_missing_boundary_sources_are_explicitly_synthetic_and_pending() -> None:
    manifest = _load_json(MANIFEST_PATH)
    synthetic_cases = {
        case["case_id"]
        for case in manifest["candidate_boundary_cases"]
        if case["source_status"] == "synthetic_pending"
    }
    synthetic_samples = manifest["synthetic_boundary_samples"]

    assert synthetic_cases == {
        "short_health_without_renewal",
        "long_guaranteed_renewal_health",
        "annuity",
        "unrecognized_clause_title",
    }
    assert {sample["boundary_case"] for sample in synthetic_samples} == synthetic_cases
    assert all(sample["source_kind"] == "synthetic" for sample in synthetic_samples)
    assert all(sample["status"] == "pending" for sample in synthetic_samples)


def test_real_product_files_still_match_frozen_sha256() -> None:
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    products = _load_json(MANIFEST_PATH)["products"]

    for product in products:
        path = PRODUCTS_DIR / product["file_name"]
        assert path.is_file(), f"验收产品缺失: {path.name}"
        assert path.stat().st_size == product["size_bytes"]
        assert _sha256(path) == product["sha256"], f"验收产品已变化: {path.name}"


def test_v5_build_manifest_still_matches_frozen_identity() -> None:
    if not KB_MANIFEST_PATH.exists():
        pytest.skip(f"知识库清单不存在: {KB_MANIFEST_PATH}")
    fixture_kb = _load_json(MANIFEST_PATH)["kb"]
    actual_kb = _load_json(KB_MANIFEST_PATH)

    assert _sha256(KB_MANIFEST_PATH) == fixture_kb["build_manifest_sha256"]
    assert actual_kb["source_file"] == fixture_kb["source_file"]
    assert actual_kb["source_sha256"] == fixture_kb["source_sha256"]
    assert actual_kb["documents"] == fixture_kb["documents"]
    assert actual_kb["chunks"] == fixture_kb["chunks"]


def test_online_catalog_matches_controlled_v5_build_identity() -> None:
    if not KB_LANCEDB_PATH.exists():
        pytest.skip(f"知识库索引不存在: {KB_LANCEDB_PATH}")
    lancedb = pytest.importorskip("lancedb")
    table = lancedb.connect(str(KB_LANCEDB_PATH)).open_table(
        "regulations_vectors"
    )
    catalog = tuple(
        {
            "id": row.get("id", ""),
            "law_name": row["metadata"].get("law_name", ""),
            "article_number": row["metadata"].get("article_number", ""),
            "category": row["metadata"].get("category", ""),
            "content": row.get("text", ""),
            "source_file": row["metadata"].get("source_file", ""),
            "metadata": dict(row["metadata"]),
        }
        for row in table.to_arrow().to_pylist()
    )
    engine = SimpleNamespace(
        config=SimpleNamespace(vector_db_path=str(KB_LANCEDB_PATH))
    )

    assert _validate_catalog_identity(engine, catalog, "v5") == ()


def test_test_baseline_distinguishes_existing_failures_from_offline_gate() -> None:
    report = _load_json(BASELINE_TEST_REPORT_PATH)

    assert report["baseline_date"] == "2026-07-28"
    assert report["full_suite"]["status"] == "known_failures"
    assert report["full_suite"]["oracle"] is False
    assert report["full_suite"]["passed"] == 703
    assert report["full_suite"]["failed"] == 24
    assert report["full_suite"]["errors"] == 13
    assert report["phase0_offline_gate"]["status"] == "passed"
    assert report["phase0_offline_gate"]["uses_external_llm"] is False
    assert report["phase0_offline_gate"]["uses_network"] is False
    assert report["phase0_offline_gate"]["covers_real_products"] == 23
    assert report["phase0_offline_gate"]["covers_legacy_doc"] == 9
