"""缓存管理器"""

from typing import Any, Optional, Callable, Dict, Tuple
from functools import wraps
import hashlib
import time


class CacheManager:
    """缓存管理器"""

    def __init__(self, ttl: int = 3600):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """设置缓存"""
        self._cache[key] = (value, time.time())

    def invalidate(self, key: str) -> None:
        """使缓存失效"""
        if key in self._cache:
            del self._cache[key]


def cached(ttl: int = 3600, key_func: Optional[Callable] = None):
    """缓存装饰器"""
    cache = CacheManager(ttl)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                key_parts = [func.__name__] + [str(a) for a in args]
                cache_key = hashlib.md5("|".join(key_parts).encode()).hexdigest()

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result

        return wrapper
    return decorator
