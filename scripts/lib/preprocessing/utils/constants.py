#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration constants for preprocessing module
"""
from dataclasses import dataclass


@dataclass
class ExtractionConfig:
    """Centralized configuration for extraction parameters"""

    # ========== Classification Thresholds ==========
    # Default threshold for product type classification
    DEFAULT_CLASSIFICATION_THRESHOLD: float = 0.3
    # Threshold for considering a product as hybrid (second highest score)
    HYBRID_PRODUCT_THRESHOLD: float = 0.5
    # Threshold for low confidence classification (triggers dynamic extraction)
    LOW_CONFIDENCE_THRESHOLD: float = 0.7

    # ========== Extractor Selection ==========
    # Character limit for key info position check
    KEY_INFO_SEARCH_WINDOW: int = 2000
    # Minimum coverage ratio of required fields in front section
    REQUIRED_FIELDS_COVERAGE_THRESHOLD: float = 0.75

    # ========== Fast Lane ==========
    FAST_CONTENT_MAX_CHARS: int = 1500
    FAST_EXTRACTION_MAX_TOKENS: int = 1500
    DEFAULT_FAST_CONFIDENCE: float = 0.85

    # ========== Dynamic Lane ==========
    DYNAMIC_CONTENT_MAX_CHARS: int = 15000
    DYNAMIC_EXTRACTION_MAX_TOKENS: int = 8000  # 提高以支持更多条款提取
    DYNAMIC_EXTRACTION_MAX_TOKENS_LARGE: int = 16000  # 大文档的条款提取
    DEFAULT_DYNAMIC_CONFIDENCE: float = 0.75

    # ========== Specialized Extractors ==========
    TABLE_CONTENT_MAX_CHARS: int = 3000
    TABLE_EXTRACTION_MAX_TOKENS: int = 2000
    CLAUSE_CONTENT_MAX_CHARS: int = 8000
    CLAUSE_EXTRACTION_MAX_TOKENS: int = 4000
    # HTML table format clauses (larger documents)
    TABLE_CLAUSE_CONTENT_MAX_CHARS: int = 50000
    TABLE_CLAUSE_EXTRACTION_MAX_TOKENS: int = 12000

    # ========== Metadata Keys ==========
    EXTRACTION_MODE: str = 'extraction_mode'
    PRODUCT_TYPE: str = 'product_type'
    IS_HYBRID: str = 'is_hybrid'
    VALIDATION_SCORE: str = 'validation_score'
    VALIDATION_ERRORS: str = 'validation_errors'
    VALIDATION_WARNINGS: str = 'validation_warnings'

    # ========== Provenance Values ==========
    PROVENANCE_FAST_LLM: str = 'fast_llm'
    PROVENANCE_DYNAMIC_LLM: str = 'dynamic_llm'
    PROVENANCE_REGEX: str = 'regex'
    PROVENANCE_SPECIALIZED: str = 'specialized_extractor'

    # ========== Specialized Extractor Keys ==========
    EXTRACTOR_PREMIUM_TABLE: str = 'premium_table'
    EXTRACTOR_CLAUSES: str = 'clauses'

    # ========== Field Indicators ==========
    FIELD_INDICATORS: dict = None

    def __post_init__(self):
        if self.FIELD_INDICATORS is None:
            self.FIELD_INDICATORS = {
                'product_name': ['产品名称', '保险产品', '保险计划'],
                'insurance_company': ['保险公司', '承保机构', '公司名称'],
                'insurance_period': ['保险期间', '保障期限', '保险期限'],
                'waiting_period': ['等待期', '观察期']
            }


# Global config instance
config = ExtractionConfig()
