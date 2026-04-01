# scripts/tests/lib/rag_engine/test_quality_detector.py
import json
import pytest
from unittest.mock import MagicMock, patch

from lib.rag_engine.quality_detector import detect_quality


def _mock_quality_response(faithfulness: float, relevance: float, completeness: float) -> str:
    return json.dumps({
        "faithfulness": {"score": faithfulness, "issues": ""},
        "relevance": {"score": relevance, "issues": ""},
        "completeness": {"score": completeness, "issues": ""},
    }, ensure_ascii=False)


class TestDetectQuality:
    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_high_quality(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.9, 0.85, 0.9)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(
            query="健康保险等待期规定",
            answer="健康保险等待期不得超过90天。",
            sources=[{"content": "健康保险等待期不得超过90天"}],
        )
        assert scores["faithfulness"] == 0.9
        assert scores["relevance"] == 0.85
        assert scores["completeness"] == 0.9
        assert scores["overall"] > 0.85

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_low_quality(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.2, 0.3, 0.1)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(
            query="健康保险等待期规定",
            answer="等待期最长为30天",
            sources=[{"content": "财产保险的理赔流程"}],
        )
        assert scores["overall"] < 0.3

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_llm_failure_raises(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        with pytest.raises(RuntimeError):
            detect_quality(
                query="test",
                answer="test",
                sources=[],
            )

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_empty_inputs(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_quality_response(0.0, 0.0, 0.0)
        mock_get_llm.return_value = mock_llm

        scores = detect_quality(query="", answer="", sources=[])
        assert scores["overall"] == 0.0

    @patch("lib.rag_engine.quality_detector._get_llm")
    def test_llm_returns_invalid_json(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not json"
        mock_get_llm.return_value = mock_llm

        with pytest.raises(ValueError):
            detect_quality(
                query="test",
                answer="test",
                sources=[{"content": "test"}],
            )
