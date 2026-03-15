#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理模块

统一的文档预处理框架，支持两类文档：

1. 保险产品文档预处理:
   - Normalizer: 文档规范化
   - ProductClassifier: 产品分类
   - ExtractorSelector: 提取器选择
   - FastExtractor: 快速提取器（快速通道）
   - DynamicExtractor: 动态提取器（动态通道）
   - ResultValidator: 结果验证器
   - DocumentExtractor: 统一提取器（主入口）

2. 法规文档元数据提取（用于 RAG 向量库）:
   - DocumentExtractor.extract_regulation_metadata(): 法规元数据提取

产品文档使用示例:
    from lib.llm import LLMClientFactory
    from lib.preprocessing import DocumentExtractor

    llm_client = LLMClientFactory.get_doc_preprocess_llm()
    extractor = DocumentExtractor(llm_client)

    result = extractor.extract(
        document=open('policy.txt').read(),
        source_type='text'
    )

法规文档使用示例:
    from lib.llm import LLMClientFactory
    from lib.preprocessing import DocumentExtractor

    llm_client = LLMClientFactory.get_doc_preprocess_llm()
    extractor = DocumentExtractor(llm_client)

    # 提取法规元数据
    result = extractor.extract_regulation_metadata(
        content=open('regulation.md').read(),
        source_file='regulation.md'
    )
    # result.record 包含 law_name, article_number, category 等字段
"""

from .models import (
    NormalizedDocument,
    DocumentProfile,
    StructureMarkers,
    ExtractResult,
    ValidationResult,
    ProductType,
    ExtractionRequest,
    ExtractionResponse,
    # 法规文档模型
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    RegulationProcessingOutcome,
    RegulationDocument,
)

from .normalizer import Normalizer
from .classifier import ProductClassifier
from .extractor_selector import ExtractorSelector
from .fast_extractor import FastExtractor, FastExtractionFailed
from .prompt_builder import PromptBuilder
from .dynamic_extractor import (
    PremiumTableExtractor,
    ClauseExtractor,
    DynamicExtractor,
)
from .validator import ResultValidator
from .document_extractor import DocumentExtractor, create_extractor
from .utils import parse_llm_json_response, config

__version__ = '1.0.0'

__all__ = [
    # Models - 产品文档
    'NormalizedDocument',
    'DocumentProfile',
    'StructureMarkers',
    'ExtractResult',
    'ValidationResult',
    'ProductType',
    'ExtractionRequest',
    'ExtractionResponse',

    # Models - 法规文档
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'RegulationProcessingOutcome',
    'RegulationDocument',

    # Core Components - 产品文档
    'Normalizer',
    'ProductClassifier',
    'ExtractorSelector',
    'FastExtractor',
    'FastExtractionFailed',
    'PromptBuilder',
    'DynamicExtractor',
    'PremiumTableExtractor',
    'ClauseExtractor',
    'ResultValidator',

    # Main Entry - 产品文档兼法规元数据提取
    'DocumentExtractor',
    'create_extractor',

    # Utils
    'parse_llm_json_response',
    'config',
]
