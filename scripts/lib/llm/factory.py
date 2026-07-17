#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 客户端工厂类，提供场景化的 LLM 客户端创建方法。"""
import threading
from typing import Dict

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient
from lib.config import (
    get_qa_llm_config, get_audit_llm_config, get_eval_llm_config,
    get_embed_llm_config, get_name_parser_llm_config, get_ocr_llm_config,
)

_client_cache: Dict[str, BaseLLMClient] = {}
_cache_lock = threading.Lock()


class LLMClientFactory:

    @staticmethod
    def _get_or_create(cfg) -> BaseLLMClient:
        cache_key = f"{cfg.provider}:{cfg.model}"
        with _cache_lock:
            if cache_key in _client_cache:
                return _client_cache[cache_key]
        client = LLMClientFactory.create_client(cfg)
        with _cache_lock:
            _client_cache[cache_key] = client
        return client

    @staticmethod
    def create_name_parser_llm() -> BaseLLMClient:
        return LLMClientFactory._get_or_create(get_name_parser_llm_config())

    @staticmethod
    def create_audit_llm() -> BaseLLMClient:
        return LLMClientFactory._get_or_create(get_audit_llm_config())

    @staticmethod
    def create_qa_llm() -> BaseLLMClient:
        return LLMClientFactory._get_or_create(get_qa_llm_config())

    @staticmethod
    def create_eval_llm() -> BaseLLMClient:
        return LLMClientFactory._get_or_create(get_eval_llm_config())

    @staticmethod
    def create_ocr_llm() -> BaseLLMClient:
        return LLMClientFactory._get_or_create(get_ocr_llm_config())

    @staticmethod
    def create_embed_llm() -> BaseLLMClient:
        return LLMClientFactory.create_client(get_embed_llm_config())

    @staticmethod
    def create_embed_model():
        from lib.rag_engine.llamaindex_adapter import _create_embedding_model
        return _create_embedding_model(get_embed_llm_config())

    @staticmethod
    def create_ragas_llm():
        from lib.llm.langchain_adapter import ChatAdapter
        return ChatAdapter(client=LLMClientFactory.create_eval_llm())

    @staticmethod
    def create_ragas_embed_model():
        from lib.llm.langchain_adapter import EmbeddingAdapter
        return EmbeddingAdapter(LLMClientFactory.create_embed_llm())

    @staticmethod
    def create_client(cfg) -> BaseLLMClient:
        if cfg.provider == 'zhipu':
            return ZhipuClient(api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url, timeout=cfg.timeout)

        elif cfg.provider == 'ollama':
            return OllamaClient(host=cfg.base_url, model=cfg.model, timeout=cfg.timeout, max_tokens=cfg.max_tokens)

        else:
            raise ValueError(f"Unsupported LLM provider: {cfg.provider}")
