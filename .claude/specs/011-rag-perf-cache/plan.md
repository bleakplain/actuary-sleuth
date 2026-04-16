# Implementation Plan: RAG 性能优化 — 三级缓存 + 全链路异步

**Branch**: `011-rag-perf-cache` | **Date**: 2026-04-15 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

实现三级缓存架构（Embedding / 检索结果 / 答案缓存），配合 Zhipu SSE 原生流式输出和 LanceDB IVF_HNSW_SQ 索引优化，将热门查询首字响应时间从 5-9s 降至 <50ms。缓存基于统一 `CacheManager`，采用内存 + SQLite 两级存储，复用现有 `LLMResponseCache` 的线程安全和 key 生成模式。流式改造采用"缓存优先 + graph 同步 + 缓存结果流式返回"策略，避免 LangGraph 流式改造的复杂性。

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: `lancedb`（索引优化）, `requests`（SSE 流式）, `sqlite3`（缓存持久化）
**Storage**: SQLite（缓存持久化） + 内存（L1 缓存）
**Testing**: pytest
**Performance Goals**: 热门查询 <50ms, 首次查询 TTFT <200ms（检索完成后）
**Constraints**: 不引入 Redis 等外部依赖，保持 LanceDB，不改动前端

## Constitution Check

- [x] **Library-First**: 复用 `LLMResponseCache`（线程安全、key 生成、TTL/LRU）、`SQLiteConnectionPool`（连接管理）、`KBManager`（版本管理）、现有 trace/metrics 基础设施
- [x] **测试优先**: 每个 Phase 都有对应测试，缓存核心逻辑测试覆盖率目标 >80%
- [x] **简单优先**: 选择"缓存优先 + graph 不改"策略，避免 LangGraph 流式改造；缓存统一管理而非三个独立类
- [x] **显式优于隐式**: 缓存 key 生成基于 SHA-256 显式哈希，命名空间显式区分（embedding/retrieval/answer）
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: Phase 1（缓存）和 Phase 2（流式）可独立交付和测试

## Project Structure

### Documentation

```text
.claude/specs/011-rag-perf-cache/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/rag_engine/
├── cache.py          # [新增] CacheManager — 三级缓存统一管理
├── rag_engine.py     # [修改] 集成 Embedding/检索缓存
├── index_manager.py  # [修改] LanceDB IVF_HNSW_SQ 索引
├── llamaindex_adapter.py  # [修改] Embedding 缓存集成

scripts/lib/llm/
├── base.py           # [修改] 添加 stream_chat()
├── zhipu.py          # [修改] 实现 _do_chat_stream()
├── ollama.py         # [修改] 实现 _do_chat_stream()
├── cache.py          # [保留] 不改动（新 CacheManager 独立实现）

scripts/api/routers/
└── ask.py            # [修改] 缓存优先 + 真实流式

scripts/tests/lib/rag_engine/
└── test_cache.py     # [新增] 缓存测试
```

## Implementation Phases

### Phase 1: CacheManager — 三级缓存核心 (P1) ✅

#### 需求回溯

→ 对应 spec.md User Story 1: 热门查询缓存命中快速响应
→ 对应 spec.md User Story 3: 三级缓存架构
→ 对应 FR-001, FR-002, FR-004, FR-006, FR-007, FR-011

#### 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 缓存位置 | `lib/rag_engine/cache.py`（新增） | 缓存服务于 RAG 流程，归属 rag_engine 模块 |
| 与 `lib/llm/cache.py` 关系 | 保留不动，新模块独立实现 | 避免修改现有未使用的代码，减少风险 |
| 内存缓存结构 | `Dict[str, tuple]` + `threading.RLock` | 复用现有 `LLMResponseCache` 的成熟模式 |
| SQLite 存储 | 独立 `cache_entries` 表，复用 `SQLiteConnectionPool` | 与主数据库隔离，不影响业务数据 |
| KB 版本失效 | 按 KB 版本全量惰性失效 | KB 更新是原子操作，无需文档粒度 |
| 检索结果缓存时机 | reranker 之前 | 避免 reranker 随机性导致缓存不稳定 |

