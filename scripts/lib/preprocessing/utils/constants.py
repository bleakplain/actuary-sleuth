#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration constants for preprocessing module
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any


@dataclass
class ExtractionConfig:
    """Centralized configuration for extraction parameters"""

    # ========== Classification Thresholds ==========
    DEFAULT_CLASSIFICATION_THRESHOLD: float = 0.3
    HYBRID_PRODUCT_THRESHOLD: float = 0.5
    LOW_CONFIDENCE_THRESHOLD: float = 0.7

    # ========== Extractor Selection ==========
    KEY_INFO_SEARCH_WINDOW: int = 2000
    REQUIRED_FIELDS_COVERAGE_THRESHOLD: float = 0.75

    # ========== Fast Lane ==========
    FAST_CONTENT_MAX_CHARS: int = 1500
    FAST_EXTRACTION_MAX_TOKENS: int = 1500
    DEFAULT_FAST_CONFIDENCE: float = 0.85

    # ========== Dynamic Lane ==========
    DYNAMIC_CONTENT_MAX_CHARS: int = 8000
    DYNAMIC_CHUNK_OVERLAP: int = 500
    DYNAMIC_EXTRACTION_MAX_TOKENS: int = 8000
    DYNAMIC_EXTRACTION_MAX_TOKENS_LARGE: int = 16000
    DEFAULT_DYNAMIC_CONFIDENCE: float = 0.75

    # ========== Noise Removal Patterns ==========
    PDF_NOISE_PATTERNS: List[Tuple[str, str]] = field(default_factory=list)
    HTML_NOISE_PATTERNS: List[Tuple[str, str]] = field(default_factory=list)

    # ========== Specialized Extractors ==========
    TABLE_CONTENT_MAX_CHARS: int = 3000
    TABLE_EXTRACTION_MAX_TOKENS: int = 2000
    CLAUSE_CONTENT_MAX_CHARS: int = 8000
    CLAUSE_EXTRACTION_MAX_TOKENS: int = 4000
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

    # ========== Semantic Deduplication ==========
    SEMANTIC_SIMILARITY_THRESHOLD: float = 0.9

    # ========== Specialized Parsers ==========
    ENABLE_SPECIALIZED_PARSERS: bool = True
    PARSER_TIMEOUT: int = 10

    # ========== Structure Analysis ==========
    STRUCTURE_ANALYSIS_SAMPLE_SIZE: int = 5000

    # ========== Multi-Strategy Extraction ==========
    MIN_VOTE_AGREEMENT: float = 0.5
    STRATEGY_TIMEOUT: int = 30

    # ========== Field Indicators ==========
    FIELD_INDICATORS: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.PDF_NOISE_PATTERNS = [
            (r'.{0,50}第\s*\d+\s*页.{0,20}\n', '\n'),
            (r'\n\s*\d+\s*\n', '\n'),
            (r'\n\s*\n\s*\n+', '\n\n'),
        ]

        self.HTML_NOISE_PATTERNS = [
            (r'<br\s*/?>', '\n'),
            (r'\n\s*\n\s*\n+', '\n\n'),
        ]

        self.FIELD_INDICATORS = {
            'product_name': ['产品名称', '保险产品', '保险计划'],
            'insurance_company': ['保险公司', '承保机构', '公司名称'],
            'insurance_period': ['保险期间', '保障期限', '保险期限'],
            'waiting_period': ['等待期', '观察期']
        }


config = ExtractionConfig()
