#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理模块

统一的保险产品文档预处理框架。

核心组件:
- DocumentNormalizer: 文档规范化
- ProductTypeClassifier: 产品类型分类
- RouteSelector: 提取路由选择
- FastExtractor: 快速提取器（快速通道）
- StructuredExtractor: 结构化提取器（完整通道）
- ResultValidator: 结果验证器
- DocumentExtractor: 统一提取器（主入口）

使用示例:
    from lib.llm_client import LLMClientFactory
    from lib.preprocessing import DocumentExtractor

    llm_client = LLMClientFactory.create_client({'provider': 'zhipu', 'model': 'glm-4-flash'})
    extractor = DocumentExtractor(llm_client)

    result = extractor.extract(
        document=open('policy.txt').read(),
        source_type='text'
    )
"""

from .models import (
    NormalizedDocument,
    FormatInfo,
    StructureMarkers,
    ExtractionRoute,
    ExtractResult,
    ValidationResult,
    ProductType,
    StructureInfo,
    ExtractionRequest,
    ExtractionResponse,
)

from .document_normalizer import DocumentNormalizer
from .classifier import ProductTypeClassifier
from .path_selector import RouteSelector
from .fast_extractor import FastExtractor, FastExtractionFailed
from .prompt_builder import PromptBuilder
from .structured_extractor import (
    StructureAnalyzer,
    PremiumTableExtractor,
    ClauseExtractor,
    StructuredExtractor,
)
from .validator import ResultValidator
from .extractor import DocumentExtractor, create_extractor

__version__ = '1.0.0'

__all__ = [
    # Models
    'NormalizedDocument',
    'FormatInfo',
    'StructureMarkers',
    'ExtractionRoute',
    'ExtractResult',
    'ValidationResult',
    'ProductType',
    'StructureInfo',
    'ExtractionRequest',
    'ExtractionResponse',

    # Core Components
    'DocumentNormalizer',
    'ProductTypeClassifier',
    'RouteSelector',
    'FastExtractor',
    'FastExtractionFailed',
    'PromptBuilder',
    'StructuredExtractor',
    'StructureAnalyzer',
    'PremiumTableExtractor',
    'ClauseExtractor',
    'ResultValidator',

    # Main Entry
    'DocumentExtractor',
    'create_extractor',
]
