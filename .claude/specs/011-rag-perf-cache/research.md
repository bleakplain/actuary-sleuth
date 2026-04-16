# RAG 性能优化 — 技术调研报告

生成时间: 2026-04-15
源规格: .claude/specs/011-rag-perf-cache/spec.md

## 执行摘要

当前 RAG 系统的主要瓶颈集中在：(1) 无缓存层，每次查询都需完整执行 Embedding → 检索 → Rerank → 生成链路；(2) LLM 调用为同步阻塞，API 层使用伪流式（`asyncio.sleep(0.01)` + 4字符分块）；(3) LanceDB 无索引优化，向量搜索为全量扫描。好消息是：`LLMResponseCache` 已实现但未接入，LangGraph 中 `retrieve_memory` 和 `rag_search` 已是并行执行（非串行），前端已完全支持真实流式。推荐采用"复用现有 cache.py 为基础扩展为三级缓存 + Zhipu SSE 原生流式 + LanceDB IVF_PQ 索引"的方案，预估热门查询可从 5-9s 降至 <50ms。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 三级缓存 | `lib/llm/cache.py` | 已实现 LLM 纯内存缓存，但未接入 RAG 流程 |
| FR-002 SQLite+内存存储 | `lib/common/database.py`, `lib/common/connection_pool.py` | SQLite 连接池已就绪（WAL 模式，pool_size=5） |
| FR-003 原生流式 | `lib/llm/base.py`, `lib/llm/zhipu.py` | 无流式接口定义，Zhipu API 支持但未实现 |
| FR-004 接入 LLM 缓存 | `lib/llm/cache.py` → `lib/rag_engine/rag_engine.py` | 缓存代码完整，0 个调用点 |
| FR-005 LanceDB 索引优化 | `lib/rag_engine/index_manager.py` | 仅使用 `LanceDBVectorStore` 默认配置，无索引参数 |
| FR-006 TTL/LRU | `lib/llm/cache.py` | TTL（lazy expiry）和 LRU（按 timestamp 淘汰）已实现 |
| FR-007 线程安全 | `lib/llm/cache.py`, `lib/common/connection_pool.py` | `threading.RLock` + 双检锁单例 |
| FR-010 Graph 并行 | `lib/rag_engine/graph.py:178-179` | **已实现** — `START` 同时连 `retrieve_memory` 和 `rag_search` |
| FR-011 KB 版本失效 | `lib/rag_engine/kb_manager.py` | KB 版本管理已实现（SQLite `kb_versions` 表） |

### 1.2 可复用组件

