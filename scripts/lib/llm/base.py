#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端抽象基类
"""
from abc import ABC, abstractmethod
from typing import List, Dict


class BaseLLMClient(ABC):
    """LLM客户端基类"""

    MAX_PROMPT_LENGTH = 100000

    def __init__(self, model: str, timeout: int = 30, use_cache: bool = True):
        self.model = model
        self.timeout = timeout
        self._session = None
        self._use_cache = use_cache

    def _validate_prompt(self, prompt: str) -> None:
        if not prompt or not prompt.strip():
            raise ValueError("提示词不能为空")
        if len(prompt) > self.MAX_PROMPT_LENGTH:
            raise ValueError(f"提示词过长: {len(prompt)} 字符 (最大 {self.MAX_PROMPT_LENGTH})")

    def _validate_messages(self, messages: List[Dict[str, str]]) -> None:
        if not messages:
            raise ValueError("消息列表不能为空")
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f"消息 {i} 必须是字典")
            if 'role' not in msg or 'content' not in msg:
                raise ValueError(f"消息 {i} 必须包含 'role' 和 'content' 字段")
            if not msg['content'] or not msg['content'].strip():
                raise ValueError(f"消息 {i} 的内容不能为空")

    def close(self):
        if hasattr(self, '_session') and self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

    def chat_with_cache(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if not self._use_cache:
            return self.chat(messages, **kwargs)

        from lib.llm.cache import get_cache
        cache = get_cache()

        cached_response = cache.get(messages, self.model)
        if cached_response is not None:
            return cached_response

        response = self.chat(messages, **kwargs)
        cache.set(messages, response, self.model)

        return response

    @abstractmethod
    def health_check(self) -> bool:
        pass
