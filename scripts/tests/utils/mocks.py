#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock工具
"""
from typing import Dict, List
from lib.llm.base import BaseLLMClient


class MockLLMClient(BaseLLMClient):
    """模拟LLM客户端"""

    def __init__(self, response: str = "", model: str = "mock-model"):
        super().__init__(model, timeout=30)
        self._response = response
        self.call_count = 0
        self.calls = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "generate", "prompt": prompt})
        return self._response

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "chat", "messages": messages})
        return self._response

    def health_check(self) -> bool:
        return True
