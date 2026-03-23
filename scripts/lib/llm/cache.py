#!/usr/bin/env python3
"""LLM 响应缓存模块

提供基于 TTL 的 LLM 响应缓存功能。
"""
import hashlib
import json
import logging
import threading
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class LLMResponseCache:
    """LLM 响应缓存

    提供:
    - 基于 prompt hash 的缓存键
    - TTL 过期机制
    - 线程安全操作
    - 缓存统计
    """

    def __init__(self, ttl: int = 3600, max_size: int = 1000):
        """
        初始化缓存

        Args:
            ttl: 缓存生存时间（秒），默认 1 小时
            max_size: 最大缓存条目数
        """
        self._ttl = ttl
        self._max_size = max_size
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.RLock()

        self._hits = 0
        self._misses = 0

    def _generate_key(self, messages: list, model: str = "") -> str:
        """
        生成缓存键

        Args:
            messages: 消息列表
            model: 模型名称

        Returns:
            str: 缓存键
        """
        content = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        if model:
            content = f"{model}:{content}"

        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, messages: list, model: str = "") -> Optional[str]:
        """
        获取缓存的响应

        Args:
            messages: 消息列表
            model: 模型名称

        Returns:
            Optional[str]: 缓存的响应，如果不存在或已过期则返回 None
        """
        key = self._generate_key(messages, model)

        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            response, timestamp = self._cache[key]

            if time.time() - timestamp > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            return response

    def set(self, messages: list, response: str, model: str = "") -> None:
        """
        设置缓存

        Args:
            messages: 消息列表
            response: LLM 响应
            model: 模型名称
        """
        key = self._generate_key(messages, model)

        with self._lock:
            if len(self._cache) >= self._max_size:
                self._evict_oldest()

            self._cache[key] = (response, time.time())

    def _evict_oldest(self) -> None:
        """淘汰最旧的缓存条目"""
        if not self._cache:
            return

        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
        del self._cache[oldest_key]

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            Dict[str, Any]: 统计信息
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0

            return {
                'size': len(self._cache),
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': hit_rate,
                'ttl': self._ttl,
                'max_size': self._max_size
            }

    def remove(self, messages: list, model: str = "") -> bool:
        """
        移除特定缓存

        Args:
            messages: 消息列表
            model: 模型名称

        Returns:
            bool: 是否成功移除
        """
        key = self._generate_key(messages, model)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False


_global_cache: Optional[LLMResponseCache] = None
_cache_lock = threading.Lock()


def get_cache(ttl: int = 3600, max_size: int = 1000) -> LLMResponseCache:
    """
    获取全局缓存实例（单例模式）

    Args:
        ttl: 缓存生存时间（秒）
        max_size: 最大缓存条目数

    Returns:
        LLMResponseCache: 缓存实例
    """
    global _global_cache

    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = LLMResponseCache(ttl=ttl, max_size=max_size)

    return _global_cache


def reset_cache():
    """重置全局缓存（主要用于测试）"""
    global _global_cache

    with _cache_lock:
        if _global_cache is not None:
            _global_cache.clear()
        _global_cache = None
