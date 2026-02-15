#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama LLM 接口模块
提供文本嵌入和生成功能
"""
import requests
import json
from typing import List, Dict, Optional, Any
from pathlib import Path


class OllamaClient:
    """Ollama 客户端类"""

    def __init__(
        self,
        host: str = 'http://localhost:11434',
        model: str = 'qwen2:7b',
        embed_model: str = 'nomic-embed-text'
    ):
        """
        初始化 Ollama 客户端

        Args:
            host: Ollama 服务地址
            model: 文本生成模型
            embed_model: 嵌入模型
        """
        self.host = host.rstrip('/')
        self.model = model
        self.embed_model = embed_model
        self.timeout = 30

    def generate(self, prompt: str, **kwargs) -> str:
        """
        生成文本

        Args:
            prompt: 提示词
            **kwargs: 其他参数（temperature, max_tokens等）

        Returns:
            str: 生成的文本
        """
        try:
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

            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            return result.get('response', '')

        except requests.exceptions.RequestException as e:
            print(f"Error calling Ollama generate API: {e}")
            return ""

    def embed(self, text: str) -> Optional[List[float]]:
        """
        生成文本嵌入向量

        Args:
            text: 输入文本

        Returns:
            List[float]: 嵌入向量，失败返回 None
        """
        try:
            url = f"{self.host}/api/embed"
            data = {
                "model": self.embed_model,
                "prompt": text
            }

            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            return result.get('embedding')

        except requests.exceptions.RequestException as e:
            print(f"Error calling Ollama embed API: {e}")
            return None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        对话生成

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            **kwargs: 其他参数

        Returns:
            str: 生成的回复
        """
        try:
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

            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            return result.get('message', {}).get('content', '')

        except requests.exceptions.RequestException as e:
            print(f"Error calling Ollama chat API: {e}")
            return ""

    def health_check(self) -> bool:
        """
        检查 Ollama 服务是否可用

        Returns:
            bool: 服务可用返回 True
        """
        try:
            url = f"{self.host}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False


# 全局客户端实例
_client = None


def get_client(
    host: str = 'http://localhost:11434',
    model: str = 'qwen2:7b',
    embed_model: str = 'nomic-embed-text'
) -> OllamaClient:
    """
    获取 Ollama 客户端实例（单例模式）

    Args:
        host: Ollama 服务地址
        model: 文本生成模型
        embed_model: 嵌入模型

    Returns:
        OllamaClient: 客户端实例
    """
    global _client
    if _client is None:
        _client = OllamaClient(host=host, model=model, embed_model=embed_model)
    return _client


if __name__ == '__main__':
    # 测试代码
    print("Testing Ollama module...")

    try:
        client = get_client()

        # 健康检查
        is_healthy = client.health_check()
        print(f"Ollama service healthy: {is_healthy}")

        if is_healthy:
            # 测试嵌入
            test_text = "保险法第十六条"
            embedding = client.embed(test_text)
            print(f"Embedding dimension: {len(embedding) if embedding else 0}")

            # 测试生成
            prompt = "什么是保险法的如实告知义务？"
            response = client.generate(prompt, max_tokens=100)
            print(f"Generated response: {response[:100]}...")

        print("Ollama module test completed!")

    except Exception as e:
        print(f"Test failed: {str(e)}")
