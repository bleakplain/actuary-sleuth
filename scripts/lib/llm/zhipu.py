#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import atexit
import json
import re
import logging
import requests
import threading
from typing import List, Dict, Optional

from .base import BaseLLMClient
from .metrics import _track_timing, _with_circuit_breaker, _retry_with_backoff
from lib.common.constants import LLMConstants


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
        with self._session_lock:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

    def __del__(self):
        self.close()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _register_cleanup(self):
        def cleanup():
            self.close()

        if cleanup not in ZhipuClient._shutdown_hooks:
            ZhipuClient._shutdown_hooks.append(cleanup)
            atexit.register(cleanup)

    def _do_generate(self, prompt: str, **kwargs) -> str:
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
        response = session.post(url, json=data, timeout=self.timeout)

        if response.status_code == 429:
            raise requests.exceptions.RequestException(f"429 Rate limit exceeded: {response.text[:200]}")
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(f"{response.status_code} Server error: {response.text[:200]}")

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
    @_retry_with_backoff(
        max_retries=LLMConstants.MAX_RETRIES,
        base_delay=LLMConstants.RETRY_BASE_DELAY,
        rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT
    )
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
            raise requests.exceptions.RequestException(f"429 Rate limit exceeded: {response.text[:200]}")
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(f"{response.status_code} Server error: {response.text[:200]}")

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
    @_retry_with_backoff(
        max_retries=LLMConstants.MAX_RETRIES,
        base_delay=LLMConstants.RETRY_BASE_DELAY,
        rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT
    )
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self._do_chat(messages, **kwargs)

    def health_check(self) -> bool:
        try:
            url = f"{self.base_url}/chat/completions"
            data = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 10
            }

            session = self._get_session()
            response = session.post(url, json=data, timeout=5)
            return response.status_code == 200

        except requests.exceptions.RequestException:
            return False

    def embed(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        if not texts:
            return []

        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        embedding_model = model or "embedding-3"

        url = f"{self.base_url}/embeddings"
        data = {
            "model": embedding_model,
            "input": valid_texts
        }

        session = self._get_session()
        try:
            response = session.post(url, json=data, timeout=self.timeout)

            if response.status_code == 429:
                raise requests.exceptions.RequestException(f"429 Rate limit exceeded: {response.text[:200]}")
            if response.status_code >= 500:
                raise requests.exceptions.RequestException(f"{response.status_code} Server error: {response.text[:200]}")

            response.raise_for_status()
            result = response.json()

            if 'data' not in result:
                raise ValueError(f"Unexpected response format: 'data' field missing. Response keys: {list(result.keys())}")

            embeddings = [item['embedding'] for item in result['data']]

            result_embeddings = []
            text_index = 0
            for text in texts:
                if text and text.strip():
                    result_embeddings.append(embeddings[text_index])
                    text_index += 1
                else:
                    result_embeddings.append([0.0] * len(embeddings[0]) if embeddings else [])

            return result_embeddings

        except requests.exceptions.RequestException:
            raise
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(f"Failed to parse embedding response: {e}")
