"""合规检查核心逻辑测试"""
import json
import pytest
from unittest.mock import patch, MagicMock

from lib.compliance.checker import (
    AuditRegulationItem,
    AuditResultItem,
    streaming_compliance_check,
    streaming_negative_check,
    identify_category,
    infer_category_from_product_tags,
    build_regulation_retrieval_query,
    load_audit_regulations,
    retrieve_audit_regulations,
    retrieve_audit_regulations_with_status,
    _extract_real_article_number,
    _build_numbered_regulations,
    _split_document_by_clauses,
    extract_clause_numbers,
    extract_section_numbers,
    normalize_clause_number,
    _parse_ndjson_tokens,
    _normalize_violation,
    CheckResult,
    CategoryResult,
)
from lib.common.product_tags import (
    ProductDesignType,
    ProductLine,
    ProductSubtype,
    ProductTags,
)


def _make_reg(chunk_id="id1", law_name="保险法", article_number="第十三条",
              content="test content here", source_type="general", **kwargs):
    return AuditRegulationItem(
        chunk_id=chunk_id, law_name=law_name, article_number=article_number,
        content=content, source_type=source_type, **kwargs,
    )


class TestExtractRealArticleNumber:
    def test_chinese_number_extraction(self):
        assert _extract_real_article_number("第十三条　投保人提出保险要求", "第1项") == "第十三条"

    def test_fallback_on_no_match(self):
        assert _extract_real_article_number("some content", "第1项") == "第1项"


class TestLoadAuditRegulations:
    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        import lib.compliance.checker as mod
        mod._regulation_cache.clear()
        mock_engine.return_value = None
        assert load_audit_regulations("健康险") == []

    @patch("lib.compliance.checker.ComplianceConstants")
    def test_category_none_loads_general(self, mock_cc):
        import lib.compliance.checker as mod
        mod._regulation_cache.clear()
        mock_engine_inst = MagicMock()
        with patch("lib.compliance.checker.get_engine", return_value=mock_engine_inst):
            mock_cc.CATEGORY_REGULATION_REGISTRY = {}
            mock_cc.GENERAL_REGULATIONS = ["保险法"]
            mock_engine_inst.search_by_metadata.return_value = [
                {"id": "uuid-1", "law_name": "保险法", "article_number": "第1项", "content": "第一条　test"}
            ]
            regulations = load_audit_regulations(None)
            assert len(regulations) == 1
            assert regulations[0].source_type == "general"


