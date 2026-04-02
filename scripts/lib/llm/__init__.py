#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块

支持多种 LLM 提供商：智谱 AI、Ollama 等

## 使用示例

### 场景化创建（推荐）
    from lib.llm import LLMClientFactory

    qa_llm = LLMClientFactory.create_qa_llm()
    audit_llm = LLMClientFactory.create_audit_llm()
"""

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient
from .factory import LLMClientFactory
from .langchain_adapter import ChatAdapter, EmbeddingAdapter

__all__ = [
    'BaseLLMClient',
    'ZhipuClient',
    'OllamaClient',
    'LLMClientFactory',
    'ChatAdapter',
    'EmbeddingAdapter',
]

__version__ = '2.0.0'
