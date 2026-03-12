#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块
支持多种LLM提供商：智谱AI、Ollama等
"""
import requests
import json
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    """LLM客户端基类"""

    def __init__(self, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """对话生成"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass


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
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def _do_generate(self, prompt: str, **kwargs) -> str:
        """
        实际执行单次 API 调用

        Args:
            prompt: 提示词
            **kwargs: 其他参数

        Returns:
            str: 生成的文本
        """
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }

        response = requests.post(
            url,
            headers=self.headers,
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

        # 提取生成内容
        if 'choices' in result and len(result['choices']) > 0:
            message = result['choices'][0]['message']

            if message.get('content'):
                return message['content']

            # GLM-4.7 reasoning mode 处理
            if message.get('reasoning_content'):
                reasoning = message['reasoning_content']
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', reasoning, re.DOTALL)
                if json_match:
                    try:
                        import json
                        parsed = json.loads(json_match.group(0))
                        return json.dumps(parsed, ensure_ascii=False)
                    except json.JSONDecodeError:
                        pass
                return reasoning

        import logging
        logging.warning(f"LLM response missing 'content' field. Response keys: {result.keys() if isinstance(result, dict) else type(result)}")
        return ""

    def generate(self, prompt: str, **kwargs) -> str:
        """
        生成文本（自动重试）

        Args:
            prompt: 提示词
            **kwargs: 其他参数（temperature, max_tokens等）

        Returns:
            str: 生成的文本
        """
        import time
        import logging

        max_retries = 3
        base_delay = 2
        last_exception = None

        for attempt in range(max_retries):
            try:
                return self._do_generate(prompt, **kwargs)
            except requests.exceptions.RequestException as e:
                last_exception = e
                error_msg = str(e)

                # 429 速率限制 - 等待更长时间
                if '429' in error_msg:
                    wait_time = base_delay * (3 ** attempt)
                    if attempt < max_retries - 1:
                        logging.warning(f"Rate limit hit, waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue

                # 5xx 服务器错误 - 指数退避
                if any(code in error_msg for code in ['500', '502', '503', '504']):
                    wait_time = base_delay * (2 ** attempt)
                    if attempt < max_retries - 1:
                        logging.warning(f"Server error, retrying {attempt + 1}/{max_retries} after {wait_time:.1f}s")
                        time.sleep(wait_time)
                        continue

                # 超时错误 - 指数退避
                if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                    wait_time = base_delay * (2 ** attempt)
                    if attempt < max_retries - 1:
                        logging.warning(f"Timeout, retrying {attempt + 1}/{max_retries} after {wait_time:.1f}s")
                        time.sleep(wait_time)
                        continue

                # 其他错误直接抛出
                if attempt == max_retries - 1:
                    logging.error(f"All retries failed. Last error: {e}")
                raise

        if last_exception:
            raise last_exception
        return ""  # 向上抛出，让调用方的重试逻辑处理

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
            url = f"{self.base_url}/chat/completions"
            data = {
                "model": kwargs.get('model', self.model),
                "messages": messages,
                "temperature": kwargs.get('temperature', 0.1),
                "max_tokens": kwargs.get('max_tokens', 8192),
                "top_p": kwargs.get('top_p', 0.7)
            }

            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                timeout=self.timeout
            )

            # 对 429 和 5xx 错误抛出包含状态码的异常，让上层重试机制能正确感知
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

            if 'choices' in result and len(result['choices']) > 0:
                message = result['choices'][0]['message']

                # 优先使用 content（包含实际答案）
                if message.get('content'):
                    return message['content']

            return ""

        except requests.exceptions.RequestException as e:
            import logging
            logging.warning(f"Error calling ZhipuAI Chat API: {e}")
            raise

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

            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                timeout=5
            )
            return response.status_code == 200

        except requests.exceptions.RequestException:
            return False


