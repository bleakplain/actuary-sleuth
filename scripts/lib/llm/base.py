#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端抽象基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Iterator, List

from lib.llm.trace import incr_llm_call_count


class BaseLLMClient(ABC):
    """LLM客户端基类"""

    MAX_PROMPT_LENGTH = 100000

    def __init__(self, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self._session = None

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

    def generate(self, prompt: str, **kwargs) -> str:
        self._validate_prompt(prompt)
        incr_llm_call_count()
        return self._do_generate(prompt, **kwargs)

    @abstractmethod
    def _do_generate(self, prompt: str, **kwargs) -> str:
        pass

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self._validate_messages(messages)
        incr_llm_call_count()
        return self._do_chat(messages, **kwargs)

    @abstractmethod
    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

    def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        self._validate_messages(messages)
        incr_llm_call_count()
        return self._do_chat_stream(messages, **kwargs)

    def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        response = self._do_chat(messages, **kwargs)
        for char in response:
            yield char

    def ocr_table(self, image_base64: str) -> str:
        """OCR 识别表格为 Markdown（默认不支持，子类按需实现）。"""
        raise NotImplementedError(f"{self.__class__.__name__} does not support OCR")

    @abstractmethod
    def health_check(self) -> bool:
        pass
