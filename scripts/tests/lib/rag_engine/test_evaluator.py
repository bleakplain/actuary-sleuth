#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 评估器单元测试

测试评估数据集、检索指标计算、生成评估器。
"""
from unittest.mock import MagicMock, patch

import pytest

from lib.rag_engine.eval_dataset import (
    EvalSample,
    QuestionType,
    DEFAULT_DATASET_PATH,
    create_default_eval_dataset,
    load_eval_dataset,
    save_eval_dataset,
)
from lib.rag_engine.evaluator import (
    RetrievalEvaluator,
    GenerationEvaluator,
    RetrievalEvalReport,
    GenerationEvalReport,
    RAGEvalReport,
    _is_relevant,
    _compute_token_jaccard,
    _compute_redundancy_rate,
    run_retrieval_evaluation,
)


@pytest.fixture
def sample_eval():
    """基础测试用 EvalSample"""
    return EvalSample(
        id="test001",
        question="健康保险的等待期有什么规定？",
        ground_truth="等待期不应与健康人群有过大差距",
        evidence_docs=["05_健康保险产品开发.md"],
        evidence_keywords=["等待期", "既往症", "健康人群"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="健康保险",
    )


@pytest.fixture
def mock_rag_engine():
    """模拟 RAG 引擎"""
    engine = MagicMock()
    return engine


@pytest.fixture
def relevant_results():
    return [
        {
            'content': '等待期规定：既往症人群的等待期不应与健康人群有过大差距',
            'law_name': '健康保险产品开发',
            'category': '健康保险',
            'source_file': '05_健康保险产品开发.md',
            'score': 0.95,
        },
        {
            'content': '对于既往症严重程度的区分，相关定义需明确',
            'law_name': '健康保险产品开发',
            'category': '健康保险',
            'source_file': '05_健康保险产品开发.md',
            'score': 0.85,
        },
    ]


@pytest.fixture
def irrelevant_results():
    return [
        {
            'content': '分红型保险的分红水平不确定',
            'law_name': '分红型人身保险',
            'category': '分红保险',
            'source_file': '07_分红型人身保险.md',
            'score': 0.5,
        },
        {
            'content': '互联网保险业务需要网络安全保护',
            'law_name': '互联网保险产品',
            'category': '互联网保险',
            'source_file': '10_互联网保险产品.md',
            'score': 0.3,
        },
    ]


@pytest.fixture
def mixed_results(relevant_results, irrelevant_results):
    """混合检索结果（2 相关 + 2 不相关）"""
    return relevant_results + irrelevant_results





class TestEvalDataset:

    def test_load_default_dataset(self):
        dataset = create_default_eval_dataset()
        assert len(dataset) == 30

    def test_eval_sample_fields(self, sample_eval):
        assert sample_eval.id == "test001"
        assert sample_eval.question_type == QuestionType.FACTUAL
        assert sample_eval.difficulty == "easy"
        assert sample_eval.topic == "健康保险"
        assert len(sample_eval.evidence_docs) >= 1
        assert len(sample_eval.evidence_keywords) >= 1

    def test_question_type_coverage(self):
        dataset = create_default_eval_dataset()
        types = set(s.question_type for s in dataset)
        assert QuestionType.FACTUAL in types
        assert QuestionType.MULTI_HOP in types
        assert QuestionType.NEGATIVE in types
        assert QuestionType.COLLOQUIAL in types

    def test_question_type_distribution(self):
        dataset = create_default_eval_dataset()
        type_counts = {}
        for s in dataset:
            t = s.question_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        assert type_counts['factual'] >= 10
        assert type_counts['multi_hop'] >= 6
        assert type_counts['negative'] >= 4
        assert type_counts['colloquial'] >= 3

    def test_to_dict_roundtrip(self, sample_eval):
        d = sample_eval.to_dict()
        assert isinstance(d, dict)
        assert d['question_type'] == 'factual'
        assert d['id'] == 'test001'

        restored = EvalSample.from_dict(d)
        assert restored == sample_eval

    def test_load_eval_dataset_from_list(self, tmp_path):
        import json
        data = [sample_eval.to_dict() for sample_eval in create_default_eval_dataset()[:3]]
        path = tmp_path / "test_dataset.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

        loaded = load_eval_dataset(str(path))
        assert len(loaded) == 3
        assert all(isinstance(s, EvalSample) for s in loaded)

    def test_load_eval_dataset_from_dict(self, tmp_path):
        import json
        samples = [sample_eval.to_dict() for sample_eval in create_default_eval_dataset()[:2]]
        data = {'samples': samples}
        path = tmp_path / "test_dataset.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

        loaded = load_eval_dataset(str(path))
        assert len(loaded) == 2

    def test_frozen_dataclass(self, sample_eval):
        with pytest.raises(AttributeError):
            sample_eval.id = "other"

    def test_default_dataset_path_defined(self):
        assert DEFAULT_DATASET_PATH is not None
        assert DEFAULT_DATASET_PATH.endswith('eval_dataset.json')

    def test_load_eval_dataset_default_path_fallback(self):
        dataset = load_eval_dataset()
        assert len(dataset) == 30

    def test_save_and_load_roundtrip(self, tmp_path):
        samples = create_default_eval_dataset()[:3]
        path = tmp_path / "test_eval.json"
        save_eval_dataset(samples, str(path))

        loaded = load_eval_dataset(str(path))
        assert len(loaded) == 3
        assert loaded[0] == samples[0]

    def test_save_creates_parent_dirs(self, tmp_path):
        nested_path = tmp_path / "sub" / "dir" / "eval.json"
        save_eval_dataset(create_default_eval_dataset()[:1], str(nested_path))
        assert nested_path.exists()





class TestRetrievalMetrics:

    def test_is_relevant_source_file_needs_keyword(self, sample_eval):
        result = {
            'content': '不相关内容',
            'law_name': '未知',
            'source_file': '05_健康保险产品开发.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, []) is False

    def test_is_relevant_source_file_with_keyword(self, sample_eval):
        result = {
            'content': '等待期规定相关内容',
            'law_name': '未知',
            'source_file': '05_健康保险产品开发.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, sample_eval.evidence_keywords) is True

    def test_is_relevant_keyword_match(self, sample_eval):
        result = {
            'content': '等待期规定相关内容，既往症人群',
            'law_name': '未知',
            'source_file': 'other.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, sample_eval.evidence_keywords) is True

    def test_is_relevant_single_keyword_not_enough(self, sample_eval):
        result = {
            'content': '等待期相关内容',
            'law_name': '未知',
            'source_file': 'other.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, ['等待期']) is True

    def test_is_relevant_law_name_needs_keyword(self, sample_eval):
        """law_name 匹配但无 keyword 和 source_file 时不算 relevant"""
        result = {
            'content': '不相关内容',
            'law_name': '05健康保险产品开发',
            'source_file': '',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, []) is False

    def test_is_relevant_law_name_with_keyword(self, sample_eval):
        result = {
            'content': '等待期相关内容',
            'law_name': '05健康保险产品开发',
            'source_file': '',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, sample_eval.evidence_keywords) is True

    def test_is_relevant_no_match(self, irrelevant_results, sample_eval):
        assert _is_relevant(irrelevant_results[0], sample_eval.evidence_docs, sample_eval.evidence_keywords) is False

    def test_is_relevant_substring_no_false_positive(self):
        result = {
            'content': '无关内容',
            'law_name': '健康保险产品开发',
            'source_file': '',
        }
        assert _is_relevant(result, ["07_分红型人身保险.md"], []) is False

    def test_is_relevant_empty_keywords_and_docs(self, sample_eval):
        result = {'content': '任意内容', 'law_name': '未知', 'source_file': ''}
        assert _is_relevant(result, [], []) is False

    def test_token_jaccard_identical(self):
        assert _compute_token_jaccard(
            "保险合同是投保人与保险人约定保险权利义务关系的协议",
            "保险合同是投保人与保险人约定保险权利义务关系的协议",
        ) == 1.0

    def test_token_jaccard_disjoint(self):
        jaccard = _compute_token_jaccard("保险公司应当按照规定提取保证金", "意外伤害保险属于定额给付型")
        assert jaccard < 0.3

    def test_token_jaccard_partial(self):
        jaccard = _compute_token_jaccard(
            "保险公司应当按照国务院保险监督管理机构的规定提取保证金",
            "保险公司应当提取保证金用于保障被保险人利益",
        )
        assert 0.2 < jaccard < 0.8

    def test_token_jaccard_empty(self):
        assert _compute_token_jaccard("", "保险合同") == 0.0
        assert _compute_token_jaccard("保险合同", "") == 0.0

    def test_redundancy_rate_no_redundancy(self):
        results = [
            {'content': '保险合同是投保人与保险人约定保险权利义务关系的协议'},
            {'content': '保险公司应当按照国务院保险监督管理机构的规定提取保证金'},
            {'content': '受益人是指人身保险合同中由被保险人或者投保人指定的享有保险金请求权的人'},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate == 0.0

    def test_redundancy_rate_high_redundancy(self):
        content = "这是一段非常长的重复内容" * 20
        results = [
            {'content': content},
            {'content': content + "微小差异"},
            {'content': content},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate > 0.0

    def test_redundancy_rate_single_result(self):
        results = [{'content': '只有一条结果'}]
        assert _compute_redundancy_rate(results) == 0.0

    def test_redundancy_rate_empty(self):
        assert _compute_redundancy_rate([]) == 0.0





class TestRetrievalEvaluator:

    def test_evaluate_single_sample_all_relevant(
        self, mock_rag_engine, sample_eval, relevant_results
    ):
        mock_rag_engine.search.return_value = relevant_results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=2)

        assert result['precision'] == 1.0
        assert result['recall'] == 1.0
        assert result['mrr'] == 1.0
        assert result['ndcg'] == 1.0
        assert result['first_relevant_rank'] == 1
        assert result['num_results'] == 2

    def test_evaluate_single_sample_partial_relevant(
        self, mock_rag_engine, sample_eval, mixed_results
    ):
        mock_rag_engine.search.return_value = mixed_results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=4)

        assert result['precision'] == pytest.approx(0.5)
        assert result['recall'] == pytest.approx(1.0)
        assert result['mrr'] == 1.0  # 第一条就命中
        assert result['ndcg'] > 0.0
        assert result['first_relevant_rank'] == 1
        assert result['num_results'] == 4

    def test_evaluate_single_sample_all_irrelevant(
        self, mock_rag_engine, sample_eval, irrelevant_results
    ):
        mock_rag_engine.search.return_value = irrelevant_results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=2)

        assert result['precision'] == 0.0
        assert result['recall'] == 0.0
        assert result['mrr'] == 0.0
        assert result['ndcg'] == 0.0
        assert result['first_relevant_rank'] is None

    def test_evaluate_single_sample_no_results(self, mock_rag_engine, sample_eval):
        mock_rag_engine.search.return_value = []

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=5)

        assert result['precision'] == 0.0
        assert result['recall'] == 0.0
        assert result['mrr'] == 0.0
        assert result['ndcg'] == 0.0
        assert result['num_results'] == 0

    def test_mrr_third_position(self, mock_rag_engine, sample_eval):
        results = [
            {'content': '不相关内容一', 'law_name': '分红', 'category': '分红', 'source_file': '07_分红型人身保险.md', 'score': 0.5},
            {'content': '不相关内容二', 'law_name': '互联网', 'category': '互联网', 'source_file': '10_互联网保险产品.md', 'score': 0.4},
            {'content': '等待期规定相关内容', 'law_name': '健康', 'category': '健康', 'source_file': '05_健康保险产品开发.md', 'score': 0.9},
        ]
        mock_rag_engine.search.return_value = results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=3)

        assert result['mrr'] == pytest.approx(1.0 / 3.0, abs=0.01)
        assert result['first_relevant_rank'] == 3

    def test_ndcg_imperfect_ranking(self, mock_rag_engine, sample_eval):
        results = [
            {'content': '不相关一', 'law_name': '分红', 'category': '分红', 'source_file': '07_分红型人身保险.md', 'score': 0.5},
            {'content': '等待期相关', 'law_name': '健康', 'category': '健康', 'source_file': '05_健康保险产品开发.md', 'score': 0.9},
            {'content': '不相关二', 'law_name': '互联网', 'category': '互联网', 'source_file': '10_互联网保险产品.md', 'score': 0.3},
            {'content': '既往症相关', 'law_name': '健康', 'category': '健康', 'source_file': '05_健康保险产品开发.md', 'score': 0.8},
        ]
        mock_rag_engine.search.return_value = results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=4)

        assert result['ndcg'] < 1.0
        assert result['ndcg'] > 0.0

    def test_evaluate_batch(self, mock_rag_engine):
        samples = create_default_eval_dataset()[:5]

        mock_rag_engine.search.return_value = [
            {
                'content': '健康保险等待期相关内容',
                'law_name': '健康保险',
                'category': '健康保险',
                'source_file': '05_健康保险产品开发.md',
                'score': 0.9,
            },
            {
                'content': '等待期不应有过大差距',
                'law_name': '健康保险产品开发',
                'category': '健康',
                'source_file': '05_健康保险产品开发.md',
                'score': 0.85,
            },
        ]

        evaluator = RetrievalEvaluator(mock_rag_engine)
        report, _ = evaluator.evaluate_batch(samples, top_k=2)

        assert isinstance(report, RetrievalEvalReport)
        assert report.precision_at_k >= 0.0
        assert report.recall_at_k >= 0.0
        assert report.mrr >= 0.0
        assert report.ndcg >= 0.0
        assert report.redundancy_rate >= 0.0
        assert len(report.by_type) > 0

    def test_by_type_breakdown(self, mock_rag_engine):
        dataset = create_default_eval_dataset()

        mock_rag_engine.search.return_value = [
            {
                'content': '等待期规定相关内容',
                'law_name': '健康保险产品开发',
                'category': '健康保险',
                'source_file': '05_健康保险产品开发.md',
                'score': 0.9,
            },
        ]

        evaluator = RetrievalEvaluator(mock_rag_engine)
        report, _ = evaluator.evaluate_batch(dataset, top_k=1)

        assert 'factual' in report.by_type
        assert 'multi_hop' in report.by_type
        assert 'negative' in report.by_type
        assert 'colloquial' in report.by_type

        for qtype_metrics in report.by_type.values():
            assert 'precision_at_k' in qtype_metrics
            assert 'recall_at_k' in qtype_metrics
            assert 'mrr' in qtype_metrics
            assert 'ndcg' in qtype_metrics

    def test_evaluate_batch_empty(self, mock_rag_engine):
        evaluator = RetrievalEvaluator(mock_rag_engine)
        report, _ = evaluator.evaluate_batch([], top_k=5)

        assert report.precision_at_k == 0.0
        assert report.recall_at_k == 0.0
        assert report.mrr == 0.0
        assert report.ndcg == 0.0





class TestGenerationEvaluator:

    def test_evaluate_without_ragas(self, mock_rag_engine, sample_eval):
        """RAGAS 不可用时使用轻量级指标"""
        with patch.dict('sys.modules', {'ragas': None, 'datasets': None}):
            evaluator = GenerationEvaluator()
            assert evaluator.ragas_available is False

            contexts = ['等待期规定：既往症人群的等待期不应与健康人群有过大差距']
            answer = '健康保险等待期不应与健康人群有过大差距'
            result = evaluator.evaluate(sample_eval, contexts, answer)

            assert 'faithfulness' in result
            assert 'answer_relevancy' in result
            assert 'answer_correctness' in result
            assert 0.0 <= result['faithfulness'] <= 1.0

    def test_evaluate_batch_without_ragas(self, mock_rag_engine):
        """RAGAS 不可用时批量评估返回轻量级指标"""
        mock_rag_engine.ask.return_value = {
            'answer': '等待期不应与健康人群有过大差距',
            'sources': [{'content': '等待期规定：既往症人群的等待期不应与健康人群有过大差距'}],
        }
        samples = create_default_eval_dataset()[:3]

        with patch.dict('sys.modules', {'ragas': None, 'datasets': None}):
            evaluator = GenerationEvaluator()
            report = evaluator.evaluate_batch(samples, mock_rag_engine)

            assert isinstance(report, GenerationEvalReport)
            assert report.faithfulness is not None
            assert report.answer_relevancy is not None
            assert report.answer_correctness is not None
            assert 0.0 <= report.faithfulness <= 1.0

    def test_evaluate_batch_no_engine(self):
        """未提供 RAG 引擎时返回空报告"""
        evaluator = GenerationEvaluator()
        report = evaluator.evaluate_batch([])

        assert isinstance(report, GenerationEvalReport)
        assert report.faithfulness is None

    def test_lightweight_faithfulness_high(self):
        """答案 token 全部出现在上下文中时 faithfulness 接近 1.0"""
        contexts = ['保险合同是投保人与保险人约定保险权利义务关系的协议']
        answer = '保险合同是投保人与保险人约定权利义务关系的协议'
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score > 0.8

    def test_lightweight_faithfulness_low(self):
        """答案包含上下文中没有的 token 时 faithfulness 较低"""
        contexts = ['保险合同是投保人与保险人约定的协议']
        answer = '万能保险的结算利率根据账户价值确定'
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score < 0.5

    def test_lightweight_faithfulness_empty(self):
        assert GenerationEvaluator._compute_faithfulness([], '保险合同') == 0.0
        assert GenerationEvaluator._compute_faithfulness(['上下文'], '') == 0.0

    def test_lightweight_correctness_high(self):
        """答案与标准答案 token 重叠度高时 correctness 接近 1.0"""
        truth = '保险公司应当提取保证金用于保障被保险人利益'
        answer = '保险公司应当提取保证金保障被保险人利益'
        score = GenerationEvaluator._compute_correctness(answer, truth)
        assert score > 0.6

    def test_lightweight_correctness_low(self):
        truth = '保险公司应当按照规定提取保证金'
        answer = '万能保险结算利率根据账户价值确定'
        score = GenerationEvaluator._compute_correctness(answer, truth)
        assert score < 0.3

    def test_lightweight_correctness_empty(self):
        assert GenerationEvaluator._compute_correctness('', '保险合同') == 0.0
        assert GenerationEvaluator._compute_correctness('保险合同', '') == 0.0

    def test_evaluate_with_ragas(self, mock_rag_engine, sample_eval):
        """RAGAS 真实评估：验证 GenerationEvaluator 能正确调用 RAGAS 并返回指标"""
        import os

        if 'ZHIPU_API_KEY' not in os.environ:
            pytest.skip("ZHIPU_API_KEY not set")

        from lib.llm import LLMClientFactory
        from lib.llm.langchain_adapter import ChatAdapter, EmbeddingAdapter

        ragas_llm = ChatAdapter(client=LLMClientFactory.create_eval_llm())
        ragas_embeddings = EmbeddingAdapter(LLMClientFactory.create_embed_llm())

        mock_rag_engine.ask.return_value = {
            'answer': '健康保险等待期不应与健康人群有过大差距',
            'sources': [
                {'content': '等待期规定：既往症人群的等待期不应与健康人群有过大差距', 'score': 0.9},
            ],
        }

        evaluator = GenerationEvaluator(mock_rag_engine, llm=ragas_llm, embeddings=ragas_embeddings)
        if not evaluator.ragas_available:
            pytest.skip("RAGAS not installed")

        report = evaluator.evaluate_batch([sample_eval], mock_rag_engine)

        assert report.faithfulness is not None
        assert 0.0 <= report.faithfulness <= 1.0





class TestRAGEvalReport:

    def test_default_report(self):
        report = RAGEvalReport()
        assert report.total_samples == 0
        assert report.failed_samples == []

        d = report.to_dict()
        assert 'retrieval' in d
        assert 'generation' in d

    def test_report_with_data(self):
        retrieval = RetrievalEvalReport(
            precision_at_k=0.8,
            recall_at_k=0.7,
            mrr=0.9,
            ndcg=0.85,
            redundancy_rate=0.1,
        )
        generation = GenerationEvalReport(
            faithfulness=0.85,
            answer_relevancy=0.80,
        )
        report = RAGEvalReport(
            retrieval=retrieval,
            generation=generation,
            total_samples=30,
            failed_samples=[{'question': 'test', 'failure_reason': 'no results'}],
        )

        d = report.to_dict()
        assert d['retrieval']['precision_at_k'] == 0.8
        assert d['generation']['faithfulness'] == 0.85
        assert d['total_samples'] == 30
        assert len(d['failed_samples']) == 1





class TestRetrievalEvalReport:

    def test_to_dict(self):
        report = RetrievalEvalReport(
            precision_at_k=0.75,
            recall_at_k=0.6,
            mrr=0.8,
            ndcg=0.7,
            redundancy_rate=0.15,
            by_type={'factual': {'precision_at_k': 0.9}},
        )
        d = report.to_dict()
        assert d['precision_at_k'] == 0.75
        assert d['by_type']['factual']['precision_at_k'] == 0.9

    def test_print_report(self, capsys):
        report = RetrievalEvalReport(precision_at_k=0.8)
        report.print_report()
        captured = capsys.readouterr()
        assert 'Precision@K' in captured.out
        assert '0.800' in captured.out





class TestGenerationEvalReport:

    def test_to_dict(self):
        report = GenerationEvalReport(faithfulness=0.9)
        d = report.to_dict()
        assert d['faithfulness'] == 0.9
        assert d['answer_relevancy'] is None

    def test_print_report(self, capsys):
        report = GenerationEvalReport(faithfulness=0.85)
        report.print_report()
        captured = capsys.readouterr()
        assert 'Faithfulness' in captured.out