class OllamaClient(BaseLLMClient):
    """Ollama客户端（向后兼容）"""

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

    def _do_generate(self, prompt: str, **kwargs) -> str:
        """实际执行单次 API 调用"""
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

    def generate(self, prompt: str, **kwargs) -> str:
        """生成文本（自动重试）"""
        import time
        import logging

        max_retries = 3
        base_delay = 2
        last_exception = None

        for attempt in range(max_retries):
            try:
                return self._do_generate(prompt, **kwargs)
            except requests.exceptions.RequestException as e:
                last_exception = e
                error_msg = str(e)

                # 只对超时和 5xx 错误重试
                if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower() or any(code in error_msg for code in ['500', '502', '503', '504']):
                    wait_time = base_delay * (2 ** attempt)
                    if attempt < max_retries - 1:
                        logging.warning(f"Ollama error, retrying {attempt + 1}/{max_retries} after {wait_time:.1f}s")
                        time.sleep(wait_time)
                        continue

                raise

        if last_exception:
            raise last_exception
        return ""

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """对话生成"""
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
            print(f"Error calling Ollama Chat API: {e}")
            return ""

    def health_check(self) -> bool:
        """健康检查"""
        try:
            url = f"{self.host}/api/tags"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


class LLMClientFactory:
    """LLM客户端工厂类"""

    @staticmethod
    def create_client(config: Dict[str, Any]) -> BaseLLMClient:
        """
        根据配置创建LLM客户端

        Args:
            config: 配置字典，包含：
                - provider: 提供商类型 ("zhipu" 或 "ollama")
                - model: 模型名称
                - api_key: API密钥（智谱需要）
                - host: 服务地址（Ollama需要）
                - timeout: 超时时间

        Returns:
            BaseLLMClient: LLM客户端实例

        Raises:
            ValueError: 不支持的提供商类型
        """
        provider = config.get('provider', 'zhipu').lower()

        if provider == 'zhipu':
            api_key = config.get('api_key')
            if not api_key:
                raise ValueError("ZhipuAI requires 'api_key' in config")
            return ZhipuClient(
                api_key=api_key,
                model=config.get('model', 'glm-z1-air'),
                base_url=config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4/'),
                timeout=config.get('timeout', 60)
            )

        elif provider == 'ollama':
            return OllamaClient(
                host=config.get('host', 'http://localhost:11434'),
                model=config.get('model', 'qwen2:7b'),
                timeout=config.get('timeout', 30)
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")


# 全局客户端实例
_client = None


def get_client(config: Optional[Dict[str, Any]] = None) -> BaseLLMClient:
    """
    获取LLM客户端实例（单例模式）

    Args:
        config: 配置字典，如果为None则使用默认配置

    Returns:
        BaseLLMClient: 客户端实例
    """
    global _client

    if _client is None:
        if config is None:
            # 默认使用智谱AI 轻量模型（高并发）
            config = {
                'provider': 'zhipu',
                'model': 'glm-z1-air',  # 轻量模型，并发数30
                'api_key': '',  # 需要从环境变量或配置文件获取
                'timeout': 60
            }

        _client = LLMClientFactory.create_client(config)

    return _client


def reset_client():
    """重置全局客户端实例"""
    global _client
    _client = None


if __name__ == '__main__':
    # 测试代码
    print("Testing LLM Client module...")

    try:
        # 测试智谱AI
        print("\n1. Testing ZhipuAI client...")
        zhipu_config = {
            'provider': 'zhipu',
            'model': 'glm-z1-air',  # 轻量模型
            'api_key': 'your_api_key_here'  # 替换为实际API密钥
        }

        try:
            zhipu_client = LLMClientFactory.create_client(zhipu_config)
            print(f"ZhipuAI client created: {zhipu_client.model}")
            print(f"Health check: {zhipu_client.health_check()}")
        except Exception as e:
            print(f"ZhipuAI test failed: {e}")

        # 测试Ollama
        print("\n2. Testing Ollama client...")
        ollama_config = {
            'provider': 'ollama',
            'model': 'qwen2:7b',
            'host': 'http://localhost:11434'
        }

        try:
            ollama_client = LLMClientFactory.create_client(ollama_config)
            print(f"Ollama client created: {ollama_client.model}")
            print(f"Health check: {ollama_client.health_check()}")
        except Exception as e:
            print(f"Ollama test failed: {e}")

        print("\nLLM Client module test completed!")

    except Exception as e:
        print(f"Test failed: {str(e)}")
