#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端工厂类

提供场景化的 LLM 客户端创建方法。
"""
import threading
from typing import Dict, Any, Optional

from .base import BaseLLMClient
from .models import ModelName
from .zhipu import ZhipuClient
from .ollama import OllamaClient


class LLMClientFactory:
    """LLM客户端工厂类（面向场景）"""

    _SCENARIOS = {
        'reg_import': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
        'doc_preprocess': {'model': None, 'timeout': None},  # 使用配置文件的值
        'audit': {'model': ModelName.GLM_4_PLUS, 'timeout': 120},
        'qa': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
    }

    @staticmethod
    def _get_base_config() -> tuple:
        """获取基础配置"""
        from lib.config import get_config
        app_config = get_config()
        return app_config.llm.api_key, app_config.llm.base_url

    @staticmethod
    def _create_zhipu_client(model: str, timeout: int) -> BaseLLMClient:
        """创建智谱客户端"""
        api_key, base_url = LLMClientFactory._get_base_config()
        return LLMClientFactory.create_client({
            'provider': 'zhipu',
            'model': model,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': timeout
        })

    @staticmethod
    def _create_scenario_llm(scenario: str) -> BaseLLMClient:
        """
        根据场景创建 LLM 客户端

        Args:
            scenario: 场景名称，对应 _SCENARIOS 的 key

        Returns:
            BaseLLMClient: LLM 客户端实例
        """
        if scenario not in LLMClientFactory._SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}. Available: {list(LLMClientFactory._SCENARIOS.keys())}")

        config = LLMClientFactory._SCENARIOS[scenario]

        # doc_preprocess 使用配置文件的值
        if config['model'] is None:
            from lib.config import get_config
            app_config = get_config()
            return LLMClientFactory._create_zhipu_client(
                app_config.llm.model, app_config.llm.timeout
            )

        return LLMClientFactory._create_zhipu_client(
            config['model'], config['timeout']
        )

    @staticmethod
    def get_reg_import_llm() -> BaseLLMClient:
        """获取法规导入场景 LLM"""
        return LLMClientFactory._create_scenario_llm('reg_import')

    @staticmethod
    def get_doc_preprocess_llm() -> BaseLLMClient:
        """获取文档预处理场景 LLM"""
        return LLMClientFactory._create_scenario_llm('doc_preprocess')

    @staticmethod
    def get_audit_llm() -> BaseLLMClient:
        """获取审计场景 LLM"""
        return LLMClientFactory._create_scenario_llm('audit')

    @staticmethod
    def get_qa_llm() -> BaseLLMClient:
        """获取问答场景 LLM"""
        return LLMClientFactory._create_scenario_llm('qa')

    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置"""
        api_key, base_url = LLMClientFactory._get_base_config()
        return {
            'provider': 'zhipu',
            'model': ModelName.EMBEDDING_3,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': 120,
        }

    @staticmethod
    def get_embedding_llm() -> OllamaClient:
        from lib.config import get_config
        app_config = get_config()
        return OllamaClient(
            host=app_config.ollama.host,
            model=app_config.ollama.embed_model,
            timeout=30
        )

    @staticmethod
    def create_client(config: Dict[str, Any]) -> BaseLLMClient:
        """
        根据配置创建LLM客户端

        Args:
            config: 配置字典，包含：
                - provider: 提供商类型 ("zhipu" 或 "ollama")
                - model: 模型名称
                - api_key: API密钥（智谱需要）
                - host: 服务地址（Ollama需要）
                - timeout: 超时时间

        Returns:
            BaseLLMClient: LLM客户端实例

        Raises:
            ValueError: 不支持的提供商类型
        """
        provider = config.get('provider', 'zhipu').lower()

        if provider == 'zhipu':
            api_key = config.get('api_key')
            if not api_key:
                raise ValueError("ZhipuAI requires 'api_key' in config")
            return ZhipuClient(
                api_key=api_key,
                model=config.get('model', 'glm-z1-air'),
                base_url=config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/'),
                timeout=config.get('timeout', 60)
            )

        elif provider == 'ollama':
            return OllamaClient(
                host=config.get('host', 'http://localhost:11434'),
                model=config.get('model', 'qwen2:7b'),
                timeout=config.get('timeout', 30)
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")


# 全局客户端实例（线程安全单例）
_client = None
_client_lock = threading.Lock()


def get_client(config: Optional[Dict[str, Any]] = None) -> BaseLLMClient:
    """
    获取LLM客户端实例

    Args:
        config: 配置字典，如果为None则使用默认配置

    Returns:
        BaseLLMClient: 客户端实例
    """
    global _client

    if _client is None:
        with _client_lock:
            if _client is None:
                if config is None:
                    api_key, base_url = LLMClientFactory._get_base_config()
                    config = {
                        'provider': 'zhipu',
                        'model': 'glm-z1-air',
                        'api_key': api_key,
                        'base_url': base_url,
                        'timeout': 60
                    }

                _client = LLMClientFactory.create_client(config)

    return _client


def reset_client():
    global _client
    with _client_lock:
        _client = None
