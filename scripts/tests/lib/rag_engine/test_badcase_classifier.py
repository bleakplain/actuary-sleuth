# scripts/tests/lib/rag_engine/test_badcase_classifier.py
import json
import pytest
from unittest.mock import MagicMock, patch

from lib.rag_engine.badcase_classifier import classify_badcase, assess_compliance_risk


def _mock_llm_return(cls_type: str, reason: str, fix_dir: str) -> str:
    return json.dumps({"type": cls_type, "reason": reason, "fix_direction": fix_dir}, ensure_ascii=False)


class TestClassifyBadcase:
    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_retrieval_failure(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "retrieval_failure",
            "相关文档未被检索到",
            "优化检索策略",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="意外险的免赔额是多少",
            retrieved_docs=[{"content": "健康保险的免赔规定"}],
            answer="未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"
        assert "fix_direction" in result

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_hallucination(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "hallucination",
            "回答包含来源不支持的内容",
            "加强 Prompt 忠实度约束",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="健康保险等待期最长多少天",
            retrieved_docs=[{"content": "健康保险等待期不得超过90天"}],
            answer="等待期最长为30天",
            unverified_claims=["等待期最长为30天"],
        )
        assert result["type"] == "hallucination"

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_knowledge_gap(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = _mock_llm_return(
            "knowledge_gap",
            "知识库中不存在相关信息",
            "补充相关法规文档",
        )
        mock_get_llm.return_value = mock_llm

        result = classify_badcase(
            query="线上理赔怎么操作",
            retrieved_docs=[],
            answer="未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "knowledge_gap"

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_llm_failure_raises(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        with pytest.raises(RuntimeError):
            classify_badcase(
                query="test",
                retrieved_docs=[],
                answer="test",
                unverified_claims=[],
            )

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_llm_returns_invalid_json(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not json at all"
        mock_get_llm.return_value = mock_llm

        with pytest.raises(ValueError):
            classify_badcase(
                query="test",
                retrieved_docs=[{"content": "test"}],
                answer="test",
                unverified_claims=[],
            )


class TestAssessComplianceRisk:
    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_high_risk(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"risk_level": 2, "reason": "包含错误金额信息"}'
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("答案错误", "身故保险金为基本保额的150%")
        assert risk == 2

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_low_risk(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"risk_level": 0, "reason": "一般性回答问题"}'
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("回答不完整", "相关规定请查阅条款")
        assert risk == 0

    @patch("lib.rag_engine.badcase_classifier.get_llm_client")
    def test_llm_failure_returns_zero(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        mock_get_llm.return_value = mock_llm

        risk = assess_compliance_risk("test", "test")
        assert risk == 0
