#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 指标收集和熔断器

提供 API 调用指标收集、熔断器、重试机制等功能。
"""
import functools
import logging
import requests  # type: ignore[import-untyped]
import threading
import time
import uuid
from collections import deque
from typing import Callable, Dict, Any, Optional
from enum import Enum


logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 熔断状态
    HALF_OPEN = "half_open"  # 半开状态


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


# 全局指标收集器
_metrics = APIMetrics()


def get_metrics() -> APIMetrics:
    return _metrics


# 全局熔断器实例
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_circuit_lock = threading.Lock()


def _get_circuit_breaker(key: str) -> CircuitBreaker:
    with _circuit_lock:
        if key not in _circuit_breakers:
            _circuit_breakers[key] = CircuitBreaker()
        return _circuit_breakers[key]


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
                        delay = base_delay * (rate_limit_delay_mult ** attempt)
                        logger.warning(f"Rate limited, retrying in {delay:.1f}s...")
                        time.sleep(delay)
                    elif is_server_error:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Server error ({e.response.status_code if hasattr(e, 'response') and e.response else '?'}), retrying in {delay:.1f}s...")
                        time.sleep(delay)
                    elif is_timeout:
                        delay = base_delay * (1.5 ** attempt)
                        logger.warning(f"Timeout, retrying in {delay:.1f}s...")
                        time.sleep(delay)
                    else:
                        logger.error(f"Request failed: {e}, retrying in {base_delay}s...")
                        time.sleep(base_delay)

            raise last_exception

        return wrapper
    return decorator


def _with_circuit_breaker(circuit_key: str) -> Callable[[Callable], Callable]:
    """熔断器装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            breaker = _get_circuit_breaker(circuit_key)

            if not breaker.can_attempt():
                raise Exception(f"Circuit breaker is OPEN for {circuit_key}")

            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise

        return wrapper
    return decorator
