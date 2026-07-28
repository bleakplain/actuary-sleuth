from lib.compliance.regulation_units import (
    aggregate_regulation_units,
    build_regulation_unit_id,
)


def _chunk(
    chunk_id: str,
    article: str = "第十条",
    content: str = "法规正文",
    chunk_index: int = 0,
) -> dict:
    return {
        "id": chunk_id,
        "law_name": "测试法规",
        "article_number": article,
        "source_file": "测试法规.md",
        "content": content,
        "applicability_status": "applicable",
        "applicability_reasons": ["line: health 命中 ['health']"],
        "matched_dimensions": ["line"],
        "regulation_topics": ["renewal.general"],
        "retrieval_sources": ["vector"],
        "metadata": {
            "section_path": article,
            "chunk_index": chunk_index,
        },
    }


def test_unit_id_is_stable_and_uses_all_identity_components():
    first = build_regulation_unit_id("v5", "测试法规.md", "第十条")

    assert first == build_regulation_unit_id("v5", "测试法规.md", "第十条")
    assert first != build_regulation_unit_id("v6", "测试法规.md", "第十条")
    assert first != build_regulation_unit_id("v5", "其他法规.md", "第十条")
    assert first != build_regulation_unit_id("v5", "测试法规.md", "第十一条")


def test_same_article_preserves_every_distinct_physical_chunk_in_source_order():
    candidates = [
        _chunk("chunk-2", content="第二段", chunk_index=2),
        _chunk("chunk-1", content="第一段", chunk_index=1),
        _chunk("chunk-2", content="重复召回", chunk_index=2),
    ]

    result = aggregate_regulation_units(candidates, kb_version="v5")

    assert not result.errors
    assert len(result.units) == 1
    unit = result.units[0]
    assert unit.chunk_ids == ("chunk-1", "chunk-2")
    assert unit.content == "第一段\n\n第二段"
    assert unit.kb_version == "v5"
    assert unit.locator_type == "article_number"
    assert unit.regulation_topics == ("renewal.general",)
    assert unit.applicability_reasons == ("line: health 命中 ['health']",)


def test_article_number_falls_back_to_section_path():
    candidate = _chunk("chunk-1", article="")
    candidate["metadata"]["section_path"] = "第二章 > 续保"

    result = aggregate_regulation_units([candidate], kb_version="v5")

    assert result.units[0].locator == "第二章 > 续保"
    assert result.units[0].locator_type == "section_path"


def test_missing_stable_identity_is_rejected_instead_of_silently_grouped():
    candidate = _chunk("chunk-1")
    candidate["source_file"] = ""

    result = aggregate_regulation_units([candidate], kb_version="v5")

    assert not result.units
    assert result.rejected_chunk_ids == ("chunk-1",)
    assert "source_file" in result.errors[0]


def test_inconsistent_chunk_applicability_is_indeterminate():
    applicable = _chunk("chunk-1")
    indeterminate = _chunk("chunk-2", chunk_index=2)
    indeterminate["applicability_status"] = "indeterminate"

    result = aggregate_regulation_units(
        [applicable, indeterminate],
        kb_version="v5",
    )

    assert result.units[0].applicability_status == "indeterminate"
    assert "状态不一致" in result.units[0].applicability_reasons[-1]
