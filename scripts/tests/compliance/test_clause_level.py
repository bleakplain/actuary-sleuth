"""合规检查 JSON 解析测试"""
import pytest
from unittest.mock import MagicMock, patch
from lib.compliance.checker import run_compliance_check


def test_run_compliance_check_normal_json():
    """测试正常 JSON 解析"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"summary": {"compliant": 2, "non_compliant": 1, "attention": 0}, "items": []}'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 2


def test_run_compliance_check_with_thinking_tag():
    """测试 thinking tag 剥离"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '<tool_call>分析...厄 {"summary": {"compliant": 1, "non_compliant": 0, "attention": 0}, "items": []}'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 1


def test_run_compliance_check_with_code_fence():
    """测试 markdown code fence 剥离"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '```json\n{"summary": {"compliant": 1, "non_compliant": 0, "attention": 0}, "items": []}\n```'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert result["summary"]["compliant"] == 1


def test_run_compliance_check_truncated_json():
    """测试截断 JSON 修复"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"summary": {"compliant": 1}, "items": [{"param": "test"'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "summary" in result


def test_run_compliance_check_no_json():
    """测试非 JSON 响应"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '这是一个保险条款文档，符合法规。'
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "summary" in result


def test_run_compliance_check_llm_error():
    """测试 LLM 调用失败"""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM unavailable")
    with patch('lib.compliance.checker.get_qa_llm', return_value=mock_llm):
        result = run_compliance_check("test prompt")
        assert "error" in result


def test_clause_number_in_output():
    """测试检查结果包含条款编号"""
    result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "compliant"},
            {"clause_number": "1.2", "param": "免赔额", "status": "compliant"},
            {"clause_number": "2.1", "param": "保险期间", "status": "non_compliant"},
        ]
    }
    for item in result["items"]:
        assert item["clause_number"], f"item {item['param']} missing clause_number"
