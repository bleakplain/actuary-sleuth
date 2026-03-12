#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档预处理模块

统一的保险产品文档预处理框架。

核心组件:
- Normalizer: 文档规范化
- ProductClassifier: 产品分类
- ExtractorSelector: 提取器选择
- FastExtractor: 快速提取器（快速通道）
- DynamicExtractor: 动态提取器（动态通道）
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
    DocumentProfile,
    StructureMarkers,
    ExtractResult,
    ValidationResult,
    ProductType,
    ExtractionRequest,
    ExtractionResponse,
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
    # Models
    'NormalizedDocument',
    'DocumentProfile',
    'StructureMarkers',
    'ExtractResult',
    'ValidationResult',
    'ProductType',
    'ExtractionRequest',
    'ExtractionResponse',

    # Core Components
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

    # Main Entry
    'DocumentExtractor',
    'create_extractor',

    # Utils
    'parse_llm_json_response',
    'config',
]