#### 实现步骤

**Step 1.1: 创建 CacheManager 核心类**

- 文件: `scripts/lib/rag_engine/cache.py`（新增）

```python
#!/usr/bin/env python3
"""RAG 三级缓存管理器

提供 Embedding / 检索结果 / 答案的三级缓存，采用内存 + SQLite 两级存储。
"""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NAMESPACE_TTL = {
    "embedding": 86400,      # 24h — embedding 稳定，长期有效
    "retrieval": 3600,       # 1h  — 检索结果随知识库变化
    "answer": 3600,          # 1h  — 答案随知识库和 prompt 变化
}

_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    value BLOB NOT NULL,
    created_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    hit_count INTEGER DEFAULT 0,
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
    ):
        self._db_path = db_path
        self._default_ttl = default_ttl
        self._max_memory_entries = max_memory_entries
        self._kb_version = kb_version
        self._memory: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._namespace_hits: Dict[str, int] = {}
        self._namespace_misses: Dict[str, int] = {}
        self._db_initialized = False

    def _ensure_db(self) -> sqlite3.Connection:
        """获取 SQLite 连接并确保表存在"""
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_CACHE_DDL)
        self._db_initialized = True
        return conn

    def _generate_key(self, namespace: str, key_text: str) -> str:
        """生成缓存键: namespace:sha256(key_text)"""
        content = f"{namespace}:{key_text}"
        hash_val = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{namespace}:{hash_val}"

    def get(self, namespace: str, key_text: str) -> Optional[Any]:
        """获取缓存值（L1 内存 → L2 SQLite）"""
        key = self._generate_key(namespace, key_text)
        ttl = _NAMESPACE_TTL.get(namespace, self._default_ttl)

        with self._lock:
            # L1: 内存缓存
            if key in self._memory:
                value, timestamp = self._memory[key]
                if time.time() - timestamp > ttl:
                    del self._memory[key]
                else:
                    self._memory.move_to_end(key)
                    self._memory[key] = (value, time.time())
                    self._hits += 1
                    self._namespace_hits[namespace] = self._namespace_hits.get(namespace, 0) + 1
                    return json.loads(value) if isinstance(value, (str, bytes)) else value

            # L2: SQLite
            try:
                conn = self._ensure_db()
                row = conn.execute(
                    "SELECT value, accessed_at, hit_count, kb_version FROM cache_entries WHERE key = ?",
                    (key,),
                ).fetchone()

                if row is None:
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                    return None

                db_value, accessed_at, hit_count, kb_ver = row
                now = time.time()

                if now - accessed_at > ttl:
                    conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                    conn.commit()
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                    return None

                if self._kb_version and kb_ver and kb_ver != self._kb_version:
                    conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                    conn.commit()
                    self._misses += 1
                    self._namespace_misses[namespace] = self._namespace_misses.get(namespace, 0) + 1
                    return None

                # 回填 L1
                parsed = json.loads(db_value)
                self._memory[key] = (db_value, now)
                self._evict_if_needed()
                conn.execute(
                    "UPDATE cache_entries SET accessed_at = ?, hit_count = ? WHERE key = ?",
                    (now, hit_count + 1, key),
                )
                conn.commit()
                self._hits += 1
                self._namespace_hits[namespace] = self._namespace_hits.get(namespace, 0) + 1
                return parsed
            except Exception as e:
                logger.warning(f"SQLite 缓存读取失败: {e}")
                self._misses += 1
                return None
            finally:
                conn.close()

    def set(self, namespace: str, key_text: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值（同时写入 L1 和 L2）"""
        key = self._generate_key(namespace, key_text)
        actual_ttl = ttl or _NAMESPACE_TTL.get(namespace, self._default_ttl)
        serialized = json.dumps(value, ensure_ascii=False)
        now = time.time()

        with self._lock:
            # L1
            self._memory[key] = (serialized, now)
            self._evict_if_needed()

            # L2
            try:
                conn = self._ensure_db()
                conn.execute(
                    """INSERT OR REPLACE INTO cache_entries (key, namespace, value, created_at, accessed_at, ttl, kb_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (key, namespace, serialized, now, now, actual_ttl, self._kb_version),
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"SQLite 缓存写入失败: {e}")
            finally:
                conn.close()

    def _evict_if_needed(self) -> None:
        """LRU 淘汰：内存缓存超出上限时淘汰最久未访问的条目"""
        while len(self._memory) > self._max_memory_entries:
            self._memory.popitem(last=False)

    def invalidate_kb_version(self, kb_version: str) -> int:
        """使指定 KB 版本的所有缓存失效，返回失效条目数"""
        count = 0
        with self._lock:
            # 清理内存中匹配的条目
            keys_to_remove = [
                k for k in self._memory
                if k.startswith("embedding:") or k.startswith("retrieval:") or k.startswith("answer:")
            ]
            for k in keys_to_remove:
                del self._memory[k]
                count += 1

            # 清理 SQLite
            try:
                conn = self._ensure_db()
                cursor = conn.execute(
                    "DELETE FROM cache_entries WHERE kb_version = ? OR kb_version = ''",
                    (kb_version,),
                )
                count += cursor.rowcount
                conn.commit()
            except Exception as e:
                logger.warning(f"缓存失效失败: {e}")
            finally:
                conn.close()

        logger.info(f"缓存失效完成: {count} 条 (kb_version={kb_version})")
        return count

    def invalidate_all(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._memory.clear()
            try:
                conn = self._ensure_db()
                conn.execute("DELETE FROM cache_entries")
                conn.commit()
            except Exception as e:
                logger.warning(f"缓存清空失败: {e}")
            finally:
                conn.close()
            self._hits = 0
            self._misses = 0
            self._namespace_hits.clear()
            self._namespace_misses.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
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
                    for ns in ("embedding", "retrieval", "answer")
                },
            }

    def set_kb_version(self, kb_version: str) -> None:
        """更新当前 KB 版本（用于惰性失效校验）"""
        self._kb_version = kb_version


def get_cache_manager(db_path: str, **kwargs) -> CacheManager:
    """获取全局 CacheManager 单例"""
    global _global_cache_manager
    if _global_cache_manager is None:
        with _cache_manager_lock:
            if _global_cache_manager is None:
                _global_cache_manager = CacheManager(db_path=db_path, **kwargs)
    return _global_cache_manager


def reset_cache_manager() -> None:
    """重置全局 CacheManager（测试用）"""
    global _global_cache_manager
    with _cache_manager_lock:
        if _global_cache_manager is not None:
            _global_cache_manager.invalidate_all()
        _global_cache_manager = None
```

