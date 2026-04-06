#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM Judge 单元测试"""
from unittest.mock import MagicMock, patch
import json
import pytest

from lib.rag_engine.llm_judge import (
    LLMPJudge, LLMPJudgeResult, LLMPJudgeBatchReport,
    FAITHFULNESS_PROMPT, CORRECTNESS_PROMPT, RELEVANCY_PROMPT,
)
from lib.rag_engine.eval_dataset import EvalSample, QuestionType


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "glm-4-flash-test"
    return llm


@pytest.fixture
def sample_eval():
    return EvalSample(
        id="test001",
        question="健康保险的等待期有什么规定？",
        ground_truth="等待期不应与健康人群有过大差距",
        evidence_docs=["05_健康保险产品开发.md"],
        evidence_keywords=["等待期", "既往症"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="健康保险",
    )


class TestLLMPJudgeResult:
    def test_frozen(self):
        result = LLMPJudgeResult(
            sample_id="s1", faithfulness_score=0.9,
            correctness_score=0.8, relevancy_score=0.85,
            faithfulness_reason="", correctness_reason="",
            relevancy_reason="", judge_model="test", judge_latency_ms=100.0,
        )
        with pytest.raises(AttributeError):
            result.sample_id = "other"

    def test_to_dict(self):
        result = LLMPJudgeResult(
            sample_id="s1", faithfulness_score=0.9,
            correctness_score=0.8, relevancy_score=0.85,
            faithfulness_reason="good", correctness_reason="ok",
            relevancy_reason="fine", judge_model="test", judge_latency_ms=100.0,
        )
        d = result.to_dict()
        assert d['faithfulness_score'] == 0.9
        assert d['judge_model'] == 'test'

    def test_to_dict_all_fields(self):
        result = LLMPJudgeResult(
            sample_id="s1", faithfulness_score=0.9,
            correctness_score=0.0, relevancy_score=0.0,
            faithfulness_reason="", correctness_reason="",
            relevancy_reason="", judge_model="test", judge_latency_ms=0.0,
        )
        d = result.to_dict()
        assert 'sample_id' in d
        assert 'faithfulness_score' in d
        assert 'correctness_score' in d
        assert 'relevancy_score' in d
        assert 'judge_model' in d
        assert 'judge_latency_ms' in d


class TestLLMPJudgeBatchReport:
    def test_empty_report(self):
        report = LLMPJudgeBatchReport()
        assert report.faithfulness == 0.0
        assert report.total_samples == 0
        assert report.by_type == {}

    def test_to_dict(self):
        report = LLMPJudgeBatchReport(
            faithfulness=0.85, correctness=0.8, relevancy=0.9,
            by_type={'factual': {'faithfulness': 0.9}},
            total_samples=10,
        )
        d = report.to_dict()
        assert d['faithfulness'] == 0.85
        assert d['total_samples'] == 10
        assert 'factual' in d['by_type']


class TestLLMPJudge:
    def test_judge_all_dimensions(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述1", "陈述2"],
            "supported": [True, True],
            "score": 1.0,
            "reason": "完全基于参考资料",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="等待期有什么规定？",
            answer="等待期不应与健康人群有过大差距",
            contexts=["等待期规定相关内容"],
            ground_truth="等待期不应有过大差距",
        )
        assert result.faithfulness_score == 1.0
        assert result.correctness_score == 1.0
        assert result.relevancy_score == 1.0
        assert result.judge_model == "glm-4-flash-test"
        assert mock_llm.chat.call_count == 3

    def test_judge_parse_invalid_json(self, mock_llm):
        mock_llm.chat.return_value = "这不是 JSON"
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="测试回答",
            contexts=["上下文"], ground_truth="标准答案",
        )
        assert result.faithfulness_score == 0.0
        assert result.correctness_score == 0.0
        assert result.relevancy_score == 0.0

    def test_judge_empty_json_object(self, mock_llm):
        mock_llm.chat.return_value = "{}"
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="标准",
        )
        assert result.faithfulness_score == 0.0

    def test_judge_score_clamped_high(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": 1.5, "reason": "",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="标准",
        )
        assert result.faithfulness_score <= 1.0

    def test_judge_score_clamped_low(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": -0.5, "reason": "",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="标准",
        )
        assert result.faithfulness_score >= 0.0

    def test_judge_correctness_with_error(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "key_points": ["要点1", "要点2"],
            "covered": [True, True],
            "has_error": True,
            "score": 0.9,
            "reason": "包含错误信息",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答包含错误",
            contexts=["上下文"], ground_truth="标准答案",
        )
        assert result.correctness_score == pytest.approx(0.7, abs=0.01)

    def test_judge_no_ground_truth(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": 0.8, "reason": "",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="",
        )
        assert result.correctness_score == 0.0
        assert result.correctness_reason == "无参考答案"

    def test_judge_multiple_samples(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": 0.8, "reason": "测试",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="标准",
            num_samples=3,
        )
        assert mock_llm.chat.call_count == 9  # 3 dimensions x 3 samples

    def test_judge_latency_ms(self, mock_llm):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": 0.9, "reason": "",
        })
        judge = LLMPJudge(mock_llm)
        result = judge.judge(
            question="测试", answer="回答",
            contexts=["上下文"], ground_truth="标准",
        )
        assert result.judge_latency_ms > 0

    def test_judge_batch(self, mock_llm, sample_eval):
        mock_llm.chat.return_value = json.dumps({
            "statements": ["等待期规定"], "supported": [True],
            "score": 0.9, "reason": "忠实",
        })
        mock_engine = MagicMock()
        mock_engine.ask.return_value = {
            'answer': '等待期不应与健康人群有过大差距',
            'sources': [{'content': '等待期规定相关内容'}],
        }
        judge = LLMPJudge(mock_llm)
        report = judge.judge_batch([sample_eval], mock_engine)
        assert isinstance(report, LLMPJudgeBatchReport)
        assert report.total_samples == 1
        assert report.faithfulness == 0.9
        assert report.correctness == 0.9
        assert report.relevancy == 0.9
        assert 'factual' in report.by_type

    def test_judge_batch_multiple_types(self, mock_llm):
        samples = [
            EvalSample(
                id="f001", question="事实题", ground_truth="答案",
                evidence_docs=["a.md"], evidence_keywords=["kw"],
                question_type=QuestionType.FACTUAL, difficulty="easy", topic="测试",
            ),
            EvalSample(
                id="m001", question="多跳题", ground_truth="答案",
                evidence_docs=["a.md"], evidence_keywords=["kw"],
                question_type=QuestionType.MULTI_HOP, difficulty="hard", topic="测试",
            ),
        ]
        mock_llm.chat.return_value = json.dumps({
            "statements": ["陈述"], "supported": [True],
            "score": 0.8, "reason": "测试",
        })
        mock_engine = MagicMock()
        mock_engine.ask.return_value = {
            'answer': '回答',
            'sources': [{'content': '上下文'}],
        }
        judge = LLMPJudge(mock_llm)
        report = judge.judge_batch(samples, mock_engine)
        assert report.total_samples == 2
        assert 'factual' in report.by_type
        assert 'multi_hop' in report.by_type

    def test_judge_batch_empty(self, mock_llm):
        mock_engine = MagicMock()
        judge = LLMPJudge(mock_llm)
        report = judge.judge_batch([], mock_engine)
        assert report.total_samples == 0
        assert report.faithfulness == 0.0


class TestPrompts:
    def test_faithfulness_prompt_contains_required_sections(self):
        assert "{contexts}" in FAITHFULNESS_PROMPT
        assert "{question}" in FAITHFULNESS_PROMPT
        assert "{answer}" in FAITHFULNESS_PROMPT

    def test_correctness_prompt_contains_required_sections(self):
        assert "{reference}" in CORRECTNESS_PROMPT
        assert "{answer}" in CORRECTNESS_PROMPT

    def test_relevancy_prompt_contains_required_sections(self):
        assert "{question}" in RELEVANCY_PROMPT
        assert "{answer}" in RELEVANCY_PROMPT
