#!/usr/bin/env python3
"""缓存 API 端点测试"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from api.app import app
    return TestClient(app)


class TestCacheEndpoints:
    def test_get_cache_stats(self, client):
        """测试获取缓存统计。"""
        resp = client.get("/api/observability/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        # 可能返回 {"status": "not_initialized"} 或完整统计
        if "status" not in data:
            assert "hits" in data
            assert "misses" in data
            assert "hit_rate" in data
            assert "memory_size" in data
            assert "evictions" in data
            assert "l2_size" in data
            assert "by_namespace" in data

    def test_list_cache_entries(self, client):
        """测试获取缓存条目列表。"""
        resp = client.get("/api/observability/cache/entries")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_list_cache_entries_with_namespace(self, client):
        """测试按作用域筛选缓存条目。"""
        resp = client.get("/api/observability/cache/entries?scope=embedding")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_cache_entries_pagination(self, client):
        """测试缓存条目分页。"""
        resp = client.get("/api/observability/cache/entries?page=1&size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_get_cache_trend(self, client):
        """测试获取缓存历史趋势。"""
        resp = client.get("/api/observability/cache/trend?range_hours=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        assert isinstance(data["points"], list)

    def test_get_cache_trend_with_range(self, client):
        """测试不同时间范围的缓存趋势。"""
        for hours in [1, 6, 24, 168]:
            resp = client.get(f"/api/observability/cache/trend?range_hours={hours}")
            assert resp.status_code == 200
            data = resp.json()
            assert "points" in data

    def test_cleanup_cache(self, client):
        """测试清理过期缓存。"""
        resp = client.post("/api/observability/cache/cleanup")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
        assert isinstance(data["deleted"], int)
