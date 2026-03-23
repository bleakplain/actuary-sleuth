#!/usr/bin/env python3
"""数据库连接池模块

提供线程安全的 SQLite 连接池管理。
"""
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from queue import Queue, Empty, Full


logger = logging.getLogger(__name__)


class SQLiteConnectionPool:
    """SQLite 连接池

    提供:
    - 连接复用，减少创建开销
    - 线程安全的连接获取
    - 自动连接健康检查
    - 连接超时管理
    """

    def __init__(
        self,
        db_path: Path,
        pool_size: int = 5,
        max_overflow: int = 10,
        timeout: float = 30.0,
        check_same_thread: bool = False
    ):
        """
        初始化连接池

        Args:
            db_path: 数据库文件路径
            pool_size: 基础连接池大小
            max_overflow: 最大额外连接数
            timeout: 获取连接超时时间（秒）
            check_same_thread: 是否检查同线程
        """
        self._db_path = db_path
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._timeout = timeout
        self._check_same_thread = check_same_thread

        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=pool_size + max_overflow)
        self._created_connections = 0
        self._lock = threading.Lock()

        self._initialize_pool()

    def _initialize_pool(self):
        """初始化连接池"""
        for _ in range(self._pool_size):
            conn = self._create_connection()
            self._pool.put(conn)

    def _create_connection(self) -> sqlite3.Connection:
        """创建新连接"""
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=self._timeout,
            check_same_thread=self._check_same_thread
        )
        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.Error as e:
            logger.warning(f"无法设置 WAL 模式: {e}")

        return conn

    @contextmanager
    def get_connection(self):
        """
        获取数据库连接（上下文管理器）

        Yields:
            sqlite3.Connection: 数据库连接

        Raises:
            TimeoutError: 获取连接超时
        """
        conn = None
        try:
            conn = self._pool.get(timeout=self._timeout)
            yield conn
            conn.commit()
        except Empty:
            with self._lock:
                if self._created_connections < self._pool_size + self._max_overflow:
                    conn = self._create_connection()
                    self._created_connections += 1
                    yield conn
                    conn.commit()
                else:
                    raise TimeoutError("获取数据库连接超时")
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                try:
                    self._validate_connection(conn)
                    self._pool.put(conn, block=False)
                except Full:
                    conn.close()

    def _validate_connection(self, conn: sqlite3.Connection) -> bool:
        """验证连接是否有效"""
        try:
            conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close_all(self):
        """关闭所有连接"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break

        with self._lock:
            self._created_connections = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


_global_pool: Optional[SQLiteConnectionPool] = None
_pool_lock = threading.Lock()


def get_connection_pool(
    db_path: Optional[Path] = None,
    pool_size: int = 5,
    max_overflow: int = 10
) -> SQLiteConnectionPool:
    """
    获取全局连接池实例（单例模式）

    Args:
        db_path: 数据库路径，如果为 None 则使用默认路径
        pool_size: 连接池大小
        max_overflow: 最大额外连接数

    Returns:
        SQLiteConnectionPool: 连接池实例
    """
    global _global_pool

    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                if db_path is None:
                    from lib.common.database import get_db_path
                    db_path = get_db_path()

                _global_pool = SQLiteConnectionPool(
                    db_path=db_path,
                    pool_size=pool_size,
                    max_overflow=max_overflow
                )

    return _global_pool


def reset_connection_pool():
    """重置全局连接池（主要用于测试）"""
    global _global_pool

    with _pool_lock:
        if _global_pool is not None:
            _global_pool.close_all()
        _global_pool = None
