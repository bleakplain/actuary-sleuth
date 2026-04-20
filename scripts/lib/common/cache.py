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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCOPE_EMBEDDING = "embedding"
SCOPE_RETRIEVAL = "retrieval"
SCOPE_GENERATION = "generation"

_DEFAULT_SCOPE_TTL: Dict[str, int] = {
    SCOPE_EMBEDDING: 86400,
    SCOPE_RETRIEVAL: 3600,
    SCOPE_GENERATION: 3600,
}


@dataclass(frozen=True)
class ScopeStats:
    hits: int = 0
    misses: int = 0


@dataclass(frozen=True)
class CacheStats:
    memory_size: int
    max_memory_entries: int
    hits: int
    misses: int
    hit_rate: float
    kb_version: str
    evictions: int
    l2_size: int
    by_scope: Dict[str, ScopeStats] = field(default_factory=dict)


@dataclass(frozen=True)
class CacheEntry:
    key: str
    scope: str
    created_at: float
    ttl: int
    kb_version: str
    size_bytes: int

_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    value BLOB NOT NULL,
    created_at REAL NOT NULL,
    ttl INTEGER NOT NULL,
    kb_version TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cache_scope ON cache_entries(scope);
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
        scope_ttl: Optional[Dict[str, int]] = None,
    ):
        self._db_path = db_path
        self._default_ttl = default_ttl
        self._max_memory_entries = max_memory_entries
        self._kb_version = kb_version
        self._scope_ttl = scope_ttl if scope_ttl is not None else dict(_DEFAULT_SCOPE_TTL)
        self._memory: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._scope_hits: Dict[str, int] = {}
        self._scope_misses: Dict[str, int] = {}
        self._evictions: int = 0
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

    def _generate_key(self, scope: str, key_text: str) -> str:
        content = f"{scope}:{key_text}"
        hash_val = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{scope}:{hash_val}"

    def _is_expired(self, created_at: float, ttl: int) -> bool:
        return time.time() - created_at >= ttl

    def get(self, scope: str, key_text: str) -> Optional[Any]:
        key = self._generate_key(scope, key_text)
        ttl = self._scope_ttl.get(scope, self._default_ttl)

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
                    self._scope_hits[scope] = self._scope_hits.get(scope, 0) + 1
                    return copy.deepcopy(obj) if isinstance(obj, (dict, list)) else obj

        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT value, created_at, kb_version, ttl FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                with self._lock:
                    self._misses += 1
                    self._scope_misses[scope] = self._scope_misses.get(scope, 0) + 1
                return None

            db_value, created_at, kb_ver, stored_ttl = row
            now = time.time()
            entry_ttl = stored_ttl if stored_ttl > 0 else ttl

            if now - created_at >= entry_ttl:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                conn.commit()
                with self._lock:
                    self._misses += 1
                    self._scope_misses[scope] = self._scope_misses.get(scope, 0) + 1
                return None

            if self._kb_version and kb_ver and kb_ver != self._kb_version:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                conn.commit()
                with self._lock:
                    self._misses += 1
                    self._scope_misses[scope] = self._scope_misses.get(scope, 0) + 1
                return None

            parsed = json.loads(db_value)
            with self._lock:
                self._memory[key] = (parsed, {"kb_version": kb_ver, "ttl": entry_ttl}, created_at)
                self._evict_if_needed()
                self._hits += 1
                self._scope_hits[scope] = self._scope_hits.get(scope, 0) + 1
            return parsed
        except Exception as e:
            logger.warning(f"SQLite 缓存读取失败: {e}")
            with self._lock:
                self._misses += 1
            return None

    def set(self, scope: str, key_text: str, value: Any, ttl: Optional[int] = None) -> None:
        key = self._generate_key(scope, key_text)
        actual_ttl = ttl or self._scope_ttl.get(scope, self._default_ttl)
        serialized = json.dumps(value, ensure_ascii=False)
        now = time.time()

        try:
            conn = self._get_db()
            conn.execute(
                """INSERT OR REPLACE INTO cache_entries (key, scope, value, created_at, ttl, kb_version)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, scope, serialized, now, actual_ttl, self._kb_version),
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
            self._evictions += 1

    def evict_kb_version(self, kb_version: str) -> int:
        count = 0
        with self._lock:
            keys_to_remove = [
                k for k, (_, meta, _) in self._memory.items()
                if meta.get("kb_version") == kb_version
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
            self._scope_hits.clear()
            self._scope_misses.clear()
        try:
            conn = self._get_db()
            conn.execute("DELETE FROM cache_entries")
            conn.commit()
        except Exception as e:
            logger.warning(f"缓存清空失败: {e}")

    def get_stats(self) -> CacheStats:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            memory_size = len(self._memory)
            hits = self._hits
            misses = self._misses
            evictions = self._evictions
            kb_version = self._kb_version
            max_memory_entries = self._max_memory_entries
            by_scope = {
                s: ScopeStats(
                    hits=self._scope_hits.get(s, 0),
                    misses=self._scope_misses.get(s, 0),
                )
                for s in self._scope_ttl
            }

        l2_size = 0
        try:
            conn = self._get_db()
            row = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()
            l2_size = row[0] if row else 0
        except Exception:
            pass

        return CacheStats(
            memory_size=memory_size,
            max_memory_entries=max_memory_entries,
            hits=hits,
            misses=misses,
            hit_rate=round(hit_rate, 4),
            kb_version=kb_version,
            evictions=evictions,
            l2_size=l2_size,
            by_scope=by_scope,
        )

    def get_entries(
        self,
        scope: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[CacheEntry], int]:
        """查询缓存条目列表。

        Args:
            scope: 作用域筛选，None 表示全部
            page: 页码，从 1 开始
            size: 每页条数

        Returns:
            (items, total) 元组
        """
        offset = (page - 1) * size

        try:
            conn = self._get_db()

            if scope:
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM cache_entries WHERE scope = ?",
                    [scope]
                ).fetchone()
            else:
                count_row = conn.execute(
                    "SELECT COUNT(*) FROM cache_entries"
                ).fetchone()
            total = count_row[0] if count_row else 0

            if scope:
                rows = conn.execute(
                    "SELECT key, scope, created_at, ttl, kb_version, LENGTH(value) as size_bytes "
                    "FROM cache_entries WHERE scope = ? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    [scope, size, offset]
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, scope, created_at, ttl, kb_version, LENGTH(value) as size_bytes "
                    "FROM cache_entries "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    [size, offset]
                ).fetchall()

            items = [
                CacheEntry(
                    key=row[0],
                    scope=row[1],
                    created_at=row[2],
                    ttl=row[3],
                    kb_version=row[4] or "",
                    size_bytes=row[5],
                )
                for row in rows
            ]
            return items, total
        except Exception as e:
            logger.warning(f"缓存条目查询失败: {e}")
            return [], 0

    def cleanup_expired(self) -> int:
        """清理所有过期缓存条目。

        Returns:
            清理的条目数量
        """
        now = time.time()
        count = 0

        with self._lock:
            keys_to_remove = []
            for key, (_, meta, created_at) in self._memory.items():
                ttl = meta.get("ttl", self._default_ttl)
                if self._is_expired(created_at, ttl):
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._memory[key]
                count += 1

        try:
            conn = self._get_db()
            cursor = conn.execute(
                "DELETE FROM cache_entries WHERE created_at + ttl < ?", (now,)
            )
            count += cursor.rowcount
            conn.commit()
        except Exception as e:
            logger.warning(f"SQLite 过期清理失败: {e}")

        return count

    def set_kb_version(self, kb_version: str) -> None:
        with self._lock:
            self._kb_version = kb_version

    def close(self) -> None:
        with self._db_lock:
            if self._db is not None:
                self._db.close()
                self._db = None


def get_cache_manager() -> Optional["CacheManager"]:
    """获取全局 CacheManager 实例。

    首次调用时自动从配置读取 enable_cache 和 scope_ttl，
    并基于 kb_version_dir 确定 db_path。
    如果缓存未启用，返回 None。
    """
    global _global_cache_manager
    if _global_cache_manager is not None:
        return _global_cache_manager

    with _cache_manager_lock:
        if _global_cache_manager is not None:
            return _global_cache_manager

        from lib.config import (
            is_cache_enabled,
            get_embedding_cache_ttl,
            get_retrieval_cache_ttl,
            get_generation_cache_ttl,
            get_kb_version_dir,
        )
        if not is_cache_enabled():
            return None

        scope_ttl = {
            SCOPE_EMBEDDING: get_embedding_cache_ttl(),
            SCOPE_RETRIEVAL: get_retrieval_cache_ttl(),
            SCOPE_GENERATION: get_generation_cache_ttl(),
        }

        cache_db = str(Path(get_kb_version_dir()) / "cache.db")
        _global_cache_manager = CacheManager(
            db_path=cache_db,
            scope_ttl=scope_ttl,
        )
        return _global_cache_manager


def reset_cache_manager() -> None:
    global _global_cache_manager
    with _cache_manager_lock:
        if _global_cache_manager is not None:
            _global_cache_manager.invalidate_all()
            _global_cache_manager.close()
        _global_cache_manager = None
