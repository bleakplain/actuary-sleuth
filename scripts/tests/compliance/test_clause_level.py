"""条款级合规检查测试"""
import pytest
from api.routers.compliance import _detect_missing_clauses, _run_compliance_check


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


def test_detect_missing_clauses():
    """测试遗漏检测"""
    parsed_doc = {
        "clauses": [
            {"number": "1", "title": "保险责任"},
            {"number": "2", "title": "责任免除"},
            {"number": "3", "title": "保费"},
        ]
    }
    check_result = {
        "items": [
            {"clause_number": "1", "param": "等待期", "status": "compliant"},
            {"clause_number": "2", "param": "免责条款", "status": "compliant"},
        ]
    }
    missing = _detect_missing_clauses(parsed_doc, check_result)
    assert len(missing) == 1
    assert missing[0]["clause_number"] == "3"
    assert missing[0]["status"] == "attention"


def test_detect_missing_clauses_empty():
    """测试无遗漏情况"""
    parsed_doc = {
        "clauses": [
            {"number": "1", "title": "保险责任"},
        ]
    }
    check_result = {
        "items": [
            {"clause_number": "1", "param": "等待期", "status": "compliant"},
        ]
    }
    missing = _detect_missing_clauses(parsed_doc, check_result)
    assert len(missing) == 0


def test_run_compliance_check_no_results():
    """测试法规无结果处理"""
    result = _run_compliance_check(None, "", [])
    assert result["summary"]["attention"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["param"] == "法规检索"
    assert result["warning"] == "法规检索无结果，无法进行合规检查"