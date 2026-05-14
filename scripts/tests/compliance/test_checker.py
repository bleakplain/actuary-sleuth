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
    _extract_real_article_number,
    extract_clause_numbers,
    extract_section_numbers,
    normalize_clause_number,
    extract_chapters,
    _extract_definitions_text,
    check_chapter_audit,
    _audit_single_chapter,
    _deduplicate_items,
    CheckResult,
    CategoryResult,
    DocumentChapter,
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

    def test_empty_content(self):
        assert _extract_real_article_number("", "第1项") == "第1项"


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
        assert regulations[0].source_type == "general"


class TestExtractClauseNumbers:
    def test_extracts_clause_numbers(self):
        text = "【条款 2.1】内容\n【条款 3.2.1】更多内容"
        assert extract_clause_numbers(text) == ["2.1", "3.2.1"]

    def test_no_clauses(self):
        assert extract_clause_numbers("没有条款编号") == []


class TestNormalizeClauseNumber:
    def test_extracts_number(self):
        assert normalize_clause_number("3.2") == "3.2"

    def test_no_number(self):
        assert normalize_clause_number("unknown") is None


class TestExtractSectionNumbers:
    def test_extracts_clauses_and_sections(self):
        text = "【条款 1.1】内容\n【投保须知】标题\n【责任免除】标题2"
        info = extract_section_numbers(text)
        assert info["clauses"] == ["1.1"]
        assert info["has_notices"] is True
        assert info["has_exclusions"] is True

    def test_definition_chapter_excluded(self):
        text = "\n".join([f"【条款 7.{i}】术语{i}" for i in range(1, 16)])
        text += "\n" + "\n".join([f"【条款 1.{i}】内容{i}" for i in range(1, 4)])
        info = extract_section_numbers(text)
        assert info["definition_chapter"] == "7"
        assert all(not c.startswith("7.") for c in info["clauses"])


class TestExtractChapters:
    def _make_doc(self, num_chapters=6, clauses_per_ch=3, add_defs=False):
        parts = []
        for ch in range(1, num_chapters + 1):
            for cl in range(1, clauses_per_ch + 1):
                parts.append(f"【条款 {ch}.{cl}】标题{ch}.{cl}\n内容{ch}.{cl}")
        if add_defs:
            for i in range(1, 16):
                parts.append(f"【条款 7.{i}】术语{i}\n释义{i}")
        return "\n\n".join(parts)

    def test_basic_extraction(self):
        text = self._make_doc()
        chapters = extract_chapters(text)
        assert len(chapters) == 6
        for ch in chapters:
            assert len(ch.clauses) == 3

    def test_definitions_excluded(self):
        text = self._make_doc(add_defs=True)
        chapters = extract_chapters(text)
        chapter_keys = [c.chapter_key for c in chapters]
        assert all(not k.startswith("7") for k in chapter_keys)

    def test_large_chapter_split(self):
        parts = [f"【条款 1.{i}】条款{i}\n内容{i}" for i in range(1, 3)]
        parts += [f"【条款 2.{i}】条款{i}\n内容{i}" for i in range(1, 13)]
        parts += [f"【条款 7.{i}】术语{i}\n释义{i}" for i in range(1, 16)]
        text = "\n\n".join(parts)
        chapters = extract_chapters(text)
        ch2_chapters = [c for c in chapters if c.chapter_key.startswith("2")]
        assert len(ch2_chapters) == 2

    def test_special_sections(self):
        text = "【条款 1.1】标题\n内容\n\n【投保须知】须知标题\n须知内容\n\n【责任免除】免责标题\n免责内容"
        chapters = extract_chapters(text)
        special_keys = [c.chapter_key for c in chapters]
        assert "special_投保须知" in special_keys
        assert "special_责任免除" in special_keys

    def test_title_from_first_clause(self):
        text = "【条款 2.1】保险期间\n本合同保险期间为1年\n\n【条款 2.2】保险金额\n保险金额由双方约定"
        chapters = extract_chapters(text)
        assert chapters[0].chapter_title == "保险期间"


class TestExtractDefinitionsText:
    def test_definitions_extracted(self):
        parts = [f"【条款 1.1】标题{i}\n内容{i}" for i in range(1, 4)]
        parts += [f"【条款 7.{i}】术语{i}\n释义{i}" for i in range(1, 16)]
        text = "\n\n".join(parts)
        defs = _extract_definitions_text(text)
        assert "术语1" in defs
        assert "术语15" in defs

    def test_no_definitions(self):
        text = "【条款 1.1】标题\n内容"
        defs = _extract_definitions_text(text)
        assert defs == ""


