#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Mock 工具"""
from unittest.mock import Mock
from lib.preprocessing.extractors.base import ExtractionResult


class MockLLMClient:
    """Mock LLM 客户端"""

    def __init__(self, response: str = '{"data": "mock"}'):
        self.response = response
        self.call_count = 0

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        return self.response


class MockExtractor:
    """Mock 提取器"""

    def __init__(self, data: dict, confidence: float = 0.9):
        self.data = data
        self.confidence = confidence

    def extract(self, document: str, structure: dict, required_fields: set) -> ExtractionResult:
        return ExtractionResult(
            data=self.data,
            confidence=self.confidence,
            extractor='mock',
            duration=0.1,
            metadata={}
        )
