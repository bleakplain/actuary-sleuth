#!/usr/bin/env python3
"""三级缓存管理器

提供 Embedding / 检索结果 / 答案的三级缓存，采用内存 + SQLite 两级存储。
"""
import copy
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_NAMESPACE_TTL: Dict[str, int] = {
    "embedding": 86400,
    "retrieval": 3600,
    "generation": 3600,
}

_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    value BLOB NOT NULL,
    created_at REAL NOT NULL,
    ttl INTEGER NOT NULL,
    kb_version TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cache_namespace ON cache_entries(namespace);
"""

_global_cache_manager: Optional["CacheManager"] = None
_cache_manager_lock = threading.Lock()


class CacheManager:
    """三级缓存管理器：Embedding / 检索结果 / 答案缓存

    L1: 内存缓存（OrderedDict，LRU 淘汰）
    L2: SQLite 持久化（进程重启后懒加载恢复）
    """

    def __init__(
        self,
        db_path: str,
        default_ttl: int = 3600,
        max_memory_entries: int = 500,
        kb_version: str = "",
        namespace_ttl: Optional[Dict[str, int]] = None,
    ):
        self._db_path = db_path
        self._default_ttl = default_ttl
        self._max_memory_entries = max_memory_entries
        self._kb_version = kb_version
        self._namespace_ttl = namespace_ttl if namespace_ttl is not None else dict(_DEFAULT_NAMESPACE_TTL)
        self._memory: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._namespace_hits: Dict[str, int] = {}
        self._namespace_misses: Dict[str, int] = {}
        self._db: Optional[sqlite3.Connection] = None
        self._db_lock = threading.Lock()

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            with self._db_lock:
                if self._db is None:
                    self._db = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
                    self._db.execute("PRAGMA journal_mode=WAL")
                    self._db.executescript(_CACHE_DDL)
        return self._db

    def _generate_key(self, namespace: str, key_text: str) -> str:
        content = f"{namespace}:{key_text}"
        hash_val = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{namespace}:{hash_val}"

    def _is_expired(self, created_at: float, ttl: int) -> bool:
        return time.time() - created_at >= ttl

    def get(self, namespace: str, key_text: str) -> Optional[Any]:
        key = self._generate_key(namespace, key_text)
        ttl = self._namespace_ttl.get(namespace, self._default_ttl)

        with self._lock:
            if key in self._memory:
                obj, meta, created_at = self._memory[key]
                stored_ttl = meta.get("ttl", ttl)
                if self._is_expired(created_at, stored_ttl):
                    del self._memory[key]
                elif self._kb_version and meta.get("kb_version") and meta.get("kb_version") != self._kb_version:
                    del self._memory[key]
                else:
                    self._memory.move_to_end(key)
                    self._hits += 1
                    self._namespace_hits[namespace] = self._namespace_hits.get(namespace, 0) + 1
                    return copy.copy(obj) if isinstance(obj, (dict, list)) else obj

        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT value, created_at, kb_version, ttl FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                with self._lock:
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                return None

            db_value, created_at, kb_ver, stored_ttl = row
            now = time.time()
            entry_ttl = stored_ttl if stored_ttl > 0 else ttl

            if now - created_at >= entry_ttl:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                conn.commit()
                with self._lock:
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                return None

            if self._kb_version and kb_ver and kb_ver != self._kb_version:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                conn.commit()
                with self._lock:
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                return None

            parsed = json.loads(db_value)
            with self._lock:
                self._memory[key] = (parsed, {"kb_version": kb_ver, "ttl": entry_ttl}, created_at)
                self._evict_if_needed()
                self._hits += 1
                self._namespace_hits[namespace] = self._namespace_hits.get(namespace, 0) + 1
            return parsed
        except Exception as e:
            logger.warning(f"SQLite 缓存读取失败: {e}")
            with self._lock:
                self._misses += 1
            return None

    def set(self, namespace: str, key_text: str, value: Any, ttl: Optional[int] = None) -> None:
        key = self._generate_key(namespace, key_text)
        actual_ttl = ttl or self._namespace_ttl.get(namespace, self._default_ttl)
        serialized = json.dumps(value, ensure_ascii=False)
        now = time.time()

        try:
            conn = self._get_db()
            conn.execute(
                """INSERT OR REPLACE INTO cache_entries (key, namespace, value, created_at, ttl, kb_version)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, namespace, serialized, now, actual_ttl, self._kb_version),
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"SQLite 缓存写入失败: {e}")
            return

        with self._lock:
            self._memory[key] = (value, {"kb_version": self._kb_version, "ttl": actual_ttl}, now)
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._memory) > self._max_memory_entries:
            self._memory.popitem(last=False)

    def evict_kb_version(self, kb_version: str) -> int:
        count = 0
        with self._lock:
            keys_to_remove = [
                k for k in self._memory
                if k.startswith("embedding:") or k.startswith("retrieval:") or k.startswith("generation:")
            ]
            for k in keys_to_remove:
                del self._memory[k]
                count += 1

        try:
            conn = self._get_db()
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE kb_version = ?",
                (kb_version,),
            )
            count += cursor.rowcount
            conn.commit()
        except Exception as e:
            logger.warning(f"缓存失效失败: {e}")

        logger.info(f"缓存失效完成: {count} 条 (kb_version={kb_version})")
        return count

    def invalidate_all(self) -> None:
        with self._lock:
            self._memory.clear()
            self._hits = 0
            self._misses = 0
            self._namespace_hits.clear()
            self._namespace_misses.clear()
        try:
            conn = self._get_db()
            conn.execute("DELETE FROM cache_entries")
            conn.commit()
        except Exception as e:
            logger.warning(f"缓存清空失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            return {
                "memory_size": len(self._memory),
                "max_memory_entries": self._max_memory_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "kb_version": self._kb_version,
                "by_namespace": {
                    ns: {
                        "hits": self._namespace_hits.get(ns, 0),
                        "misses": self._namespace_misses.get(ns, 0),
                    }
                    for ns in self._namespace_ttl
                },
            }

    def set_kb_version(self, kb_version: str) -> None:
        with self._lock:
            self._kb_version = kb_version

    def close(self) -> None:
        with self._db_lock:
            if self._db is not None:
                self._db.close()
                self._db = None


def get_cache_manager(db_path: str, **kwargs) -> CacheManager:
    global _global_cache_manager
    if _global_cache_manager is not None:
        if _global_cache_manager._db_path != db_path:
            raise ValueError(
                f"CacheManager already initialized with db_path={_global_cache_manager._db_path}, "
                f"cannot reinitialize with db_path={db_path}"
            )
        return _global_cache_manager
    with _cache_manager_lock:
        if _global_cache_manager is None:
            _global_cache_manager = CacheManager(db_path=db_path, **kwargs)
    return _global_cache_manager


def reset_cache_manager() -> None:
    global _global_cache_manager
    with _cache_manager_lock:
        if _global_cache_manager is not None:
            _global_cache_manager.invalidate_all()
            _global_cache_manager.close()
        _global_cache_manager = None
