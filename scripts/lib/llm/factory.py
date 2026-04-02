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
from lib.common.config_validator import ConfigValidator


class LLMClientFactory:
    """LLM客户端工厂类（面向场景）"""

    _SCENARIOS = {
        'reg_import': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
        'doc_preprocess': {'model': None, 'timeout': None},  # 使用配置文件的值
        'audit': {'model': ModelName.GLM_4_PLUS, 'timeout': 120},
        'qa': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
        'eval': {'model': ModelName.GLM_4_FLASH, 'timeout': 180},
    }

    @staticmethod
    def _build_provider_config(provider: str, scene: str, **overrides) -> dict:
        """根据 provider 和场景构建客户端配置"""
        from lib.config import get_config
        cfg = get_config()
        if provider == 'ollama':
            result = {
                'provider': 'ollama',
                'model': getattr(cfg._ollama, f'{scene}_model'),
                'host': cfg._ollama.host,
                'timeout': cfg._ollama.timeout,
            }
        else:
            result = {
                'provider': 'zhipu',
                'model': getattr(cfg._zhipu, f'{scene}_model'),
                'api_key': cfg._zhipu.api_key,
                'base_url': cfg._zhipu.base_url,
                'timeout': cfg._zhipu.timeout,
            }
        result.update(overrides)
        return result

    @staticmethod
    def _create_zhipu_client(model: str, timeout: int) -> BaseLLMClient:
        """创建智谱客户端"""
        return LLMClientFactory.create_client(
            LLMClientFactory._build_provider_config('zhipu', 'chat', model=model, timeout=timeout)
        )

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
            cfg = get_config()
            provider = cfg._llm.chat.get('provider', 'zhipu')
            return LLMClientFactory.create_client(
                LLMClientFactory._build_provider_config(provider, 'chat')
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
    def get_eval_llm() -> BaseLLMClient:
        """获取评估场景 LLM（RAGAS 等评估框架使用，timeout 较长）"""
        return LLMClientFactory._create_scenario_llm('eval')

    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置"""
        from lib.config import get_config
        cfg = get_config()
        provider = cfg._llm.embed.get('provider', 'zhipu')
        return LLMClientFactory._build_provider_config(provider, 'embed')

    @staticmethod
    def get_embedding_llm() -> ZhipuClient:
        config = LLMClientFactory.get_embedding_config()
        if config['provider'] == 'zhipu':
            return ZhipuClient(
                api_key=config['api_key'],
                model=config['model'],
                base_url=config['base_url'],
                timeout=config['timeout']
            )
        raise ValueError("get_embedding_llm() only supports zhipu provider")

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
            ConfigurationError: 配置无效
        """
        provider = config.get('provider', 'zhipu').lower()

        if provider == 'zhipu':
            api_key = ConfigValidator.validate_zhipu_api_key(
                config.get('api_key')
            )
            model = ConfigValidator.validate_model_name(
                config.get('model', 'glm-z1-air'),
                '智谱'
            )
            base_url = ConfigValidator.validate_base_url(
                config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/'),
                '智谱'
            )
            timeout = ConfigValidator.validate_timeout(
                config.get('timeout', 60),
                '智谱'
            )
            return ZhipuClient(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout=timeout
            )

        elif provider == 'ollama':
            host = config.get('host', 'http://localhost:11434')
            model = ConfigValidator.validate_model_name(
                config.get('model', 'qwen2:7b'),
                'Ollama'
            )
            timeout = ConfigValidator.validate_timeout(
                config.get('timeout', 30),
                'Ollama'
            )
            return OllamaClient(
                host=host,
                model=model,
                timeout=timeout
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
                    from lib.config import get_config
                    cfg = get_config()
                    provider = cfg._llm.chat.get('provider', 'zhipu')
                    config = LLMClientFactory._build_provider_config(provider, 'chat')

                _client = LLMClientFactory.create_client(config)

    return _client


def reset_client():
    global _client
    with _client_lock:
        _client = None
