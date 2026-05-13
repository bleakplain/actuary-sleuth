"""合规检查核心逻辑测试"""
import json
import pytest
from unittest.mock import patch, MagicMock

from lib.compliance.checker import (
    AuditRegulationItem,
    AuditResultItem,
    check_negative_list,
    identify_category,
    load_audit_regulations,
    build_audit_context,
    run_compliance_check,
    _build_reg_index,
    _extract_real_article_number,
    extract_clause_numbers,
    CheckResult,
    CategoryResult,
)


class TestExtractRealArticleNumber:
    def test_chinese_number_extraction(self):
        assert _extract_real_article_number("第十三条　投保人提出保险要求", "第1项") == "第十三条"

    def test_fallback_on_no_match(self):
        assert _extract_real_article_number("some content", "第1项") == "第1项"

    def test_empty_content(self):
        assert _extract_real_article_number("", "第1项") == "第1项"

    def test_multiple_numbers(self):
        assert _extract_real_article_number("第一百条　test", "第1项") == "第一百条"


class TestBuildRegIndex:
    def test_exact_match(self):
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="保险法", article_number="第十三条", content="test", source_type="general"),
            AuditRegulationItem(chunk_id="id2", law_name="健康保险管理办法", article_number="第2项", content="test", source_type="category"),
        ]
        reg_index = _build_reg_index(regulations)
        assert reg_index["R1"].chunk_id == "id1"
        assert reg_index["R2"].chunk_id == "id2"

    def test_no_match(self):
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="保险法", article_number="第十三条", content="test", source_type="general"),
        ]
        reg_index = _build_reg_index(regulations)
        assert "R99" not in reg_index

    def test_empty_regulations(self):
        reg_index = _build_reg_index([])
        assert len(reg_index) == 0


class TestLoadAuditRegulations:
    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        regulations = load_audit_regulations("健康险")
        assert regulations == []

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_category_none_loads_general(self, mock_engine, mock_cat_regs, mock_gen_regs):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = []
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.return_value = [
            {"id": "uuid-1", "law_name": "保险法", "article_number": "第1项", "content": "第一条　test"}
        ]
        regulations = load_audit_regulations(None)
        assert len(regulations) == 1
        assert regulations[0].law_name == "保险法"
        assert regulations[0].source_type == "general"
        assert regulations[0].chunk_id == "uuid-1"
        assert regulations[0].article_number == "第一条"

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_category_loads_both(self, mock_engine, mock_cat_regs, mock_gen_regs):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = ["健康保险管理办法"]
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.side_effect = [
            [{"id": "id1", "law_name": "健康保险管理办法", "article_number": "第1项", "content": "health content"}],
            [{"id": "id2", "law_name": "保险法", "article_number": "第1项", "content": "general content"}],
        ]
        regulations = load_audit_regulations("健康险")
        assert len(regulations) == 2
        assert regulations[0].source_type == "category"
        assert regulations[1].source_type == "general"

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_dedup_category_and_general_overlap(self, mock_engine, mock_cat_regs, mock_gen_regs):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = ["保险法"]
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.side_effect = [
            [{"id": "id1", "law_name": "保险法", "article_number": "第1项", "content": "content"}],
            [{"id": "id1", "law_name": "保险法", "article_number": "第1项", "content": "content"}],
        ]
        regulations = load_audit_regulations("寿险")
        assert len(regulations) == 1
        assert regulations[0].source_type == "category"