| 组件 | 位置 | 复用方式 |
|------|------|---------|
| `LLMResponseCache` | `lib/llm/cache.py:16-157` | 核心缓存逻辑可复用，需扩展 SQLite 持久层和 Embedding/检索缓存 |
| `get_cache()` 单例 | `lib/llm/cache.py:163-181` | 双检锁模式可复用于新的缓存管理器 |
| `SQLiteConnectionPool` | `lib/common/connection_pool.py:18-143` | 缓存 SQLite 存储可直接使用现有连接池 |
| `ThreadLocalSettings` | `lib/rag_engine/rag_engine.py:77-114` | 线程本地 LlamaIndex Settings 管理 |
| `trace_span` | `lib/llm/trace.py` | 缓存命中/未命中可纳入 trace |
| `_run_with_ctx` | `lib/rag_engine/retrieval.py:23-25` | 子线程 contextvars 复制 |
| `KBManager` | `lib/rag_engine/kb_manager.py` | KB 版本切换时触发缓存失效 |

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/rag_engine/cache.py` | **新增** | 三级缓存统一管理（Embedding/检索/答案） |
| `lib/llm/cache.py` | **修改** | 扩展为支持 SQLite 持久化，或被新模块替代 |
| `lib/llm/base.py` | **修改** | 添加 `stream_chat()` 抽象方法 |
| `lib/llm/zhipu.py` | **修改** | 实现 `_do_chat_stream()` SSE 流式调用 |
| `lib/llm/ollama.py` | **修改** | 启用 NDJSON 流式（当前 `"stream": False`） |
| `lib/rag_engine/rag_engine.py` | **修改** | `_do_ask()` 集成缓存检查/写入，添加 `stream_ask()` |
| `lib/rag_engine/graph.py` | **修改** | `generate()` 节点支持流式输出 |
| `lib/rag_engine/index_manager.py` | **修改** | 知识库构建后创建 LanceDB 优化索引 |
| `lib/rag_engine/llamaindex_adapter.py` | **修改** | `ZhipuEmbeddingAdapter` 添加 Embedding 缓存 |
| `api/routers/ask.py` | **修改** | 替换伪流式为真实 LLM 流式，集成缓存命中快速返回 |

---

## 二、技术选型研究

### 2.1 缓存架构方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 统一 CacheManager + 三层表** | 代码简洁，统一管理，复用 `LLMResponseCache` 的 key 生成和线程安全逻辑 | 单一 SQLite 文件，表结构需设计好 | **推荐** |
| B: 独立 EmbeddingCache + RetrievalCache + AnswerCache | 职责分离，可独立配置 TTL | 代码重复多，维护成本高 | 不推荐 |
| C: 使用 cachetools 库 | 功能丰富（TTLCache, LRUCache），社区成熟 | 新增外部依赖，与现有 `LLMResponseCache` 重复 | 不推荐（已有实现） |

**选择方案 A**：创建统一的 `CacheManager`，内部用三个命名空间（`embedding`/`retrieval`/`answer`）管理不同类型缓存，底层共用内存 + SQLite 两级存储。

### 2.2 流式输出方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: LLM 客户端原生流式** | 真正的 TTFT <200ms，用户体验最佳 | 需改动 LLM 客户端层和 graph | **推荐** |
| B: 保持伪流式，仅优化生成速度 | 改动最小 | 无法改善首字感知时间 | 不推荐 |
| C: WebSocket 替代 SSE | 双向通信 | 前端需大改，当前 SSE 已够用 | 不推荐 |

**选择方案 A**：Zhipu API 原生支持 SSE 流式（`stream: true`），仅需在 `ZhipuClient` 中添加 `_do_chat_stream()` 方法。

### 2.3 LanceDB 索引方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **IVF_HNSW_SQ** | 最佳召回/延迟平衡，LanceDB 推荐 | 构建时间较长 | **推荐** |
| IVF_PQ | 内存占用最小 | 召回率略低，需调 `num_sub_vectors` | 备选 |
| 无索引（当前） | 零配置 | 大数据集性能差 | 当前状态 |

**选择 IVF_HNSW_SQ**：LanceDB 官方推荐的默认索引类型，适合当前数据规模（万级 chunk），在召回率和延迟间取得最佳平衡。

### 2.4 依赖分析

| 依赖 | 当前版本 | 用途 | 兼容性 |
|------|---------|------|--------|
| `lancedb` | 已安装 | 向量索引优化 | IVF_HNSW_SQ 为内置功能，无需升级 |
| `requests` | 已安装 | Zhipu SSE 流式（`stream=True`） | `requests.Session.post(stream=True)` 原生支持 |
| `sqlite3` | 内置 | 缓存持久化 | 无额外依赖 |
| `sse-starlette` | 已安装 | API 层 SSE 推送 | 已在使用，无需改动 |
| `llama-index` | 已安装 | 向量索引管理 | 需确认 `LanceDBVectorStore` 是否支持 `create_index()` |

---

## 三、数据流分析

### 3.1 现有数据流（完整查询链路）

```
用户请求 POST /api/ask/chat
    │
    ▼
ask.py:event_stream()                              # ask.py:109
    │
    ├── graph.invoke(state, context=context)        # ask.py:131 (asyncio.to_thread)
    │       │
    │       ├── [并行] retrieve_memory()            # graph.py:50  ← 已并行
    │       │       └── memory_svc.search()         # graph.py:57
    │       │
    │       ├── [并行] rag_search()                 # graph.py:86  ← 已并行
    │       │       └── engine.search()             # graph.py:90
    │       │           └── _hybrid_search()        # rag_engine.py:378
    │       │               ├── [并行] vector_search()   # retrieval.py:41
    │       │               │   └── index.as_retriever().retrieve()
    │       │               │       └── Embedding API 调用  ← 无缓存！200-500ms
    │       │               │
    │       │               ├── [并行] bm25_index.search()  # retrieval.py:132
    │       │               │   └── 内存计算 10-50ms (已缓存)
    │       │               │
    │       │               └── reciprocal_rank_fusion()    # fusion.py:24
    │       │
    │       ├── generate()                         # graph.py:95
    │       │   ├── llm.chat(messages)             # graph.py:123 ← 阻塞 2-5s！
    │       │   └── parse_citations()               # graph.py:128
    │       │
    │       ├── extract_memory()                    # graph.py:144
    │       └── update_user_profile()               # graph.py:160
    │
    ├── [伪流式] 4字符分块 + sleep(0.01)           # ask.py:146-155 ← 人为延迟！
    │
    └── yield done event                            # ask.py:191-194
