"""条款级验证测试"""
import pytest
from pathlib import Path
from tests.compliance.validate_flow import compare_clause_level, load_fixture


def test_compare_clause_level_match():
    """测试条款级对比匹配"""
    auto_result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "compliant"},
            {"clause_number": "1.2", "param": "免赔额", "status": "compliant"},
            {"clause_number": "2.1", "param": "保险期间", "status": "non_compliant"},
        ]
    }
    human_result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "compliant"},
            {"clause_number": "1.2", "param": "免赔额", "status": "compliant"},
            {"clause_number": "2.1", "param": "保险期间", "status": "non_compliant"},
        ]
    }
    result = compare_clause_level(auto_result, human_result)
    assert result.clause_accuracy == 1.0
    assert result.status_accuracy == 1.0
    assert all(m.match for m in result.mismatches)


def test_compare_clause_level_mismatch():
    """测试条款级对比不匹配"""
    auto_result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "compliant"},
        ]
    }
    human_result = {
        "items": [
            {"clause_number": "1.1", "param": "等待期", "status": "non_compliant"},
        ]
    }
    result = compare_clause_level(auto_result, human_result)
    assert result.clause_accuracy == 0.0
    assert not result.mismatches[0].match


def test_load_fixture():
    """测试加载 fixture"""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "compliance" / "sample_1.json"
    if fixture_path.exists():
        fixture = load_fixture(str(fixture_path))
        assert "human_result" in fixture
        assert "auto_result" in fixture


def test_sample_1_validation():
    """测试 sample_1 验证"""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "compliance" / "sample_1.json"
    if not fixture_path.exists():
        pytest.skip("sample_1.json not found")
    fixture = load_fixture(str(fixture_path))
    result = compare_clause_level(fixture["auto_result"], fixture["human_result"])
    assert result.clause_accuracy >= 0.8
