#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化数据库
"""
import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    """获取数据库路径"""
    from lib.config import get_config
    config = get_config()
    rel_path = config.data_paths.sqlite_db  # 从配置读取相对路径

    # 如果是相对路径，相对于脚本目录解析
    if not Path(rel_path).is_absolute():
        script_dir = Path(__file__).parent
        return script_dir / rel_path
    return Path(rel_path)


def init_database():
    """初始化数据库表"""
    try:
        db_path = get_db_path()

        # 确保 data 目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as conn:
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
            print(f"Database initialized: {db_path}")
            return True
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        return False


if __name__ == '__main__':
    init_database()