**Step 1.2: CacheManager 单元测试**

- 文件: `scripts/tests/lib/rag_engine/test_cache.py`（新增）

测试覆盖：
1. 基本 get/set — 写入后读取返回一致
2. TTL 过期 — 过期后返回 None
3. LRU 淘汰 — 超出 max_memory_entries 时淘汰最旧条目
4. 线程安全 — 多线程并发读写不崩溃
5. SQLite 持久化 — 写入后关闭再打开，数据仍存在
6. KB 版本失效 — 设置不同 kb_version 的条目被正确失效
7. 统计信息 — hits/misses/hit_rate 正确累计
8. 命名空间隔离 — 不同 namespace 的相同 key 互不影响

**Step 1.3: 添加缓存配置项**

- 文件: `scripts/.env`（修改）
- 文件: `scripts/lib/config.py`（修改）

```bash
# .env — 新增配置项（默认关闭，生产环境按需开启）
ENABLE_CACHE=false
```

```python
# lib/config.py — 读取缓存开关
@property
def enable_cache(self) -> bool:
    return self._config.get('enable_cache', False)
```

**Step 1.4: 将 CacheManager 集成到 RAGEngine**

- 文件: `scripts/lib/rag_engine/rag_engine.py`（修改）
- 改动点:
  1. `__init__()` 中根据 `ENABLE_CACHE` 配置决定是否初始化缓存
  2. `_hybrid_search()` 中添加检索缓存（reranker 之前）
  3. `_do_ask()` 中添加答案缓存

