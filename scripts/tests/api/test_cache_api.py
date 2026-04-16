"""缓存 API 集成测试"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.database import init_db


@pytest.fixture()
def cache_test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """创建缓存测试专用客户端"""
    import lib.common.database as db_mod
    import lib.common.connection_pool as pool_mod

    # 重置全局连接池
    pool_mod._global_pool = None
    db_mod._connection_pool = None

    db_path = tmp_path / "test.db"

    # 用临时路径替换数据库路径
    monkeypatch.setattr(db_mod, "get_sqlite_db_path", lambda: str(db_path))
    monkeypatch.setattr(db_mod, "get_db_path", lambda: db_path)

    # 初始化连接池
    pool_mod.get_connection_pool(
        db_path=db_path, pool_size=2, max_overflow=2
    )

    # 建表
    init_db()

    # Mock RAG 引擎和 Cache
    mock_cache = MagicMock()
    mock_cache.get_stats.return_value = {
        "memory_size": 10,
        "max_memory_entries": 500,
        "hits": 100,
        "misses": 20,
        "hit_rate": 0.8333,
        "kb_version": "v1",
        "evictions": 5,
        "l2_size": 50,
        "by_namespace": {
            "embedding": {"hits": 50, "misses": 10},
            "retrieval": {"hits": 30, "misses": 5},
            "generation": {"hits": 20, "misses": 5},
        },
    }
    mock_cache.get_entries.return_value = (
        [
            {
                "key": "embedding:abc123",
                "namespace": "embedding",
                "created_at": 1700000000.0,
                "ttl": 86400,
                "kb_version": "v1",
                "size_bytes": 1024,
            }
        ],
        1,
    )
    mock_cache.cleanup_expired.return_value = 3

    mock_engine = MagicMock()
    mock_engine.cache = mock_cache

    monkeypatch.setattr("api.dependencies.get_rag_engine", lambda: mock_engine)

    # 创建测试应用
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from api.routers import observability

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.include_router(observability.router)

    with TestClient(test_app) as client:
        yield client

    # 清理
    pool_mod.reset_connection_pool()
    db_mod.close_pool()


class TestCacheEndpoints:
    def test_get_cache_stats(self, cache_test_client):
        resp = cache_test_client.get("/api/observability/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hits"] == 100
        assert data["misses"] == 20

    def test_list_cache_entries(self, cache_test_client):
        resp = cache_test_client.get("/api/observability/cache/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_cache_entries_with_namespace(self, cache_test_client):
        resp = cache_test_client.get("/api/observability/cache/entries?namespace=embedding")
        assert resp.status_code == 200

    def test_get_cache_trend(self, cache_test_client):
        resp = cache_test_client.get("/api/observability/cache/trend?range_hours=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data

    def test_get_cache_trend_invalid_range(self, cache_test_client):
        resp = cache_test_client.get("/api/observability/cache/trend?range_hours=0")
        assert resp.status_code == 422

    def test_cleanup_cache(self, cache_test_client):
        resp = cache_test_client.post("/api/observability/cache/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
        assert data["deleted"] == 3
