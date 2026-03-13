#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 客户端模块
支持多种LLM提供商：智谱AI、Ollama等
"""
import requests
import json
import threading
import time
import logging
import functools
import uuid
from collections import deque
from typing import List, Dict, Optional, Any, Callable
from abc import ABC, abstractmethod
from enum import Enum

logger = logging.getLogger(__name__)


class ModelName(str, Enum):
    """模型名称常量"""
    GLM_4_FLASH = "glm-4-flash"
    GLM_4_PLUS = "glm-4-plus"
    GLM_Z1_AIR = "glm-z1-air"
    GLM_4_AIR = "glm-4-air"
    EMBEDDING_3 = "embedding-3"
    NOMIC_EMBED_TEXT = "nomic-embed-text"


class APIMetrics:
    """API 调用指标收集"""

    MAX_LATENCY_RECORDS = 100

    def __init__(self):
        self._calls: Dict[str, int] = {}
        self._failures: Dict[str, int] = {}
        self._latencies: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def record_call(self, api: str, latency: float, success: bool):
        with self._lock:
            self._calls[api] = self._calls.get(api, 0) + 1
            if not success:
                self._failures[api] = self._failures.get(api, 0) + 1

            if api not in self._latencies:
                self._latencies[api] = deque(maxlen=self.MAX_LATENCY_RECORDS)
            self._latencies[api].append(latency)

    def get_stats(self, api: str) -> Dict[str, Any]:
        with self._lock:
            latencies = list(self._latencies.get(api, []))
            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            return {
                "calls": self._calls.get(api, 0),
                "failures": self._failures.get(api, 0),
                "success_rate": (
                    (self._calls.get(api, 0) - self._failures.get(api, 0)) / self._calls.get(api, 1)
                ),
                "avg_latency_ms": avg_latency * 1000,
            }

    def reset(self, api: Optional[str] = None):
        with self._lock:
            if api:
                self._calls.pop(api, None)
                self._failures.pop(api, None)
                self._latencies.pop(api, None)
            else:
                self._calls.clear()
                self._failures.clear()
                self._latencies.clear()


# 全局指标收集器
_metrics = APIMetrics()


def get_metrics() -> APIMetrics:
    return _metrics


def _track_timing(api_name: str) -> Callable[[Callable], Callable]:
    """计时装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            request_id = str(uuid.uuid4())[:8]
            start_time = time.time()
            success = False

            logger.debug(f"[{request_id}] Calling {api_name}.{func.__name__}")

            try:
                result = func(*args, **kwargs)
                success = True
                return result
            finally:
                latency = time.time() - start_time
                _metrics.record_call(f"{api_name}.{func.__name__}", latency, success)

                if success:
                    logger.debug(
                        f"[{request_id}] {api_name}.{func.__name__} completed in {latency*1000:.1f}ms"
                    )
                else:
                    logger.warning(
                        f"[{request_id}] {api_name}.{func.__name__} failed after {latency*1000:.1f}ms"
                    )

        return wrapper
    return decorator


class CircuitState(Enum):
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 熔断状态
    HALF_OPEN = "half_open"  # 半开状态


class CircuitBreaker:
    """熔断器：防止连续失败时继续调用 API"""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60,
        half_open_attempts: int = 1
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_attempts = half_open_attempts
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._half_open_success_count = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self.half_open_attempts:
                    self._state = CircuitState.CLOSED
                    self._half_open_success_count = 0
                    logger.info("Circuit breaker recovered to CLOSED state")

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    self._state = CircuitState.OPEN
                    logger.error(
                        f"Circuit breaker opened after {self._failure_count} failures"
                    )

    def can_attempt(self) -> bool:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_success_count = 0
                    logger.info("Circuit breaker entering HALF_OPEN state")
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                return True

            return False


# 全局熔断器实例
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_circuit_lock = threading.Lock()


def _get_circuit_breaker(key: str) -> CircuitBreaker:
    with _circuit_lock:
        if key not in _circuit_breakers:
            _circuit_breakers[key] = CircuitBreaker()
        return _circuit_breakers[key]


