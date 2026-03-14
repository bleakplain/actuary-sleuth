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

2. 法规文档预处理（用于 RAG 向量库）:
   - RegulationCleaner: 法规文档清洗
   - RegulationExtractor: 法规结构化信息提取

产品文档使用示例:
    from lib.llm_client import LLMClientFactory
    from lib.preprocessing import DocumentExtractor

    llm_client = LLMClientFactory.create_client({'provider': 'zhipu', 'model': 'glm-4-flash'})
    extractor = DocumentExtractor(llm_client)

    result = extractor.extract(
        document=open('policy.txt').read(),
        source_type='text'
    )

法规文档使用示例:
    from lib.preprocessing import RegulationCleaner, RegulationExtractor
    from lib.preprocessing.models import RegulationRecord

    cleaner = RegulationCleaner()
    extractor = RegulationExtractor()
    record = RegulationRecord(law_name="", article_number="", category="未分类")

    # 清洗
    clean_result = cleaner.clean(content, 'regulation.md', record)
    # 提取
    extract_result = extractor.extract(content, record)
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

# 法规文档预处理
from .regulation_cleaner import RegulationCleaner
from .regulation_extractor import (
    RegulationExtractor,
    get_regulation_cleaning_prompt,
    get_regulation_extraction_prompt,
    format_regulation_completeness_prompt,
)

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

    # Core Components - 法规文档
    'RegulationCleaner',
    'RegulationExtractor',
    'get_regulation_cleaning_prompt',
    'get_regulation_extraction_prompt',
    'format_regulation_completeness_prompt',

    # Main Entry - 产品文档
    'DocumentExtractor',
    'create_extractor',

    # Utils
    'parse_llm_json_response',
    'config',
]
