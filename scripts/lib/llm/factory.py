#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 客户端工厂类，提供场景化的 LLM 客户端创建方法。"""
from typing import Dict, Any

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient
from lib.common.config_validator import ConfigValidator
from lib.config import (
    get_qa_llm_config, get_audit_llm_config, get_eval_llm_config,
    get_embed_llm_config, get_name_parser_llm_config, get_ocr_llm_config,
)


class LLMClientFactory:
    """LLM 客户端工厂类（面向场景）"""

    @staticmethod
    def create_name_parser_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_name_parser_llm_config())

    @staticmethod
    def create_audit_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_audit_llm_config())

    @staticmethod
    def create_qa_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_qa_llm_config())

    @staticmethod
    def create_eval_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_eval_llm_config())

    @staticmethod
    def create_ocr_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_ocr_llm_config())

    @staticmethod
    def create_embed_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_embed_llm_config())

    @staticmethod
    def create_embed_model():
        """创建 LlamaIndex BaseEmbedding 实例，用于向量检索。"""
        from lib.rag_engine.llamaindex_adapter import _create_embedding_model
        return _create_embedding_model(get_embed_llm_config())

    @staticmethod
    def create_client(config: Dict[str, Any]) -> BaseLLMClient:
        provider = config.get('provider', 'zhipu').lower()

        if provider == 'zhipu':
            api_key = ConfigValidator.validate_zhipu_api_key(config.get('api_key'))
            model = ConfigValidator.validate_model_name(
                config.get('model', 'glm-z1-air'), '智谱'
            )
            base_url = ConfigValidator.validate_base_url(
                config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/'), '智谱'
            )
            timeout = ConfigValidator.validate_timeout(config.get('timeout', 60), '智谱')
            return ZhipuClient(
                api_key=api_key, model=model, base_url=base_url, timeout=timeout
            )

        elif provider == 'ollama':
            host = config.get('host', 'http://localhost:11434')
            model = ConfigValidator.validate_model_name(
                config.get('model', 'qwen2:7b'), 'Ollama'
            )
            timeout = ConfigValidator.validate_timeout(config.get('timeout', 30), 'Ollama')
            return OllamaClient(host=host, model=model, timeout=timeout)

        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
