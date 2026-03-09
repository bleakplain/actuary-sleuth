#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险产品文档提取模块

提供格式无关的文档提取框架。

核心组件：
- BaseChunker: 分块策略基类
- HybridChunker: 智能分块器（自动适配表格/章节/纯文本）
- BaseDeduplicator: 去重器基类
- DocumentExtractor: 文档提取器（LLM + 规则混合提取）

DocumentExtractor 支持通过 max_concurrent 参数配置并发数。
"""
from .chunkers import BaseChunker, HybridChunker, TableSplitter, SectionSplitter, SemanticSplitter
from .deduplicator import BaseDeduplicator, HashDeduplicator
from .models import ExtractResult, QualityMetrics
from .llm_extractor import LLMExtractor
from .rule_extractor import RuleExtractor
from .result_merger import LLMRuleMerger, ExtractQualityAssessor
from .document_extractor import DocumentExtractor

__all__ = [
    # Chunkers
    'BaseChunker',
    'HybridChunker',
    'TableSplitter',
    'SectionSplitter',
    'SemanticSplitter',
    # Deduplicators
    'BaseDeduplicator',
    'HashDeduplicator',
    # Models
    'ExtractResult',
    'QualityMetrics',
    # Extractors
    'LLMExtractor',
    'RuleExtractor',
    'DocumentExtractor',
    # Merger & Quality
    'LLMRuleMerger',
    'ExtractQualityAssessor',
]
