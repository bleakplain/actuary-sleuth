#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块

支持多种LLM提供商：智谱AI、Ollama等

## 使用示例

### 场景化创建（推荐）
    from lib.llm import LLMClientFactory

    qa_llm = LLMClientFactory.get_qa_llm()
    audit_llm = LLMClientFactory.get_audit_llm()
    preprocess_llm = LLMClientFactory.get_doc_preprocess_llm()

### 直接创建客户端
    from lib.llm import LLMClientFactory

    client = LLMClientFactory.create_client({
        'provider': 'zhipu',
        'model': 'glm-4-flash',
        'api_key': 'your-api-key',
        'timeout': 60
    })

    response = client.chat([
        {'role': 'user', 'content': '你好'}
    ])

### 使用便捷函数
    from lib.llm import get_client

    client = get_client()  # 使用默认配置
    result = client.generate("解释一下保险法")
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
from .factory import (
    LLMClientFactory,
    get_client,
    reset_client,
    get_zhipu_client,
    get_ollama_client,
    get_embedding_client,
)

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
    'get_client',
    'reset_client',
    'get_zhipu_client',
    'get_ollama_client',
    'get_embedding_client',
]

__version__ = '2.0.0'
