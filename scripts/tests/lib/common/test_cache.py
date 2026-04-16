#!/usr/bin/env python3
"""CacheManager 单元测试"""
import json
import os
import tempfile
import threading
import time

import pytest

from lib.common.cache import CacheManager, reset_cache_manager


@pytest.fixture
def cache_db(tmp_path):
    return str(tmp_path / "test_cache.db")


@pytest.fixture
def cm(cache_db):
    reset_cache_manager()
    return CacheManager(db_path=cache_db, max_memory_entries=10)


class TestBasicGetSet:
    def test_set_and_get_string(self, cm):
        cm.set("generation", "q1", "hello world")
        assert cm.get("generation", "q1") == "hello world"

    def test_set_and_get_dict(self, cm):
        value = {"generation": "test", "citations": []}
        cm.set("generation", "q1", value)
        result = cm.get("generation", "q1")
        assert result == value

    def test_set_and_get_list(self, cm):
        value = [{"score": 0.9}, {"score": 0.8}]
        cm.set("retrieval", "q1", value)
        assert cm.get("retrieval", "q1") == value

    def test_get_miss_returns_none(self, cm):
        assert cm.get("generation", "nonexistent") is None

    def test_namespace_isolation(self, cm):
        cm.set("embedding", "text1", [0.1, 0.2])
        cm.set("retrieval", "text1", [{"score": 0.9}])
        assert cm.get("embedding", "text1") == [0.1, 0.2]
        assert cm.get("retrieval", "text1") == [{"score": 0.9}]

    def test_overwrite(self, cm):
        cm.set("generation", "q1", "first")
        cm.set("generation", "q1", "second")
        assert cm.get("generation", "q1") == "second"


class TestTTL:
    def test_expired_entry_returns_none(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=100)
        cm.set("generation", "q1", "value", ttl=1)
        time.sleep(1.1)
        assert cm.get("generation", "q1") is None

    def test_default_ttl_per_namespace(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=10)
        cm.set("embedding", "text1", [0.1, 0.2])
        assert cm.get("embedding", "text1") is not None


class TestLRU:
    def test_eviction_on_overflow(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=5)
        for i in range(10):
            cm.set("generation", f"q{i}", f"answer_{i}")
        assert len(cm._memory) <= 5
        stats = cm.get_stats()
        assert stats["memory_size"] <= 5

    def test_lru_update_on_access(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=5)
        for i in range(5):
            cm.set("generation", f"q{i}", f"answer_{i}")
        cm.get("generation", "q0")
        cm.set("generation", "q_new", "answer_new")
        assert cm.get("generation", "q0") is not None
        assert "q1" not in cm._memory


class TestThreadSafety:
    def test_concurrent_reads(self, cm):
        cm.set("generation", "q1", "value")
        results = [None] * 10
        errors = []

        def read(idx):
            try:
                results[idx] = cm.get("generation", "q1")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert all(r == "value" for r in results)

    def test_concurrent_writes(self, cm):
        errors = []

        def write(idx):
            try:
                cm.set("generation", f"q{idx}", f"value_{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestSQLitePersistence:
    def test_data_survives_reopen(self, cache_db):
        cm1 = CacheManager(db_path=cache_db, max_memory_entries=10)
        cm1.set("generation", "q1", "persisted_value")
        del cm1

        cm2 = CacheManager(db_path=cache_db, max_memory_entries=10)
        result = cm2.get("generation", "q1")
        assert result == "persisted_value"
        del cm2

    def test_sqlite_l2_fills_l1(self, cache_db):
        cm1 = CacheManager(db_path=cache_db, max_memory_entries=10)
        cm1.set("retrieval", "q1", [{"score": 0.9}])
        del cm1

        cm2 = CacheManager(db_path=cache_db, max_memory_entries=10)
        result = cm2.get("retrieval", "q1")
        assert result == [{"score": 0.9}]
        assert len(cm2._memory) == 1


class TestKBVersionEviction:
    def test_kb_version_mismatch_returns_none(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=100, kb_version="v1")
        cm.set("generation", "q1", "value_for_v1")
        cm.set_kb_version("v2")
        result = cm.get("generation", "q1")
        assert result is None

    def test_evict_kb_version_clears_matching(self, cache_db):
        cm = CacheManager(db_path=cache_db, max_memory_entries=100, kb_version="v1")
        cm.set("generation", "q1", "value1")
        cm.set("retrieval", "q1", [{"score": 0.9}])
        cm.set("embedding", "text1", [0.1, 0.2])
        count = cm.evict_kb_version("v1")
        assert count >= 3
        assert cm.get("generation", "q1") is None
        assert cm.get("retrieval", "q1") is None
        assert cm.get("embedding", "text1") is None


class TestStats:
    def test_initial_stats(self, cm):
        stats = cm.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0
        assert stats["memory_size"] == 0

    def test_hit_miss_tracking(self, cm):
        cm.get("generation", "miss")
        cm.set("generation", "hit", "value")
        cm.get("generation", "hit")
        stats = cm.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_namespace_stats(self, cm):
        cm.get("embedding", "miss")
        cm.set("generation", "hit", "value")
        cm.get("generation", "hit")
        stats = cm.get_stats()
        assert stats["by_namespace"]["embedding"]["misses"] == 1
        assert stats["by_namespace"]["generation"]["hits"] == 1


class TestInvalidateAll:
    def test_clears_everything(self, cm):
        cm.set("generation", "q1", "v1")
        cm.set("retrieval", "q1", [{"score": 0.9}])
        cm.invalidate_all()
        assert cm.get("generation", "q1") is None
        assert cm.get("retrieval", "q1") is None
        assert cm.get_stats()["hits"] == 0


class TestSetKBVersion:
    def test_set_kb_version(self, cm):
        cm.set_kb_version("v2")
        assert cm._kb_version == "v2"
