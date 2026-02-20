#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库操作模块

优化并发支持:
- 启用 WAL 模式 (Write-Ahead Logging) 提升并发性能
- 设置合理的超时时间避免锁等待失败
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'actuary.db'

# 并发优化配置
DB_TIMEOUT = 30  # 30秒超时
DB_WAL_MODE = True  # 启用WAL模式


def get_connection():
    """获取数据库连接（优化并发支持）"""
    conn = sqlite3.connect(
        DB_PATH,
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


def find_regulation(article_number):
    """精确查找法规条款"""
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
            return None
    except sqlite3.Error as e:
        print(f"Error finding regulation: {e}")
        return None


def search_regulations(keyword):
    """关键词搜索法规"""
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
        print(f"Error searching regulations: {e}")
        return []


def get_negative_list():
    """获取负面清单"""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM negative_list ORDER BY severity DESC')
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        print(f"Error getting negative list: {e}")
        return []


def save_audit_record(record):
    """保存审核记录"""
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
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"Error saving audit record: {e}")
        return False


def add_regulation(regulation_data):
    """添加法规记录"""
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
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"Error adding regulation: {e}")
        return False


def add_negative_list_rule(rule_data):
    """添加负面清单规则"""
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
            conn.commit()
            return True
    except sqlite3.Error as e:
        print(f"Error adding negative list rule: {e}")
        return False