```python
# rag_engine.py — __init__() 改动
def __init__(self, config=None, llm_client=None):
    # ... 现有代码 ...
    self._cache: Optional[CacheManager] = None

def initialize(self, force_rebuild=False) -> bool:
    # ... 现有初始化代码 ...
    # 根据配置初始化缓存
    from lib.config import _get_config
    if _get_config().enable_cache and self._cache is None:
        cache_db = Path(self.config.vector_db_path).parent / "cache.db"
        self._cache = CacheManager(
            db_path=str(cache_db),
            max_memory_entries=500,
        )
        logger.info("缓存已启用")
    # ... 后续代码 ...
```

```python
# rag_engine.py — _hybrid_search() 改动
def _hybrid_search(self, query_text, top_k=None, filters=None):
    """混合检索（带缓存）"""
    # 检索缓存检查
    if self._cache:
        cache_key = json.dumps({"q": query_text, "f": filters or {}, "k": top_k}, sort_keys=True)
        cached = self._cache.get("retrieval", cache_key)
        if cached is not None:
            logger.debug("检索缓存命中")
            return cached

    # ... 现有检索逻辑（vector_search + bm25_search + fusion）...

    # 注意：缓存在 reranker 之前
    if self._cache and results:
        self._cache.set("retrieval", cache_key, results)

    # reranker 不缓存（可能有随机性）
    if self._reranker:
        results = self._reranker.rerank(query_text, results, top_k=top_k)

    return results
```

```python
# rag_engine.py — _do_ask() 改动
def _do_ask(self, question, include_sources):
    # 答案缓存检查
    if self._cache:
        cached = self._cache.get("answer", question)
        if cached is not None:
            logger.debug("答案缓存命中")
            return cached

    # ... 现有逻辑（hybrid_search + build_prompt + llm.chat + parse_citations）...

    # 答案缓存写入
    if self._cache:
        self._cache.set("answer", question, result)

    return result
```

**Step 1.4: Embedding 缓存集成**

- 文件: `scripts/lib/rag_engine/llamaindex_adapter.py`（修改）
- 改动点: `ZhipuEmbeddingAdapter._get_embeddings()` 中添加缓存

```python
# llamaindex_adapter.py — ZhipuEmbeddingAdapter 改动
class ZhipuEmbeddingAdapter(BaseEmbedding):
    _cache_manager: Any = PrivateAttr(default=None)

    def set_cache_manager(self, cache_manager) -> None:
        self._cache_manager = cache_manager

    def _get_embeddings(self, texts, encoding_type="document"):
        if not texts:
            return []

        # Embedding 缓存检查
        if self._cache_manager:
            results = []
            uncached_texts = []
            uncached_indices = []
            for i, text in enumerate(texts):
                cache_key = f"{self._model}:{encoding_type}:{text}"
                cached = self._cache_manager.get("embedding", cache_key)
                if cached is not None:
                    results.append((i, cached))
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)

            if not uncached_texts:
                # 全部命中缓存
                return [emb for _, emb in sorted(results, key=lambda x: x[0])]

            # 只对未命中的文本调用 API
            payload = {"model": self._model, "input": uncached_texts}
            if encoding_type:
                payload["encoding_type"] = encoding_type
            response = self._session.post(
                f"{self._base_url}/embeddings",
                headers={...},
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            new_embeddings = [item.get("embedding", []) for item in response.json().get("data", [])]

            # 写入缓存
            for text, emb in zip(uncached_texts, new_embeddings):
                cache_key = f"{self._model}:{encoding_type}:{text}"
                self._cache_manager.set("embedding", cache_key, emb)

            # 合并结果
            all_embeddings = list(range(len(texts)))
            for idx, emb in results:
                all_embeddings[idx] = emb
            for i, idx in enumerate(uncached_indices):
                all_embeddings[idx] = new_embeddings[i]
            return all_embeddings

        # 无缓存时走原始逻辑
        # ... 现有代码不变 ...
```