```

### 3.2 新增/变更的数据流（优化后）

```
用户请求 POST /api/ask/chat
    │
    ▼
ask.py:event_stream()
    │
    ├── CacheManager.get_answer(question)           # [新增] 答案缓存检查
    │   ├── [命中] → 直接流式返回缓存答案            # < 50ms
    │   └── [未命中] ↓
    │
    ├── graph.invoke(state, context=context)
    │       │
    │       ├── [并行] retrieve_memory()            # 不变
    │       │
    │       ├── [并行] rag_search()                 # 不变
    │       │   └── _hybrid_search()
    │       │       ├── CacheManager.get_embedding() # [新增] Embedding 缓存
    │       │       │   ├── [命中] → 跳过 API 调用
    │       │       │   └── [未命中] → API 调用 → CacheManager.set_embedding()
    │       │       │
    │       │       ├── CacheManager.get_retrieval() # [新增] 检索结果缓存
    │       │       │   ├── [命中] → 跳过向量+BM25搜索
    │       │       │   └── [未命中] → 正常检索 → CacheManager.set_retrieval()
    │       │       │
    │       │       └── [reranker 不缓存]
    │       │
    │       └── generate() → [流式]                 # [变更] 原生 LLM 流式
    │           ├── llm.stream_chat(messages)       # 新增方法
    │           │   └── Zhipu SSE: stream=True      # 真实 token 流
    │           └── parse_citations()               # 流结束后解析
    │
    ├── [真实流式] 逐 token SSE 推送                # [变更] 替换伪流式
    │
    ├── CacheManager.set_answer(question, answer)   # [新增] 缓存答案
    │
    └── yield done event
```

### 3.3 关键数据结构

```python
# 三级缓存的统一键值结构
@dataclass(frozen=True)
class CacheKey:
    """缓存键 — 基于 SHA-256 哈希"""
    namespace: str       # "embedding" | "retrieval" | "answer"
    hash_value: str      # SHA-256(input)

# 缓存条目（SQLite 持久化结构）
@dataclass
class CacheEntry:
    key: str             # namespace:hash_value
    value: bytes         # 序列化的缓存值（JSON 或 pickle）
    created_at: float    # 创建时间戳
    accessed_at: float   # 最后访问时间戳
    hit_count: int       # 命中次数
    ttl: int             # 过期时间（秒）
    kb_version: str      # 关联的知识库版本（用于失效）

# 流式输出块
@dataclass(frozen=True)
class StreamChunk:
    content: str         # token 文本
    is_final: bool       # 是否结束标记
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] **Zhipu SSE 流式可靠性** — 验证 `requests.post(url, json=data, stream=True).iter_lines()` 能正确解析 Zhipu SSE 格式（`data: {...}\n\n`），包括 `[DONE]` 信号处理
- [ ] **LanceDB IVF_HNSW_SQ 通过 LlamaIndex** — 验证 `LanceDBVectorStore` 创建的表能否通过 `lancedb.connect().open_table().create_index()` 直接添加索引，还是需要在 LlamaIndex 之外管理
- [ ] **Embedding 缓存序列化效率** — 验证 float array（1024维）序列化为 JSON 的存储大小（预估单条 ~8KB），SQLite BLOB vs TEXT 存储效率对比
- [ ] **Graph 流式与 LangGraph 兼容性** — 验证 LangGraph 的 `generate` 节点能否产出流式结果，还是需要将流式逻辑移到 graph.invoke 之外
- [ ] **缓存命中时的 citation 处理** — 缓存的答案包含 `[来源X]` 引用，但 `citations` 列表需要与 `sources` 重新关联

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Zhipu SSE 连接中断 | 中 | 流式输出不完整 | 添加超时和重试，前端 error 事件处理已就绪 |
| SQLite 缓存表膨胀 | 低 | 磁盘占用过大 | LRU 淘汰 + TTL 过期 + 定期清理过期条目 |
| 缓存击穿（cache stampede） | 低 | 并发请求同时穿透缓存 | 使用 `threading.Lock` 做 singleflight |
| Embedding 缓存 key 碰撞 | 极低 | 语义不同但 hash 相同 | SHA-256 碰撞概率可忽略 |
| LanceDB 索引构建耗时 | 低 | KB 构建时间增加 | 仅在 `force_rebuild` 或新版本创建时构建 |
| Graph 流式改造复杂度高 | 中 | 开发周期延长 | 备选方案：流式逻辑放在 graph 外部（API 层直接调用 `llm.stream_chat`） |
| KB 版本切换缓存失效遗漏 | 中 | 返回过期数据 | `CacheEntry` 存储 `kb_version`，查询时校验 |

