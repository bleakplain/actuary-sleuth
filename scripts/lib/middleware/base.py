"""中间件基类"""

from abc import ABC, abstractmethod
from typing import Callable, Any, List, Dict, Optional
import logging
import time


class Middleware(ABC):
    """中间件基类"""

    @abstractmethod
    def process(self, call: Callable, *args, **kwargs) -> Any:
        """处理调用"""
        pass


class LoggingMiddleware(Middleware):
    """日志记录中间件"""

    def __init__(self, logger_instance: logging.Logger):
        self.logger = logger_instance

    def process(self, call: Callable, *args, **kwargs) -> Any:
        self.logger.info(f"调用 {call.__name__}")
        try:
            result = call(*args, **kwargs)
            self.logger.info(f"{call.__name__} 成功")
            return result
        except Exception as e:
            self.logger.error(f"{call.__name__} 失败: {e}")
            raise


class PerformanceMiddleware(Middleware):
    """性能监控中间件"""

    def __init__(self):
        self.metrics: Dict[str, float] = {}

    def process(self, call: Callable, *args, **kwargs) -> Any:
        start = time.time()
        try:
            return call(*args, **kwargs)
        finally:
            elapsed = time.time() - start
            self.metrics[call.__name__] = elapsed


class MiddlewareChain:
    """中间件链"""

    def __init__(self, middlewares: Optional[List[Middleware]] = None):
        self.middlewares = middlewares or []

    def add(self, middleware: Middleware) -> 'MiddlewareChain':
        """添加中间件"""
        self.middlewares.append(middleware)
        return self

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """执行中间件链"""
        wrapped = func
        for middleware in reversed(self.middlewares):
            def make_wrapper(f: Callable, m: Middleware) -> Callable:
                return lambda *a, **kw: m.process(lambda: f(*a, **kw))
            wrapped = make_wrapper(wrapped, middleware)

        return wrapped(*args, **kwargs)
