#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 客户端工厂类，提供场景化的 LLM 客户端创建方法。"""

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient
from .minimax import MinimaxClient
from lib.config import (
    get_qa_llm_config, get_audit_llm_config, get_eval_llm_config,
    get_embed_llm_config, get_name_parser_llm_config, get_ocr_llm_config,
)


class LLMClientFactory:

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
        from lib.rag_engine.llamaindex_adapter import _create_embedding_model
        return _create_embedding_model(get_embed_llm_config())

    @staticmethod
    def create_client(cfg) -> BaseLLMClient:
        if cfg.provider == 'zhipu':
            return ZhipuClient(api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url, timeout=cfg.timeout)

        elif cfg.provider == 'ollama':
            return OllamaClient(host=cfg.base_url, model=cfg.model, timeout=cfg.timeout)

        elif cfg.provider == 'minmax':
            return MinimaxClient(api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url, timeout=cfg.timeout)

        else:
            raise ValueError(f"Unsupported LLM provider: {cfg.provider}")