class TestDeduplicateItems:
    def test_keeps_highest_priority(self):
        items = [
            {"clause_number": "2.1", "status": "compliant", "conclusion": "ok"},
            {"clause_number": "2.1", "status": "non_compliant", "conclusion": "bad"},
        ]
        result = _deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["status"] == "non_compliant"

    def test_attention_over_compliant(self):
        items = [
            {"clause_number": "3.1", "status": "compliant", "conclusion": "ok"},
            {"clause_number": "3.1", "status": "attention", "conclusion": "warn"},
        ]
        result = _deduplicate_items(items)
        assert len(result) == 1
        assert result[0]["status"] == "attention"

    def test_unknown_clause_numbers_kept(self):
        items = [
            {"clause_number": "未知", "status": "compliant", "conclusion": "ok"},
            {"clause_number": "未知", "status": "non_compliant", "conclusion": "bad"},
        ]
        result = _deduplicate_items(items)
        assert len(result) == 2

    def test_different_clauses_all_kept(self):
        items = [
            {"clause_number": "1.1", "status": "compliant", "conclusion": "ok"},
            {"clause_number": "1.2", "status": "non_compliant", "conclusion": "bad"},
        ]
        result = _deduplicate_items(items)
        assert len(result) == 2

    def test_empty_input(self):
        assert _deduplicate_items([]) == []


class TestAuditSingleChapter:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_returns_items_with_chunk_id(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = json.dumps({
            "items": [{"clause_number": "2.1", "clause_content": "保险期间1年", "status": "compliant",
                        "conclusion": "符合", "suggestion": "", "article_number": "第十三条"}]
        })
        ch = DocumentChapter("2", "保险责任", ["【条款 2.1】保险期间\n1年"], ["2.1"], 20)
        regs = [_make_reg(chunk_id="chunk-abc", article_number="第十三条")]
        items = _audit_single_chapter(ch, regs, "", mock_llm_inst)
        assert len(items) == 1
        assert items[0]["chunk_id"] == "chunk-abc"
        assert items[0]["check_type"] == "regulation"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_llm_error_returns_none(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.side_effect = Exception("timeout")
        ch = DocumentChapter("1", "test", ["c1"], ["1.1"], 10)
        items = _audit_single_chapter(ch, [_make_reg()], "", mock_llm_inst)
        assert items is None


class TestCheckChapterAudit:
    @patch("lib.compliance.checker.get_audit_llm")
    def test_empty_regulations(self, mock_llm):
        result = check_chapter_audit("doc", [])
        assert result["summary"]["compliant"] == 0
        assert result["items"] == []

    @patch("lib.compliance.checker.get_audit_llm")
    def test_chapter_audit_flow(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        mock_llm_inst.chat.return_value = json.dumps({
            "items": [
                {"clause_number": "3.2", "clause_content": "犹豫期15天", "status": "compliant",
                 "conclusion": "符合", "suggestion": "", "article_number": "第十五条"},
            ]
        })
        doc = "【条款 3.1】合同成立\n内容\n\n【条款 3.2】犹豫期\n自签收之日起15天"
        regs = [_make_reg(chunk_id="c1", article_number="第十五条", content="犹豫期不得少于15天")]
        result = check_chapter_audit(doc, regs)
        assert len(result["items"]) >= 1
        assert result["items"][0]["check_type"] == "regulation"

    @patch("lib.compliance.checker.get_audit_llm")
    def test_partial_error(self, mock_llm):
        mock_llm_inst = MagicMock()
        mock_llm.return_value = mock_llm_inst
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("fail")
            return json.dumps({"items": [{"clause_number": "2.1", "clause_content": "c", "status": "compliant",
                                          "conclusion": "ok", "suggestion": "", "article_number": "第一条"}]})
        mock_llm_inst.chat.side_effect = side_effect
        doc = "【条款 2.1】保险\n内容\n\n【条款 3.1】合同\n内容"
        regs = [_make_reg(chunk_id="c1")]
        result = check_chapter_audit(doc, regs)
        assert result.get("partial_error") is True


class TestCheckNegativeList:
    @patch("lib.compliance.checker.get_engine")
    def test_engine_none(self, mock_engine):
        mock_engine.return_value = None
        items, result, regulations = check_negative_list("test content")
        assert result == CheckResult.SKIPPED

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
        mock_llm_inst.chat.return_value = json.dumps({
            "is_violation": True, "clause_number": "2.1", "clause_content": "本产品保证续保",
            "reason": "违反负面清单", "suggestion": "删除", "conclusion": "负面清单禁止",
        })
        items, result, regulations = check_negative_list("本产品保证续保")
        assert result == CheckResult.VIOLATED
        assert items[0].chunk_id == "neg-1"
        assert items[0].check_type == "negative_list"


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
