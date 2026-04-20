#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rag_engine/evaluator.py — NDCG, _is_relevant, compute_faithfulness."""
import math
import pytest

from lib.rag_engine.evaluator import (
    _is_relevant,
    _compute_redundancy_rate,
    compute_faithfulness,
    RetrievalEvaluator,
    RetrievalEvalReport,
    GenerationEvalReport,
)


class TestIsRelevant:
    def test_keyword_match_above_threshold(self):
        result = {"content": "等待期 既往症 健康人群", "source_file": "", "law_name": ""}
        # 3 keywords, 60% threshold = 2, all 3 present -> relevant
        assert _is_relevant(result, [], ["等待期", "既往症", "健康人群"]) is True

    def test_keyword_match_below_threshold(self):
        result = {"content": "等待期", "source_file": "", "law_name": ""}
        # 3 keywords, 60% threshold = 2, only 1 present -> not relevant
        assert _is_relevant(result, [], ["等待期", "既往症", "健康人群"]) is False

    def test_keyword_match_single_keyword(self):
        result = {"content": "等待期", "source_file": "", "law_name": ""}
        # single keyword, threshold = max(2, 1*0.6) = 2 -> not relevant
        assert _is_relevant(result, [], ["等待期"]) is False

    def test_keyword_match_two_keywords(self):
        result = {"content": "等待期 既往症", "source_file": "", "law_name": ""}
        # 2 keywords, threshold = max(2, 2*0.6) = 2, both present -> relevant
        assert _is_relevant(result, [], ["等待期", "既往症"]) is True

    def test_law_name_requires_keywords(self):
        result = {"content": "一些内容", "source_file": "05_健康保险.md", "law_name": "05_健康保险"}
        # law_name matches but no keywords -> not relevant
        assert _is_relevant(result, ["05_健康保险.md"], []) is False

    def test_law_name_with_keywords(self):
        result = {"content": "等待期 相关内容", "source_file": "05_健康保险.md", "law_name": "05_健康保险"}
        assert _is_relevant(result, ["05_健康保险.md"], ["等待期"]) is True

    def test_source_file_with_keywords(self):
        result = {"content": "等待期", "source_file": "05_健康保险.md", "law_name": ""}
        assert _is_relevant(result, ["05_健康保险.md"], ["等待期"]) is True

    def test_embedding_fallback_with_original_query(self):
        result = {"content": "长期健康保险可以包含保证续保条款，在保证续保期间内保险公司不得因被保险人健康状况变化而拒绝续保。", "source_file": "", "law_name": ""}
        # Using original query for embedding (much more semantically meaningful)
        query = "长期健康险能否保证续保"
        assert _is_relevant(result, [], ["健康保险", "续保"], original_query=query) is True

    def test_no_match_returns_false(self):
        result = {"content": "这是完全不相关的内容", "source_file": "", "law_name": ""}
        assert _is_relevant(result, [], ["等待期", "既往症"]) is False


class TestNDCG:
    def _compute_ndcg(self, relevance, k=5):
        """Replicate the NDCG logic from RetrievalEvaluator.evaluate."""
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
        total_relevant = sum(relevance)
        if total_relevant == 0:
            return 0.0
        ideal = [1.0] * total_relevant
        idcg = sum(r / math.log2(rank + 1) for rank, r in enumerate(ideal, 1))
        return dcg / idcg

    def test_ndcg_perfect_ranking(self):
        # All 5 results relevant -> NDCG = 1.0
        relevance = [1, 1, 1, 1, 1]
        assert self._compute_ndcg(relevance) == 1.0

    def test_ndcg_partial_relevant(self):
        # 3 relevant, 2 not relevant mixed: top 2 relevant, then 1 irrelevant, then 2 relevant
        # This is NOT the ideal order (should be 1,1,1,0,0), so NDCG < 1.0
        relevance = [1, 1, 0, 1, 0]
        ndcg = self._compute_ndcg(relevance)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_relevant_at_bottom(self):
        # Relevant results at bottom -> NDCG < 1.0
        relevance = [0, 0, 1, 1, 1]
        ndcg = self._compute_ndcg(relevance)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_zero_relevant(self):
        # No relevant results -> NDCG = 0.0
        relevance = [0, 0, 0, 0, 0]
        assert self._compute_ndcg(relevance) == 0.0

    def test_ndcg_single_relevant(self):
        # One relevant at rank 1 -> NDCG = 1.0
        relevance = [1]
        assert self._compute_ndcg(relevance) == 1.0

    def test_ndcg_single_relevant_not_first(self):
        # One relevant at rank 3 -> NDCG < 1.0
        relevance = [0, 0, 1]
        ndcg = self._compute_ndcg(relevance)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_all_irrelevant(self):
        relevance = [0, 0, 0]
        assert self._compute_ndcg(relevance) == 0.0


class TestComputeFaithfulness:
    def test_faithfulness_with_matching_context(self):
        contexts = ["既往症人群的等待期不应与健康人群有过大差距。"]
        answer = "既往症人群的等待期不应与健康人群有过大差距。"
        score = compute_faithfulness(contexts, answer)
        assert score > 0.7

    def test_faithfulness_no_context(self):
        assert compute_faithfulness([], "some answer") == 0.0

    def test_faithfulness_no_answer(self):
        assert compute_faithfulness(["some context"], "") == 0.0

    def test_faithfulness_empty_context(self):
        assert compute_faithfulness([""], "some answer") == 0.0


class TestRedundancyRate:
    def test_redundancy_single_result(self):
        results = [{"content": "some content"}]
        assert _compute_redundancy_rate(results) == 0.0

    def test_redundancy_no_overlap(self):
        results = [
            {"content": "保险产品设计"},
            {"content": "理赔流程说明"},
        ]
        rate = _compute_redundancy_rate(results)
        assert 0.0 <= rate <= 0.6  # no overlap, should be 0

    def test_redundancy_identical(self):
        results = [
            {"content": "保险产品设计 等待期 既往症"},
            {"content": "保险产品设计 等待期 既往症"},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate > 0.6  # identical content has high Jaccard


class TestRetrievalEvalReport:
    def test_to_dict(self):
        report = RetrievalEvalReport(
            precision_at_k=0.8,
            recall_at_k=0.6,
            mrr=0.75,
            ndcg=0.7,
            redundancy_rate=0.1,
            context_relevance=0.65,
        )
        d = report.to_dict()
        assert d["precision_at_k"] == 0.8
        assert d["recall_at_k"] == 0.6
        assert d["mrr"] == 0.75
        assert d["ndcg"] == 0.7
        assert d["redundancy_rate"] == 0.1
        assert d["context_relevance"] == 0.65


class TestGenerationEvalReport:
    def test_to_dict(self):
        report = GenerationEvalReport(
            faithfulness=0.85,
            answer_relevancy=0.78,
            answer_correctness=0.72,
        )
        d = report.to_dict()
        assert d["faithfulness"] == 0.85
        assert d["answer_relevancy"] == 0.78
        assert d["answer_correctness"] == 0.72

    def test_to_dict_with_none(self):
        report = GenerationEvalReport()
        d = report.to_dict()
        assert d["faithfulness"] is None
        assert d["answer_relevancy"] is None
        assert d["answer_correctness"] is None
