#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import atexit
import json
import re
import logging
import requests  # type: ignore[import-untyped]
import threading
import weakref
from dataclasses import dataclass
from typing import Dict, Iterator, List, Mapping, Optional, Tuple

from .base import BaseLLMClient
from .metrics import (
    LLMRateLimitError,
    _track_timing,
    _with_circuit_breaker,
    _retry_with_backoff,
)
from lib.common.constants import LLMConstants


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZhipuUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def _usage_value(usage: Mapping[str, object], name: str) -> int:
    value = usage.get(name, 0)
    return value if isinstance(value, int) else 0


class ZhipuClient(BaseLLMClient):
    """智谱AI客户端"""

    _instances: weakref.WeakSet["ZhipuClient"] = weakref.WeakSet()
    _cleanup_registered = False
    _cleanup_lock = threading.Lock()

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
        self._usage_lock = threading.Lock()
        self._usage_records: List[ZhipuUsage] = []
        self._register_cleanup()

    @property
    def usage_records(self) -> Tuple[ZhipuUsage, ...]:
        with self._usage_lock:
            return tuple(self._usage_records)

    def _record_usage(self, result: object) -> None:
        if not isinstance(result, Mapping):
            return
        usage = result.get("usage")
        if not isinstance(usage, Mapping):
            return
        record = ZhipuUsage(
            prompt_tokens=_usage_value(usage, "prompt_tokens"),
            completion_tokens=_usage_value(usage, "completion_tokens"),
            total_tokens=_usage_value(usage, "total_tokens"),
        )
        with self._usage_lock:
            self._usage_records.append(record)

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
                        # 重试统一由带审核 deadline 的外层策略负责，避免两层重试
                        # 将一次法规单元调用拖过整份审核预算。
                        max_retries=0,
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
        with ZhipuClient._cleanup_lock:
            ZhipuClient._instances.add(self)
            if not ZhipuClient._cleanup_registered:
                atexit.register(ZhipuClient._close_all_instances)
                ZhipuClient._cleanup_registered = True

    @classmethod
    def _close_all_instances(cls) -> None:
        for client in tuple(cls._instances):
            client.close()

    def _do_generate(self, prompt: str, **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        model = str(kwargs.get("model") or self.model)
        data: Dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }
        if "response_format" in kwargs:
            data["response_format"] = kwargs["response_format"]
        if "4.5" in model or "4.6" in model or "4.7" in model:
            data["thinking"] = {"type": "disabled"}

        session = self._get_session()
        response = session.post(url, json=data, timeout=kwargs.get("timeout", self.timeout))

        if response.status_code == 429:
            raise LLMRateLimitError(f"429 Rate limit exceeded: {response.text[:200]}")
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(f"{response.status_code} Server error: {response.text[:200]}")

        response.raise_for_status()
        result = response.json()
        self._record_usage(result)

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
        return super().generate(prompt, **kwargs)

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        url = f"{self.base_url}/chat/completions"
        model = str(kwargs.get("model") or self.model)
        data: Dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }
        if "response_format" in kwargs:
            data["response_format"] = kwargs["response_format"]
        if "4.5" in model or "4.6" in model or "4.7" in model:
            data["thinking"] = {"type": "disabled"}

        session = self._get_session()
        response = session.post(url, json=data, timeout=kwargs.get("timeout", self.timeout))

        if response.status_code == 429:
            raise LLMRateLimitError(f"429 Rate limit exceeded: {response.text[:200]}")
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(f"{response.status_code} Server error: {response.text[:200]}")

        response.raise_for_status()
        result = response.json()
        self._record_usage(result)

        if 'choices' not in result or len(result['choices']) == 0:
            raise ValueError(f"Unexpected response format: 'choices' field missing or empty. Response keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")

        message = result['choices'][0]['message']
        if message.get('content'):
            return message['content']
        if message.get('reasoning_content'):
            return message['reasoning_content']
        raise ValueError(f"Message missing both 'content' and 'reasoning_content' fields. Available keys: {list(message.keys())}")

    @_track_timing("zhipu")
    @_with_circuit_breaker("zhipu")
    @_retry_with_backoff(
        max_retries=LLMConstants.MAX_RETRIES,
        base_delay=LLMConstants.RETRY_BASE_DELAY,
        rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT
    )
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return super().chat(messages, **kwargs)

    def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        url = f"{self.base_url}/chat/completions"
        model = str(kwargs.get("model") or self.model)
        data: Dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7),
            "stream": True,
        }
        if "4.5" in model or "4.6" in model or "4.7" in model:
            data["thinking"] = {"type": "disabled"}

        session = self._get_session()
        response = session.post(url, json=data, stream=True, timeout=self.timeout)

        if response.status_code == 429:
            raise LLMRateLimitError(
                f"429 Rate limit exceeded: {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(
                f"{response.status_code} Server error: {response.text[:200]}"
            )
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
            except json.JSONDecodeError:
                continue

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

    def _do_ocr_table(self, image_base64: str) -> str:
        """调用 GLM-OCR 识别表格为 Markdown。"""
        url = f"{self.base_url}/layout_parsing"
        data = {
            "model": "glm-ocr",
            "file": image_base64,
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
        return result.get("md_results", result.get("content", ""))

    @_track_timing("zhipu")
    @_with_circuit_breaker("zhipu")
    @_retry_with_backoff(
        max_retries=LLMConstants.MAX_RETRIES,
        base_delay=LLMConstants.RETRY_BASE_DELAY,
        rate_limit_delay_mult=LLMConstants.RATE_LIMIT_DELAY_MULT
    )
    def ocr_table(self, image_base64: str) -> str:
        return self._do_ocr_table(image_base64)
