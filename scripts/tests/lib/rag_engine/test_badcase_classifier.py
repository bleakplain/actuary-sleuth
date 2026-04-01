import pytest
from lib.rag_engine.badcase_classifier import (
    classify_badcase,
    assess_compliance_risk,
)


class TestClassifyBadcase:
    def test_knowledge_gap(self):
        """知识库中没有相关信息"""
        result = classify_badcase(
            query="线上理赔怎么操作",
            retrieved_docs=[{"content": "健康保险等待期规定", "source_file": "health_ins.md"}],
            answer="提供的法规条款中未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "knowledge_gap"

    def test_hallucination(self):
        """检索到了正确文档但 LLM 答错了"""
        result = classify_badcase(
            query="健康保险等待期最长多少天",
            retrieved_docs=[{"content": "健康保险等待期不得超过90天"}],
            answer="等待期最长为30天",
            unverified_claims=["等待期最长为30天"],
        )
        assert result["type"] == "hallucination"

    def test_retrieval_failure(self):
        """检索到了文档但不是最相关的"""
        result = classify_badcase(
            query="意外险的免赔额是多少",
            retrieved_docs=[{"content": "健康保险的免赔规定", "source_file": "health_ins.md"}],
            answer="提供的法规条款中未找到关于意外险免赔额的信息",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"

    def test_no_unverified_and_answer_matches(self):
        """答案与检索结果一致，用户仍不满意 → 检索失败"""
        result = classify_badcase(
            query="保险合同解除条件",
            retrieved_docs=[{"content": "投保人可以解除保险合同"}],
            answer="投保人可以解除保险合同",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"


class TestAssessComplianceRisk:
    def test_amount_in_wrong_answer(self):
        """错误答案中包含金额 → 高风险"""
        risk = assess_compliance_risk(
            reason="答案错误",
            answer="身故保险金为基本保额的150%",
        )
        assert risk == 2

    def test_compliance_keywords(self):
        """涉及合规关键词 → 中风险"""
        risk = assess_compliance_risk(
            reason="答案错误",
            answer="保险公司不得拒绝承保",
        )
        assert risk == 1

    def test_low_risk(self):
        risk = assess_compliance_risk(
            reason="回答不完整",
            answer="相关规定请查阅条款",
        )
        assert risk == 0
