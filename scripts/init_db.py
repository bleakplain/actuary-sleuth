#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化数据库
"""
import sqlite3
from pathlib import Path

from lib.common.database import get_db_path


def init_database():
    """初始化数据库表"""
    try:
        db_path = get_db_path()

        # 确保 data 目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as conn:
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
            print(f"Database initialized: {db_path}")
            return True
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        return False


if __name__ == '__main__':
    init_database()
