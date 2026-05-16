"""负面清单流式检查测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import streaming_negative_check, CheckResult


def test_streaming_negative_no_engine():
    with patch('lib.compliance.checker.get_engine', return_value=None):
        results = list(streaming_negative_check("测试内容"))
        assert results[0]["type"] == "negative_list_result"
        assert results[0]["data"] == CheckResult.SKIPPED


def test_streaming_negative_no_docs():
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = []
    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        results = list(streaming_negative_check("本产品保险期间为1年。"))
        assert results[0]["data"] == CheckResult.SKIPPED


def test_streaming_negative_violation():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.stream_chat.return_value = iter([
        '{"clause_number":"1.1","clause_content":"本产品保证续保","conclusion":"违反负面清单","suggestion":"删除","source_ref":"[NR1]"}\n',
    ])

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            results = list(streaming_negative_check("本产品保证续保"))
            violations = [r for r in results if r["type"] == "violation"]
            assert len(violations) == 1
            assert violations[0]["data"]["chunk_id"] == "neg-1"
            result_events = [r for r in results if r["type"] == "negative_list_result"]
            assert result_events[0]["data"] == CheckResult.VIOLATED


def test_streaming_negative_passed():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.stream_chat.return_value = iter([])

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            results = list(streaming_negative_check("本产品保险期间1年"))
            result_events = [r for r in results if r["type"] == "negative_list_result"]
            assert result_events[0]["data"] == CheckResult.PASSED


def test_streaming_negative_llm_error():
    mock_docs = [
        {"id": "neg-1", "law_name": "负面清单", "article_number": "第一条", "content": "禁止保证续保表述"},
    ]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.stream_chat.side_effect = RuntimeError("LLM unavailable")

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.compliance.checker.get_audit_llm', return_value=mock_llm):
            results = list(streaming_negative_check("本产品保险期间1年"))
            result_events = [r for r in results if r["type"] == "negative_list_result"]
            assert result_events[0]["data"] == CheckResult.SKIPPED


def test_streaming_negative_empty_metadata():
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = [
        {"law_name": "", "article_number": "", "content": ""},
    ]
    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        results = list(streaming_negative_check("本产品保险期间1年"))
        result_events = [r for r in results if r["type"] == "negative_list_result"]
        assert result_events[0]["data"] == CheckResult.SKIPPED