class TestTaggedRegulationRetrieval:
    @patch("lib.compliance.checker._get_general_regulations", return_value=[])
    @patch("lib.compliance.checker._list_registered_regulations", return_value=[])
    @patch("lib.compliance.checker.get_engine")
    def test_layers_semantic_candidates_by_product_and_topic(
        self, mock_engine, _mock_registered_regs, _mock_general_regs,
    ):
        mock_engine.return_value.search_candidates.return_value = [
            {
                "law_name": "寿险规定",
                "article_number": "第1条",
                "content": "寿险规则",
                "metadata": {"适用标签": "life"},
            },
            {
                "law_name": "短期健康险规定",
                "article_number": "第2条",
                "content": "应明确写明不保证续保",
                "metadata": {
                    "适用标签": "health,short_term",
                    "条款主题": "renewal.non_guaranteed",
                },
            },
        ]
        product_tags = ProductTags(line=ProductLine.HEALTH)

        result = retrieve_audit_regulations(
            "不保证续保",
            "健康险",
            product_tags,
            ("renewal.non_guaranteed",),
            top_k=8,
        )

        assert len(result) == 1
        assert result[0].law_name == "短期健康险规定"
        assert result[0].matched_topics == ("renewal.non_guaranteed",)
        assert result[0].applicability_status == "indeterminate"

    @patch("lib.compliance.checker.load_audit_regulations")
    @patch("lib.compliance.checker.get_engine", return_value=None)
    def test_falls_back_to_legacy_loader_when_engine_is_unavailable(
        self, _mock_engine, mock_legacy,
    ):
        mock_legacy.return_value = [_make_reg()]

        result = retrieve_audit_regulations(
            "query", "健康险", ProductTags(), (), top_k=8,
        )

        assert result == mock_legacy.return_value

    @patch("lib.compliance.checker.load_audit_regulations", return_value=[])
    @patch("lib.compliance.checker.get_engine", return_value=None)
    def test_engine_unavailable_returns_explicit_degraded_status(
        self, _mock_engine, _mock_legacy,
    ):
        outcome = retrieve_audit_regulations_with_status(
            "query", "健康险", ProductTags(),
        )

        assert outcome.regulations == ()
        assert outcome.degraded is True
        assert "知识库未初始化" in outcome.warnings[0]

    @patch("lib.compliance.checker.load_audit_regulations")
    @patch("lib.compliance.checker._get_general_regulations", return_value=[])
    @patch("lib.compliance.checker._list_registered_regulations", return_value=[])
    @patch("lib.compliance.checker.get_engine")
    def test_does_not_restore_explicitly_excluded_candidates(
        self, mock_engine, _mock_registered_regs, _mock_general_regs, mock_legacy,
    ):
        mock_engine.return_value.search_candidates.return_value = [{
            "law_name": "寿险规定",
            "article_number": "第1条",
            "content": "仅适用于寿险",
            "metadata": {"适用标签": "life"},
        }]

        result = retrieve_audit_regulations(
            "健康保险", "健康险", ProductTags(line=ProductLine.HEALTH),
        )

        assert result == []
        mock_legacy.assert_not_called()

    @patch("lib.compliance.checker._get_general_regulations", return_value=["共同法规"])
    @patch("lib.compliance.checker._list_registered_regulations", return_value=["共同法规"])
    @patch("lib.compliance.checker.get_engine")
    def test_merges_semantic_and_registered_retrieval_sources(
        self, mock_engine, _mock_registered_regs, _mock_general_regs,
    ):
        raw = {
            "id": "chunk-1",
            "law_name": "共同法规",
            "article_number": "第1条",
            "content": "健康保险规则",
            "metadata": {"适用标签": "health"},
        }
        mock_engine.return_value.search_by_metadata.return_value = [raw]
        mock_engine.return_value.search_candidates.return_value = [{
            **raw,
            "retrieval_sources": ["vector", "bm25"],
        }]

        result = retrieve_audit_regulations(
            "健康保险", "健康险", ProductTags(line=ProductLine.HEALTH),
        )

        assert len(result) == 1
        assert result[0].source_type == "category"
        assert result[0].retrieval_sources == (
            "bm25", "registered:category", "registered:general", "vector",
        )

    @patch("lib.compliance.checker._get_general_regulations", return_value=[])
    @patch("lib.compliance.checker._list_registered_regulations", return_value=["分段法规"])
    @patch("lib.compliance.checker.get_engine")
    def test_registered_path_preserves_multiple_chunks_of_same_article(
        self, mock_engine, _mock_registered_regs, _mock_general_regs,
    ):
        mock_engine.return_value.search_candidates.return_value = []
        mock_engine.return_value.search_by_metadata.return_value = [
            {
                "id": f"chunk-{index}",
                "law_name": "分段法规",
                "article_number": "第1条",
                "content": f"第{index}段",
                "metadata": {"适用标签": "health"},
            }
            for index in (1, 2)
        ]

        result = retrieve_audit_regulations(
            "健康保险", "健康险", ProductTags(line=ProductLine.HEALTH),
        )

        assert [item.chunk_id for item in result] == ["chunk-1", "chunk-2"]

    @patch("lib.compliance.checker._get_general_regulations", return_value=[])
    @patch("lib.compliance.checker._list_registered_regulations", return_value=["健康法规"])
    @patch("lib.compliance.checker.get_engine")
    def test_semantic_failure_returns_registered_candidates_and_degraded_status(
        self, mock_engine, _mock_registered_regs, _mock_general_regs,
    ):
        mock_engine.return_value.search_by_metadata.return_value = [{
            "id": "chunk-1",
            "law_name": "健康法规",
            "article_number": "第1条",
            "content": "健康保险规则",
            "metadata": {"适用标签": "health"},
        }]
        mock_engine.return_value.search_candidates.side_effect = RuntimeError("vector unavailable")

        outcome = retrieve_audit_regulations_with_status(
            "健康保险", "健康险", ProductTags(line=ProductLine.HEALTH),
        )

        assert len(outcome.regulations) == 1
        assert outcome.degraded is True
        assert "语义检索失败" in outcome.warnings[0]


