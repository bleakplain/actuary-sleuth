#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块

支持多种 LLM 提供商：智谱 AI、Ollama 等

## 使用示例

### 场景化获取（推荐）
    from lib.llm import get_qa_llm, get_audit_llm

    qa_llm = get_qa_llm()
    audit_llm = get_audit_llm()

### 工厂创建（高级）
    from lib.llm import LLMClientFactory

    qa_llm = LLMClientFactory.create_qa_llm()
"""

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient
from .factory import LLMClientFactory
from .langchain_adapter import ChatAdapter, EmbeddingAdapter


def get_qa_llm() -> BaseLLMClient:
    """获取问答场景 LLM 客户端"""
    return LLMClientFactory.create_qa_llm()


def get_audit_llm() -> BaseLLMClient:
    """获取审核场景 LLM 客户端"""
    return LLMClientFactory.create_audit_llm()


def get_eval_llm() -> BaseLLMClient:
    """获取评估场景 LLM 客户端"""
    return LLMClientFactory.create_eval_llm()


def get_name_parser_llm() -> BaseLLMClient:
    """获取名称解析场景 LLM 客户端"""
    return LLMClientFactory.create_name_parser_llm()


def get_ocr_llm() -> BaseLLMClient:
    """获取 OCR 场景 LLM 客户端"""
    return LLMClientFactory.create_ocr_llm()


__all__ = [
    'BaseLLMClient',
    'ZhipuClient',
    'OllamaClient',
    'LLMClientFactory',
    'ChatAdapter',
    'EmbeddingAdapter',
    'get_qa_llm',
    'get_audit_llm',
    'get_eval_llm',
    'get_name_parser_llm',
    'get_ocr_llm',
]

__version__ = '2.1.0'
