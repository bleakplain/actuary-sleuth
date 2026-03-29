#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""attribution 模块单元测试"""
import pytest
from lib.rag_engine.attribution import (
    parse_citations,
    attribute_by_similarity,
    Citation,
    AttributionResult,
    _cosine_similarity,
    _contains_factual_pattern,
)


class TestParseCitations:

    def _make_sources(self, count=3):
        return [
            {
                'law_name': f'法规{i+1}',
                'article_number': f'第{i+1}条',
                'content': f'这是第{i+1}条法规的内容。',
                'source_file': f'test_{i+1}.md',
            }
            for i in range(count)
        ]

    def test_single_citation(self):
        answer = '等待期不得超过90天 [来源1]。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.citations) == 1
        assert result.citations[0].law_name == '法规1'

    def test_multiple_citations(self):
        answer = '等待期不得超过90天 [来源1]。投保人应如实告知 [来源2]。'
        sources = self._make_sources(3)
        result = parse_citations(answer, sources)

        assert len(result.citations) == 2
        assert result.citations[0].source_idx == 0
        assert result.citations[1].source_idx == 1

    def test_uncited_sources(self):
        answer = '等待期不得超过90天 [来源1]。'
        sources = self._make_sources(3)
        result = parse_citations(answer, sources)

        assert result.uncited_sources == [1, 2]

    def test_unverified_factual_claim(self):
        answer = '保险期间为5年，等待期不超过180天。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.unverified_claims) > 0

    def test_verified_claim_not_flagged(self):
        answer = '等待期不得超过90天 [来源1]。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.unverified_claims) == 0

    def test_empty_answer(self):
        result = parse_citations('', [])
        assert result.citations == []
        assert result.unverified_claims == []

    def test_out_of_range_source(self):
        answer = '等待期不得超过90天 [来源99]。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.citations) == 0

    def test_strong_assertion_detected(self):
        answer = '保险公司必须设立合规部门。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.unverified_claims) > 0

    def test_regulation_name_detected(self):
        answer = '根据《保险法》规定。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.unverified_claims) > 0

    def test_non_factual_not_flagged(self):
        answer = '这是一个需要综合考虑的问题。'
        sources = self._make_sources(1)
        result = parse_citations(answer, sources)

        assert len(result.unverified_claims) == 0


class TestCosineSimilarity:

    def test_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_empty_vector(self):
        assert _cosine_similarity([], [1.0, 2.0]) == 0.0


class TestContainsFactualPattern:

    def test_days_pattern(self):
        assert _contains_factual_pattern('等待期90天') is True

    def test_years_pattern(self):
        assert _contains_factual_pattern('保险期间5年') is True

    def test_percentage_pattern(self):
        assert _contains_factual_pattern('费率3%') is True

    def test_money_pattern(self):
        assert _contains_factual_pattern('限额10万元') is True

    def test_strong_assertion(self):
        assert _contains_factual_pattern('保险公司不得拒保') is True

    def test_no_pattern(self):
        assert _contains_factual_pattern('这是一个普通的描述性句子') is False


class TestAttributeBySimilarity:

    def test_empty_answer(self):
        result = attribute_by_similarity('', [{'content': 'test'}])
        assert result.citations == []

    def test_no_embed_func(self):
        result = attribute_by_similarity('test', [{'content': 'test'}])
        assert result.citations == []

    def test_matching_sentence(self):
        answer = '等待期不超过90天。'
        sources = [{'content': '等待期不超过90天。'}]
        embed_func = lambda x: [1.0, 0.0] if '90天' in x else [0.0, 1.0]
        result = attribute_by_similarity(answer, sources, embed_func=embed_func, threshold=0.5)

        assert len(result.citations) == 1
        assert result.citations[0].confidence == 'similarity'

    def test_no_match_below_threshold(self):
        answer = '完全不相关的内容。'
        sources = [{'content': '等待期不超过90天。'}]
        embed_func = lambda x: [0.0, 1.0] if '90天' in x else [1.0, 0.0]
        result = attribute_by_similarity(answer, sources, embed_func=embed_func, threshold=0.9)

        assert len(result.citations) == 0
