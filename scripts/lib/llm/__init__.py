#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块

支持多种 LLM 提供商：智谱 AI、Ollama 等

## 使用示例

### 场景化创建（推荐）
    from lib.llm import LLMClientFactory

    qa_llm = LLMClientFactory.get_qa_llm()
    audit_llm = LLMClientFactory.get_audit_llm()
    preprocess_llm = LLMClientFactory.get_doc_preprocess_llm()
"""

# 基础组件
from .models import ModelName
from .base import BaseLLMClient
from .metrics import (
    APIMetrics,
    CircuitBreaker,
    CircuitState,
    get_metrics,
)

# 客户端实现
from .zhipu import ZhipuClient
from .ollama import OllamaClient

# 工厂
from .factory import LLMClientFactory

# LangChain 适配器
from .langchain_adapter import ChatAdapter, EmbeddingAdapter

__all__ = [
    # 基础
    'ModelName',
    'BaseLLMClient',

    # 指标
    'APIMetrics',
    'CircuitBreaker',
    'CircuitState',
    'get_metrics',

    # 客户端
    'ZhipuClient',
    'OllamaClient',

    # 工厂
    'LLMClientFactory',

    # LangChain 适配器
    'ChatAdapter',
    'EmbeddingAdapter',
]

__version__ = '2.0.0'
