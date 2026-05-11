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
    _build_ref_map,
    _normalize_ref,
    _extract_real_article_number,
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


class TestNormalizeRef:
    def test_strips_brackets(self):
        assert _normalize_ref("《保险法-第十六条》") == "保险法-第十六条"

    def test_strips_all_brackets(self):
        assert _normalize_ref("【保险法-第十三条】") == "保险法-第十三条"

    def test_strips_spaces(self):
        assert _normalize_ref(" 保险法 - 第十六条 ") == "保险法-第十六条"

    def test_strips_fullwidth_spaces(self):
        assert _normalize_ref("《保险法\u3000-　第十六条》") == "保险法-第十六条"

    def test_plain_ref(self):
        assert _normalize_ref("保险法-第十三条") == "保险法-第十三条"


class TestBuildRefMap:
    def test_exact_match(self):
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="保险法", article_number="第十三条", content="test", source_type="general"),
            AuditRegulationItem(chunk_id="id2", law_name="健康保险管理办法", article_number="第2项", content="test", source_type="category"),
        ]
        ref_map = _build_ref_map(regulations)
        assert ref_map["保险法-第十三条"].chunk_id == "id1"
        assert ref_map["健康保险管理办法-第2项"].chunk_id == "id2"

    def test_no_match(self):
        regulations = [
            AuditRegulationItem(chunk_id="id1", law_name="保险法", article_number="第十三条", content="test", source_type="general"),
        ]
        ref_map = _build_ref_map(regulations)
        assert "不存在的法规-第1条" not in ref_map

    def test_empty_regulations(self):
        ref_map = _build_ref_map([])
        assert len(ref_map) == 0


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

    def test_single_regulation(self):
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="保险法", article_number="第十三条",
            content="test content", source_type="general"
        )]
        context = build_audit_context(regulations)
        assert "【保险法-第十三条】" in context
        assert "test content" in context

    def test_regulation_with_metadata(self):
        regulations = [AuditRegulationItem(
            chunk_id="id1", law_name="保险法", article_number="第十三条",
            content="content", source_type="general",
            doc_number="国发2023", issuing_authority="国务院",
            effective_date="2023-01-01"
        )]
        context = build_audit_context(regulations)
        assert "国发2023" in context
        assert "国务院" in context
        assert "2023-01-01" in context


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
    def test_negative_list_violated(self, mock_engine, mock_llm):
        mock_docs = [
            {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
        ]
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = mock_docs

        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = '[{"source_ref": "负面清单-第一条", "is_violation": true, "reason": "文档中出现保证续保", "source_excerpt": "本产品保证续保", "suggestion": "删除该表述"}]'

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
    def test_source_ref_matching(self, mock_llm):
        """source_ref 匹配时应写入 chunk_id"""
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_ref": "保险法-第十三条"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        regulations = [
            AuditRegulationItem(chunk_id="uuid-abc", law_name="保险法", article_number="第十三条", content="test", source_type="general")
        ]
        result = run_compliance_check("test prompt", regulations=regulations)
        assert result["items"][0]["chunk_id"] == "uuid-abc"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_source_ref_mismatch(self, mock_llm):
        """source_ref 匹配失败时 chunk_id 为 None"""
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_ref": "不存在的法规-第1条"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt", regulations=[])
        assert result["items"][0]["chunk_id"] is None

    @patch("lib.compliance.checker.get_audit_llm")
    def test_clause_number_default(self, mock_llm):
        """clause_number 缺失时默认为未知"""
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant"}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt")
        assert result["items"][0]["clause_number"] == "未知"
