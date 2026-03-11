#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理模块

统一的保险产品文档预处理框架。

核心组件:
- DocumentNormalizer: 文档规范化
- ProductTypeClassifier: 产品类型分类
- ExtractionPathSelector: 提取路径选择
- LightweightExtractor: 轻量级提取器（快速路径）
- StructuredExtractor: 结构化提取器（完整路径）
- ExtractResultValidator: 结果验证器
- UnifiedDocumentExtractor: 统一提取器（主入口）

使用示例:
    from lib.llm_client import LLMClientFactory
    from lib.preprocessing import UnifiedDocumentExtractor

    llm_client = LLMClientFactory.create_client({'provider': 'zhipu', 'model': 'glm-4-flash'})
    extractor = UnifiedDocumentExtractor(llm_client)

    result = extractor.extract(
        document=open('policy.txt').read(),
        source_type='text'
    )
"""

from .models import (
    NormalizedDocument,
    FormatInfo,
    StructureMarkers,
    ExtractionPath,
    ExtractResult,
    ValidationResult,
    ProductType,
    StructureInfo,
    ExtractionRequest,
    ExtractionResponse,
)

from .document_normalizer import DocumentNormalizer
from .classifier import ProductTypeClassifier
from .path_selector import ExtractionPathSelector
from .lightweight_extractor import LightweightExtractor, FastPathExtractionFailed
from .prompt_builder import PromptBuilder
from .structured_extractor import (
    StructureAnalyzer,
    PremiumTableExtractor,
    ClauseExtractor,
    StructuredExtractor,
)
from .validator import ExtractResultValidator
from .extractor import UnifiedDocumentExtractor, create_extractor

__version__ = '1.0.0'

__all__ = [
    # Models
    'NormalizedDocument',
    'FormatInfo',
    'StructureMarkers',
    'ExtractionPath',
    'ExtractResult',
    'ValidationResult',
    'ProductType',
    'StructureInfo',
    'ExtractionRequest',
    'ExtractionResponse',

    # Core Components
    'DocumentNormalizer',
    'ProductTypeClassifier',
    'ExtractionPathSelector',
    'LightweightExtractor',
    'FastPathExtractionFailed',
    'PromptBuilder',
    'StructuredExtractor',
    'StructureAnalyzer',
    'PremiumTableExtractor',
    'ClauseExtractor',
    'ExtractResultValidator',

    # Main Entry
    'UnifiedDocumentExtractor',
    'create_extractor',
]