def _retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 2,
    rate_limit_delay_mult: float = 3
) -> Callable[[Callable], Callable]:
    """重试装饰器，支持指数退避和速率限制处理"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.RequestException as e:
                    last_exception = e

                    is_rate_limit = False
                    is_server_error = False
                    is_timeout = False

                    if hasattr(e, 'response') and e.response is not None:
                        status_code = e.response.status_code
                        if status_code == 429:
                            is_rate_limit = True
                        elif status_code >= 500:
                            is_server_error = True
                    elif isinstance(e, requests.exceptions.Timeout):
                        is_timeout = True
                    elif 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                        is_timeout = True

                    if is_rate_limit:
                        wait_time = base_delay * (rate_limit_delay_mult ** attempt)
                        if attempt < max_retries - 1:
                            logger.warning(f"Rate limit hit, waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}")
                            time.sleep(wait_time)
                            continue

                    if is_server_error:
                        wait_time = base_delay * (2 ** attempt)
                        if attempt < max_retries - 1:
                            logger.warning(f"Server error, retrying {attempt + 1}/{max_retries} after {wait_time:.1f}s")
                            time.sleep(wait_time)
                            continue

                    if is_timeout:
                        wait_time = base_delay * (2 ** attempt)
                        if attempt < max_retries - 1:
                            logger.warning(f"Timeout, retrying {attempt + 1}/{max_retries} after {wait_time:.1f}s")
                            time.sleep(wait_time)
                            continue

                    if attempt == max_retries - 1:
                        logger.error(f"All retries failed. Last error: {e}")
                    raise

            if last_exception:
                raise last_exception
            return None

        return wrapper
    return decorator


def _with_circuit_breaker(circuit_key: str) -> Callable[[Callable], Callable]:
    """熔断器装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cb = _get_circuit_breaker(circuit_key)

            if not cb.can_attempt():
                raise Exception(
                    f"Circuit breaker is {cb.state.value}. API calls are temporarily blocked."
                )

            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except (requests.exceptions.RequestException, ValueError, TimeoutError, ConnectionError) as e:
                cb.record_failure()
                raise

        return wrapper
    return decorator


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
        """显式关闭会话"""
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

    @abstractmethod
    def health_check(self) -> bool:
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


class LLMClientFactory:
    """LLM客户端工厂类（面向场景）"""

    _SCENARIOS = {
        'reg_import': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
        'doc_preprocess': {'model': None, 'timeout': None},  # 使用配置文件的值
        'audit': {'model': ModelName.GLM_4_PLUS, 'timeout': 120},
        'qa': {'model': ModelName.GLM_4_FLASH, 'timeout': 60},
    }

    @staticmethod
    def _get_base_config() -> tuple:
        """获取基础配置"""
        from lib.config import get_config
        app_config = get_config()
        return app_config.llm.api_key, app_config.llm.base_url

    @staticmethod
    def _create_zhipu_client(model: str, timeout: int) -> BaseLLMClient:
        """创建智谱客户端"""
        api_key, base_url = LLMClientFactory._get_base_config()
        return LLMClientFactory.create_client({
            'provider': 'zhipu',
            'model': model,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': timeout
        })

    @staticmethod
    def get_reg_import_llm() -> BaseLLMClient:
        return LLMClientFactory._create_zhipu_client(
            ModelName.GLM_4_FLASH, 60
        )

    @staticmethod
    def get_doc_preprocess_llm() -> BaseLLMClient:
        from lib.config import get_config
        app_config = get_config()
        return LLMClientFactory._create_zhipu_client(
            app_config.llm.model, app_config.llm.timeout
        )

    @staticmethod
    def get_audit_llm() -> BaseLLMClient:
        return LLMClientFactory._create_zhipu_client(
            ModelName.GLM_4_PLUS, 120
        )

    @staticmethod
    def get_qa_llm() -> BaseLLMClient:
        return LLMClientFactory._create_zhipu_client(
            ModelName.GLM_4_FLASH, 60
        )

    @staticmethod
    def get_embedding_config() -> dict:
        """获取嵌入模型配置"""
        api_key, base_url = LLMClientFactory._get_base_config()
        return {
            'provider': 'zhipu',
            'model': ModelName.EMBEDDING_3,
            'api_key': api_key,
            'base_url': base_url,
            'timeout': 120,
        }

    @staticmethod
    def get_embedding_llm() -> OllamaClient:
        from lib.config import get_config
        app_config = get_config()
        return OllamaClient(
            host=app_config.ollama.host,
            model=app_config.ollama.embed_model,
            timeout=30
        )

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


# 全局客户端实例（线程安全单例）
_client = None
_client_lock = threading.Lock()


def get_client(config: Optional[Dict[str, Any]] = None) -> BaseLLMClient:
    """
    获取LLM客户端实例

    Args:
        config: 配置字典，如果为None则使用默认配置

    Returns:
        BaseLLMClient: 客户端实例
    """
    global _client

    if _client is None:
        with _client_lock:
            if _client is None:
                if config is None:
                    api_key, base_url = LLMClientFactory._get_base_config()
                    config = {
                        'provider': 'zhipu',
                        'model': 'glm-z1-air',
                        'api_key': api_key,
                        'base_url': base_url,
                        'timeout': 60
                    }

                _client = LLMClientFactory.create_client(config)

    return _client


def reset_client():
    global _client
    with _client_lock:
        _client = None


def get_zhipu_client():
    return LLMClientFactory.get_qa_llm()


def get_ollama_client():
    return LLMClientFactory.create_client({
        'provider': 'ollama',
        'model': 'qwen2:7b',
        'host': 'http://localhost:11434',
        'timeout': 30
    })


def get_embedding_client():
    return LLMClientFactory.get_embedding_llm()


# 导出指标收集函数
__all__ = [
    'BaseLLMClient',
    'ZhipuClient',
    'OllamaClient',
    'LLMClientFactory',
    'get_client',
    'reset_client',
    'get_zhipu_client',
    'get_ollama_client',
    'get_embedding_client',
    'get_metrics',
]
