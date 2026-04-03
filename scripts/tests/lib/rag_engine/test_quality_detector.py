import pytest
from lib.rag_engine.quality_detector import (
    detect_quality,
    compute_retrieval_relevance,
    compute_info_completeness,
)


class TestComputeRetrievalRelevance:
    def test_empty_inputs(self):
        assert compute_retrieval_relevance("", []) == 0.0
        assert compute_retrieval_relevance("query", []) == 0.0
        assert compute_retrieval_relevance("", [{"content": "test"}]) == 0.0

    def test_high_relevance(self):
        sources = [{"content": "健康保险等待期不得超过90天"}]
        score = compute_retrieval_relevance("健康保险等待期规定", sources)
        assert score > 0.5

    def test_low_relevance(self):
        sources = [{"content": "分红型保险的分红水平不确定"}]
        score = compute_retrieval_relevance("意外伤害保险免责条款", sources)
        assert score < 0.3

    def test_multiple_sources(self):
        sources = [
            {"content": "不相关内容"},
            {"content": "健康保险等待期规定"},
        ]
        score = compute_retrieval_relevance("健康保险等待期", sources)
        assert score > 0.0


class TestComputeInfoCompleteness:
    def test_no_numbers_in_query(self):
        assert compute_info_completeness("等待期有什么规定", "不超过90天") == 1.0

    def test_answer_contains_query_numbers(self):
        score = compute_info_completeness("等待期不超过多少天", "等待期不超过90天")
        assert score > 0.0

    def test_answer_missing_query_numbers(self):
        score = compute_info_completeness("佣金比例上限是多少", "佣金应当合理")
        assert score == 0.0

    def test_empty_inputs(self):
        assert compute_info_completeness("", "90天") == 0.0
        assert compute_info_completeness("等待期", "") == 0.0


class TestDetectQuality:
    def test_high_quality(self):
        result = detect_quality(
            query="健康保险等待期",
            answer="等待期不得超过90天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.9,
        )
        assert result["overall"] > 0.7
        assert result["faithfulness"] == 0.9

    def test_low_faithfulness(self):
        result = detect_quality(
            query="等待期",
            answer="万能保险结算利率根据账户价值确定",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.2,
        )
        assert result["overall"] < 0.5

    def test_no_sources(self):
        result = detect_quality("等待期", "不确定", [])
        assert result["retrieval_relevance"] == 0.0

    def test_none_faithfulness_defaults_to_zero(self):
        result = detect_quality("query", "answer", [{"content": "query answer"}])
        assert result["faithfulness"] == 0.0

    def test_none_faithfulness_uses_equal_weights(self):
        result = detect_quality(
            query="健康保险等待期",
            answer="等待期不得超过90天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=None,
        )
        rr = result["retrieval_relevance"]
        comp = result["completeness"]
        expected = 0.5 * rr + 0.5 * comp
        assert abs(result["overall"] - round(expected, 4)) < 0.0001

    def test_values_rounded_to_four_decimals(self):
        result = detect_quality(
            query="等待期",
            answer="不得超过90天",
            sources=[{"content": "等待期不得超过90天"}],
            faithfulness_score=0.123456,
        )
        assert result["faithfulness"] == 0.1235