class TestBuildAuditContext:
    def test_empty_regulations(self):
        assert build_audit_context([]) == ""

    def test_single_regulation_with_index(self):
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="保险法", article_number="第十三条",
            content="test content", source_type="general"
        )]
        context = build_audit_context(regulations)
        assert "[R1] 保险法 第十三条" in context
        assert "test content" in context

    def test_regulation_with_doc_number(self):
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="保险法", article_number="第十三条",
            content="content", source_type="general",
            doc_number="国发2023",
        )]
        context = build_audit_context(regulations)
        assert "国发2023" in context

    def test_no_issuing_authority_or_effective_date(self):
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="保险法", article_number="第十三条",
            content="content", source_type="general",
            issuing_authority="国务院", effective_date="2023-01-01"
        )]
        context = build_audit_context(regulations)
        assert "国务院" not in context
        assert "2023-01-01" not in context

    def test_multiple_regulations_sequential_index(self):
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="法A", article_number="第1条", content="c1", source_type="category"),
            AuditRegulationItem(chunk_id="id2", law_name="法B", article_number="第2条", content="c2", source_type="general"),
        ]
        context = build_audit_context(regulations)
        assert "[R1] 法A 第1条" in context
        assert "[R2] 法B 第2条" in context


class TestExtractClauseNumbers:
    def test_extracts_clause_numbers(self):
        text = "【条款 2.1】内容\n【条款 3.2.1】更多内容"
        assert extract_clause_numbers(text) == ["2.1", "3.2.1"]

    def test_no_clauses(self):
        assert extract_clause_numbers("没有条款编号") == []

    def test_multiple_same_number(self):
        text = "【条款 2.1】内容\n【条款 2.1】重复"
        assert extract_clause_numbers(text) == ["2.1", "2.1"]


