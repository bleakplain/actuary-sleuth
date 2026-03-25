#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智谱 AI 客户端（资源安全版本）
"""
import atexit
import json
import re
import logging
import requests
import threading
from typing import List, Dict, Optional

from .base import BaseLLMClient
from .metrics import _track_timing, _with_circuit_breaker, _retry_with_backoff


logger = logging.getLogger(__name__)


class ZhipuClient(BaseLLMClient):
    """智谱AI客户端"""

    _shutdown_hooks = []

    def __init__(
        self,
        api_key: str,
        model: str = "glm-z1-air",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/",
        timeout: int = 120
    ):
        super().__init__(model, timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._session = None
        self._session_lock = threading.Lock()

        self._register_cleanup()

    def _get_session(self) -> requests.Session:
        """延迟初始化会话（线程安全）"""
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    session = requests.Session()
                    session.headers.update({
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    })
                    adapter = requests.adapters.HTTPAdapter(
                        pool_connections=10,
                        pool_maxsize=20,
                        max_retries=3
                    )
                    session.mount('http://', adapter)
                    session.mount('https://', adapter)
                    self._session = session
        return self._session

    def close(self):
        """显式关闭会话"""
        with self._session_lock:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

    def __del__(self):
        """析构时确保关闭"""
        self.close()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _register_cleanup(self):
        """注册退出清理"""
        def cleanup():
            self.close()

        if cleanup not in ZhipuClient._shutdown_hooks:
            ZhipuClient._shutdown_hooks.append(cleanup)
            atexit.register(cleanup)

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

        session = self._get_session()
        response = session.post(
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
    @_retry_with_backoff(max_retries=2, base_delay=1, rate_limit_delay_mult=2)
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

        session = self._get_session()
        response = session.post(url, json=data, timeout=self.timeout)

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
    @_retry_with_backoff(max_retries=2, base_delay=1, rate_limit_delay_mult=2)
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
