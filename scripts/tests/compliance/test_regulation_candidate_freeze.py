from unittest.mock import patch

from lib.common.product_tags import ProductLine, ProductTags
from lib.compliance.checker import retrieve_audit_regulations_with_status


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


@patch("lib.compliance.checker._get_general_regulations", return_value=[])
@patch("lib.compliance.checker._list_registered_regulations", return_value=[])
@patch("lib.compliance.checker.get_engine")
def test_full_catalog_freeze_does_not_apply_final_top_k(
    mock_engine,
    _mock_registered,
    _mock_general,
):
    catalog = [
        _candidate("chunk-1", "第一条", "health"),
        _candidate("chunk-2", "第二条", "health"),
        _candidate("chunk-3", "第三条", "life"),
    ]
    mock_engine.return_value.search_by_metadata.return_value = catalog
    mock_engine.return_value.search_candidates.return_value = [catalog[0]]

    outcome = retrieve_audit_regulations_with_status(
        "续保",
        "健康险",
        ProductTags(line=ProductLine.HEALTH),
        ("renewal.general",),
        top_k=1,
    )

    assert [item.chunk_id for item in outcome.regulations] == ["chunk-1", "chunk-2"]
    assert len(outcome.regulation_units) == 2
    assert outcome.candidate_count == 3
    assert outcome.excluded_count == 1
    assert outcome.coverage is not None
    assert outcome.coverage.complete_candidate_freeze
    assert outcome.coverage.catalog_candidate_count == 3
    assert all(item.applicability_reasons for item in outcome.regulations)
    assert all(item.regulation_unit_id for item in outcome.regulations)


@patch("lib.compliance.checker._get_general_regulations", return_value=[])
@patch("lib.compliance.checker._list_registered_regulations", return_value=[])
@patch("lib.compliance.checker.get_engine")
def test_category_fallback_and_missing_registered_path_are_explicit(
    mock_engine,
    _mock_registered,
    _mock_general,
):
    catalog = [_candidate("chunk-1", "第一条", "health")]
    mock_engine.return_value.search_by_metadata.return_value = catalog
    mock_engine.return_value.search_candidates.return_value = []

    outcome = retrieve_audit_regulations_with_status(
        "健康保险",
        None,
        ProductTags(line=ProductLine.HEALTH),
    )

    assert outcome.degraded
    assert outcome.coverage is not None
    assert outcome.coverage.category_resolution == "product_tags"
    assert not outcome.coverage.registered_available
    assert "registered_retrieval" in outcome.coverage.uncovered_scopes
    assert any("产品标签回退" in warning for warning in outcome.warnings)
