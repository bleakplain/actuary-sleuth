#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Fixture"""
import pytest
from lib.preprocessing.normalizer import Normalizer
from lib.preprocessing.classifier import Classifier
from lib.preprocessing.semantic_analyzer import SemanticAnalyzer
from .mocks import MockLLMClient


@pytest.fixture
def mock_llm():
    """Mock LLM 客户端"""
    return MockLLMClient()


@pytest.fixture
def normalizer():
    """规范化器实例"""
    return Normalizer()


@pytest.fixture
def classifier(mock_llm):
    """分类器实例"""
    return Classifier(mock_llm)


@pytest.fixture
def semantic_analyzer(mock_llm):
    """语义分析器实例"""
    return SemanticAnalyzer(mock_llm)


@pytest.fixture
def sample_document():
    """示例文档"""
    return """
    # 产品名称：测试保险
    ## 保险期间：终身
    ### 条款
    第一条：保障范围
    """