class TestCheckNegativeList:
    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        items, result, regulations = check_negative_list("test content")
        assert result == CheckResult.SKIPPED
        assert items == []
        assert regulations == []

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_no_negative_docs(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = []
        items, result, regulations = check_negative_list("test content")
        assert result == CheckResult.SKIPPED

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_passed(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = [
            {"id": "neg-1", "law_name": "保险法", "article_number": "第1项", "content": "禁止虚假宣传"}
        ]
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = "[]"
        items, result, regulations = check_negative_list("合规文档内容")
        assert result == CheckResult.PASSED
        assert items == []
        assert len(regulations) == 1

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_violated_with_index(self, mock_engine, mock_llm):
        mock_docs = [
            {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
        ]
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = mock_docs

        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = '[{"source_ref": "R1", "is_violation": true, "reason": "文档中出现保证续保", "source_excerpt": "本产品保证续保", "suggestion": "删除该表述"}]'

        items, result, regulations = check_negative_list("本产品保证续保，保险期间1年")
        assert result == CheckResult.VIOLATED
        assert len(items) == 1
        assert items[0].status == "non_compliant"
        assert items[0].check_type == "negative_list"
        assert items[0].source_type == "negative_list"
        assert items[0].chunk_id == "neg-1"
        assert len(regulations) == 1


class TestIdentifyCategory:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_keyword_match(self, mock_llm):
        result = identify_category("这是一款健康保险产品", "某某健康险")
        assert result.category == "健康险"
        assert result.method == "keyword"
        assert result.confidence == 0.7

    @patch("lib.compliance.checker.get_audit_llm")
    def test_llm_fallback(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = "这是一款寿险产品"
        result = identify_category("某产品文档内容", "某产品")
        assert result.category == "寿险"
        assert result.method == "llm"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_unknown_category(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.side_effect = Exception("LLM error")
        result = identify_category("无法识别的内容", "某某产品")
        assert result.category is None
        assert result.method == "unknown"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_subcategory_mapping(self, mock_llm):
        result = identify_category("教育金产品", "某某教育险")
        assert result.category == "年金险"
        assert result.method == "keyword"


class TestRunComplianceCheck:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_valid_json_response(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        expected = {"summary": {"compliant": 5, "non_compliant": 0, "attention": 0}, "items": []}
        mock_llm_inst.chat.return_value = json.dumps(expected, ensure_ascii=False)
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 5

    @patch("lib.compliance.checker.get_audit_llm")
    def test_json_in_code_block(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {"summary": {"compliant": 3, "non_compliant": 1, "attention": 0}, "items": []}
        mock_llm_inst.chat.return_value = f"```json\n{json.dumps(data, ensure_ascii=False)}\n```"
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 3

    @patch("lib.compliance.checker.get_audit_llm")
    def test_no_json_found(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = "No JSON here"
        result = run_compliance_check("test prompt")
        assert "error" in result

    @patch("lib.compliance.checker.get_audit_llm")
    def test_llm_exception(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.side_effect = Exception("LLM error")
        result = run_compliance_check("test prompt")
        assert "error" in result

    @patch("lib.compliance.checker.get_audit_llm")
    def test_source_ref_index_matching(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_ref": "R1"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        regulations = [
            AuditRegulationItem(chunk_id="uuid-abc", law_name="保险法", article_number="第十三条", content="test content here", source_type="general")
        ]
        result = run_compliance_check("test prompt", regulations=regulations)
        assert result["items"][0]["chunk_id"] == "uuid-abc"
        assert "保险法" in result["items"][0]["requirement"]
        assert "test content here" in result["items"][0]["source_excerpt"]

    @patch("lib.compliance.checker.get_audit_llm")
    def test_source_ref_index_mismatch(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_ref": "R99"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt", regulations=[])
        assert result["items"][0]["chunk_id"] is None
        assert result["items"][0]["requirement"] == "法规来源待确认（引用 R99 未匹配）"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_source_ref_empty(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 1, "non_compliant": 0, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "compliant", "suggestion": ""}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt", regulations=[])
        assert result["items"][0]["requirement"] == "法规来源待确认"
        assert result["items"][0]["source_excerpt"] == ""

    @patch("lib.compliance.checker.get_audit_llm")
    def test_clause_number_default(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt")
        assert result["items"][0]["clause_number"] == "未知"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_backend_backfill_requirement(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 1, "non_compliant": 0, "attention": 0},
            "items": [{"clause_number": "3.2", "param": "犹豫期", "value": "10天", "status": "compliant", "source_ref": "R2", "requirement": "LLM写的", "suggestion": ""}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="法A", article_number="第1条", content="content A", source_type="category"),
            AuditRegulationItem(chunk_id="id2", law_name="法B", article_number="第5条", content="犹豫期不得少于15天", source_type="general"),
        ]
        result = run_compliance_check("test prompt", regulations=regulations)
        item = result["items"][0]
        assert item["chunk_id"] == "id2"
        assert "法B" in item["requirement"]
        assert "犹豫期不得少于15天" in item["requirement"]
        assert "犹豫期不得少于15天" in item["source_excerpt"]


class TestSplitByClauses:
    def test_includes_preamble_text(self):
        from lib.compliance.checker import _split_by_clauses
        text = "产品概述：本产品是健康险\n【条款 1.1】保险责任\n内容\n【条款 2.1】免责\n内容2"
        batches = _split_by_clauses(text, 10000)
        assert batches[0].startswith("产品概述")

    def test_splits_at_clause_boundary(self):
        from lib.compliance.checker import _split_by_clauses
        text = "【条款 1.1】A\n" + "x" * 50 + "\n【条款 2.1】B\n内容"
        batches = _split_by_clauses(text, 60)
        assert len(batches) == 2

    def test_no_clauses_fallback(self):
        from lib.compliance.checker import _split_by_clauses
        text = "无条款标记的文本" * 10
        batches = _split_by_clauses(text, 50)
        assert len(batches) > 1

    def test_short_text_single_batch(self):
        from lib.compliance.checker import _split_by_clauses
        text = "【条款 1.1】短文本\n内容"
        batches = _split_by_clauses(text, 10000)
        assert len(batches) == 1

    def test_max_clauses_per_batch(self):
        from lib.compliance.checker import _split_by_clauses
        clauses = "\n".join([f"【条款 {i}.1】标题{i}\n内容{i}" for i in range(1, 21)])
        batches = _split_by_clauses(clauses, 100000, max_clauses_per_batch=10)
        assert len(batches) == 2


class TestInvalidItemsFiltered:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_empty_status_filtered(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 1, "non_compliant": 0, "attention": 0},
            "items": [
                {"param": "ok", "status": "compliant"},
                {"param": "bad", "status": ""},
                {"param": "also_bad", "status": "unknown"},
            ]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt")
        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "compliant"


class TestBatchPartialError:
    @patch("lib.compliance.checker._split_by_clauses")
    @patch("lib.compliance.checker.run_compliance_check")
    def test_partial_error_keeps_items(self, mock_run, mock_split):
        mock_split.return_value = ["batch1", "batch2"]
        mock_run.side_effect = [
            {"items": [{"param": "a", "status": "compliant", "clause_number": "1.1"}]},
            {"error": "json_parse_failed"},
        ]
        from lib.compliance.checker import batch_compliance_check
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="法", article_number="第一条", content="c", source_type="general"
        )]
        result = batch_compliance_check("x" * 300000, regulations)
        assert len(result["items"]) == 1
        assert result.get("partial_error") is True

    @patch("lib.compliance.checker.run_compliance_check")
    def test_single_batch_short_doc(self, mock_run):
        mock_run.return_value = {"items": [{"param": "a", "status": "compliant", "clause_number": "1.1"}]}
        from lib.compliance.checker import batch_compliance_check
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="法", article_number="第一条", content="c", source_type="general"
        )]
        result = batch_compliance_check("短文本", regulations)
        assert len(result["items"]) == 1
        mock_run.assert_called_once()


class TestExtractSectionNumbers:
    def test_extracts_clauses_and_sections(self):
        from lib.compliance.checker import extract_section_numbers
        text = "【条款 1.1】内容\n【投保须知】标题\n内容\n【责任免除】标题2"
        info = extract_section_numbers(text)
        assert info["clauses"] == ["1.1"]
        assert info["has_notices"] is True
        assert info["has_exclusions"] is True
        assert info["has_health"] is False

    def test_no_sections(self):
        from lib.compliance.checker import extract_section_numbers
        info = extract_section_numbers("普通文本")
        assert info["clauses"] == []
        assert info["has_notices"] is False


class TestRelevanceCheck:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_relevant_param(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 1, "non_compliant": 0, "attention": 0},
            "items": [{"clause_number": "3.1", "param": "等待期", "value": "90天", "status": "compliant", "source_ref": "R1", "suggestion": ""}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="健康保险管理办法", article_number="第一条", content="等待期不得超过180天", source_type="category"
        )]
        result = run_compliance_check("test prompt", regulations=regulations)
        assert "[法规相关性待确认]" not in result["items"][0]["requirement"]

    @patch("lib.compliance.checker.get_audit_llm")
    def test_irrelevant_param(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 1, "non_compliant": 0, "attention": 0},
            "items": [{"clause_number": "3.1", "param": "免赔额", "value": "1万元", "status": "compliant", "source_ref": "R1", "suggestion": ""}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="疾病定义规范", article_number="第一条", content="恶性肿瘤的定义和诊断标准", source_type="category"
        )]
        result = run_compliance_check("test prompt", regulations=regulations)
        assert "[法规相关性待确认]" in result["items"][0]["requirement"]


class TestHTMLConverter:
    def test_div_content(self):
        from lib.common.html_converter import SimpleHTMLParser
        parser = SimpleHTMLParser()
        parser.feed("<div>Hello World</div>")
        assert "Hello World" in parser.paragraphs

    def test_li_items(self):
        from lib.common.html_converter import SimpleHTMLParser
        parser = SimpleHTMLParser()
        parser.feed("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "• Item 1" in parser.paragraphs
        assert "• Item 2" in parser.paragraphs

    def test_br_in_p(self):
        from lib.common.html_converter import SimpleHTMLParser
        parser = SimpleHTMLParser()
        parser.feed("<p>Line 1<br>Line 2</p>")
        assert "Line 1\nLine 2" in parser.paragraphs
