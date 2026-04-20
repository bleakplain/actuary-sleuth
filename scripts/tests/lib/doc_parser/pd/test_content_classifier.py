#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容分类器测试"""
import pytest
from unittest.mock import Mock, patch

from lib.doc_parser.pd.content_classifier import (
    ContentClassifier, KeywordDetector, RuleDetector,
    DetectionMethod, DetectionResult
)
from lib.doc_parser.models import SectionType


class TestKeywordDetector:
    """关键词检测器测试"""

    def test_detect_notice(self):
        """检测投保须知"""
        detector = KeywordDetector({
            'notice': ['投保须知', '重要提示'],
            'exclusion': ['责任免除'],
        })

        result = detector.detect("投保须知：本产品仅限...")

        assert result.section_type == SectionType.NOTICE
        assert result.method == DetectionMethod.KEYWORD
        assert result.confidence >= 0.5

    def test_detect_exclusion(self):
        """检测责任免除"""
        detector = KeywordDetector({
            'notice': ['投保须知'],
            'exclusion': ['责任免除', '免责条款'],
        })

        result = detector.detect("责任免除条款如下...")

        assert result.section_type == SectionType.EXCLUSION
        assert result.confidence >= 0.5

    def test_no_match_returns_clause(self):
        """未匹配时返回条款类型"""
        detector = KeywordDetector({
            'notice': ['投保须知'],
        })

        result = detector.detect("这是一段普通文本")

        assert result.section_type == SectionType.CLAUSE
        assert result.confidence == 0.0


class TestRuleDetector:
    """规则检测器测试"""

    def test_detect_exclusion_rule(self):
        """检测责任免除规则"""
        detector = RuleDetector()

        result = detector.detect(
            "因下列原因导致被保险人身故的，保险人不承担保险责任："
        )

        assert result.section_type == SectionType.EXCLUSION
        assert result.method == DetectionMethod.RULE

    def test_detect_health_disclosure_rule(self):
        """检测健康告知规则"""
        detector = RuleDetector()

        result = detector.detect(
            "健康告知：\n被保险人曾患有以下疾病...",
            context="请如实填写"
        )

        assert result.section_type == SectionType.HEALTH_DISCLOSURE

    def test_no_rule_match(self):
        """未匹配规则"""
        detector = RuleDetector()

        result = detector.detect("一些无关的文本内容")

        assert result.section_type == SectionType.CLAUSE
        assert result.confidence == 0.0


class TestContentClassifier:
    """混合分类器测试"""

    @pytest.fixture
    def classifier(self):
        """创建分类器"""
        return ContentClassifier(
            section_keywords={
                'notice': ['投保须知', '重要提示'],
                'exclusion': ['责任免除', '免责条款'],
                'health_disclosure': ['健康告知'],
                'rider': ['附加险'],
            },
            llm_enabled=False
        )

    def test_keyword_high_confidence_returns_early(self, classifier):
        """关键词高置信度直接返回"""
        result = classifier.classify("投保须知：本产品仅限...")

        assert result.method == DetectionMethod.KEYWORD
        assert result.section_type == SectionType.NOTICE
        assert result.confidence >= 0.7

    def test_rule_detection_fallback(self, classifier):
        """关键词低置信度时使用规则检测"""
        result = classifier.classify(
            "因下列原因导致被保险人身故的，保险人不承担保险责任"
        )

        assert result.method == DetectionMethod.RULE
        assert result.section_type == SectionType.EXCLUSION

    def test_returns_highest_confidence(self, classifier):
        """返回最高置信度结果"""
        # 关键词不匹配，规则也不匹配，返回默认
        result = classifier.classify("一些普通的条款内容")

        assert result.section_type == SectionType.CLAUSE

    @patch('lib.doc_parser.pd.content_classifier.LLMDetector')
    def test_llm_fallback_enabled(self, mock_llm_class):
        """启用 LLM 时低置信度触发 LLM 检测"""
        mock_llm = Mock()
        mock_llm.detect.return_value = DetectionResult(
            section_type=SectionType.RIDER,
            confidence=0.9,
            method=DetectionMethod.LLM,
            reasoning="LLM 判断"
        )
        mock_llm_class.return_value = mock_llm

        classifier = ContentClassifier(
            section_keywords={'notice': ['投保须知']},
            llm_enabled=True
        )

        result = classifier.classify("附加险条款说明...")

        # 关键词不匹配，应该调用 LLM
        assert result.method == DetectionMethod.LLM
        assert result.section_type == SectionType.RIDER


class TestDetectionResult:
    """检测结果测试"""

    def test_frozen_dataclass(self):
        """检测结果应不可变"""
        result = DetectionResult(
            section_type=SectionType.NOTICE,
            confidence=0.8,
            method=DetectionMethod.KEYWORD,
            reasoning="测试"
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            result.confidence = 0.9
