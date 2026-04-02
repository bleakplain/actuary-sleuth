#!/usr/bin/env python3
import inspect
import logging
import sqlite3
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable
from lib.common.connection_pool import get_connection_pool, SQLiteConnectionPool
from lib.common.exceptions import DatabaseError, RecordNotFoundError
from lib.config import get_sqlite_db_path

logger = logging.getLogger(__name__)

_connection_pool = None
_pool_lock = threading.Lock()

# 数据库路径 - 从配置读取
def get_db_path() -> Path:
    """获取数据库路径"""
    return Path(get_sqlite_db_path())

# 并发优化配置
DB_TIMEOUT = 30
DB_WAL_MODE = True


def _get_pool() -> SQLiteConnectionPool:
    """获取全局连接池实例"""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                db_path = get_db_path()
                _connection_pool = get_connection_pool(
                    db_path=db_path,
                    pool_size=5,
                    max_overflow=10
                )
    return _connection_pool


def _create_connection(db_path: Path = None):
    """创建数据库连接"""
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(
        str(db_path),
        timeout=DB_TIMEOUT,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row

    if DB_WAL_MODE:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.Error:
            pass

    return conn


@contextmanager
def get_connection(use_pool: bool = True):
    """获取数据库连接（使用连接池）"""
    if use_pool:
        pool = _get_pool()
        with pool.get_connection() as conn:
            yield conn
    else:
        db_path = get_db_path()
        conn = _create_connection(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def close_pool():
    """关闭连接池（主要用于测试）"""
    global _connection_pool
    with _pool_lock:
        if _connection_pool is not None:
            _connection_pool.close_all()
        _connection_pool = None


def get_negative_list():
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM negative_list ORDER BY severity DESC')
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"获取负面清单失败: {e}")
        raise DatabaseError(f"Failed to get negative list: {e}")


def save_audit_record(record):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO audit_history (id, user_id, document_url, violations, score)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                record['id'],
                record.get('user_id', ''),
                record.get('document_url', ''),
                json.dumps(record.get('violations', []), ensure_ascii=False),
                record.get('score', 0)
            ))
            return True
    except sqlite3.Error as e:
        logger.error(f"保存审核记录失败: {e}")
        raise DatabaseError(f"Failed to save audit record: {e}")


def add_negative_list_rule(rule_data):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT OR REPLACE INTO negative_list
                (id, rule_number, description, severity, category, remediation, keywords, patterns, version, effective_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                rule_data.get('id'),
                rule_data.get('rule_number'),
                rule_data.get('description'),
                rule_data.get('severity'),
                rule_data.get('category', ''),
                rule_data.get('remediation', ''),
                json.dumps(rule_data.get('keywords', []), ensure_ascii=False),
                json.dumps(rule_data.get('patterns', []), ensure_ascii=False),
                rule_data.get('version', 'v1.0'),
                rule_data.get('effective_date', '')
            ))
            return True
    except sqlite3.Error as e:
        logger.error(f"添加负面清单规则失败: {e}")
        raise DatabaseError(f"Failed to add negative list rule: {e}")


# ========== 数据库连接管理辅助工具（内部使用）==========

@contextmanager
def _managed_query(query_func: Callable, *args, **kwargs):
    """
    确保查询函数在 context manager 中执行（内部函数）

    Args:
        query_func: 查询函数
        *args: 位置参数
        **kwargs: 关键字参数

    Yields:
        查询结果

    Note:
        内部使用，不作为公开 API
    """
    with get_connection() as conn:
        # 检查函数是否接受 conn 参数
        sig = inspect.signature(query_func)
        if 'conn' in sig.parameters:
            result = query_func(*args, conn=conn, **kwargs)
        else:
            # 对于不需要 conn 的函数，直接调用
            # (函数内部应该使用 get_connection())
            result = query_func(*args, **kwargs)
        yield result
