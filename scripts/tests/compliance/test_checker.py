"""合规检查核心逻辑测试"""
import json
import pytest
from unittest.mock import patch, MagicMock

from lib.compliance.checker import (
    AuditSource,
    AuditItem,
    check_negative_list,
    identify_category,
    load_audit_sources,
    format_context_for_llm,
    run_compliance_check,
    CheckResult,
    CategoryResult,
)


class TestLoadAuditSources:
    """load_audit_sources 从 RAG 加载法规，去重并标记 source_type"""

    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        sources = load_audit_sources("健康险")
        assert sources == []

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_category_none_loads_general(self, mock_engine, mock_cat_regs, mock_gen_regs):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = []
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.return_value = [
            {"law_name": "保险法", "article_number": "第1条", "content": "test content"}
        ]
        sources = load_audit_sources(None)
        assert len(sources) == 1
        assert sources[0].law_name == "保险法"
        assert sources[0].source_type == "general"
        assert sources[0].source_id == 1

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_category_loads_both(self, mock_engine, mock_cat_regs, mock_gen_regs):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = ["健康保险管理办法"]
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.side_effect = [
            [{"law_name": "健康保险管理办法", "article_number": "第1条", "content": "health content"}],
            [{"law_name": "保险法", "article_number": "第1条", "content": "general content"}],
        ]
        sources = load_audit_sources("健康险")
        assert len(sources) == 2
        assert sources[0].source_type == "category"
        assert sources[1].source_type == "general"

    @patch("lib.compliance.checker.get_general_regulations")
    @patch("lib.compliance.checker.get_category_regulations")
    @patch("lib.compliance.checker.get_engine")
    def test_dedup_category_and_general_overlap(self, mock_engine, mock_cat_regs, mock_gen_regs):
        """通用法规与险种法规重叠时去重，保留险种优先级"""
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_cat_regs.return_value = ["保险法"]
        mock_gen_regs.return_value = ["保险法"]
        mock_engine_inst.search_by_metadata.side_effect = [
            [{"law_name": "保险法", "article_number": "第1条", "content": "content"}],
            [{"law_name": "保险法", "article_number": "第1条", "content": "content"}],
        ]
        sources = load_audit_sources("寿险")
        assert len(sources) == 1
        assert sources[0].source_type == "category"


class TestFormatContextForLlm:
    """format_context_for_llm 将 AuditSource 列表格式化为 LLM 上下文"""

    def test_empty_sources(self):
        assert format_context_for_llm([]) == ""

    def test_single_source(self):
        sources = [AuditSource(
            source_id=1, law_name="保险法", article_number="第1条",
            content="test content", source_type="general"
        )]
        context = format_context_for_llm(sources)
        assert "[来源1]" in context
        assert "保险法" in context
        assert "test content" in context

    def test_source_with_metadata(self):
        sources = [AuditSource(
            source_id=1, law_name="保险法", article_number="第1条",
            content="content", source_type="general",
            doc_number="国发2023", issuing_authority="国务院",
            effective_date="2023-01-01"
        )]
        context = format_context_for_llm(sources)
        assert "国发2023" in context
        assert "国务院" in context
        assert "2023-01-01" in context


class TestCheckNegativeList:
    """负面清单检查，返回 (items, result, sources)"""

    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        items, result, sources = check_negative_list("test content")
        assert result == CheckResult.SKIPPED
        assert items == []
        assert sources == []

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_no_negative_docs(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = []
        items, result, sources = check_negative_list("test content")
        assert result == CheckResult.SKIPPED

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_passed(self, mock_engine, mock_llm):
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = [
            {"law_name": "保险法", "article_number": "第1条", "content": "禁止虚假宣传"}
        ]
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = "[]"
        items, result, sources = check_negative_list("合规文档内容")
        assert result == CheckResult.PASSED
        assert items == []
        assert len(sources) == 1

    @patch("lib.compliance.checker.get_audit_llm")
    @patch("lib.compliance.checker.get_engine")
    def test_negative_list_violated(self, mock_engine, mock_llm):
        mock_docs = [
            {"law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
        ]
        mock_engine_inst = MagicMock()
        mock_engine.return_value = mock_engine_inst
        mock_engine_inst.search_by_metadata.return_value = mock_docs

        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = '[{"rule_id": 1, "is_violation": true, "reason": "文档中出现保证续保", "source_excerpt": "本产品保证续保", "suggestion": "删除该表述"}]'

        items, result, sources = check_negative_list("本产品保证续保，保险期间1年")
        assert result == CheckResult.VIOLATED
        assert len(items) == 1
        assert items[0].status == "non_compliant"
        assert items[0].check_type == "negative_list"
        assert items[0].source_type == "negative_list"
        assert len(sources) == 1


class TestIdentifyCategory:
    """险种识别"""

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
        """教育险应映射为年金险"""
        result = identify_category("教育金产品", "某某教育险")
        assert result.category == "年金险"
        assert result.method == "keyword"


class TestRunComplianceCheck:
    """合规检查 LLM 调用"""

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
    def test_source_id_validation(self, mock_llm):
        """source_id 越界时应被设为 None"""
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_id": 99}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt", num_sources=3)
        assert result["items"][0]["source_id"] is None

    @patch("lib.compliance.checker.get_audit_llm")
    def test_clause_number_default(self, mock_llm):
        """clause_number 缺失时默认为未知"""
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        data = {
            "summary": {"compliant": 0, "non_compliant": 1, "attention": 0},
            "items": [{"param": "test", "value": "v", "status": "non_compliant", "source_id": 1}]
        }
        mock_llm_inst.chat.return_value = json.dumps(data, ensure_ascii=False)
        result = run_compliance_check("test prompt", num_sources=5)
        assert result["items"][0]["clause_number"] == "未知"