def test_disability_income_product_is_deterministically_health():
    result = identify_category("", "互联网失能收入损失保险")

    assert result.category == "健康险"
    assert result.method == "keyword"


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (ProductTags(line=ProductLine.HEALTH, primary_subtype=ProductSubtype.MEDICAL), "医疗险"),
        (ProductTags(line=ProductLine.HEALTH, primary_subtype=ProductSubtype.CRITICAL_ILLNESS), "重疾险"),
        (ProductTags(line=ProductLine.HEALTH, primary_subtype=ProductSubtype.NURSING), "健康险"),
        (ProductTags(line=ProductLine.LIFE, primary_subtype=ProductSubtype.ANNUITY), "年金险"),
        (ProductTags(line=ProductLine.LIFE, design_type=ProductDesignType.PARTICIPATING), "分红险"),
        (ProductTags(line=ProductLine.ACCIDENT), "意外险"),
        (ProductTags(), None),
    ],
)
def test_category_can_be_recovered_from_product_tags(tags, expected):
    assert infer_category_from_product_tags(tags) == expected


def test_retrieval_query_includes_parent_line_and_specific_subtype_terms():
    query = build_regulation_retrieval_query(
        "某某失能收入损失保险条款",
        "保险期间为一年。",
        ProductTags(
            line=ProductLine.HEALTH,
            primary_subtype=ProductSubtype.DISABILITY_INCOME,
        ),
    )

    assert "健康保险" in query
    assert "失能收入损失保险" in query


class TestExtractClauseNumbers:
    def test_extracts_clause_numbers(self):
        assert extract_clause_numbers("【条款 2.1】内容\n【条款 3.2.1】更多") == ["2.1", "3.2.1"]

    def test_no_clauses(self):
        assert extract_clause_numbers("没有条款编号") == []


class TestNormalizeClauseNumber:
    def test_extracts_number(self):
        assert normalize_clause_number("3.2") == "3.2"

    def test_strips_prefix(self):
        assert normalize_clause_number("条款 2.3.1") == "2.3.1"

    def test_preserves_sub_clause(self):
        assert normalize_clause_number("7.16(1)") == "7.16(1)"

    def test_no_number(self):
        assert normalize_clause_number("unknown") is None


class TestExtractSectionNumbers:
    def test_extracts_clauses_and_sections(self):
        text = "【条款 1.1】内容\n【投保须知】标题\n【责任免除】标题2"
        info = extract_section_numbers(text)
        assert info["clauses"] == ["1.1"]
        assert info["has_notices"] is True

    def test_definition_chapter_excluded(self):
        text = "\n".join([f"【条款 7.{i}】术语{i}" for i in range(1, 16)])
        text += "\n" + "\n".join([f"【条款 1.{i}】内容{i}" for i in range(1, 4)])
        info = extract_section_numbers(text)
        assert info["definition_chapter"] == "7"


class TestBuildNumberedRegulations:
    def test_numbered_regulations(self):
        regs = [_make_reg(chunk_id="c1"), _make_reg(chunk_id="c2", law_name="合同法")]
        text, mapping = _build_numbered_regulations(regs)
        assert "[R1]" in text
        assert "[R2]" in text
        assert mapping == {"[R1]": "c1", "[R2]": "c2"}

    def test_custom_prefix(self):
        text, mapping = _build_numbered_regulations([_make_reg()], prefix="[NR")
        assert "[NR1]" in text

    def test_empty(self):
        text, mapping = _build_numbered_regulations([])
        assert text == ""


