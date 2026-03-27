#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 量化评估器

分层评估体系：
- RetrievalEvaluator: 独立检索评估（Precision@K, Recall@K, MRR, NDCG, 冗余率）
- GenerationEvaluator: 独立生成评估（RAGAS 可用时使用，否则跳过）
"""
import math
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType

logger = logging.getLogger(__name__)


@dataclass
class RetrievalEvalReport:
    """检索评估报告"""
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'precision_at_k': self.precision_at_k,
            'recall_at_k': self.recall_at_k,
            'mrr': self.mrr,
            'ndcg': self.ndcg,
            'redundancy_rate': self.redundancy_rate,
            'by_type': self.by_type,
        }

    def print_report(self):
        print("\n" + "=" * 60)
        print("检索评估报告 (Retrieval Evaluation)")
        print("=" * 60)
        print(f"  Precision@K:     {self.precision_at_k:.3f}")
        print(f"  Recall@K:        {self.recall_at_k:.3f}")
        print(f"  MRR:             {self.mrr:.3f}")
        print(f"  NDCG:            {self.ndcg:.3f}")
        print(f"  Redundancy Rate: {self.redundancy_rate:.3f}")

        if self.by_type:
            print("\n  按题型分组:")
            for qtype, metrics in self.by_type.items():
                print(f"    [{qtype}]")
                for metric_name, value in metrics.items():
                    print(f"      {metric_name}: {value:.3f}")

        print("=" * 60 + "\n")


@dataclass
class GenerationEvalReport:
    """生成评估报告"""
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    answer_correctness: Optional[float] = None
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'faithfulness': self.faithfulness,
            'answer_relevancy': self.answer_relevancy,
            'answer_correctness': self.answer_correctness,
            'by_type': self.by_type,
        }

    def print_report(self):
        print("\n" + "=" * 60)
        print("生成评估报告 (Generation Evaluation)")
        print("=" * 60)

        if self.faithfulness is not None:
            print(f"  Faithfulness:      {self.faithfulness:.3f}")
        if self.answer_relevancy is not None:
            print(f"  Answer Relevancy:  {self.answer_relevancy:.3f}")
        if self.answer_correctness is not None:
            print(f"  Answer Correctness:{self.answer_correctness:.3f}")

        if not any([self.faithfulness, self.answer_relevancy, self.answer_correctness]):
            print("  RAGAS 不可用，跳过生成质量评估")

        if self.by_type:
            print("\n  按题型分组:")
            for qtype, metrics in self.by_type.items():
                print(f"    [{qtype}]")
                for metric_name, value in metrics.items():
                    if value is not None:
                        print(f"      {metric_name}: {value:.3f}")

        print("=" * 60 + "\n")


@dataclass
class RAGEvalReport:
    """RAG 综合评估报告"""
    retrieval: RetrievalEvalReport = field(default_factory=RetrievalEvalReport)
    generation: GenerationEvalReport = field(default_factory=GenerationEvalReport)
    total_samples: int = 0
    failed_samples: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'retrieval': self.retrieval.to_dict(),
            'generation': self.generation.to_dict(),
            'total_samples': self.total_samples,
            'failed_samples': self.failed_samples,
        }

    def print_report(self):
        print("\n" + "=" * 70)
        print(f"RAG 量化评估报告 (共 {self.total_samples} 条样本)")
        print("=" * 70)
        self.retrieval.print_report()
        self.generation.print_report()

        if self.failed_samples:
            print(f"\n失败案例 ({len(self.failed_samples)} 条):")
            print("-" * 70)
            for i, sample in enumerate(self.failed_samples, 1):
                print(f"  [{i}] {sample.get('question', 'N/A')}")
                print(f"      类型: {sample.get('question_type', 'N/A')}")
                print(f"      原因: {sample.get('failure_reason', 'N/A')}")
                print(f"      Recall: {sample.get('recall', 'N/A')}")
                print(f"      Precision: {sample.get('precision', 'N/A')}")
                print(f"      期望文档: {sample.get('evidence_docs', [])}")
                print()

        print("=" * 70 + "\n")


def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    """判断检索结果是否与期望证据相关

    匹配逻辑：
    1. 检查 content 是否包含 evidence_keywords 中的关键词
    2. 检查 law_name/category 是否与 evidence_docs 近似匹配
    """
    content = result.get('content', '').lower()

    # 关键词匹配：content 中包含至少一个 evidence_keyword
    keyword_match = any(
        kw.lower() in content
        for kw in evidence_keywords
        if len(kw) >= 2  # 忽略单字关键词
    )

    if keyword_match:
        return True

    # 文档来源匹配：law_name 或 category 与 evidence_docs 近似匹配
    law_name = result.get('law_name', '').lower()
    category = result.get('category', '').lower()

    for doc in evidence_docs:
        doc_stem = doc.lower().replace('.md', '').replace('_', '')
        if doc_stem in law_name or doc_stem in category:
            return True
        # 反向：law_name 中的关键部分出现在 doc 中
        if any(part in doc_stem for part in law_name.split() if len(part) >= 2):
            return True

    return False


def _compute_jaccard(text_a: str, text_b: str) -> float:
    """计算两段文本的 Jaccard 相似度（基于字符集合）"""
    if not text_a or not text_b:
        return 0.0
    set_a = set(text_a)
    set_b = set(text_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _compute_redundancy_rate(results: List[Dict[str, Any]]) -> float:
    """计算检索结果中的冗余率

    基于 Jaccard 相似度 > 0.8 视为冗余
    """
    if len(results) <= 1:
        return 0.0

    contents = [r.get('content', '') for r in results]
    redundant_count = 0
    compared = set()

    for i in range(len(contents)):
        for j in range(i + 1, len(contents)):
            if _compute_jaccard(contents[i], contents[j]) > 0.8:
                pair = (i, j)
                if pair not in compared:
                    compared.add(pair)
                    redundant_count += 1

    return redundant_count / len(results)


class RetrievalEvaluator:
    """检索质量评估器

    独立评估检索环节质量，不依赖 LLM 生成。
    """

    def __init__(self, rag_engine):
        self.rag_engine = rag_engine

    def evaluate(
        self,
        sample: EvalSample,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """评估单条样本的检索质量

        Returns:
            包含 precision, recall, mrr, ndcg, first_relevant_rank 的字典
        """
        results = self.rag_engine.search(sample.question, top_k=top_k)

        if not results:
            return {
                'sample_id': sample.id,
                'precision': 0.0,
                'recall': 0.0,
                'mrr': 0.0,
                'ndcg': 0.0,
                'redundancy_rate': 0.0,
                'first_relevant_rank': None,
                'num_results': 0,
            }

        # 判断每个结果是否相关
        relevance = [
            1 if _is_relevant(r, sample.evidence_docs, sample.evidence_keywords) else 0
            for r in results
        ]

        # Precision@K
        precision = sum(relevance) / len(relevance)

        # Recall@K (capped at 1.0: can't recall more than 100% of evidence docs)
        recall = min(sum(relevance) / len(sample.evidence_docs), 1.0) if sample.evidence_docs else 0.0

        # MRR
        mrr = 0.0
        first_relevant_rank = None
        for rank, rel in enumerate(relevance, 1):
            if rel == 1:
                mrr = 1.0 / rank
                first_relevant_rank = rank
                break

        # NDCG (二值相关性)
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
        # Ideal DCG: 所有相关结果排在最前
        n_relevant = min(sum(relevance), len(relevance))
        ideal_relevance = [1] * n_relevant + [0] * (len(relevance) - n_relevant)
        idcg = sum(
            rel / math.log2(rank + 1)
            for rank, rel in enumerate(ideal_relevance, 1)
        )
        ndcg = dcg / idcg if idcg > 0 else 0.0

        # 冗余率
        redundancy = _compute_redundancy_rate(results)

        return {
            'sample_id': sample.id,
            'precision': precision,
            'recall': recall,
            'mrr': mrr,
            'ndcg': ndcg,
            'redundancy_rate': redundancy,
            'first_relevant_rank': first_relevant_rank,
            'num_results': len(results),
        }

    def evaluate_batch(
        self,
        samples: List[EvalSample],
        top_k: int = 5,
    ) -> RetrievalEvalReport:
        """批量评估检索质量

        Returns:
            RetrievalEvalReport: 汇总报告
        """
        all_results = []
        by_type_results: Dict[str, List[Dict[str, Any]]] = {}

        for sample in samples:
            result = self.evaluate(sample, top_k=top_k)
            all_results.append(result)

            qtype = sample.question_type.value
            by_type_results.setdefault(qtype, []).append(result)

        if not all_results:
            return RetrievalEvalReport()

        n = len(all_results)
        report = RetrievalEvalReport(
            precision_at_k=sum(r['precision'] for r in all_results) / n,
            recall_at_k=sum(r['recall'] for r in all_results) / n,
            mrr=sum(r['mrr'] for r in all_results) / n,
            ndcg=sum(r['ndcg'] for r in all_results) / n,
            redundancy_rate=sum(r['redundancy_rate'] for r in all_results) / n,
        )

        # 按题型分组统计
        for qtype, type_results in by_type_results.items():
            tn = len(type_results)
            report.by_type[qtype] = {
                'precision_at_k': sum(r['precision'] for r in type_results) / tn,
                'recall_at_k': sum(r['recall'] for r in type_results) / tn,
                'mrr': sum(r['mrr'] for r in type_results) / tn,
                'ndcg': sum(r['ndcg'] for r in type_results) / tn,
            }

        return report


class GenerationEvaluator:
    """生成质量评估器

    RAGAS 可用时使用 RAGAS 批量评估，不可用时跳过生成质量评估。

    Args:
        rag_engine: 用于生成答案的 RAG 引擎
        llm: RAGAS 评估用 LLM，由调用方注入
        embeddings: RAGAS 评估用 Embedding，由调用方注入
    """

    def __init__(self, rag_engine=None, llm=None, embeddings=None):
        self.rag_engine = rag_engine
        self._ragas_available = False
        self._eval_llm = llm
        self._eval_embeddings = embeddings

        try:
            from ragas import evaluate as ragas_evaluate  # noqa: F401
            from ragas.metrics import (  # noqa: F401
                faithfulness,
                answer_relevancy,
                answer_correctness,
            )
            self._ragas_available = True
            self._ragas_evaluate = ragas_evaluate
            self._ragas_metrics = [faithfulness, answer_relevancy, answer_correctness]
        except ImportError:
            logger.info(
                "RAGAS 未安装，将跳过生成质量评估。"
                "安装: pip install ragas"
            )

    @property
    def ragas_available(self) -> bool:
        return self._ragas_available

    def evaluate(
        self,
        sample: EvalSample,
        contexts: List[str],
        answer: str,
    ) -> Dict[str, float]:
        """评估单条样本的生成质量

        仅在 RAGAS 可用时返回有效结果。
        """
        if not self._ragas_available:
            return {}

        from datasets import Dataset

        dataset = Dataset.from_dict({
            "user_input": [sample.question],
            "retrieved_contexts": [contexts],
            "response": [answer],
            "reference": [sample.ground_truth],
        })

        result = self._ragas_evaluate(
            dataset,
            metrics=self._ragas_metrics,
            llm=self._eval_llm,
            embeddings=self._eval_embeddings,
        )

        return result.to_pandas().to_dict('records')[0]

    def evaluate_batch(
        self,
        samples: List[EvalSample],
        rag_engine=None,
    ) -> GenerationEvalReport:
        """批量评估生成质量

        Args:
            samples: 评估样本列表
            rag_engine: 用于生成答案的 RAG 引擎

        Returns:
            GenerationEvalReport: 汇总报告
        """
        engine = rag_engine or self.rag_engine
        if not engine:
            logger.warning("未提供 RAG 引擎，跳过生成评估")
            return GenerationEvalReport()

        if not self._ragas_available:
            logger.info("RAGAS 不可用，跳过生成质量评估")
            return GenerationEvalReport()

        from datasets import Dataset

        questions = []
        contexts_list = []
        answers = []
        ground_truths = []
        by_type_data: Dict[str, Dict[str, list]] = {}

        for sample in samples:
            result = engine.ask(sample.question, include_sources=True)
            answer = result.get('answer', '')
            contexts = [s.get('content', '') for s in result.get('sources', [])]

            questions.append(sample.question)
            contexts_list.append(contexts)
            answers.append(answer)
            ground_truths.append(sample.ground_truth)

            qtype = sample.question_type.value
            by_type_data.setdefault(qtype, {
                'user_input': [], 'retrieved_contexts': [], 'response': [], 'reference': []
            })
            by_type_data[qtype]['user_input'].append(sample.question)
            by_type_data[qtype]['retrieved_contexts'].append(contexts)
            by_type_data[qtype]['response'].append(answer)
            by_type_data[qtype]['reference'].append(sample.ground_truth)

        dataset = Dataset.from_dict({
            "user_input": questions,
            "retrieved_contexts": contexts_list,
            "response": answers,
            "reference": ground_truths,
        })

        result = self._ragas_evaluate(
            dataset,
            metrics=self._ragas_metrics,
            llm=self._eval_llm,
            embeddings=self._eval_embeddings,
        )

        df = result.to_pandas()

        report = GenerationEvalReport()

        metric_map = {
            'faithfulness': 'faithfulness',
            'answer_relevancy': 'answer_relevancy',
            'answer_correctness': 'answer_correctness',
        }

        for ragas_key, attr_name in metric_map.items():
            if ragas_key in df.columns:
                values = df[ragas_key].dropna()
                if len(values) > 0:
                    setattr(report, attr_name, float(values.mean()))

        # 按题型分组评估
        for qtype, type_data in by_type_data.items():
            type_dataset = Dataset.from_dict(type_data)
            type_result = self._ragas_evaluate(
                type_dataset,
                metrics=self._ragas_metrics,
                llm=self._eval_llm,
                embeddings=self._eval_embeddings,
            )
            type_df = type_result.to_pandas()

            type_metrics = {}
            for ragas_key, attr_name in metric_map.items():
                if ragas_key in type_df.columns:
                    values = type_df[ragas_key].dropna()
                    if len(values) > 0:
                        type_metrics[attr_name] = float(values.mean())

            if type_metrics:
                report.by_type[qtype] = type_metrics

        return report


def run_retrieval_evaluation(
    rag_engine,
    samples: List[EvalSample],
    top_k: int = 5,
) -> tuple:
    """运行检索评估

    Returns:
        (RetrievalEvalReport, failed_samples)
    """
    evaluator = RetrievalEvaluator(rag_engine)
    all_results = []

    for sample in samples:
        result = evaluator.evaluate(sample, top_k=top_k)
        result['_sample'] = sample
        all_results.append(result)

    # 汇总报告
    report = RetrievalEvalReport()
    if all_results:
        n = len(all_results)
        report.precision_at_k = sum(r['precision'] for r in all_results) / n
        report.recall_at_k = sum(r['recall'] for r in all_results) / n
        report.mrr = sum(r['mrr'] for r in all_results) / n
        report.ndcg = sum(r['ndcg'] for r in all_results) / n
        report.redundancy_rate = sum(r['redundancy_rate'] for r in all_results) / n

        # 按题型分组
        by_type: Dict[str, List[Dict]] = {}
        for r in all_results:
            qtype = r['_sample'].question_type.value
            by_type.setdefault(qtype, []).append(r)

        for qtype, type_results in by_type.items():
            tn = len(type_results)
            report.by_type[qtype] = {
                'precision_at_k': sum(r['precision'] for r in type_results) / tn,
                'recall_at_k': sum(r['recall'] for r in type_results) / tn,
                'mrr': sum(r['mrr'] for r in type_results) / tn,
                'ndcg': sum(r['ndcg'] for r in type_results) / tn,
            }

    # 失败案例分析
    failed = []
    for r in all_results:
        sample = r['_sample']
        if r['recall'] < 0.5:
            # 分类失败原因
            if r['num_results'] == 0:
                reason = '检索无结果'
            elif r['precision'] == 0.0:
                reason = '结果不相关'
            else:
                reason = '排序错误（相关文档排名靠后）'

            failed.append({
                'sample_id': sample.id,
                'question': sample.question,
                'question_type': sample.question_type.value,
                'difficulty': sample.difficulty,
                'evidence_docs': sample.evidence_docs,
                'failure_reason': reason,
                'recall': r['recall'],
                'precision': r['precision'],
                'first_relevant_rank': r['first_relevant_rank'],
            })

    return report, failed
