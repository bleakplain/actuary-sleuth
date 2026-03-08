#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档格式检测器

分析保险产品文档的结构特征，识别文档格式类型。
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List


logger = logging.getLogger(__name__)


@dataclass
class FormatProfile:
    """文档格式特征"""
    primary_type: str  # HTML_TABLE, MARKDOWN, PLAIN_TEXT, MIXED
    confidence: float  # 0-1
    features: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"FormatProfile(type={self.primary_type}, confidence={self.confidence:.2f})"


class DocumentFormatDetector:
    """文档格式检测器"""

    # 格式检测阈值
    MIN_HTML_TABLE_ROWS = 10
    MIN_MARKDOWN_HEADERS = 3
    MIN_PLAIN_TEXT_CONFIDENCE = 0.3

    def __init__(self):
        self._detectors = {
            'HTML_TABLE': self._detect_html_table,
            'MARKDOWN': self._detect_markdown,
            'PLAIN_TEXT': self._detect_plain_text,
        }

    def analyze(self, document: str) -> FormatProfile:
        """
        分析文档格式

        Args:
            document: 文档内容

        Returns:
            FormatProfile: 格式特征描述
        """
        if not document or len(document.strip()) < 100:
            return FormatProfile(
                primary_type='PLAIN_TEXT',
                confidence=0.0,
                features={'reason': 'document_too_short'}
            )

        scores = {}
        for format_name, detector in self._detectors.items():
            try:
                scores[format_name] = detector(document)
            except Exception as e:
                logger.warning(f"格式检测失败 {format_name}: {e}")
                scores[format_name] = {'score': 0, 'features': {}}

        # 找出最高分格式
        max_format = max(scores.items(), key=lambda x: x[1]['score'])
        max_score = max_format[1]['score']

        # 如果最高分低于阈值，判定为混合格式
        if max_score < 0.6:
            detected_formats = [k for k, v in scores.items() if v['score'] > self.MIN_PLAIN_TEXT_CONFIDENCE]
            return FormatProfile(
                primary_type='MIXED',
                confidence=0.5,
                features={
                    'formats': detected_formats,
                    'scores': {k: v['score'] for k, v in scores.items()}
                }
            )

        return FormatProfile(
            primary_type=max_format[0],
            confidence=max_score,
            features=max_format[1]['features']
        )

    def _detect_html_table(self, doc: str) -> Dict[str, Any]:
        """检测 HTML 表格格式"""
        tr_count = len(re.findall(r'<tr', doc))
        td_count = len(re.findall(r'<td', doc))

        if tr_count < self.MIN_HTML_TABLE_ROWS:
            return {'score': 0, 'features': {}}

        # 分析表格行模式
        rows = re.findall(r'<tr>(.*?)</tr>', doc, re.DOTALL)
        pattern_2td = sum(1 for r in rows if len(re.findall(r'<td', r)) == 2)
        pattern_3td = sum(1 for r in rows if len(re.findall(r'<td', r)) == 3)

        # 计算规范行比例
        regular_ratio = (pattern_2td + pattern_3td) / len(rows) if rows else 0
        score = regular_ratio if regular_ratio > 0.5 else 0

        return {
            'score': score,
            'features': {
                'tr_count': tr_count,
                'td_count': td_count,
                'pattern_2td': pattern_2td,
                'pattern_3td': pattern_3td,
                'regular_ratio': regular_ratio,
            }
        }

    def _detect_markdown(self, doc: str) -> Dict[str, Any]:
        """检测 Markdown 格式"""
        h1 = len(re.findall(r'^#\s+', doc, re.MULTILINE))
        h2 = len(re.findall(r'^##\s+', doc, re.MULTILINE))
        h3 = len(re.findall(r'^###\s+', doc, re.MULTILINE))

        # 检测条款模式
        clause_chinese = len(re.findall(
            r'^第[一二三四五六七八九十百千]+[条章节]\s*(.+)?',
            doc, re.MULTILINE
        ))
        clause_arabic = len(re.findall(
            r'^第\d+[条章节]\s*(.+)?',
            doc, re.MULTILINE
        ))

        # 检测列表模式
        list_items = len(re.findall(r'^\s*[-*+]\s+', doc, re.MULTILINE))
        numbered_items = len(re.findall(r'^\s*\d+\.\s+', doc, re.MULTILINE))

        # 计算得分（基于特征数量）
        feature_count = h1 + h2 + h3 + clause_chinese + clause_arabic + list_items + numbered_items
        score = min(1.0, feature_count / 20)

        return {
            'score': score if score >= self.MIN_PLAIN_TEXT_CONFIDENCE else 0,
            'features': {
                'h1_count': h1,
                'h2_count': h2,
                'h3_count': h3,
                'clause_chinese': clause_chinese,
                'clause_arabic': clause_arabic,
                'list_items': list_items,
                'numbered_items': numbered_items,
            }
        }

    def _detect_plain_text(self, doc: str) -> Dict[str, Any]:
        """检测纯文本格式"""
        # 纯文本特征：无HTML、无复杂Markdown、行较短
        has_html = bool(re.search(r'<[a-z]+', doc, re.IGNORECASE))
        has_table = bool(re.search(r'<table|<tr|<td', doc, re.IGNORECASE))
        has_md_headers = bool(re.search(r'^#+\s', doc, re.MULTILINE))

        if has_table:
            return {'score': 0, 'features': {'reason': 'has_html_table'}}

        lines = doc.split('\n')
        if not lines:
            return {'score': 0, 'features': {}}

        # 计算平均行长
        non_empty_lines = [l for l in lines if l.strip()]
        if not non_empty_lines:
            return {'score': 0, 'features': {}}

        avg_len = sum(len(l) for l in non_empty_lines) / len(non_empty_lines)

        # 纯文本通常行较短（<100字符）
        length_score = 1.0 if avg_len < 100 else max(0, 1.0 - (avg_len - 100) / 200)

        # 检测是否有缩进（可能是代码块）
        has_indent = any(l.startswith((' ', '\t')) for l in lines)
        if has_indent and has_md_headers:
            return {'score': 0, 'features': {'reason': 'likely_markdown_with_code'}}

        return {
            'score': length_score * 0.8,  # 纯文本得分较低，作为fallback
            'features': {
                'avg_line_length': avg_len,
                'line_count': len(lines),
                'has_indentation': has_indent,
            }
        }