class TestSplitDocumentByClauses:
    def test_short_document_not_split(self):
        text = "【条款 1.1】内容1\n【条款 1.2】内容2"
        assert len(_split_document_by_clauses(text, 5)) == 1

    def test_long_document_split(self):
        # 每条条款很长（500 字符），budget 较小，触发分批
        parts = [f"【条款 {i}.1】{'x' * 500}" for i in range(1, 120)]
        result = _split_document_by_clauses("\n\n".join(parts), 10000)
        assert len(result) >= 2


class TestNormalizeViolation:
    def test_valid_item(self):
        raw = {"clause_number": "3.2", "clause_content": "犹豫期15天", "status": "non_compliant",
               "conclusion": "不合规", "suggestion": "修改", "source_ref": "[R1]"}
        result = _normalize_violation(raw, {"[R1]": "c1"}, "regulation")
        assert result is not None
        assert isinstance(result, AuditResultItem)
        assert result.chunk_id == "c1"
        assert result.check_type == "regulation"
        assert result.source_ref == "[R1]"

    def test_empty_content_returns_none(self):
        raw = {"clause_number": "3.2", "clause_content": "", "status": "non_compliant"}
        assert _normalize_violation(raw, {}, "regulation") is None

    def test_invalid_source_ref_cleared(self):
        raw = {"clause_number": "3.2", "clause_content": "内容", "source_ref": "[R99]"}
        result = _normalize_violation(raw, {"[R1]": "c1"}, "regulation")
        assert result.chunk_id is None
        assert result.source_ref == ""

    def test_malformed_source_ref_cleared(self):
        raw = {"clause_number": "3.2", "clause_content": "内容", "source_ref": "R1"}
        result = _normalize_violation(raw, {"[R1]": "c1"}, "regulation")
        assert result.source_ref == ""

    def test_no_source_ref(self):
        raw = {"clause_content": "内容"}
        result = _normalize_violation(raw, {"[R1]": "c1"}, "regulation")
        assert result.source_ref == ""
        assert result.chunk_id is None

    def test_negative_list_source_ref(self):
        raw = {"clause_content": "违规内容", "source_ref": "[NR1]"}
        result = _normalize_violation(raw, {"[NR1]": "neg-1"}, "negative_list")
        assert result.chunk_id == "neg-1"
        assert result.source_ref == "[NR1]"


class TestParseNdjsonTokens:
    def test_parses_ndjson_lines(self):
        tokens = [
            '{"clause_number":"3.2","clause_content":"内容","status":"non_compliant","conclusion":"违规","suggestion":"修改"}\n',
            '{"clause_number":"5.1","clause_content":"更多内容","status":"non_compliant","conclusion":"违规2","suggestion":"修改2"}\n',
        ]
        items = list(_parse_ndjson_tokens(iter(tokens), {}, "regulation"))
        assert len(items) == 2
        assert items[0].clause_number == "3.2"
        assert items[1].clause_number == "5.1"
        assert all(isinstance(i, AuditResultItem) for i in items)

    def test_skips_malformed_lines(self):
        tokens = ["not json\n", '{"clause_number":"3.2","clause_content":"内容","status":"non_compliant","conclusion":"c"}\n']
        items = list(_parse_ndjson_tokens(iter(tokens), {}, "regulation"))
        assert len(items) == 1

    def test_skips_wrappers(self):
        tokens = ["[]\n", "{}\n"]
        items = list(_parse_ndjson_tokens(iter(tokens), {}, "regulation"))
        assert len(items) == 0

    def test_handles_remaining_buffer(self):
        tokens = ['{"clause_number":"3.2","clause_content":"内容","status":"non_compliant","conclusion":"c"}']
        items = list(_parse_ndjson_tokens(iter(tokens), {}, "regulation"))
        assert len(items) == 1

    def test_splits_tokens_across_line(self):
        tokens = ['{"clause_number":"3.2",', '"clause_content":"内容","status":"non_compliant","conclusion":"c"}\n']
        items = list(_parse_ndjson_tokens(iter(tokens), {"[R1]": "c1"}, "regulation"))
        assert len(items) == 1


