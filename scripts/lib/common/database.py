#!/usr/bin/env python3
import logging
import sqlite3
import json
import inspect
from contextlib import contextmanager
from pathlib import Path
from typing import Callable
from lib.common.exceptions import DatabaseError, RecordNotFoundError

logger = logging.getLogger(__name__)

# 数据库路径 - 从配置读取
def get_db_path() -> Path:
    """获取数据库路径"""
    from lib.config import get_config
    config = get_config()
    rel_path = config.data_paths.sqlite_db  # 从配置读取相对路径

    # 如果是相对路径，相对于脚本目录解析
    if not Path(rel_path).is_absolute():
        script_dir = Path(__file__).parent.parent
        return script_dir / rel_path
    return Path(rel_path)

# 并发优化配置
DB_TIMEOUT = 30  # 30秒超时
DB_WAL_MODE = True  # 启用WAL模式


def _create_connection(db_path: Path = None):
    """创建数据库连接"""
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(
        str(db_path),
        timeout=DB_TIMEOUT,
        check_same_thread=False  # 允许多线程使用
    )
    conn.row_factory = sqlite3.Row

    # 启用 WAL 模式以提升并发性能
    if DB_WAL_MODE:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")  # 30秒忙等待
        except sqlite3.Error:
            # 如果无法设置WAL模式（例如某些网络文件系统），静默失败
            pass

    return conn


@contextmanager
def get_connection():
    """
    获取数据库连接（支持 with 语句，自动关闭连接）
    """
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


def find_regulation(article_number):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT * FROM regulations
                WHERE article_number = ?
            ''', (article_number,))
            row = cur.fetchone()
            if row:
                return dict(row)
            raise RecordNotFoundError(f"Regulation not found: {article_number}")
    except sqlite3.Error as e:
        logger.error(f"查找法规失败: {e}")
        raise DatabaseError(f"Failed to find regulation: {e}")


def search_regulations(keyword):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                SELECT * FROM regulations
                WHERE content LIKE ? OR article_number LIKE ?
                LIMIT 20
            ''', (f'%{keyword}%', f'%{keyword}%'))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"搜索法规失败: {e}")
        raise DatabaseError(f"Failed to search regulations: {e}")


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


def add_regulation(regulation_data):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT OR REPLACE INTO regulations
                (id, law_name, article_number, content, category, tags, effective_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                regulation_data.get('id'),
                regulation_data.get('law_name'),
                regulation_data.get('article_number'),
                regulation_data.get('content'),
                regulation_data.get('category', ''),
                regulation_data.get('tags', ''),
                regulation_data.get('effective_date', '')
            ))
            return True
    except sqlite3.Error as e:
        logger.error(f"添加法规失败: {e}")
        raise DatabaseError(f"Failed to add regulation: {e}")


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
