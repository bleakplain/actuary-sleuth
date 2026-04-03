import pytest
from lib.rag_engine.attribution import parse_citations, AttributionResult


class TestContentMismatchDetection:
    def test_wrong_percentage_detected(self):
        result = parse_citations(
            answer="身故保险金为基本保额的150%[来源1]",
            sources=[{"content": "身故保险金为基本保额的200%", "law_name": "保险法"}],
        )
        assert len(result.content_mismatches) > 0
        assert result.content_mismatches[0]["value"] == "150%"

    def test_correct_percentage_no_mismatch(self):
        result = parse_citations(
            answer="身故保险金为基本保额的200%[来源1]",
            sources=[{"content": "身故保险金为基本保额的200%", "law_name": "保险法"}],
        )
        assert len(result.content_mismatches) == 0

    def test_empty_answer_no_mismatch(self):
        result = parse_citations("", [])
        assert result.content_mismatches == []

    def test_no_numbers_no_mismatch(self):
        result = parse_citations(
            answer="保险合同可以解除",
            sources=[{"content": "保险合同可以解除"}],
        )
        assert len(result.content_mismatches) == 0

    def test_wrong_amount_detected(self):
        result = parse_citations(
            answer="赔付上限为5万元",
            sources=[{"content": "赔付上限为3万元"}],
        )
        assert len(result.content_mismatches) > 0
        assert result.content_mismatches[0]["value"] == "5万元"

    def test_multiple_mismatches(self):
        result = parse_citations(
            answer="等待期60天，赔付200%",
            sources=[{"content": "等待期90天，赔付150%"}],
        )
        assert len(result.content_mismatches) == 2

    def test_value_in_sources_no_mismatch(self):
        result = parse_citations(
            answer="等待期90天",
            sources=[{"content": "等待期90天", "content2": "其他内容"}],
        )
        assert len(result.content_mismatches) == 0


class TestAttributionResultDefault:
    def test_empty_result_has_empty_mismatches(self):
        result = parse_citations("", [])
        assert result.content_mismatches == []

    def test_no_sources_has_empty_mismatches(self):
        result = parse_citations("回答内容", [])
        assert result.content_mismatches == []
