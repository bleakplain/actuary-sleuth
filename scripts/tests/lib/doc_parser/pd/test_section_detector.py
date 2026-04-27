#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容类型检测器测试"""
import pytest

pytest.importorskip("docx")

from lib.doc_parser.pd.section_detector import SectionDetector
from lib.doc_parser.models import SectionType


class TestSectionDetector:

    def test_detect_notice(self):
        detector = SectionDetector()
        result = detector.detect_section_type("投保须知")
        assert result == SectionType.NOTICE

    def test_detect_health_disclosure(self):
        detector = SectionDetector()
        result = detector.detect_section_type("健康告知事项")
        assert result == SectionType.HEALTH_DISCLOSURE

    def test_detect_exclusion(self):
        detector = SectionDetector()
        result = detector.detect_section_type("责任免除条款")
        assert result == SectionType.EXCLUSION

    def test_detect_rider(self):
        detector = SectionDetector()
        result = detector.detect_section_type("附加险说明")
        assert result == SectionType.RIDER
        # 独立章节标题
        assert detector.detect_section_type("附加险条款") == SectionType.RIDER
        # 条款正文中的"附加险"不应误匹配
        assert detector.detect_section_type("2.1 保险期间 本附加险合同的保险期间为1年") is None
        assert detector.detect_section_type("2.5 保险责任 本附加险合同有效期内") is None

    def test_is_clause_table(self):
        detector = SectionDetector()
        assert detector.is_clause_table("1")
        assert detector.is_clause_table("1.2")
        assert detector.is_clause_table("1.2.3")
        assert not detector.is_clause_table("条款")
        assert not detector.is_clause_table("")

    def test_is_premium_table(self):
        detector = SectionDetector()
        assert detector.is_premium_table(["年龄", "性别", "费率"])
        assert not detector.is_premium_table(["条款编号", "条款内容"])

    def test_is_non_clause_table(self):
        detector = SectionDetector()
        assert detector.is_non_clause_table(["公司名称", "地址"])
        assert not detector.is_non_clause_table(["1", "保险责任"])
