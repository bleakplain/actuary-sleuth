#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化数据库
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'actuary.db'


def init_database():
    """初始化数据库表"""
    try:
        # 确保 data 目录存在
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(DB_PATH) as conn:
            # 创建法规表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS regulations (
                    id TEXT PRIMARY KEY,
                    law_name TEXT NOT NULL,
                    article_number TEXT,
                    content TEXT NOT NULL,
                    category TEXT,
                    tags TEXT,
                    effective_date TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_article
                ON regulations(law_name, article_number)
            ''')

            # 创建负面清单表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS negative_list (
                    id INTEGER PRIMARY KEY,
                    rule_number TEXT UNIQUE,
                    description TEXT NOT NULL,
                    severity TEXT,
                    category TEXT,
                    remediation TEXT,
                    keywords TEXT,
                    patterns TEXT,
                    version TEXT,
                    effective_date TEXT
                )
            ''')

            # 创建审核历史表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS audit_history (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    document_url TEXT,
                    document_type TEXT,
                    violations TEXT,
                    score REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            print(f"Database initialized: {DB_PATH}")
            return True
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        return False


if __name__ == '__main__':
    init_database()
