from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.compliance.readiness import (
    KnowledgeBaseReadiness,
    ProductReadiness,
    ReadinessReport,
    inspect_knowledge_base_rows,
    scan_readiness,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "compliance_audit" / "v1"
KB_ROOT = Path("/Users/plain/work/actuary-assets/kb")
REFERENCES_DIR = KB_ROOT / "references"
PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products")
TOPIC_KEYWORDS = (
    Path(__file__).parents[2]
    / "lib"
    / "doc_parser"
    / "pd"
    / "data"
    / "clause_topic_keywords.json"
)


def _row(
    chunk_id: int,
    section: str,
    text: str,
    **metadata: object,
) -> dict[str, object]:
    return {
        "text": text,
        "metadata": {
            "chunk_id": chunk_id,
            "source_file": "regulation.md",
            "section_path": section,
            **metadata,
        },
    }


def test_inspect_knowledge_base_rows_counts_tag_semantics() -> None:
    rows = [
        _row(
            0,
            "第一条",
            "第一条独立内容。",
            适用标签="health,medical",
            适用标签语义="限定",
            条款主题="coverage.waiting_period",
        ),
        _row(
            1,
            "第二条",
            "第二条独立内容。",
            适用标签="health",
            适用标签语义="涉及",
            涉及标签="health",
        ),
        _row(2, "第三条", "第三条独立内容。", 适用标签="health"),
    ]

    result = inspect_knowledge_base_rows(rows, "v5", 1, 3)

    assert result.document_count == 1
    assert result.chunk_count == 3
    assert result.applicability_tagged_chunks == 3
    assert result.limited_tagged_chunks == 1
    assert result.involved_tagged_chunks == 1
    assert result.ambiguous_semantics_chunks == 1
    assert result.regulation_topic_tagged_chunks == 1
    assert result.manifest_matches
    assert not result.boundary_issues


def test_inspect_knowledge_base_rows_detects_cross_section_pollution() -> None:
    repeated = "这是错误复制到另一个法规条款的完整正文，长度足以触发边界检查。"
    overlap = "这是不应跨越不同法规条款边界的重复内容片段，扫描器必须把这种污染明确记录下来"
    rows = [
        _row(0, "第一条", repeated),
        _row(1, "第二条", repeated),
        _row(2, "第三条", f"第三条正文开头。{overlap}"),
        _row(3, "第四条", f"{overlap}第四条剩余正文。"),
    ]

    result = inspect_knowledge_base_rows(rows, "v5", 1, 4)

    assert [issue.issue_type for issue in result.boundary_issues] == [
        "duplicate_text_across_sections",
        "suffix_prefix_overlap_across_sections",
    ]
    assert result.blocking


def test_report_separates_known_gaps_from_blockers() -> None:
    kb = KnowledgeBaseReadiness(
        version="v5",
        document_count=25,
        chunk_count=171,
        expected_document_count=25,
        expected_chunk_count=171,
        applicability_tagged_chunks=125,
        limited_tagged_chunks=125,
        involved_tagged_chunks=0,
        ambiguous_semantics_chunks=0,
        regulation_topic_tagged_chunks=29,
        missing_section_path_chunks=0,
        boundary_issues=(),
    )
    products = ProductReadiness(
        document_count=23,
        parsed_document_count=23,
        extension_counts=((".doc", 9), (".docx", 11), (".pdf", 3)),
        subtype_counts=(("medical", 23),),
        clause_block_count=100,
        tagged_clause_block_count=31,
        clause_char_count=1000,
        tagged_clause_char_count=390,
        topic_code_count=27,
        keyword_mapping_count=47,
        parse_failures=(),
        unknown_subtype_files=(),
    )

    report = ReadinessReport(kb, products, ("涉及标签尚未落地",))

    assert report.status == "ready_with_known_gaps"
    assert report.to_dict()["status"] == "ready_with_known_gaps"


def test_live_readiness_matches_frozen_phase0_report() -> None:
    required_paths = (KB_ROOT / "v5" / "lancedb", REFERENCES_DIR, PRODUCTS_DIR)
    if not all(path.exists() for path in required_paths):
        pytest.skip("本地 v5 或真实产品目录不可用")
    expected = json.loads(
        (FIXTURE_DIR / "readiness-report.json").read_text(encoding="utf-8")
    )

    actual = scan_readiness(
        kb_root=KB_ROOT,
        references_dir=REFERENCES_DIR,
        product_dir=PRODUCTS_DIR,
        topic_keywords_path=TOPIC_KEYWORDS,
    )

    assert actual.to_dict() == expected
