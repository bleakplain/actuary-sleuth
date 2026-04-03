#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 量化评估器

分层评估体系：
- RetrievalEvaluator: 独立检索评估（Precision@K, Recall@K, MRR, NDCG, 冗余率）
- GenerationEvaluator: 独立生成评估（RAGAS 可用时使用 RAGAS，否则使用轻量级 token 覆盖率指标）
"""
import math
import re
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType
from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_RAGAS_METRICS = ('faithfulness', 'answer_relevancy', 'answer_correctness')

_ANSWER_SENTENCE_PATTERN = re.compile(r'[^。！？\n]+[。！？\n]?')

_SEMANTIC_RELEVANCE_THRESHOLD = 0.65
_SENTENCE_COVERAGE_THRESHOLD = 0.4

_embed_model_cache: Optional[Any] = None


def _get_embed_model():
    global _embed_model_cache
    if _embed_model_cache is not None:
        return _embed_model_cache
    try:
        from lib.rag_engine.llamaindex_adapter import get_embedding_model
        from lib.config import get_embed_llm_config
        _embed_model_cache = get_embedding_model(get_embed_llm_config())
        return _embed_model_cache
    except Exception as e:
        logger.warning(f"Embedding 模型加载失败，将仅使用关键词匹配: {e}")
        return None


def _compute_embedding_similarity(text_a: str, text_b: str) -> float:
    embed_model = _get_embed_model()
    if embed_model is None:
        return 0.0
    try:
        emb_a = embed_model.get_query_embedding(text_a)
        emb_b = embed_model.get_query_embedding(text_b)
        dot = sum(a * b for a, b in zip(emb_a, emb_b))
        norm_a = math.sqrt(sum(a * a for a in emb_a))
        norm_b = math.sqrt(sum(b * b for b in emb_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
    except Exception as e:
        logger.debug(f"Embedding 相似度计算失败: {e}")
        return 0.0


@dataclass
class RetrievalEvalReport:
    """检索评估报告"""
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    context_relevance: float = 0.0
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'precision_at_k': self.precision_at_k,
            'recall_at_k': self.recall_at_k,
            'mrr': self.mrr,
            'ndcg': self.ndcg,
            'redundancy_rate': self.redundancy_rate,
            'context_relevance': self.context_relevance,
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
        print(f"  Context Relevance: {self.context_relevance:.3f}")

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
            print("  无生成评估结果")

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


def _contains_keyword(content: str, keywords: List[str]) -> bool:
    return any(kw in content for kw in keywords if len(kw) >= 2)


def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    if evidence_keywords:
        long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
        matched = sum(1 for kw in long_keywords if kw in content)
        required = min(2, len(long_keywords))
        if matched >= required:
            return True

    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set and evidence_keywords:
        if _contains_keyword(content, evidence_keywords):
            return True

    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if _contains_keyword(content, evidence_keywords):
                        return True
                elif source_file and source_file in doc_set:
                    return True

    if evidence_keywords:
        query_text = ' '.join(evidence_keywords)
        similarity = _compute_embedding_similarity(query_text, content)
        if similarity >= _SEMANTIC_RELEVANCE_THRESHOLD:
            return True

    return False


def _tokenize_to_set(text: str) -> Optional[Set[str]]:
    """分词并返回 token 集合，空文本返回 None"""
    if not text:
        return None
    tokens = set(tokenize_chinese(text))
    return tokens if tokens else None


def _jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _compute_token_jaccard(text_a: str, text_b: str) -> float:
    return _jaccard_similarity(
        _tokenize_to_set(text_a) or set(),
        _tokenize_to_set(text_b) or set(),
    )


def _compute_redundancy_rate(results: List[Dict[str, Any]]) -> float:
    if len(results) <= 1:
        return 0.0

    valid_sets: List[Set[str]] = [
        ts for r in results
        if (ts := _tokenize_to_set(r.get('content', ''))) is not None
    ]
    n = len(valid_sets)
    if n <= 1:
        return 0.0

    redundant_count = 0

    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard_similarity(valid_sets[i], valid_sets[j]) > 0.6:
                redundant_count += 1

    return redundant_count / (n * (n - 1) / 2)


def _token_bigrams(text: str) -> Set[str]:
    tokens = tokenize_chinese(text)
    return {tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1)} if len(tokens) >= 2 else set()


def _bigram_overlap(bigrams_a: Set[str], bigrams_b: Set[str]) -> float:
    if not bigrams_a or not bigrams_b:
        return 0.0
    covered = bigrams_a & bigrams_b
    return len(covered) / len(bigrams_a)


def _compute_context_relevance(query: str, results: List[Dict[str, Any]]) -> float:
    """计算检索上下文中与问题 query 的 bigram 重叠度"""
    if not query or not results:
        return 0.0
    query_bigrams = _token_bigrams(query)
    if not query_bigrams:
        return 0.0
    context_bigrams: Set[str] = set()
    for r in results:
        content = r.get('content', '')
        if content:
            context_bigrams |= _token_bigrams(content)
    if not context_bigrams:
        return 0.0
    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)


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
                'context_relevance': 0.0,
                'first_relevant_rank': None,
                'num_results': 0,
            }

        # 判断每个结果是否相关
        relevance = [
            1 if _is_relevant(r, sample.evidence_docs, sample.evidence_keywords) else 0
            for r in results
        ]

        precision = sum(relevance) / len(relevance)

        recall = sum(relevance) / len(sample.evidence_docs) if sample.evidence_docs else 0.0

        mrr = 0.0
        first_relevant_rank = None
        for rank, rel in enumerate(relevance, 1):
            if rel == 1:
                mrr = 1.0 / rank
                first_relevant_rank = rank
                break

        # NDCG: 二值相关性下 DCG = IDCG，所以 NDCG = DCG / IDCG
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
        # Ideal DCG: 所有相关结果排在最前
        n_relevant = min(sum(relevance), len(relevance))
        ideal_relevance = [1] * n_relevant + [0] * (len(relevance) - n_relevant)
        idcg = sum(
            rel / math.log2(rank + 1)
            for rank, rel in enumerate(ideal_relevance, 1)
        )
        ndcg = dcg / idcg if idcg > 0 else 0.0

        redundancy = _compute_redundancy_rate(results)

        context_relevance = _compute_context_relevance(sample.question, results)

        return {
            'sample_id': sample.id,
            'precision': precision,
            'recall': recall,
            'mrr': mrr,
            'ndcg': ndcg,
            'redundancy_rate': redundancy,
            'context_relevance': context_relevance,
            'first_relevant_rank': first_relevant_rank,
            'num_results': len(results),
        }

    def evaluate_batch(
        self,
        samples: List[EvalSample],
        top_k: int = 5,
    ) -> Tuple[RetrievalEvalReport, List[Dict[str, Any]]]:
        """批量评估检索质量

        Returns:
            (RetrievalEvalReport, List[Dict]) — 汇总报告和每条样本的评估结果
        """
        all_results: List[Dict[str, Any]] = []
        by_type_results: Dict[str, List[Dict[str, Any]]] = {}

        for sample in samples:
            result = self.evaluate(sample, top_k=top_k)
            all_results.append(result)

            qtype = sample.question_type.value
            by_type_results.setdefault(qtype, []).append(result)

        if not all_results:
            return RetrievalEvalReport(), []

        n = len(all_results)
        report = RetrievalEvalReport(
            precision_at_k=sum(r['precision'] for r in all_results) / n,
            recall_at_k=sum(r['recall'] for r in all_results) / n,
            mrr=sum(r['mrr'] for r in all_results) / n,
            ndcg=sum(r['ndcg'] for r in all_results) / n,
            redundancy_rate=sum(r['redundancy_rate'] for r in all_results) / n,
            context_relevance=sum(r['context_relevance'] for r in all_results) / n,
        )

        for qtype, type_results in by_type_results.items():
            tn = len(type_results)
            report.by_type[qtype] = {
                'precision_at_k': sum(r['precision'] for r in type_results) / tn,
                'recall_at_k': sum(r['recall'] for r in type_results) / tn,
                'mrr': sum(r['mrr'] for r in type_results) / tn,
                'ndcg': sum(r['ndcg'] for r in type_results) / tn,
            }

        return report, all_results


class GenerationEvaluator:
    """生成质量评估器

    RAGAS 可用时使用 RAGAS 批量评估，不可用时使用轻量级 token 覆盖率指标。

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
                "RAGAS 未安装，将使用轻量级指标进行生成评估。"
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

        RAGAS 可用时使用 RAGAS 评估，否则使用轻量级指标。
        """
        if not self._ragas_available:
            return self._lightweight_evaluate(sample, contexts, answer)

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
            logger.info("RAGAS 不可用，使用轻量级指标进行生成评估")
            return self._lightweight_evaluate_batch(engine, samples)

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

        for column in _RAGAS_METRICS:
            if column in df.columns:
                values = df[column].dropna()
                if len(values) > 0:
                    setattr(report, column, float(values.mean()))

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
            for column in _RAGAS_METRICS:
                if column in type_df.columns:
                    values = type_df[column].dropna()
                    if len(values) > 0:
                        type_metrics[column] = float(values.mean())

            if type_metrics:
                report.by_type[qtype] = type_metrics

        return report

    def _lightweight_evaluate(
        self,
        sample: EvalSample,
        contexts: List[str],
        answer: str,
    ) -> Dict[str, float]:
        """轻量级单条生成质量评估（无需 LLM）

        - faithfulness: 答案 token 对检索上下文 token 的覆盖率
        - answer_relevancy: 答案与标准答案的 token Jaccard 相似度
        - answer_correctness: 答案关键 token 与标准答案的覆盖率
        """
        faithfulness = self._compute_faithfulness(contexts, answer)
        relevancy = _compute_token_jaccard(answer, sample.ground_truth)
        correctness = self._compute_correctness(answer, sample.ground_truth)

        return {
            'faithfulness': faithfulness,
            'answer_relevancy': relevancy,
            'answer_correctness': correctness,
        }

    def _lightweight_evaluate_batch(
        self,
        engine,
        samples: List[EvalSample],
    ) -> GenerationEvalReport:
        """轻量级批量生成质量评估"""
        all_metrics: List[Dict[str, float]] = []
        by_type_metrics: Dict[str, List[Dict[str, float]]] = {}

        for sample in samples:
            result = engine.ask(sample.question, include_sources=True)
            answer = result.get('answer', '')
            contexts = [s.get('content', '') for s in result.get('sources', [])]

            metrics = self._lightweight_evaluate(sample, contexts, answer)
            all_metrics.append(metrics)

            qtype = sample.question_type.value
            by_type_metrics.setdefault(qtype, []).append(metrics)

        if not all_metrics:
            return GenerationEvalReport()

        n = len(all_metrics)
        report = GenerationEvalReport(
            faithfulness=sum(m['faithfulness'] for m in all_metrics) / n,
            answer_relevancy=sum(m['answer_relevancy'] for m in all_metrics) / n,
            answer_correctness=sum(m['answer_correctness'] for m in all_metrics) / n,
        )

        for qtype, type_metrics_list in by_type_metrics.items():
            tn = len(type_metrics_list)
            report.by_type[qtype] = {
                'faithfulness': sum(m['faithfulness'] for m in type_metrics_list) / tn,
                'answer_relevancy': sum(m['answer_relevancy'] for m in type_metrics_list) / tn,
                'answer_correctness': sum(m['answer_correctness'] for m in type_metrics_list) / tn,
            }

        return report

    @staticmethod
    def _compute_faithfulness(contexts: List[str], answer: str) -> float:
        if not contexts or not answer:
            return 0.0

        context_text = ' '.join(contexts)
        context_bigrams = _token_bigrams(context_text)
        answer_bigrams = _token_bigrams(answer)

        sentences = _ANSWER_SENTENCE_PATTERN.findall(answer)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
        if not sentences:
            return _bigram_overlap(answer_bigrams, context_bigrams)

        supported_count = 0
        for sentence in sentences:
            sentence_bigrams = _token_bigrams(sentence)
            if not sentence_bigrams:
                continue
            covered = sentence_bigrams & context_bigrams
            if len(covered) / len(sentence_bigrams) >= _SENTENCE_COVERAGE_THRESHOLD:
                supported_count += 1

        sentence_coverage = supported_count / len(sentences)
        bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)
        return 0.7 * sentence_coverage + 0.3 * bigram_overlap

    @staticmethod
    def _compute_correctness(answer: str, ground_truth: str) -> float:
        if not answer or not ground_truth:
            return 0.0
        return _bigram_overlap(_token_bigrams(ground_truth), _token_bigrams(answer))


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
    report, all_results = evaluator.evaluate_batch(samples, top_k=top_k)

    failed = []
    for sample, result in zip(samples, all_results):
        if result['recall'] < 0.5:
            if result['num_results'] == 0:
                reason = '检索无结果'
            elif result['precision'] == 0.0:
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
                'recall': result['recall'],
                'precision': result['precision'],
                'first_relevant_rank': result['first_relevant_rank'],
            })

    return report, failed
