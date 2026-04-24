"""负面清单检查测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import check_negative_list


def test_check_negative_list_no_engine():
    """测试引擎未初始化情况"""
    with patch('lib.compliance.checker.get_engine', return_value=None):
        items = check_negative_list("测试内容")
        assert items == []


def test_check_negative_list_no_violation():
    """测试无违规情况"""
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = []
    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        content = "本产品保险期间为1年，等待期为90天。"
        items = check_negative_list(content)
        assert isinstance(items, list)
        assert len(items) == 0


def test_check_negative_list_with_violation():
    """测试有违规情况（LLM 判断违规）"""
    mock_docs = [{
        "law_name": "负面清单",
        "article_number": "第一条",
        "content": "禁止在保险产品中使用保证续保表述。",
    }]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"is_violation": true, "reason": "文档中出现保证续保表述", "source_excerpt": "本产品保证续保", "suggestion": "删除保证续保表述"}'

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.llm.get_qa_llm', return_value=mock_llm):
            content = "本产品保证续保，保险期间为1年。"
            items = check_negative_list(content)
            assert len(items) == 1
            assert items[0]["status"] == "non_compliant"
            assert items[0]["source"] == "负面清单"


def test_check_negative_list_no_violation_llm():
    """测试 LLM 判断无违规"""
    mock_docs = [{
        "law_name": "负面清单",
        "article_number": "第一条",
        "content": "禁止在保险产品中使用保证续保表述。",
    }]
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = mock_docs

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"is_violation": false, "reason": "", "source_excerpt": "", "suggestion": ""}'

    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        with patch('lib.llm.get_qa_llm', return_value=mock_llm):
            content = "本产品保险期间为1年。"
            items = check_negative_list(content)
            assert items == []


def test_check_negative_list_empty_metadata():
    """测试知识库中无负面清单文档"""
    mock_engine = MagicMock()
    mock_engine.search_by_metadata.return_value = []
    with patch('lib.compliance.checker.get_engine', return_value=mock_engine):
        content = "本产品保险期间为1年。"
        items = check_negative_list(content)
        assert items == []