class TestStreamingComplianceCheck:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_empty_regulations(self, mock_llm):
        results = list(streaming_compliance_check("doc", []))
        assert results == []

    @patch("lib.compliance.checker.get_audit_llm")
    def test_streaming_violations(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.stream_chat.return_value = iter([
            '{"clause_number":"5.5","clause_content":"诉讼时效2年","status":"non_compliant","conclusion":"应为5年","suggestion":"修改为5年","source_ref":"[R1]"}\n',
        ])
        doc = "【条款 5.5】诉讼时效2年"
        regs = [_make_reg(chunk_id="c1", article_number="第十八条")]
        results = list(streaming_compliance_check(doc, regs))
        violations = [r for r in results if r["type"] == "violation"]
        assert len(violations) == 1
        assert violations[0]["data"].clause_number == "5.5"
        assert violations[0]["data"].chunk_id == "c1"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_llm_error_yields_progress(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.stream_chat.side_effect = Exception("timeout")
        regs = [_make_reg()]
        results = list(streaming_compliance_check("doc", regs))
        progress = [r for r in results if r["type"] == "progress" and "失败" in r["data"]]
        assert len(progress) == 1


class TestStreamingNegativeCheck:
    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        results = list(streaming_negative_check("doc"))
        assert results[0]["type"] == "negative_list_result"
        assert results[0]["data"] == CheckResult.SKIPPED

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_passed(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = [
            {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止虚假宣传"}
        ]
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.stream_chat.return_value = iter([])
        results = list(streaming_negative_check("正常内容"))
        result_events = [r for r in results if r["type"] == "negative_list_result"]
        assert result_events[0]["data"] == CheckResult.PASSED

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_violated(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = [
            {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止虚假宣传"}
        ]
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.stream_chat.return_value = iter([
            '{"clause_number":"2.1","clause_content":"保证续保","conclusion":"违规","suggestion":"删除","source_ref":"[NR1]"}\n',
        ])
        results = list(streaming_negative_check("本产品保证续保"))
        violations = [r for r in results if r["type"] == "violation"]
        assert len(violations) == 1
        assert violations[0]["data"].check_type == "negative_list"
        result_events = [r for r in results if r["type"] == "negative_list_result"]
        assert result_events[0]["data"] == CheckResult.VIOLATED


class TestIdentifyCategory:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_keyword_match(self, mock_llm):
        result = identify_category("这是一款健康保险产品", "某某健康险")
        assert result.category == "健康险"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_unknown_category(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.side_effect = Exception("LLM error")
        result = identify_category("无法识别的内容", "某某产品")
        assert result.category is None


class TestRegulationCache:
    @patch("lib.compliance.checker.ComplianceConstants")
    def test_cache_returns_same_result(self, mock_cc):
        import lib.compliance.checker as mod
        mod._regulation_cache.clear()
        mock_engine_inst = MagicMock()
        with patch("lib.compliance.checker.get_engine", return_value=mock_engine_inst):
            mock_cc.CATEGORY_REGULATION_REGISTRY = {}
            mock_cc.GENERAL_REGULATIONS = ["保险法"]
            mock_engine_inst.search_by_metadata.return_value = [
                {"id": "u1", "law_name": "保险法", "article_number": "第一条", "content": "内容"}
            ]
            r1 = mod.load_audit_regulations(None)
            r2 = mod.load_audit_regulations(None)
            assert r1 is r2
            assert mock_engine_inst.search_by_metadata.call_count == 1
        mod._regulation_cache.clear()
