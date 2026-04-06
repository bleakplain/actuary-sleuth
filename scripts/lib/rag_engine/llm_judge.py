#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM-as-a-Judge 评估器 — 使用 LLM 评判生成质量。"""
import json
import logging
import time
from dataclasses import dataclass, replace, field
from typing import Dict, List, Any

from .eval_dataset import EvalSample

logger = logging.getLogger(__name__)


def _parse_json_response(response: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON，支持嵌套结构"""
    depth = 0
    start = -1
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(response[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    return {}


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class LLMPJudgeResult:
    """单条样本的 LLM Judge 评分结果"""
    sample_id: str
    faithfulness_score: float
    correctness_score: float
    relevancy_score: float
    faithfulness_reason: str
    correctness_reason: str
    relevancy_reason: str
    judge_model: str
    judge_latency_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sample_id': self.sample_id,
            'faithfulness_score': self.faithfulness_score,
            'correctness_score': self.correctness_score,
            'relevancy_score': self.relevancy_score,
            'faithfulness_reason': self.faithfulness_reason,
            'correctness_reason': self.correctness_reason,
            'relevancy_reason': self.relevancy_reason,
            'judge_model': self.judge_model,
            'judge_latency_ms': self.judge_latency_ms,
        }


@dataclass
class LLMPJudgeBatchReport:
    """LLM Judge 批量评估报告"""
    faithfulness: float = 0.0
    correctness: float = 0.0
    relevancy: float = 0.0
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)
    total_samples: int = 0
    results: List[LLMPJudgeResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'faithfulness': self.faithfulness,
            'correctness': self.correctness,
            'relevancy': self.relevancy,
            'by_type': self.by_type,
            'total_samples': self.total_samples,
        }


FAITHFULNESS_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的忠实度。

## 检索到的参考资料：
{contexts}

## 用户问题：
{question}

## 系统回答：
{answer}

## 评估步骤：
1. 将系统回答拆分为独立的事实陈述（每句以句号结尾的内容为一个陈述）
2. 逐条检查每个事实陈述是否能在参考资料中找到依据
3. 统计有依据的陈述数量

请严格按以下 JSON 格式输出，不要输出其他内容：
{{"statements": ["陈述1", "陈述2"], "supported": [true, false], "score": 0.0, "reason": "评分理由"}}

评分规则：
- score = 有依据的陈述数 / 总陈述数，保留两位小数
- 如果回答完全基于参考资料，score = 1.0
- 如果回答包含无法在参考资料中找到依据的内容，按比例扣分
- 如果回答与参考资料矛盾，score = 0.0"""

CORRECTNESS_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的正确性。

## 参考答案（标准答案）：
{reference}

## 系统回答：
{answer}

请严格按以下 JSON 格式输出，不要输出其他内容：
{{"key_points": ["要点1", "要点2"], "covered": [true, false], "has_error": false, "score": 0.0, "reason": "评分理由"}}

评分规则：
- score = 覆盖的关键信息点数 / 总关键信息点数，保留两位小数
- 如果包含与参考答案矛盾的错误信息，score 减 0.2
- 语义等价视为覆盖（不要求字面匹配）"""

RELEVANCY_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的相关性。

## 用户问题：
{question}

## 系统回答：
{answer}

请严格按以下 JSON 格式输出，不要输出其他内容：
{{"score": 0.0, "reason": "评分理由"}}

评分规则：
- 1.0: 回答完全针对问题，信息充分
- 0.7: 回答基本针对问题，但有小部分偏题
- 0.4: 回答部分相关，但有明显偏题或信息不足
- 0.0: 回答完全无关或答非所问"""


class LLMPJudge:
    """LLM-as-a-Judge 评估器

    使用 LLM 评判生成质量，支持忠实度、正确性、相关性三个维度。
    """

    def __init__(self, llm_client):
        """
        Args:
            llm_client: BaseLLMClient 实例，通过 LLMClientFactory.create_eval_llm() 创建
        """
        self._llm = llm_client

    def _evaluate_faithfulness(
        self, question: str, answer: str, contexts: List[str]
    ) -> Dict[str, Any]:
        context_text = '\n'.join(f'[{i+1}] {c}' for i, c in enumerate(contexts))
        prompt = FAITHFULNESS_PROMPT.format(
            contexts=context_text,
            question=question,
            answer=answer,
        )
        response = self._llm.chat([{'role': 'user', 'content': prompt}])
        result = _parse_json_response(response)
        return {
            'score': _clamp_score(float(result.get('score', 0.0))),
            'reason': result.get('reason', ''),
        }

    def _evaluate_correctness(
        self, answer: str, ground_truth: str
    ) -> Dict[str, Any]:
        prompt = CORRECTNESS_PROMPT.format(
            reference=ground_truth,
            answer=answer,
        )
        response = self._llm.chat([{'role': 'user', 'content': prompt}])
        result = _parse_json_response(response)
        score = float(result.get('score', 0.0))
        if result.get('has_error'):
            score = max(0.0, score - 0.2)
        return {
            'score': _clamp_score(score),
            'reason': result.get('reason', ''),
        }

    def _evaluate_relevancy(
        self, question: str, answer: str
    ) -> Dict[str, Any]:
        prompt = RELEVANCY_PROMPT.format(question=question, answer=answer)
        response = self._llm.chat([{'role': 'user', 'content': prompt}])
        result = _parse_json_response(response)
        return {
            'score': _clamp_score(float(result.get('score', 0.0))),
            'reason': result.get('reason', ''),
        }

    def judge(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: str = "",
        num_samples: int = 1,
    ) -> LLMPJudgeResult:
        """评估单条样本

        Args:
            num_samples: 多次采样取均值（提高稳定性），默认 1 次
        """
        start = time.time()
        model = self._llm.model

        faithfulness_scores: List[float] = []
        correctness_scores: List[float] = []
        relevancy_scores: List[float] = []
        last_reasons: Dict[str, str] = {'f': '', 'c': '', 'r': ''}

        for _ in range(num_samples):
            f = self._evaluate_faithfulness(question, answer, contexts)
            c = (
                self._evaluate_correctness(answer, ground_truth)
                if ground_truth
                else {'score': 0.0, 'reason': '无参考答案'}
            )
            r = self._evaluate_relevancy(question, answer)

            faithfulness_scores.append(f['score'])
            correctness_scores.append(c['score'])
            relevancy_scores.append(r['score'])
            last_reasons = {'f': f['reason'], 'c': c['reason'], 'r': r['reason']}

        latency_ms = (time.time() - start) * 1000

        return LLMPJudgeResult(
            sample_id='',
            faithfulness_score=sum(faithfulness_scores) / len(faithfulness_scores),
            correctness_score=sum(correctness_scores) / len(correctness_scores),
            relevancy_score=sum(relevancy_scores) / len(relevancy_scores),
            faithfulness_reason=last_reasons['f'],
            correctness_reason=last_reasons['c'],
            relevancy_reason=last_reasons['r'],
            judge_model=model,
            judge_latency_ms=latency_ms,
        )

    def judge_batch(
        self,
        samples: List[EvalSample],
        rag_engine,
        num_samples: int = 1,
    ) -> LLMPJudgeBatchReport:
        """批量评估"""
        results: List[LLMPJudgeResult] = []
        by_type_data: Dict[str, List[LLMPJudgeResult]] = {}

        for sample in samples:
            result = rag_engine.ask(sample.question, include_sources=True)
            answer = result.get('answer', '')
            contexts = [s.get('content', '') for s in result.get('sources', [])]

            judge_result = self.judge(
                question=sample.question,
                answer=answer,
                contexts=contexts,
                ground_truth=sample.ground_truth,
                num_samples=num_samples,
            )
            judge_result = replace(judge_result, sample_id=sample.id)
            results.append(judge_result)

            qtype = sample.question_type.value
            by_type_data.setdefault(qtype, []).append(judge_result)

        if not results:
            return LLMPJudgeBatchReport()

        n = len(results)
        report = LLMPJudgeBatchReport(
            faithfulness=sum(r.faithfulness_score for r in results) / n,
            correctness=sum(r.correctness_score for r in results) / n,
            relevancy=sum(r.relevancy_score for r in results) / n,
            total_samples=n,
            results=results,
        )

        for qtype, type_results in by_type_data.items():
            tn = len(type_results)
            report.by_type[qtype] = {
                'faithfulness': sum(r.faithfulness_score for r in type_results) / tn,
                'correctness': sum(r.correctness_score for r in type_results) / tn,
                'relevancy': sum(r.relevancy_score for r in type_results) / tn,
            }

        return report