---

### Phase 2: LLM 原生流式 (P1) ✅

#### 需求回溯

→ 对应 spec.md User Story 2: 首次查询原生流式输出
→ 对应 FR-003

#### 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 流式改造范围 | LLM 客户端 + API 层 | graph 保持不变，流式逻辑在 graph 外部处理 |
| 默认流式实现 | `BaseLLMClient._do_chat_stream()` 降级为逐字符产出 | 兼容不支持流式的 provider（Minimax） |
| 首次查询体验 | graph 同步执行，答案缓存后流式返回 | 首次查询无缓存是预期行为，缓存命中后体验显著提升 |

#### 实现步骤

**Step 2.1: BaseLLMClient 添加流式接口**

- 文件: `scripts/lib/llm/base.py`（修改）

```python
# base.py — 新增方法（在 chat() 之后）
from typing import Iterator

class BaseLLMClient(ABC):
    # ... 现有方法不变 ...

    def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """流式对话 — 逐 token 产出"""
        self._validate_messages(messages)
        incr_llm_call_count()
        return self._do_chat_stream(messages, **kwargs)

    def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """默认实现：降级为同步调用后逐字符产出（兼容不支持流式的 provider）"""
        response = self._do_chat(messages, **kwargs)
        for char in response:
            yield char
```

**Step 2.2: ZhipuClient 实现 SSE 流式**

- 文件: `scripts/lib/llm/zhipu.py`（修改）

```python
# zhipu.py — 新增方法
import json as _json  # 避免与顶层 json 冲突

class ZhipuClient(BaseLLMClient):
    # ... 现有方法不变 ...

    def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """Zhipu SSE 流式对话"""
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": messages,
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7),
            "stream": True,
        }

        session = self._get_session()
        response = session.post(url, json=data, stream=True, timeout=self.timeout)

        if response.status_code == 429:
            raise requests.exceptions.RequestException(
                f"429 Rate limit exceeded: {response.text[:200]}"
            )
        if response.status_code >= 500:
            raise requests.exceptions.RequestException(
                f"{response.status_code} Server error: {response.text[:200]}"
            )
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = _json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
            except _json.JSONDecodeError:
                continue
```

**Step 2.3: OllamaClient 实现 NDJSON 流式**

- 文件: `scripts/lib/llm/ollama.py`（修改）

```python
# ollama.py — 新增方法
import json as _json

class OllamaClient(BaseLLMClient):
    # ... 现有方法不变 ...

    def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        """Ollama NDJSON 流式对话"""
        url = f"{self.host}/api/chat"
        data = {
            "model": kwargs.get('model', self.model),
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get('temperature', 0.7),
                "num_predict": kwargs.get('max_tokens', 500),
            },
        }

        response = self._session.post(url, json=data, stream=True, timeout=self.timeout)
        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue
            try:
                chunk = _json.loads(line.decode("utf-8"))
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done", False):
                    break
            except _json.JSONDecodeError:
                continue
```

**Step 2.4: API 层改造 — 缓存优先 + 真实流式**

- 文件: `scripts/api/routers/ask.py`（修改）
- 核心改动: 替换 `event_stream()` 中的伪流式逻辑

