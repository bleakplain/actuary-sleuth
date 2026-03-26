#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理模块

基于渐进式多策略架构的文档预处理框架。

核心架构:
    文档输入
        ↓
    规范化 (Normalizer)
        ↓
    语义分析 (SemanticAnalyzer)
        ↓
    混合提取 (HybridExtractor)
        ├─ 正则提取 (RegexExtractor)
        ├─ Few-shot 提取 (FewShotExtractor)
        ├─ 表格提取 (TableExtractor)
        └─ 分块 LLM 提取 (ChunkedLLMExtractor)
        ↓
    融合 (Fuser)
        ↓
    去重 (Deduplicator)
        ↓
    验证 (Validator)
        ↓
    结构化输出

使用示例:
    from lib.llm import LLMClientFactory
    from lib.preprocessing import DocumentExtractor

    llm_client = LLMClientFactory.get_doc_preprocess_llm()
    extractor = DocumentExtractor(llm_client)

    result = extractor.extract(
        document=open('policy.txt').read(),
        source_type='text'
    )
"""

# Models
from .models import (
    NormalizedDocument,
    DocumentProfile,
    StructureMarkers,
    ExtractResult,
    ValidationResult,
    ProductType,
    ExtractionRequest,
    ExtractionResponse,
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    RegulationProcessingOutcome,
    RegulationDocument,
)

# Core Components
from .normalizer import Normalizer
from .classifier import Classifier
from .semantic_analyzer import SemanticAnalyzer
from .parser_engine import ParserEngine, PremiumTableParser, DiseaseListParser
from .deduplicator import Deduplicator
from .prompt_builder import PromptBuilder
from .validator import Validator

# New Architecture Components
from .hybrid_extractor import HybridExtractor
from .fuser import Fuser

# Extractors
from .extractors.base import Extractor, ExtractionResult
from .extractors.regex import RegexExtractor
from .extractors.fewshot import FewShotExtractor
from .extractors.table import TableExtractor
from .extractors.chunked_llm import ChunkedLLMExtractor

# Main Entry
from .document_extractor import DocumentExtractor, create_extractor

# Utils
from .utils import parse_llm_json_response, config

__version__ = '2.0.0'

__all__ = [
    # Models
    'NormalizedDocument',
    'DocumentProfile',
    'StructureMarkers',
    'ExtractResult',
    'ValidationResult',
    'ProductType',
    'ExtractionRequest',
    'ExtractionResponse',
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'RegulationProcessingOutcome',
    'RegulationDocument',

    # Core Components
    'Normalizer',
    'Classifier',
    'SemanticAnalyzer',
    'ParserEngine',
    'PremiumTableParser',
    'DiseaseListParser',
    'Deduplicator',
    'PromptBuilder',
    'Validator',

    # New Architecture
    'HybridExtractor',
    'Fuser',

    # Extractors
    'Extractor',
    'ExtractionResult',
    'RegexExtractor',
    'FewShotExtractor',
    'TableExtractor',
    'ChunkedLLMExtractor',

    # Main Entry
    'DocumentExtractor',
    'create_extractor',

    # Utils
    'parse_llm_json_response',
    'config',
]