---

## 五、各需求实现路径详析

### 5.1 三级缓存实现路径

**核心设计：统一 `CacheManager`，三个命名空间**

```python
# lib/rag_engine/cache.py（新增）
class CacheManager:
    """三级缓存管理器：Embedding / 检索结果 / 答案缓存"""

    def __init__(self, db_path: str, default_ttl: int = 3600, max_memory_entries: int = 500):
        # L1: OrderedDict（Python 内置，线程安全需加锁）
        self._memory_cache: Dict[str, tuple] = {}
        self._lock = threading.RLock()
        # L2: SQLite（复用 connection_pool）
        self._db_path = db_path

    def get(self, namespace: str, key_text: str) -> Optional[Any]: ...
    def set(self, namespace: str, key_text: str, value: Any, ttl: int = ...) -> None: ...
    def invalidate_kb_version(self, kb_version: str) -> int: ...
    def get_stats(self) -> Dict[str, Any]: ...
```

**Embedding 缓存集成点**：
- `ZhipuEmbeddingAdapter._get_embeddings()` (`llamaindex_adapter.py:130-155`) — 在 API 调用前后加缓存
- `JinaEmbeddingAdapter._get_query_embedding()` (`llamaindex_adapter.py:222-224`) — 同理
- Key = `sha256(model:text)`，Value = `List[float]`（JSON 序列化）

**检索结果缓存集成点**：
- `RAGEngine._hybrid_search()` (`rag_engine.py:378-425`) — 在调用 `hybrid_search()` 前后加缓存
- Key = `sha256(normalized_query + filters_json)`
- Value = `List[Dict]`（检索结果列表，JSON 序列化）
- 注意：需包含 reranker 之前的结果（reranker 可能有随机性）

**答案缓存集成点**：
- `RAGEngine._do_ask()` (`rag_engine.py:245-306`) 或 API 层 `ask.py:109`
- Key = `sha256(question + search_results_hash)`（包含检索上下文）
- Value = 完整 answer 字符串 + citations + sources
- 这是达成 <50ms 目标的关键路径

**SQLite 表结构**：
```sql
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
CREATE INDEX idx_cache_namespace ON cache_entries(namespace);
CREATE INDEX idx_cache_expires ON cache_entries(namespace, created_at + ttl);
```

### 5.2 原生流式实现路径

**BaseLLMClient 改造**（`lib/llm/base.py`）：
```python
from typing import Iterator
from abc import abstractmethod

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

**ZhipuClient 流式实现**（`lib/llm/zhipu.py`）：
```python
def _do_chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
    url = f"{self.base_url}/chat/completions"
    data = {
        "model": kwargs.get('model', self.model),
        "messages": messages,
        "temperature": kwargs.get('temperature', 0.1),
        "max_tokens": kwargs.get('max_tokens', 8192),
        "top_p": kwargs.get('top_p', 0.7),
        "stream": True,  # 启用流式
    }
    session = self._get_session()
    response = session.post(url, json=data, stream=True, timeout=self.timeout)
    response.raise_for_status()

    for line in response.iter_lines():
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        chunk = json.loads(data_str)
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        content = delta.get("content", "")
        if content:
            yield content
```

**API 层改造**（`api/routers/ask.py:109-229`）：

核心变更在 `event_stream()` 内部：

```python
async def event_stream():
    # 1. 答案缓存检查
    cached = cache_manager.get("answer", req.question)
    if cached:
        # 模拟流式返回缓存答案（快速分块，无 sleep）
        answer_data = json.loads(cached)
        for chunk in _chunk_string(answer_data["answer"], 4):
            yield {"event": "message", "data": json.dumps({"type": "token", "data": chunk})}
        yield {"event": "message", "data": json.dumps({"type": "done", "data": answer_data["meta"]})}
        return

    # 2. 非缓存路径：检索阶段（同步）
    result = await asyncio.to_thread(graph.invoke, state, context=context)

    # 3. 流式生成阶段
    answer_parts = []
    for token in llm_client.stream_chat(messages):
        answer_parts.append(token)
        yield {"event": "message", "data": json.dumps({"type": "token", "data": token})}

    answer = "".join(answer_parts)
    # 4. 解析 citations（流结束后）
    attribution = parse_citations(answer, included_sources)
    # 5. 缓存答案
    cache_manager.set("answer", req.question, answer_data)
    # 6. yield done event
