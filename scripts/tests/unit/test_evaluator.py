#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluator 模块单元测试"""
import pytest
from lib.rag_engine.evaluator import _compute_redundancy_rate


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
