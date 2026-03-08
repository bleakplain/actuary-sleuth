#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险产品文档提取模块

提供格式无关的文档提取框架，支持多种文档格式的自适应处理。
"""
from .detector import DocumentFormatDetector, FormatProfile
from .adapters import BaseFormatAdapter, get_adapter
from .chunkers import BaseChunker, TableSplitter, SectionSplitter, SemanticSplitter
from .deduplicator import BaseDeduplicator, HashDeduplicator
from .pipeline import ExtractionPipeline

__all__ = [
    'DocumentFormatDetector',
    'FormatProfile',
    'BaseFormatAdapter',
    'get_adapter',
    'BaseChunker',
    'TableSplitter',
    'SectionSplitter',
    'SemanticSplitter',
    'BaseDeduplicator',
    'HashDeduplicator',
    'ExtractionPipeline',
]
