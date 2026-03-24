#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发访问测试 - 使用真实的数据库和连接
"""
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import tempfile


class TestConcurrentAccess:
    """并发访问测试"""

    def test_concurrent_database_access(self):
        """测试并发数据库访问"""
        from lib.common.connection_pool import SQLiteConnectionPool

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            pool = SQLiteConnectionPool(db_path=db_path, pool_size=5)

            try:
                def query():
                    with pool.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT 1")
                        row = cursor.fetchone()
                        return tuple(row)

                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(query) for _ in range(10)]
                    results = [f.result() for f in as_completed(futures)]

                assert len(results) == 10
                assert all(r == (1,) for r in results)
            finally:
                pool.close_all()

    def test_concurrent_config_access(self):
        """测试并发配置访问"""
        from lib.config import get_config, reset_config

        reset_config()

        def get_and_validate():
            config = get_config()
            assert config is not None
            assert hasattr(config, 'llm')
            return config.version

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(get_and_validate) for _ in range(20)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 20

    def test_thread_safe_connection_pool(self):
        """测试连接池线程安全"""
        from lib.common.connection_pool import SQLiteConnectionPool
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            pool = SQLiteConnectionPool(
                db_path=db_path,
                pool_size=3,
                max_overflow=5
            )

            try:
                def concurrent_query(worker_id):
                    with pool.get_connection() as conn:
                        time.sleep(0.01)
                        cursor = conn.cursor()
                        cursor.execute("SELECT ? + ?", (worker_id, worker_id))
                        return cursor.fetchone()[0]

                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(concurrent_query, i) for i in range(20)]
                    results = [f.result() for f in as_completed(futures)]

                assert len(results) == 20
                # 每个结果应该是 worker_id * 2
                expected = [i * 2 for i in range(20)]
                # 由于并发，顺序可能不一致，所以用集合比较
                assert set(results) == set(expected)

            finally:
                pool.close_all()

    def test_concurrent_validation(self):
        """测试并发验证"""
        from lib.reporting.export.validation import sanitize_message

        messages = ["Test message"] * 50

        def sanitize(msg):
            return sanitize_message(msg)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(sanitize, msg) for msg in messages]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 50
        assert all(r == "Test message" for r in results)
