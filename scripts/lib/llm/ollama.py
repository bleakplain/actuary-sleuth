#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama 客户端
"""
import logging
import requests  # type: ignore[import-untyped]
from typing import List, Dict

from .base import BaseLLMClient
from .metrics import _track_timing, _with_circuit_breaker, _retry_with_backoff


logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Ollama 客户端"""

    _session: requests.Session

    def __init__(
        self,
        host: str = 'http://localhost:11434',
        model: str = 'qwen2:7b',
        timeout: int = 30
    ):
        """
        初始化Ollama客户端

        Args:
            host: Ollama服务地址
            model: 模型名称
            timeout: 请求超时时间
        """
        super().__init__(model, timeout)
        self.host = host.rstrip('/')
        self._session = requests.Session()

    def _do_generate(self, prompt: str, **kwargs) -> str:
        """实际执行单次 API 调用"""
        self._validate_prompt(prompt)
        url = f"{self.host}/api/generate"
        data = {
            "model": kwargs.get('model', self.model),
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get('temperature', 0.7),
                "num_predict": kwargs.get('max_tokens', 500)
            }
        }

        response = self._session.post(url, json=data, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        return result.get('response', '')

    @_track_timing("ollama")
    @_with_circuit_breaker("ollama")
    @_retry_with_backoff(max_retries=3, base_delay=2, rate_limit_delay_mult=2)
    def generate(self, prompt: str, **kwargs) -> str:
        return self._do_generate(prompt, **kwargs)

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self._validate_messages(messages)
        url = f"{self.host}/api/chat"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get('temperature', 0.7),
                "num_predict": kwargs.get('max_tokens', 500)
            }
        }

        response = self._session.post(url, json=data, timeout=self.timeout)
        response.raise_for_status()
        result = response.json()
        return result.get('message', {}).get('content', '')

    @_track_timing("ollama")
    @_with_circuit_breaker("ollama")
    @_retry_with_backoff(max_retries=3, base_delay=2, rate_limit_delay_mult=2)
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self._do_chat(messages, **kwargs)

    def health_check(self) -> bool:
        """健康检查"""
        try:
            url = f"{self.host}/api/tags"
            response = self._session.get(url, timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