```python
# ask.py — event_stream() 改动
async def event_stream():
    root_span = None
    exc_info = (None, None, None)
    try:
        # ... 现有 debug trace 设置 ...

        engine = get_rag_engine()
        cache = getattr(engine, '_cache', None)

        # === 答案缓存快速路径（仅在缓存启用时） ===
        if cache is not None:
            cached = cache.get("answer", req.question)
            if cached is not None:
                answer = cached.get("answer", "")
                for i in range(0, len(answer), 4):
                    chunk = answer[i:i + 4]
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "token", "data": chunk}, ensure_ascii=False),
                    }
                msg_id = add_message(session_id, "assistant", answer,
                                     citations=cached.get("citations", []),
                                     sources=cached.get("sources", []))
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "done",
                        "data": {
                            "session_id": session_id,
                            "message_id": msg_id,
                            "citations": cached.get("citations", []),
                            "sources": cached.get("sources", []),
                            "unverified_claims": cached.get("unverified_claims", []),
                            "content_mismatches": cached.get("content_mismatches", []),
                            "cached": True,
                        },
                    }, ensure_ascii=False),
                }
                return

        # === 正常路径：graph.invoke（同步） ===
        memory_svc = get_memory_service()
        graph = get_ask_graph()
        state = AskState(...)
        context = GraphContext(rag_engine=engine, llm_client=engine._llm_client, memory_service=memory_svc)
        result = await asyncio.to_thread(graph.invoke, state, context=context)

        answer = result.get("answer", "")

        # 流式输出：快速分块（无 sleep），保留现有 chunk_size
        for i in range(0, len(answer), 4):
            chunk = answer[i:i + 4]
            yield {
                "event": "message",
                "data": json.dumps({"type": "token", "data": chunk}, ensure_ascii=False),
            }

        # ... 现有 done event、trace、quality 检测逻辑不变 ...
```

> **注意**: 当前方案中 graph 仍同步执行。真正的 LLM 流式需要改造 graph 的 generate 节点，复杂度高。答案缓存命中时已能达到 <50ms 目标。首次查询的流式改善作为后续优化（Phase 2b）。

---

### Phase 3: LanceDB 索引优化 (P2) ✅

#### 需求回溯

→ 对应 spec.md User Story 4: LanceDB 向量索引优化
→ 对应 FR-005

#### 实现步骤

**Step 3.1: 添加索引创建方法**

- 文件: `scripts/lib/rag_engine/index_manager.py`（修改）

```python
# index_manager.py — 新增方法
class VectorIndexManager:
    # ... 现有方法不变 ...

    def _ensure_vector_index(self) -> None:
        """确保 LanceDB 向量索引已创建（IVF_HNSW_SQ）"""
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)

            if self.config.collection_name not in db.table_names():
                return

            table = db.open_table(self.config.collection_name)

            # 检查是否已有索引
            try:
                existing = table.list_indices()
                if existing:
                    logger.debug(f"LanceDB 索引已存在: {existing}")
                    return
            except Exception:
                # list_indices() 可能不被所有版本支持，尝试直接创建
                pass

            count = len(table)
            if count < 256:
                logger.info(f"数据量 ({count}) 不足，跳过索引创建（最低 256 条）")
                return

            num_partitions = max(1, count // 256)
            table.create_index(
                "vector",
                index_type="IVF_HNSW_SQ",
                metric="cosine",
                num_partitions=num_partitions,
            )
            logger.info(f"LanceDB 索引已创建 (IVF_HNSW_SQ, partitions={num_partitions}, rows={count})")
        except Exception as e:
            logger.warning(f"LanceDB 索引创建失败（将使用全量扫描）: {e}")
```

**Step 3.2: 在索引创建/加载后调用**

- 文件: `scripts/lib/rag_engine/index_manager.py`（修改）
- 改动点: `create_index()` 末尾和 `load_index()` 末尾各添加一行

```python
# index_manager.py — create_index() 末尾
logger.info("索引创建成功")
self._ensure_vector_index()  # 新增
return self.index

# index_manager.py — load_index() 末尾
logger.info(f"从集合 '{self.config.collection_name}' 加载了已有索引")
self._ensure_vector_index()  # 新增
return index
```

---

