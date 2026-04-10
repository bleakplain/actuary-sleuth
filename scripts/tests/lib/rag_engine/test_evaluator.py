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
    _match_source_to_evidence,
    _compute_redundancy_rate,
    evaluate_retrieval,
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

    def test_eval_sample_fields(self, sample_eval):
        assert sample_eval.id == "test001"
        assert sample_eval.question_type == QuestionType.FACTUAL
        assert sample_eval.difficulty == "easy"
        assert sample_eval.topic == "健康保险"
        assert len(sample_eval.evidence_docs) >= 1
        assert len(sample_eval.evidence_keywords) >= 1

    def test_to_dict_roundtrip(self, sample_eval):
        d = sample_eval.to_dict()
        assert isinstance(d, dict)
        assert d['question_type'] == 'factual'
        assert d['id'] == 'test001'

        restored = EvalSample.from_dict(d)
        assert restored == sample_eval

    def test_save_eval_dataset_to_path(self, tmp_path, sample_eval):
        path = tmp_path / "test_eval.json"
        save_eval_dataset([sample_eval], str(path))
        assert path.exists()

    def test_load_eval_dataset_returns_list(self):
        dataset = load_eval_dataset()
        assert isinstance(dataset, list)

    def test_save_creates_parent_dirs(self, tmp_path, sample_eval):
        nested_path = tmp_path / "sub" / "dir" / "eval.json"
        save_eval_dataset([sample_eval], str(nested_path))
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

    def test_is_relevant_single_keyword_correct_source(self, sample_eval):
        """单领域关键词 + 正确 source_file 应判为相关"""
        result = {
            'content': '等待期相关内容',
            'law_name': '未知',
            'source_file': '05_健康保险产品开发.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, ['等待期']) is True

    def test_is_relevant_single_keyword_wrong_source(self, sample_eval, monkeypatch):
        """单领域关键词 + 错误 source_file 应判为不相关（禁用 embedding 兜底）"""
        monkeypatch.setattr('lib.rag_engine.evaluator._get_embed_model', lambda: None)
        result = {
            'content': '等待期相关内容',
            'law_name': '未知',
            'source_file': 'other.md',
        }
        assert _is_relevant(result, sample_eval.evidence_docs, ['等待期']) is False

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

    def test_is_relevant_no_match(self, irrelevant_results, sample_eval, monkeypatch):
        monkeypatch.setattr('lib.rag_engine.evaluator._get_embed_model', lambda: None)
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

    def test_is_relevant_semantic_match(self, monkeypatch):
        """同义表达但字面不匹配时，embedding 语义判定应识别为相关"""
        def mock_similarity(text_a, text_b):
            return 0.75
        monkeypatch.setattr(
            'lib.rag_engine.evaluator._compute_embedding_similarity',
            mock_similarity,
        )
        result = {
            'content': '观察期内发生保险事故不承担赔偿责任',
            'law_name': '健康保险管理办法',
            'source_file': 'other.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期", "保险事故"]) is True

    def test_is_relevant_semantic_below_threshold(self, monkeypatch):
        """embedding 相似度低于阈值时仍判为不相关"""
        def mock_similarity(text_a, text_b):
            return 0.4
        monkeypatch.setattr(
            'lib.rag_engine.evaluator._compute_embedding_similarity',
            mock_similarity,
        )
        result = {
            'content': '分红型保险的分红水平不确定',
            'law_name': '分红型人身保险',
            'source_file': '07_分红型人身保险.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期"]) is False

    def test_is_relevant_keyword_match_still_first(self, monkeypatch):
        """关键词匹配优先于 embedding 判定"""
        call_count = 0
        def mock_similarity(text_a, text_b):
            nonlocal call_count
            call_count += 1
            return 0.0
        monkeypatch.setattr(
            'lib.rag_engine.evaluator._compute_embedding_similarity',
            mock_similarity,
        )
        result = {
            'content': '等待期规定相关内容，既往症人群的等待期不应有过大差距',
            'law_name': '未知',
            'source_file': 'other.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["等待期", "既往症"]) is True
        assert call_count == 0

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

    def test_match_source_to_evidence_exact(self):
        assert _match_source_to_evidence("05_健康保险产品开发.md", ["05_健康保险产品开发.md"]) == "05_健康保险产品开发.md"

    def test_match_source_to_evidence_without_extension(self):
        assert _match_source_to_evidence("05_健康保险产品开发", ["05_健康保险产品开发.md"]) == "05_健康保险产品开发.md"

    def test_match_source_to_evidence_with_path(self):
        assert _match_source_to_evidence("/data/references/05_健康保险产品开发.md", ["05_健康保险产品开发.md"]) == "05_健康保险产品开发.md"

    def test_match_source_to_evidence_no_match(self):
        assert _match_source_to_evidence("07_分红型人身保险.md", ["05_健康保险产品开发.md"]) is None

    def test_match_source_to_evidence_empty(self):
        assert _match_source_to_evidence("", ["05_健康保险产品开发.md"]) is None
        assert _match_source_to_evidence("05_健康保险产品开发.md", []) is None

    def test_is_relevant_synonym_expansion(self):
        """同义词扩展：evidence_keywords 含'退保'，content 含'解除保险合同'应判为相关"""
        result = {
            'content': '解除保险合同应当退还保单现金价值',
            'law_name': '保险法',
            'source_file': '01_保险法.md',
        }
        assert _is_relevant(result, ["01_保险法.md"], ["退保", "现金价值"]) is True

    def test_is_relevant_synonym_reverse_lookup(self):
        """反向同义词：evidence_keywords 含'自付额'，content 含'免赔额'应判为相关"""
        result = {
            'content': '自付额即免赔额，每次就诊的自付额为500元',
            'law_name': '健康保险',
            'source_file': '05_健康保险产品开发.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["自付额", "免赔"]) is True

    def test_is_relevant_generic_keywords_rejected(self, monkeypatch):
        """泛关键词不单独触发相关（禁用 embedding 兜底）"""
        monkeypatch.setattr('lib.rag_engine.evaluator._get_embed_model', lambda: None)
        result = {
            'content': '保险合同条款规定了相关要求',
            'law_name': '保险法',
            'source_file': '07_分红型人身保险.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["保险", "条款"]) is False

    def test_is_relevant_domain_keyword_with_synonym(self):
        """领域关键词通过同义词扩展匹配"""
        result = {
            'content': '自付额为每次100元',
            'law_name': '健康保险产品开发',
            'source_file': '05_健康保险产品开发.md',
        }
        assert _is_relevant(result, ["05_健康保险产品开发.md"], ["免赔额"]) is True





class TestRetrievalEvaluator:

    def test_evaluate_single_sample_all_relevant(
        self, mock_rag_engine, sample_eval, relevant_results
    ):
        mock_rag_engine.search.return_value = relevant_results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(sample_eval, top_k=2)

        assert result['precision'] == 1.0
        assert result['recall'] == 1.0  # 2 relevant results match same 1 evidence doc
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
        assert result['recall'] == 1.0  # 2 relevant results match same 1 evidence doc
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
        samples = [
            EvalSample(
                id="batch_001", question="等待期规定？",
                ground_truth="等待期不超过90天",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy", topic="健康保险",
            ),
            EvalSample(
                id="batch_002", question="犹豫期多久？",
                ground_truth="不少于15日",
                evidence_docs=["06_健康保险管理办法.md"],
                evidence_keywords=["犹豫期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy", topic="健康保险",
            ),
        ]

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
        dataset = [
            EvalSample(
                id="t_factual", question="等待期？",
                ground_truth="答案",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy", topic="健康保险",
            ),
            EvalSample(
                id="t_multihop", question="等待期和犹豫期区别？",
                ground_truth="答案",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期", "犹豫期"],
                question_type=QuestionType.MULTI_HOP,
                difficulty="medium", topic="健康保险",
            ),
            EvalSample(
                id="t_negative", question="能不能单方面修改保额？",
                ground_truth="不能",
                evidence_docs=["01_保险法.md"],
                evidence_keywords=["保额", "修改"],
                question_type=QuestionType.NEGATIVE,
                difficulty="easy", topic="保险法",
            ),
            EvalSample(
                id="t_colloquial", question="买完保险想反悔咋整？",
                ground_truth="可在犹豫期退保",
                evidence_docs=["06_健康保险管理办法.md"],
                evidence_keywords=["犹豫期", "退保"],
                question_type=QuestionType.COLLOQUIAL,
                difficulty="easy", topic="健康保险",
            ),
        ]

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

    def test_evaluate_single_sample_multi_doc_recall(self, mock_rag_engine):
        """多个 evidence_doc 场景：recall = matched_docs / evidence_docs"""
        multi_doc_sample = EvalSample(
            id="test_multi_doc",
            question="等待期和犹豫期有什么区别？",
            ground_truth="等待期是合同生效后的观察期，犹豫期是收到保单后的退保期",
            evidence_docs=["05_健康保险产品开发.md", "06_健康保险管理办法.md"],
            evidence_keywords=["等待期", "犹豫期"],
            question_type=QuestionType.FACTUAL,
            difficulty="medium",
            topic="健康保险",
        )
        results = [
            {
                'content': '等待期规定：既往症人群的等待期不应与健康人群有过大差距',
                'law_name': '健康保险产品开发',
                'source_file': '05_健康保险产品开发.md',
                'score': 0.95,
            },
            {
                'content': '犹豫期自收到保险单之日起不少于15天',
                'law_name': '健康保险管理办法',
                'source_file': '06_健康保险管理办法.md',
                'score': 0.9,
            },
        ]
        mock_rag_engine.search.return_value = results

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(multi_doc_sample, top_k=2)

        assert result['recall'] == 1.0  # 2 docs matched / 2 evidence docs

    def test_evaluate_unanswerable_sample(self, mock_rag_engine):
        """UNANSWERABLE 样本：evidence_docs 为空时 recall = 0.0"""
        unanswerable_sample = EvalSample(
            id="test_unanswerable",
            question="保险公司可以在抖音上直播卖保险吗？",
            ground_truth="知识库中无对应规定",
            evidence_docs=[],
            evidence_keywords=["直播", "销售"],
            question_type=QuestionType.UNANSWERABLE,
            difficulty="easy",
            topic="互联网保险",
        )
        mock_rag_engine.search.return_value = [
            {
                'content': '互联网保险业务需要网络安全保护',
                'law_name': '互联网保险产品',
                'source_file': '10_互联网保险产品.md',
                'score': 0.5,
            },
        ]

        evaluator = RetrievalEvaluator(mock_rag_engine)
        result = evaluator.evaluate(unanswerable_sample, top_k=1)

        assert result['recall'] == 0.0

    def test_evaluate_batch_excludes_unanswerable_from_recall(self, mock_rag_engine):
        """UNANSWERABLE 样本不计入 recall 均值"""
        samples = [
            EvalSample(
                id="test_normal",
                question="等待期有什么规定？",
                ground_truth="等待期不超过90天",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy",
                topic="健康保险",
            ),
            EvalSample(
                id="test_unanswerable",
                question="保险公司可以在抖音上直播卖保险吗？",
                ground_truth="知识库中无对应规定",
                evidence_docs=[],
                evidence_keywords=["直播"],
                question_type=QuestionType.UNANSWERABLE,
                difficulty="easy",
                topic="互联网保险",
            ),
        ]
        mock_rag_engine.search.return_value = [
            {
                'content': '等待期规定相关内容',
                'law_name': '健康保险',
                'source_file': '05_健康保险产品开发.md',
                'score': 0.9,
            },
        ]

        evaluator = RetrievalEvaluator(mock_rag_engine)
        report, _ = evaluator.evaluate_batch(samples, top_k=1)

        assert report.recall_at_k == 1.0
        assert report.rejection_rate is not None
        assert report.rejection_rate == 1.0





class TestGenerationEvaluator:

    def test_evaluate_without_ragas_raises(self):
        """RAGAS 未安装时 GenerationEvaluator 应抛出 ImportError"""
        with patch.dict('sys.modules', {'ragas': None, 'datasets': None}):
            with pytest.raises(ImportError, match="RAGAS"):
                GenerationEvaluator()

    @pytest.mark.ragas
    def test_evaluate_batch_no_engine(self):
        """未提供 RAG 引擎时返回空报告"""
        evaluator = GenerationEvaluator()
        report = evaluator.evaluate_batch([])

        assert isinstance(report, GenerationEvalReport)
        assert report.faithfulness is None

    @pytest.mark.ragas
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


class TestEvaluateRetrieval:
    def test_run_with_all_failures(self, mock_rag_engine):
        mock_rag_engine.search.return_value = [
            {'content': '不相关内容', 'law_name': '其他', 'source_file': 'other.md', 'score': 0.5},
        ]
        samples = [
            EvalSample(
                id=f"fail_{i}", question=f"问题{i}",
                ground_truth="答案",
                evidence_docs=["05_健康保险产品开发.md"],
                evidence_keywords=["等待期"],
                question_type=QuestionType.FACTUAL,
                difficulty="easy", topic="健康保险",
            )
            for i in range(5)
        ]
        report, failed = evaluate_retrieval(mock_rag_engine, samples, top_k=1)

        assert report.precision_at_k == 0.0
        assert len(failed) == 5
        for f in failed:
            assert f['failure_reason'] in (
                '检索无结果', '结果不相关', '排序错误（相关文档排名靠后）'
            )

    def test_run_with_all_pass(self, mock_rag_engine, sample_eval):
        from lib.rag_engine.evaluator import evaluate_retrieval

        mock_rag_engine.search.return_value = [
            {'content': '等待期规定相关内容', 'law_name': '健康保险产品开发', 'source_file': '05_健康保险产品开发.md', 'score': 0.9},
        ]
        report, failed = evaluate_retrieval(mock_rag_engine, [sample_eval], top_k=1)

        assert len(failed) == 0