```

**Graph 流式改造的备选方案**：

LangGraph 的 `StateGraph` 设计为节点间传递完整状态，不原生支持流式输出。推荐方案：

**方案 A（推荐）：将 LLM 流式调用从 graph 中移出**
- `generate()` 节点仍做同步调用（保持 graph 简单）
- API 层在 `graph.invoke()` 之前检查缓存，命中则跳过 graph
- 缓存未命中时，graph 正常执行（同步），答案结果缓存
- 后续请求直接从缓存流式返回
- **优点**：graph 改动最小，缓存命中路径 <50ms
- **缺点**：首次查询仍为同步（但这是可接受的，首次查询无缓存是预期行为）

**方案 B：graph 节点改为异步生成器**
- 改造复杂度高，LangGraph 对流式节点的支持有限
- 不推荐

### 5.3 LanceDB 索引优化路径

**当前问题**：`index_manager.py:46-49` 创建 `LanceDBVectorStore` 时无索引参数。

**实现方式**：
```python
# index_manager.py — 在 create_index() 或 load_index() 后添加
def _ensure_vector_index(self):
    """确保 LanceDB 向量索引已创建"""
    try:
        import lancedb
        db = lancedb.connect(self.config.vector_db_path)
        table = db.open_table(self.config.collection_name)

        # 检查是否已有索引
        existing_indexes = table.list_indices()
        if existing_indexes:
            return

        # 创建 IVF_HNSW_SQ 索引
        count = len(table)
        num_partitions = max(1, count // 256)
        table.create_index(
            "vector",
            index_type="IVF_HNSW_SQ",
            metric="cosine",
            num_partitions=num_partitions,
        )
        logger.info(f"LanceDB 索引已创建 (IVF_HNSW_SQ, partitions={num_partitions})")
    except Exception as e:
        logger.warning(f"LanceDB 索引创建失败: {e}")
```

**集成点**：
- `create_index()` 方法末尾（`index_manager.py:64` 之后）调用 `_ensure_vector_index()`
- `load_index()` 方法末尾（`index_manager.py:90` 之后）调用 `_ensure_vector_index()`

---

## 六、关键发现与修正

### 6.1 spec.md 中的修正

1. **FR-010 "Graph 节点并行执行"** — 实际上 `graph.py:178-179` 已经实现了 `retrieve_memory` 和 `rag_search` 的并行执行（`START` 同时连两个节点）。**无需修改**。spec 中应将此标记为"已满足"。

2. **User Story 2 "首次查询原生流式"** — 需要明确：原生流式的价值主要在于改善用户感知，对端到端延迟的实际影响有限（检索 200-500ms + LLM 生成 2-5s，流式只是把 LLM 生成的 2-5s 变成渐进式展示）。真正的 <50ms 需要靠答案缓存命中。

3. **"HNSW 索引调优"** — LanceDB 不支持独立 HNSW 索引，仅支持 `IVF_HNSW_SQ`（IVF + HNSW 子索引）。需更新 spec 中的措辞。

### 6.2 性能预估（优化后）

| 场景 | 当前耗时 | 优化后耗时 | 优化手段 |
|------|---------|-----------|---------|
| 热门查询（答案缓存命中） | 4-9s | **< 50ms** | 答案缓存直接返回 |
| 重复查询（Embedding 缓存命中） | 4-9s | **3-8s** | 节省 200-500ms Embedding 调用 |
| 重复查询（检索缓存命中） | 4-9s | **2-5s** | 跳过向量+BM25 检索 |
| 首次查询（流式） | 4-9s（阻塞） | **~2s TTFT** | 原生流式改善感知 |
| 首次查询（索引优化） | 4-9s | **3-7s** | 向量检索提速 |

### 6.3 缓存失效策略建议

针对 spec.md 中的 FR-012（NEEDS CLARIFICATION），推荐：

**按 KB 版本全量失效**（而非按文档粒度）：
- 理由：KB 版本是原子更新（`kb_versions` 表管理），不存在单文档更新场景
- 实现：`CacheEntry` 存储 `kb_version` 字段，`CacheManager.get()` 时校验当前活跃版本
- 失效方式：惰性失效（查询时检查）+ KB 版本切换时主动清理

---

## 七、参考实现

- [Zhipu AI 流式文档](https://docs.bigmodel.cn/cn/guide/capabilities/streaming) — SSE 流式协议和 Python 示例
- [LanceDB Vector Indexes](https://docs.lancedb.com/indexing/vector-index) — IVF_HNSW_SQ 索引创建和参数调优
- [cachetools TTLCache](https://cachetools.readthedocs.io/) — 参考其 TTL + LRU 实现模式（但本项目选择自研以避免新依赖）
- [FastAPI SSE with sse-starlette](https://sse-starlette.readthedocs.io/) — 当前项目已使用的 SSE 库