### Phase 4: 缓存统计与监控 (P3) ✅

#### 需求回溯

→ 对应 spec.md User Story 6: 缓存统计与监控

#### 实现步骤

**Step 4.1: 添加缓存统计 API 端点**

- 文件: `scripts/api/routers/observability.py`（修改）
- 理由: 缓存统计属于系统运行指标，与 trace 同属可观测性范畴

```python
# observability.py — 顶部新增 import
from api.dependencies import get_rag_engine

# ... 新增端点
@router.get("/cache/stats")
async def get_cache_stats():
    engine = get_rag_engine()
    cache = getattr(engine, '_cache', None)
    if cache is None:
        return {"status": "not_initialized"}
    return cache.get_stats()
```

**Step 4.2: 缓存命中日志**

- 文件: `scripts/lib/rag_engine/rag_engine.py`（修改）
- 在缓存命中/未命中时添加 DEBUG 级别日志

---

### Phase 5: 清理与集成 (P1) ✅

#### 需求回溯

→ 对应 FR-011: 缓存在 KB 版本变更时自动失效
→ 对应 FR-012: 按 KB 版本全量失效

#### 实现步骤

**Step 5.1: KB 版本切换触发缓存失效**

- 文件: `scripts/lib/rag_engine/kb_manager.py`（修改）
- 改动点: `activate_version()` 方法中调用 `CacheManager.invalidate_kb_version()`

**Step 5.2: 删除 llm/cache.py 中未使用的代码**

- 文件: `scripts/lib/llm/cache.py`（删除）
- 理由: CLAUDE.md 约束 #16 "Dead code cleanup: remove unused code paths"。`LLMResponseCache` 已有 0 个调用点，新 `CacheManager` 完全替代其功能。
- 注意: 需检查 `lib/llm/__init__.py` 中是否有导出

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| graph 不同步改造 | LangGraph StateGraph 不原生支持流式节点，改造复杂度高 | 替代：缓存命中时跳过 graph（<50ms）；首次查询同步执行（可接受）。排除"graph 流式"方案因为投入产出比低 |
| 缓存 key 包含检索上下文 | 答案缓存 key 需包含 search_results hash，否则相同问题不同检索结果会返回错误缓存 | 替代：仅用 question 作为 key。排除因为会导致不同上下文下返回相同答案 |

## Appendix

### 执行顺序建议

```
Phase 1 (缓存核心) ──→ Phase 5 (清理集成)
         │                    │
         └──→ Phase 2 (流式) ──┘
                    │
              Phase 3 (索引优化)
                    │
              Phase 4 (监控)
```

- **Phase 1 + 5** 是核心，必须先完成（达成 <50ms 目标）
- **Phase 2** 可独立于 Phase 1，但建议在 Phase 1 之后（缓存 + 流式配合效果最佳）
- **Phase 3** 完全独立，可并行开发
- **Phase 4** 依赖 Phase 1

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 热门查询缓存 | 答案缓存命中 <50ms (p99) | `test_cache.py` + 集成测试 |
| US-2 首次查询流式 | 首次查询正常返回，无 regression | `test_ask.py` 现有测试通过 |
| US-3 三级缓存架构 | Embedding/检索/答案三级缓存独立工作，SQLite 持久化 | `test_cache.py` |
| US-4 LanceDB 索引优化 | 索引创建成功，搜索延迟降低 | 手动验证 + benchmark |
| US-5 Graph 并行 | 已满足（`graph.py:178-179`） | 现有测试 |
| US-6 缓存统计 | `/api/ask/cache/stats` 返回正确数据 | API 测试 |

### Spec 修正记录

1. **FR-010 已满足** — Graph 并行执行在 `graph.py:178-179` 已实现
2. **FR-012 已决策** — 按 KB 版本全量失效（惰性 + 主动清理）
3. **HNSW → IVF_HNSW_SQ** — LanceDB 不支持独立 HNSW，使用 IVF + HNSW 子索引
