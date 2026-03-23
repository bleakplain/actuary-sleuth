#!/usr/bin/env python3
"""配置验证模块

提供配置项验证功能，确保关键配置项（如 API 密钥）正确设置。
"""
import os
import re
from typing import Optional


class ConfigurationError(Exception):
    """配置错误异常"""
    pass


class ConfigValidator:
    """配置验证器"""

    @staticmethod
    def require_api_key(env_var: str, provider: str) -> str:
        """
        要求 API 密钥必须通过环境变量设置

        Args:
            env_var: 环境变量名
            provider: 提供商名称

        Returns:
            str: API 密钥

        Raises:
            ConfigurationError: 环境变量未设置或值为空
        """
        api_key = os.getenv(env_var)
        if not api_key:
            raise ConfigurationError(
                f"{provider} API 密钥未设置。请设置环境变量 '{env_var}'"
            )

        api_key = api_key.strip()
        if not api_key:
            raise ConfigurationError(
                f"{provider} API 密钥为空。请设置有效的环境变量 '{env_var}'"
            )

        return api_key

    @staticmethod
    def validate_zhipu_api_key(api_key: Optional[str] = None) -> str:
        """
        验证智谱 API 密钥

        Args:
            api_key: API 密钥，如果为 None 则从环境变量读取

        Returns:
            str: 有效的 API 密钥

        Raises:
            ConfigurationError: API 密钥无效
        """
        if api_key is None:
            api_key = ConfigValidator.require_api_key('ZHIPU_API_KEY', '智谱')

        if not api_key.startswith(('sk-', 'SDK')):
            raise ConfigurationError(
                f"智谱 API 密钥格式无效。密钥应以 'sk-' 或 'SDK' 开头"
            )

        if len(api_key) < 20:
            raise ConfigurationError(
                f"智谱 API 密钥长度不足。密钥长度应至少为 20 个字符"
            )

        return api_key

    @staticmethod
    def validate_feishu_app_config(app_id: Optional[str] = None, app_secret: Optional[str] = None) -> tuple:
        """
        验证飞书应用配置

        Args:
            app_id: 应用 ID
            app_secret: 应用密钥

        Returns:
            tuple: (app_id, app_secret)

        Raises:
            ConfigurationError: 配置无效
        """
        if app_id is None:
            app_id = os.getenv('FEISHU_APP_ID', '')
        if app_secret is None:
            app_secret = os.getenv('FEISHU_APP_SECRET', '')

        if not app_id or not app_id.strip():
            raise ConfigurationError(
                "飞书 App ID 未设置。请设置环境变量 'FEISHU_APP_ID'"
            )

        if not app_secret or not app_secret.strip():
            raise ConfigurationError(
                "飞书 App Secret 未设置。请设置环境变量 'FEISHU_APP_SECRET'"
            )

        return app_id.strip(), app_secret.strip()

    @staticmethod
    def validate_base_url(base_url: Optional[str] = None, provider: str = "zhipu") -> str:
        """
        验证基础 URL

        Args:
            base_url: 基础 URL
            provider: 提供商名称

        Returns:
            str: 有效的基础 URL

        Raises:
            ConfigurationError: URL 无效
        """
        if base_url is None:
            return ""

        base_url = base_url.strip()

        if not base_url:
            return ""

        url_pattern = re.compile(
            r'^https?://[a-zA-Z0-9.-]+(:\d+)?(/.*)?$',
            re.IGNORECASE
        )

        if not url_pattern.match(base_url):
            raise ConfigurationError(
                f"{provider} 基础 URL 格式无效: {base_url}"
            )

        return base_url

    @staticmethod
    def validate_timeout(timeout: Optional[int], provider: str = "llm") -> int:
        """
        验证超时设置

        Args:
            timeout: 超时时间（秒）
            provider: 提供商名称

        Returns:
            int: 有效的超时时间

        Raises:
            ConfigurationError: 超时时间无效
        """
        if timeout is None:
            return 60

        if not isinstance(timeout, int) or timeout <= 0:
            raise ConfigurationError(
                f"{provider} 超时时间必须为正整数，当前值: {timeout}"
            )

        if timeout > 600:
            raise ConfigurationError(
                f"{provider} 超时时间过长（超过 600 秒）: {timeout}"
            )

        return timeout

    @staticmethod
    def validate_model_name(model: str, provider: str = "llm") -> str:
        """
        验证模型名称

        Args:
            model: 模型名称
            provider: 提供商名称

        Returns:
            str: 有效的模型名称

        Raises:
            ConfigurationError: 模型名称无效
        """
        if not model or not model.strip():
            raise ConfigurationError(
                f"{provider} 模型名称不能为空"
            )

        model = model.strip()

        if len(model) > 100:
            raise ConfigurationError(
                f"{provider} 模型名称过长（超过 100 个字符）: {model[:50]}..."
            )

        return model
