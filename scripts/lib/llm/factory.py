#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端工厂类

提供场景化的 LLM 客户端创建方法。
"""
from typing import Optional

from .base import BaseLLMClient
from .zhipu import ZhipuClient
from .ollama import OllamaClient


class LLMClientFactory:
    """LLM 客户端工厂（面向场景）"""

    @staticmethod
    def _create_chat_client(
        provider: str, model: str, api_key: Optional[str],
        base_url: Optional[str], host: Optional[str], timeout: int,
    ) -> BaseLLMClient:
        """根据配置值创建聊天客户端（内部方法）"""
        if provider == 'zhipu':
            return ZhipuClient(
                api_key=api_key, model=model,
                base_url=base_url, timeout=timeout,
            )
        return OllamaClient(
            host=host, model=model, timeout=timeout,
        )

    @staticmethod
    def create_qa_llm() -> BaseLLMClient:
        """创建问答场景 LLM"""
        from lib.config import get_config
        return LLMClientFactory._create_chat_client(*get_config().get_qa_llm())

    @staticmethod
    def create_audit_llm() -> BaseLLMClient:
        """创建审计场景 LLM"""
        from lib.config import get_config
        return LLMClientFactory._create_chat_client(*get_config().get_audit_llm())

    @staticmethod
    def create_eval_llm() -> BaseLLMClient:
        """创建评估场景 LLM（RAGAS 等评估框架使用）"""
        from lib.config import get_config
        return LLMClientFactory._create_chat_client(*get_config().get_eval_llm())

    @staticmethod
    def create_embed_llm() -> 'BaseEmbedding':
        """创建嵌入模型（LlamaIndex BaseEmbedding）"""
        from lib.config import get_config
        from lib.rag_engine.llamaindex_adapter import get_embedding_model
        return get_embedding_model(get_config().get_embed_llm())
