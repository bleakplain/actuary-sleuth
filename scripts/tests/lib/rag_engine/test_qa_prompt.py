#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 生成环节测试 - Prompt 构建、引用解析、幻觉检测
"""
import pytest

from lib.rag_engine.rag_engine import RAGEngine, _SYSTEM_PROMPT, _truncate_at_sentence_boundary
from lib.rag_engine.config import GenerationConfig


class TestQAPrompt:

    def test_prompt_uses_numbered_list(self):
        results = [
            {'law_name': '健康保险', 'article_number': '第一条', 'content': '等待期90天'},
            {'law_name': '保险法', 'article_number': '第十六条', 'content': '如实告知'},
        ]
        prompt, count = RAGEngine._build_qa_prompt(GenerationConfig(), "等待期规定", results)
        assert '1. 【健康保险】第一条' in prompt
        assert '2. 【保险法】第十六条' in prompt
        assert count == 2

    def test_prompt_uses_only_based_wording(self):
        results = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        prompt, count = RAGEngine._build_qa_prompt(GenerationConfig(), "测试", results)
        assert '仅依据' in prompt

    def test_context_truncation_respects_config(self):
        results = [
            {'law_name': '测试', 'article_number': f'第{i}条', 'content': 'A' * 200}
            for i in range(10)
        ]
        prompt, count = RAGEngine._build_qa_prompt(GenerationConfig(max_context_chars=100), "测试", results)
        assert count == 0

    def test_build_prompt_returns_included_count(self):
        results = [
            {'law_name': '测试', 'article_number': '第一条', 'content': '短'},
            {'law_name': '测试', 'article_number': '第二条', 'content': '短'},
        ]
        _, count = RAGEngine._build_qa_prompt(GenerationConfig(), "测试", results)
        assert count == 2

    def test_empty_results_returns_zero_count(self):
        _, count = RAGEngine._build_qa_prompt(GenerationConfig(), "测试", [])
        assert count == 0


class TestPromptSeparation:

    def test_system_prompt_is_static(self):
        assert '{context}' not in _SYSTEM_PROMPT
        assert '{question}' not in _SYSTEM_PROMPT

    def test_system_prompt_has_number_rules(self):
        assert '完全一致' in _SYSTEM_PROMPT
        assert '不得近似或四舍五入' in _SYSTEM_PROMPT

    def test_system_prompt_has_disambiguation_rule(self):
        assert '多个不同法规文件' in _SYSTEM_PROMPT

    def test_system_prompt_has_unified_rejection(self):
        assert _SYSTEM_PROMPT.count('提供的法规条款中未找到相关信息') >= 1

    def test_system_prompt_no_fewshot_example(self):
        assert '回答示例' not in _SYSTEM_PROMPT

    def test_user_prompt_contains_context_and_question(self):
        results = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        prompt, count = RAGEngine._build_qa_prompt(GenerationConfig(), "测试", results)
        assert '## 法规条款' in prompt
        assert '## 用户问题' in prompt
        assert '## 重要提醒' in prompt

    def test_user_prompt_has_trailing_reminder(self):
        results = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        prompt, _ = RAGEngine._build_qa_prompt(GenerationConfig(), "测试", results)
        lines = prompt.strip().split('\n')
        assert any('仅依据' in line for line in lines[-3:])


class TestSentenceBoundaryTruncation:

    def test_truncate_at_sentence_boundary(self):
        text = "第一条规定保险合同的成立条件。第二条规定保险合同的生效时间。第三条规定保险合同的终止情形。"
        result = _truncate_at_sentence_boundary(text, 30)
        assert '。' in result
        assert '[注：此条款内容已被截断]' in result

    def test_no_truncate_when_short(self):
        text = "短文本"
        result = _truncate_at_sentence_boundary(text, 100)
        assert result == text

    def test_fallback_when_no_boundary(self):
        text = "这是一段没有句号结尾的长文本内容用来测试当没有句子边界时的回退行为"
        result = _truncate_at_sentence_boundary(text, 20)
        assert '……' in result

    def test_exact_fit_no_truncation(self):
        text = "内容。"
        result = _truncate_at_sentence_boundary(text, 10)
        assert result == text


class TestCitationParsing:

    def test_parse_valid_citations(self):
        from lib.rag_engine.attribution import parse_citations
        answer = "根据《健康保险管理办法》第一条[来源1]，等待期不超过90天。"
        sources = [
            {'law_name': '健康保险管理办法', 'article_number': '第一条', 'content': '等待期90天'},
        ]
        result = parse_citations(answer, sources)
        assert len(result.citations) == 1
        assert result.citations[0].law_name == '健康保险管理办法'

    def test_parse_ignores_out_of_range(self):
        from lib.rag_engine.attribution import parse_citations
        answer = "根据[来源5]的规定"
        sources = [{'law_name': '测试', 'article_number': '第一条', 'content': '内容'}]
        result = parse_citations(answer, sources)
        assert len(result.citations) == 0

    def test_parse_empty_answer(self):
        from lib.rag_engine.attribution import parse_citations
        result = parse_citations("", [])
        assert result.citations == []
        assert result.unverified_claims == []


class TestUnverifiedClaimsDetection:

    def test_text_after_last_citation_is_unverified(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        answer = "等待期不得超过90天[来源1]。保费为每年5000元。"
        claims = _detect_unverified_claims(answer)
        assert len(claims) == 1
        assert '5000元' in claims[0]

    def test_claim_without_citation_is_unverified(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        answer = "等待期不得超过90天。"
        claims = _detect_unverified_claims(answer)
        assert len(claims) == 1

    def test_all_cited_no_unverified(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        answer = "等待期为90天[来源1]。根据上述法规，免赔额为100元[来源2]。"
        claims = _detect_unverified_claims(answer)
        assert len(claims) == 0

    def test_gap_between_citations_is_unverified(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        answer = "等待期为90天[来源1]。保费为每年5000元。"
        claims = _detect_unverified_claims(answer)
        assert len(claims) == 1
        assert '5000元' in claims[0]

    def test_no_factual_patterns_no_claims(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        answer = "这是一段普通回答。"
        claims = _detect_unverified_claims(answer)
        assert len(claims) == 0

    def test_empty_answer(self):
        from lib.rag_engine.attribution import _detect_unverified_claims
        assert _detect_unverified_claims("") == []


class TestFaithfulness:

    def test_high_faithfulness(self):
        from lib.rag_engine.evaluator import GenerationEvaluator
        contexts = ["健康保险产品的等待期不得超过90天"]
        answer = "健康保险产品的等待期不得超过90天"
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score > 0.8

    def test_low_faithfulness(self):
        from lib.rag_engine.evaluator import GenerationEvaluator
        contexts = ["健康保险产品的等待期不得超过90天"]
        answer = "根据宇宙大爆炸理论，宇宙已有138亿年历史"
        score = GenerationEvaluator._compute_faithfulness(contexts, answer)
        assert score < 0.3

    def test_empty_inputs(self):
        from lib.rag_engine.evaluator import GenerationEvaluator
        assert GenerationEvaluator._compute_faithfulness([], "答案") == 0.0
        assert GenerationEvaluator._compute_faithfulness(["上下文"], "") == 0.0
