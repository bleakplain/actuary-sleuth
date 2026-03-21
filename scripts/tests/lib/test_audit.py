import pytest
from lib.common.audit import EvaluationResult, AnalyzedResult, CheckedResult, PreprocessedResult
from lib.common.models import Product, ProductCategory
from datetime import datetime


def test_evaluation_result_get_violations():
    preprocessed = PreprocessedResult(
        audit_id="test-001",
        document_url="https://example.com",
        timestamp=datetime.now(),
        product=Product(
            name="Test Product",
            company="Test Company",
            category=ProductCategory.OTHER,
            period="1年"
        ),
        clauses=[],
        pricing_params={}
    )
    checked = CheckedResult(preprocessed=preprocessed, violations=[])
    analyzed = AnalyzedResult(checked=checked, pricing_analysis={})
    result = EvaluationResult(
        analyzed=analyzed,
        score=100,
        grade="A",
        summary={}
    )

    assert result.get_violations() == []
    assert result.get_violation_count() == 0


def test_evaluation_result_get_violation_summary():
    violations = [
        {"severity": "high"},
        {"severity": "medium"},
        {"severity": "low"},
        {"severity": "high"}
    ]

    preprocessed = PreprocessedResult(
        audit_id="test-002",
        document_url="https://example.com",
        timestamp=datetime.now(),
        product=Product(
            name="Test Product",
            company="Test Company",
            category=ProductCategory.OTHER,
            period="1年"
        ),
        clauses=[],
        pricing_params={}
    )
    checked = CheckedResult(preprocessed=preprocessed, violations=violations)
    analyzed = AnalyzedResult(checked=checked, pricing_analysis={})
    result = EvaluationResult(
        analyzed=analyzed,
        score=60,
        grade="C",
        summary={}
    )

    summary = result.get_violation_summary()
    assert summary == {"high": 2, "medium": 1, "low": 1}
    assert result.get_violation_count() == 4


def test_evaluation_result_to_dict():
    violations = [{"severity": "high", "description": "Test violation"}]

    preprocessed = PreprocessedResult(
        audit_id="test-003",
        document_url="https://example.com",
        timestamp=datetime.now(),
        product=Product(
            name="Test Product",
            company="Test Company",
            category=ProductCategory.OTHER,
            period="1年"
        ),
        clauses=[],
        pricing_params={}
    )
    checked = CheckedResult(preprocessed=preprocessed, violations=violations)
    analyzed = AnalyzedResult(checked=checked, pricing_analysis={})
    result = EvaluationResult(
        analyzed=analyzed,
        score=80,
        grade="B",
        summary={"test": "summary"}
    )

    result_dict = result.to_dict()
    assert result_dict["success"] is True
    assert result_dict["audit_id"] == "test-003"
    assert result_dict["score"] == 80
    assert result_dict["grade"] == "B"
    assert result_dict["violation_count"] == 1
    assert result_dict["violation_summary"]["high"] == 1
