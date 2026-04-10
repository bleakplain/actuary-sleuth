#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 量化评估器

分层评估体系：
- RetrievalEvaluator: 独立检索评估（Precision@K, Recall@K, MRR, NDCG, 冗余率）
- GenerationEvaluator: 独立生成评估（依赖 RAGAS，需安装 ragas 包）
"""
import math
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType
from .tokenizer import tokenize_chinese, tokenize_to_set as _tokenize_to_set, jaccard_similarity as _jaccard_similarity

logger = logging.getLogger(__name__)

_RAGAS_METRICS = ('faithfulness', 'answer_relevancy', 'answer_correctness')

_ANSWER_SENTENCE_PATTERN = re.compile(r'[^。！？\n]+[。！？\n]?')

_SEMANTIC_RELEVANCE_THRESHOLD = 0.65
_SEMANTIC_COVERAGE_THRESHOLD = 0.7
_SENTENCE_COVERAGE_THRESHOLD = 0.4

_embed_model: Optional[Any] = None


def _get_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    try:
        from lib.rag_engine.llamaindex_adapter import _create_embedding_model
        from lib.config import get_embed_llm_config
        _embed_model = _create_embedding_model(get_embed_llm_config())
        return _embed_model
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


@dataclass(frozen=True)
class RetrievalEvalReport:
    """检索评估报告"""
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    context_relevance: float = 0.0
    rejection_rate: Optional[float] = None
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'precision_at_k': self.precision_at_k,
            'recall_at_k': self.recall_at_k,
            'mrr': self.mrr,
            'ndcg': self.ndcg,
            'redundancy_rate': self.redundancy_rate,
            'context_relevance': self.context_relevance,
            'by_type': self.by_type,
        }
        if self.rejection_rate is not None:
            result['rejection_rate'] = self.rejection_rate
        return result

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


@dataclass(frozen=True)
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

        if all(v is None for v in [self.faithfulness, self.answer_relevancy, self.answer_correctness]):
            print("  无生成评估结果")

        if self.by_type:
            print("\n  按题型分组:")
            for qtype, metrics in self.by_type.items():
                print(f"    [{qtype}]")
                for metric_name, value in metrics.items():
                    if value is not None:
                        print(f"      {metric_name}: {value:.3f}")

        print("=" * 60 + "\n")


@dataclass(frozen=True)
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


def _normalize_doc_name(doc: str) -> str:
    return doc.replace('.md', '').replace('_', '').strip()


def _match_source_to_evidence(source_file: str, evidence_docs: List[str]) -> Optional[str]:
    if not source_file or not evidence_docs:
        return None
    src_normalized = _normalize_doc_name(source_file)
    for doc in evidence_docs:
        if src_normalized == _normalize_doc_name(doc):
            return doc
        if '/' in source_file or '\\' in source_file:
            fname = Path(source_file).stem.replace('_', '')
            if fname == _normalize_doc_name(doc):
                return doc
    return None


def _contains_keyword(content: str, keywords: List[str]) -> bool:
    return any(kw in content for kw in keywords if len(kw) >= 2)


def _build_synonym_reverse_index() -> Dict[str, Set[str]]:
    from .query_preprocessor import _INSURANCE_SYNONYMS
    reverse: Dict[str, Set[str]] = {}
    for standard, variants in _INSURANCE_SYNONYMS.items():
        for variant in variants:
            if variant not in reverse:
                reverse[variant] = set()
            reverse[variant].add(standard)
            reverse[variant].update(variants)
    return reverse


_SYNONYM_REVERSE_INDEX: Dict[str, Set[str]] = _build_synonym_reverse_index()


def _expand_keywords_with_synonyms(keywords: List[str]) -> Set[str]:
    from .query_preprocessor import _INSURANCE_SYNONYMS
    expanded: Set[str] = set(keywords)
    for kw in keywords:
        if kw in _INSURANCE_SYNONYMS:
            expanded.update(_INSURANCE_SYNONYMS[kw])
        if kw in _SYNONYM_REVERSE_INDEX:
            expanded.update(_SYNONYM_REVERSE_INDEX[kw])
    return expanded


def _build_generic_keywords() -> Set[str]:
    import json
    domain_terms: Set[str] = set()
    synonyms_file = Path(__file__).parent / 'data' / 'synonyms.json'
    if synonyms_file.exists():
        with open(synonyms_file, 'r', encoding='utf-8') as f:
            for standard, variants in json.load(f).items():
                domain_terms.add(standard)
                domain_terms.update(variants)
    dict_file = Path(__file__).parent / 'data' / 'insurance_dict.txt'
    if dict_file.exists():
        with open(dict_file, 'r', encoding='utf-8') as f:
            for line in f:
                term = line.strip().split()[0] if line.strip() else ''
                if term:
                    domain_terms.add(term)
    generic = {
        '保险', '条款', '规定', '办法', '通知', '要求', '内容',
        '相关', '应当', '可以', '不得', '按照', '根据', '关于',
        '合同', '产品', '公司', '投保', '被保', '人身', '财产',
    }
    return generic - domain_terms


GENERIC_KEYWORDS: Set[str] = _build_generic_keywords()


def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    """判定检索结果是否与评估样本相关。

    匹配层级（快速确定性 → 慢速概率性）：
    1. 领域关键词匹配（≥2个命中即相关，单关键词需 source_file 匹配）
    2. source_file + 任意关键词匹配
    3. law_name + 关键词/doc 匹配
    4. 同义词扩展关键词匹配
    5. embedding 语义相似度

    注意：precision 使用本函数的宽松判定，recall 使用 _match_source_to_evidence
    的严格文档名匹配，二者衡量不同维度。
    """
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    doc_set = set(evidence_docs)

    if evidence_keywords:
        domain_kw = [kw for kw in evidence_keywords
                     if len(kw) >= 2 and kw not in GENERIC_KEYWORDS]
        generic_kw = [kw for kw in evidence_keywords
                      if len(kw) >= 2 and kw in GENERIC_KEYWORDS]
        domain_matched = sum(1 for kw in domain_kw if kw in content)
        generic_matched = sum(1 for kw in generic_kw if kw in content)

        if domain_matched >= 2:
            return True
        if domain_matched >= 1 and generic_matched >= 1 and source_file in doc_set:
            return True
        if len(domain_kw) == 1 and domain_matched >= 1 and source_file in doc_set:
            return True

    if source_file and source_file in doc_set and evidence_keywords:
        if _contains_keyword(content, evidence_keywords):
            return True

    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = _normalize_doc_name(doc)
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if _contains_keyword(content, evidence_keywords):
                        return True
                elif source_file and source_file in doc_set:
                    return True

    if evidence_keywords:
        expanded = _expand_keywords_with_synonyms(evidence_keywords)
        expanded_long = [kw for kw in expanded if len(kw) >= 2 and kw not in GENERIC_KEYWORDS]
        matched = sum(1 for kw in expanded_long if kw in content)
        if matched >= 2:
            return True
        if matched >= 1 and source_file in doc_set:
            return True

    if evidence_keywords:
        query_text = ' '.join(evidence_keywords)
        similarity = _compute_embedding_similarity(query_text, content)
        if similarity >= _SEMANTIC_RELEVANCE_THRESHOLD:
            return True

    return False


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


def compute_faithfulness(contexts: List[str], answer: str) -> float:
    """评估答案对检索上下文的忠实度。embedding 可用时使用语义相似度，否则回退 bigram。"""
    if not contexts or not answer:
        return 0.0

    context_text = ' '.join(contexts)

    sentences = _ANSWER_SENTENCE_PATTERN.findall(answer)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

    embed_model = _get_embed_model()
    if embed_model and sentences:
        supported_count = 0
        for sentence in sentences:
            similarity = _compute_embedding_similarity(sentence, context_text)
            if similarity >= _SEMANTIC_COVERAGE_THRESHOLD:
                supported_count += 1
        sentence_coverage = supported_count / len(sentences)

        answer_bigrams = _token_bigrams(answer)
        context_bigrams = _token_bigrams(context_text)
        bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)

        return 0.7 * sentence_coverage + 0.3 * bigram_overlap

    context_bigrams = _token_bigrams(context_text)
    answer_bigrams = _token_bigrams(answer)

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

        matched_docs: Set[str] = set()
        relevance = []
        for r in results:
            is_rel = _is_relevant(r, sample.evidence_docs, sample.evidence_keywords)
            relevance.append(1 if is_rel else 0)
            if is_rel:
                matched_doc = _match_source_to_evidence(
                    r.get('source_file', ''), sample.evidence_docs
                )
                if matched_doc:
                    matched_docs.add(matched_doc)

        precision = sum(relevance) / len(relevance)

        if not sample.evidence_docs:
            recall = 0.0
        else:
            recall = len(matched_docs) / len(sample.evidence_docs)

        mrr = 0.0
        first_relevant_rank = None
        for rank, rel in enumerate(relevance, 1):
            if rel == 1:
                mrr = 1.0 / rank
                first_relevant_rank = rank
                break

        # NDCG: IDCG 将所有相关结果排在最前，DCG 除以 IDCG 得到归一化分数
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
        recall_results = [
            r for r, s in zip(all_results, samples) if s.evidence_docs
        ]
        recall_avg = (
            sum(r['recall'] for r in recall_results) / len(recall_results)
            if recall_results else 0.0
        )

        unanswerable_results = [
            r for r, s in zip(all_results, samples)
            if s.question_type == QuestionType.UNANSWERABLE
        ]
        rejection_rate: Optional[float] = None
        if unanswerable_results:
            rejected = sum(1 for r in unanswerable_results if r['precision'] == 0.0)
            rejection_rate = rejected / len(unanswerable_results)

        by_type: Dict[str, Dict[str, float]] = {}
        for qtype, type_results in by_type_results.items():
            tn = len(type_results)
            by_type[qtype] = {
                'precision_at_k': sum(r['precision'] for r in type_results) / tn,
                'recall_at_k': sum(r['recall'] for r in type_results) / tn,
                'mrr': sum(r['mrr'] for r in type_results) / tn,
                'ndcg': sum(r['ndcg'] for r in type_results) / tn,
            }

        report = RetrievalEvalReport(
            precision_at_k=sum(r['precision'] for r in all_results) / n,
            recall_at_k=recall_avg,
            mrr=sum(r['mrr'] for r in all_results) / n,
            ndcg=sum(r['ndcg'] for r in all_results) / n,
            redundancy_rate=sum(r['redundancy_rate'] for r in all_results) / n,
            context_relevance=sum(r['context_relevance'] for r in all_results) / n,
            rejection_rate=rejection_rate,
            by_type=by_type,
        )

        return report, all_results


class GenerationEvaluator:
    """生成质量评估器（依赖 RAGAS，需安装 ragas 包）

    Args:
        rag_engine: 用于生成答案的 RAG 引擎
        llm: RAGAS 评估用 LLM，由调用方注入
        embeddings: RAGAS 评估用 Embedding，由调用方注入
    """

    def __init__(self, rag_engine=None, llm=None, embeddings=None):
        self.rag_engine = rag_engine
        self._eval_llm = llm
        self._eval_embeddings = embeddings

        try:
            from ragas import evaluate as ragas_evaluate  # noqa: F401
            from ragas.metrics import (  # noqa: F401
                faithfulness,
                answer_relevancy,
                answer_correctness,
            )
            self._ragas_evaluate = ragas_evaluate
            self._ragas_metrics = [faithfulness, answer_relevancy, answer_correctness]
        except ImportError as e:
            raise ImportError(
                "RAGAS 是生成评估的必需依赖。请安装: pip install ragas"
            ) from e

    def evaluate(
        self,
        sample: EvalSample,
        contexts: List[str],
        answer: str,
    ) -> Dict[str, float]:
        """评估单条样本的生成质量"""
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

        return self._ragas_evaluate_batch(engine, samples)

    def _ragas_evaluate_batch(
        self,
        engine,
        samples: List[EvalSample],
    ) -> GenerationEvalReport:
        from datasets import Dataset

        questions = []
        contexts_list = []
        answers = []
        ground_truths = []
        question_types = []

        for sample in samples:
            result = engine.ask(sample.question, include_sources=True)
            answer = result.get('answer', '')
            contexts = [s.get('content', '') for s in result.get('sources', [])]

            questions.append(sample.question)
            contexts_list.append(contexts)
            answers.append(answer)
            ground_truths.append(sample.ground_truth)
            question_types.append(sample.question_type.value)

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

        metric_values: Dict[str, Optional[float]] = {
            'faithfulness': None, 'answer_relevancy': None, 'answer_correctness': None,
        }
        for column in _RAGAS_METRICS:
            if column in df.columns:
                values = df[column].dropna()
                if len(values) > 0:
                    metric_values[column] = float(values.mean())

        by_type: Dict[str, Dict[str, float]] = {}
        for qtype in set(question_types):
            type_mask = [qt == qtype for qt in question_types]
            type_metrics: Dict[str, float] = {}
            for column in _RAGAS_METRICS:
                if column in df.columns:
                    type_values = df[column][type_mask].dropna()
                    if len(type_values) > 0:
                        type_metrics[column] = float(type_values.mean())
            if type_metrics:
                by_type[qtype] = type_metrics

        report = GenerationEvalReport(
            faithfulness=metric_values['faithfulness'],
            answer_relevancy=metric_values['answer_relevancy'],
            answer_correctness=metric_values['answer_correctness'],
            by_type=by_type,
        )

        return report



def evaluate_retrieval(
    rag_engine,
    samples: List[EvalSample],
    top_k: int = 5,
) -> Tuple[RetrievalEvalReport, List[Dict[str, Any]]]:
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
