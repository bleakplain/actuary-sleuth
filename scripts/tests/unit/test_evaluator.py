#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluator 模块单元测试"""
import pytest
from lib.rag_engine.evaluator import (
    _compute_redundancy_rate,
    _is_relevant,
    _compute_context_relevance,
    GenerationEvaluator,
)


class TestRedundancyRate:

    def test_empty_results(self):
        assert _compute_redundancy_rate([]) == 0.0

    def test_single_result(self):
        assert _compute_redundancy_rate([{'content': '测试内容'}]) == 0.0

    def test_no_redundancy(self):
        results = [
            {'content': '健康保险等待期规定'},
            {'content': '意外伤害保险理赔流程'},
        ]
        rate = _compute_redundancy_rate(results)
        assert 0.0 <= rate <= 1.0

    def test_identical_results(self):
        results = [
            {'content': '健康保险等待期不得超过90天'},
            {'content': '健康保险等待期不得超过90天'},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate == 1.0

    def test_rate_never_exceeds_one(self):
        results = [{'content': f'内容{i}' * 5} for i in range(10)]
        rate = _compute_redundancy_rate(results)
        assert 0.0 <= rate <= 1.0

    def test_empty_content_skipped(self):
        results = [
            {'content': '有效内容'},
            {'content': ''},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate == 0.0

    def test_three_results_all_same(self):
        results = [
            {'content': '相同内容相同内容'},
            {'content': '相同内容相同内容'},
            {'content': '相同内容相同内容'},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate == 1.0

    def test_two_pairs_redundant(self):
        results = [
            {'content': '内容A内容A内容A'},
            {'content': '内容A内容A内容A'},
            {'content': '内容B内容B内容B'},
            {'content': '内容B内容B内容B'},
        ]
        rate = _compute_redundancy_rate(results)
        assert rate == 1.0


class TestIsRelevant:

    def test_keyword_match(self):
        result = {'content': '等待期不超过90天', 'source_file': 'test.md', 'law_name': '健康险'}
        assert _is_relevant(result, ['test.md'], ['等待期', '90天']) is True

    def test_source_file_match_with_keywords(self):
        result = {'content': '保险费率规定', 'source_file': 'test.md', 'law_name': '保险法'}
        assert _is_relevant(result, ['test.md'], ['费率']) is True

    def test_law_name_match_no_keywords_no_source(self):
        result = {'content': '等待期不超过90天', 'source_file': 'other.md', 'law_name': '健康保险管理办法'}
        assert _is_relevant(result, ['健康保险管理办法.md'], []) is False

    def test_law_name_match_no_keywords_with_source(self):
        result = {'content': '等待期不超过90天', 'source_file': '健康保险管理办法.md', 'law_name': '健康保险管理办法'}
        assert _is_relevant(result, ['健康保险管理办法.md'], []) is True

    def test_no_match(self):
        result = {'content': '完全不相关的内容', 'source_file': 'other.md', 'law_name': '其他法规'}
        assert _is_relevant(result, ['test.md'], ['等待期']) is False


class TestContextRelevance:

    def test_high_relevance(self):
        query = "健康保险等待期"
        results = [{'content': '健康保险等待期不得超过90天'}]
        score = _compute_context_relevance(query, results)
        assert score > 0.5

    def test_low_relevance(self):
        query = "健康保险等待期"
        results = [{'content': '保险公司应当遵守法律法规规定'}]
        score = _compute_context_relevance(query, results)
        assert score < 0.5

    def test_empty_inputs(self):
        assert _compute_context_relevance("", []) == 0.0
        assert _compute_context_relevance("test", []) == 0.0

    def test_empty_content(self):
        assert _compute_context_relevance("test", [{'content': ''}]) == 0.0


class TestLightweightFaithfulness:

    def test_bigram_overlap(self):
        contexts = ['健康保险等待期不得超过90天']
        answer = '健康保险等待期不超过90天'
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score > 0.0

    def test_hallucination_detected(self):
        contexts = ['健康保险等待期不得超过90天']
        answer = '健康保险等待期不得超过180天'
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score < 1.0

    def test_empty_contexts(self):
        assert GenerationEvaluator._compute_faithfulness([], 'test') == 0.0

    def test_empty_answer(self):
        assert GenerationEvaluator._compute_faithfulness(['context'], '') == 0.0
