#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端工厂类

提供场景化的 LLM 客户端创建方法。
"""
from typing import Dict

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient


class LLMClientFactory:
    """LLM 客户端工厂（面向场景）"""

    @staticmethod
    def _create_client(provider: str) -> BaseLLMClient:
        """根据 provider 创建聊天客户端（内部方法）"""
        from lib.config import get_config
        cfg = get_config()

        if provider == 'zhipu':
            return ZhipuClient(
                api_key=cfg._zhipu.api_key,
                model=cfg._zhipu.chat_model,
                base_url=cfg._zhipu.base_url,
                timeout=cfg._zhipu.timeout,
            )
        elif provider == 'ollama':
            return OllamaClient(
                host=cfg._ollama.host,
                model=cfg._ollama.chat_model,
                timeout=cfg._ollama.timeout,
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    @staticmethod
    def get_qa_llm() -> BaseLLMClient:
        """获取问答场景 LLM"""
        from lib.config import get_config
        return LLMClientFactory._create_client(
            get_config()._llm.get_provider('qa')
        )

    @staticmethod
    def get_audit_llm() -> BaseLLMClient:
        """获取审计场景 LLM"""
        from lib.config import get_config
        return LLMClientFactory._create_client(
            get_config()._llm.get_provider('audit')
        )

    @staticmethod
    def get_eval_llm() -> BaseLLMClient:
        """获取评估场景 LLM（RAGAS 等评估框架使用）"""
        from lib.config import get_config
        return LLMClientFactory._create_client(
            get_config()._llm.get_provider('eval')
        )

    @staticmethod
    def get_doc_preprocess_llm() -> BaseLLMClient:
        """获取文档预处理场景 LLM"""
        from lib.config import get_config
        return LLMClientFactory._create_client(
            get_config()._llm.get_provider('doc_preprocess')
        )

    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置（供 get_embedding_model 使用）"""
        from lib.config import get_config
        cfg = get_config()
        provider = cfg._llm.get_provider('embed')

        if provider == 'ollama':
            return {
                'provider': 'ollama',
                'model': cfg._ollama.embed_model,
                'host': cfg._ollama.host,
                'timeout': cfg._ollama.timeout,
            }
        else:
            return {
                'provider': 'zhipu',
                'model': cfg._zhipu.embed_model,
                'api_key': cfg._zhipu.api_key,
                'base_url': cfg._zhipu.base_url,
                'timeout': cfg._zhipu.timeout,
            }

    @staticmethod
    def get_embedding_llm() -> ZhipuClient:
        """获取嵌入模型客户端"""
        config = LLMClientFactory.get_embedding_config()
        if config['provider'] == 'zhipu':
            return ZhipuClient(
                api_key=config['api_key'],
                model=config['model'],
                base_url=config['base_url'],
                timeout=config['timeout'],
            )
        raise ValueError("get_embedding_llm() only supports zhipu provider")
