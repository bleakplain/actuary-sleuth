#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智谱 AI 客户端
"""
import json
import re
import logging
import requests
from typing import List, Dict

from .base import BaseLLMClient
from .metrics import _track_timing, _with_circuit_breaker, _retry_with_backoff


logger = logging.getLogger(__name__)


class ZhipuClient(BaseLLMClient):
    """智谱AI客户端"""

    def __init__(
        self,
        api_key: str,
        model: str = "glm-z1-air",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/",
        timeout: int = 60
    ):
        """
        初始化智谱AI客户端

        Args:
            api_key: 智谱AI API密钥
            model: 模型名称，默认 glm-z1-air（轻量模型，并发数30）
                   可选:
                   - glm-z1-air: 轻量模型，并发数30，适合批量处理
                   - glm-4-flash: 快速响应，并发数较高
                   - glm-4-air: 平衡性能
                   - glm-4-plus: 高质量，并发数2
                   - glm-4-0520: 旧版本
            base_url: API基础URL
            timeout: 请求超时时间（秒）
        """
        super().__init__(model, timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

    def _do_generate(self, prompt: str, **kwargs) -> str:
        """
        实际执行单次 API 调用

        Args:
            prompt: 提示词
            **kwargs: 其他参数

        Returns:
            str: 生成的文本
        """
        self._validate_prompt(prompt)
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }

        response = self._session.post(
            url,
            json=data,
            timeout=self.timeout
        )

        # 对 429 和 5xx 错误抛出包含状态码的异常
        if response.status_code == 429:
            raise requests.exceptions.RequestException(
                f"429 Rate limit exceeded: {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(
                f"{response.status_code} Server error: {response.text[:200]}"
            )

        response.raise_for_status()
        result = response.json()

        if 'choices' not in result or len(result['choices']) == 0:
            raise ValueError(f"Unexpected response format: 'choices' field missing or empty. Response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

        message = result['choices'][0]['message']

        if message.get('content'):
            return message['content']

        if message.get('reasoning_content'):
            reasoning = message['reasoning_content']
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', reasoning, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    return json.dumps(parsed, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
            return reasoning

        raise ValueError(f"Message missing both 'content' and 'reasoning_content' fields. Available keys: {list(message.keys())}")

    @_track_timing("zhipu")
    @_with_circuit_breaker("zhipu")
    @_retry_with_backoff(max_retries=3, base_delay=2, rate_limit_delay_mult=3)
    def generate(self, prompt: str, **kwargs) -> str:
        return self._do_generate(prompt, **kwargs)

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self._validate_messages(messages)
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": messages,
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }

        response = self._session.post(url, json=data, timeout=self.timeout)

        if response.status_code == 429:
            raise requests.exceptions.RequestException(
                f"429 Rate limit exceeded: {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(
                f"{response.status_code} Server error: {response.text[:200]}"
            )

        response.raise_for_status()
        result = response.json()

        if 'choices' not in result or len(result['choices']) == 0:
            raise ValueError(f"Unexpected response format: 'choices' field missing or empty. Response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

        message = result['choices'][0]['message']
        if not message.get('content'):
            raise ValueError(f"Message missing 'content' field. Available keys: {list(message.keys())}")

        return message['content']

    @_track_timing("zhipu")
    @_with_circuit_breaker("zhipu")
    @_retry_with_backoff(max_retries=3, base_delay=2, rate_limit_delay_mult=3)
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self._do_chat(messages, **kwargs)

    def health_check(self) -> bool:
        """
        检查智谱AI服务是否可用

        Returns:
            bool: 服务可用返回 True
        """
        try:
            url = f"{self.base_url}/chat/completions"
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 10
            }

            response = self._session.post(
                url,
                json=data,
                timeout=5
            )
            return response.status_code == 200

        except requests.exceptions.RequestException:
            return False
