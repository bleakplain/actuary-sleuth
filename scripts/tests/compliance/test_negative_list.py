"""负面清单检查测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import check_negative_list, CheckResult


def test_check_negative_list_no_engine():
    with patch('lib.compliance.checker.get_engine', return_value=None):
        items, result, regulations = check_negative_list("测试内容")
        assert items == []
        assert result == CheckResult.SKIPPED
        assert regulations == []


def test_check_negative_list_no_docs():
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = []
    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        items, result, regulations = check_negative_list("本产品保险期间为1年。")
        assert items == []
        assert result == CheckResult.SKIPPED


def test_check_negative_list_batch_violation():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
        {"id": "neg-2", "law_name": "负面清单", "article_number": "第二条", "content": "禁止夸大收益"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '[{"source_ref": "R1", "is_violation": true, "reason": "文档中出现保证续保", "source_excerpt": "本产品保证续保", "suggestion": "删除该表述"}]'

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            items, result, regulations = check_negative_list("本产品保证续保，保险期间1年")
            assert result == CheckResult.VIOLATED
            assert len(items) == 1
            assert items[0].status == "non_compliant"
            assert items[0].chunk_id == "neg-1"
            assert len(regulations) == 2


def test_check_negative_list_batch_passed():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '[]'

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            items, result, regulations = check_negative_list("本产品保险期间1年")
            assert result == CheckResult.PASSED
            assert items == []


def test_check_negative_list_llm_error():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM unavailable")

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            items, result, regulations = check_negative_list("本产品保险期间1年")
            assert result == CheckResult.SKIPPED
            assert items == []


def test_check_negative_list_empty_metadata():
    mock_docs = [
        {"law_name": "", "article_number": "", "content": ""},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        items, result, regulations = check_negative_list("本产品保险期间1年")
        assert items == []
        assert result == CheckResult.SKIPPED
