# RAG 记忆增强与 Agent 框架 - 技术调研报告

生成时间: 2026-04-07
源规格: specs/004-rag-memory-agent/spec.md

## 执行摘要

**技术方案**: LangGraph（工作流编排）+ Mem0（记忆管理）+ LanceDB（向量存储，通过 LangChain 桥接）。

LangGraph 通过 `context_schema` 注入现有 RAGEngine/LLMClient 实例，Mem0 负责记忆生命周期（事实提取、冲突检测 ADD/UPDATE/DELETE/NOOP），LanceDB（项目已有）作为向量存储后端，通过 `langchain_community.vectorstores.LanceDB` 桥接传入 Mem0。Mem0 的 LLM 通过 OpenAI 兼容接口接入 Zhipu glm-4-flash，Embedding 通过 `provider: "langchain"` 复用项目现有的 `JinaEmbeddingAdapter`（Jina v5, 1024 维），与 RAG 引擎完全统一。

**记忆架构**：采用三层分类（语义记忆/情节记忆/程序性记忆）+ 双层时效（短期/长期）架构：
- **语义记忆**（共享知识）= 现有 RAG 引擎的法规知识库，所有用户共享，按内容语义检索
- **情节记忆**（用户专属历史）= Mem0 管理，按 user_id 隔离，每次对话提取→冲突检测→持久化
- **程序性记忆**（审核流程规则）= 固化在 LangGraph 节点和 System Prompt 中，不参与检索

记忆模块与 RAG 检索模块是**并行双检索源**关系：RAG 提供静态法规知识（"世界知道什么"），记忆提供动态用户上下文（"我知道关于这个用户什么"），两路结果融合后一起喂给 LLM 生成回答。

**验证结论**：langchain-community、langgraph、lancedb 均已安装（零新增包），Zhipu API 与 Mem0 openai provider 完全兼容，LangGraph context_schema 已 GA 稳定，Mem0 langchain embedder provider 支持传入自定义 embeddings 实例。需处理的问题：(1) Mem0 不原生支持 TTL 和活跃度衰减，需自建。

---

## 一、现有代码分析

### 1.1 需求与模块映射

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 记忆检索注入 | `api/routers/ask.py:113` | **需修改** — `engine.ask(question)` 仅传 question，无记忆上下文 |
| FR-002 对话记忆提取 | `api/routers/ask.py:177-197` | **需修改** — 后处理阶段可并行加入记忆提取 |
| FR-003 Mem0 冲突管理 | 无 | **需新增** |
| FR-004 LangGraph 编排 | `lib/rag_engine/rag_engine.py:236-301` | **需修改** — `_do_ask()` 线性流程重构为图节点 |
| FR-005 用户隔离 | `api/database.py:16-31` | **需新增** — conversations 表无 user_id |
| FR-006 TTL 过期 | 无 | **需新增** — Mem0 不原生支持 |
| FR-007 管理 API | 无 | **需新增** |
| FR-008 降级运行 | 无 | **需新增** |
| FR-009 现有 LLM | `lib/llm/base.py`, `factory.py` | **可复用** |
| FR-010 现有存储 | `api/database.py`, `lib/rag_engine/index_manager.py` | **可复用** — LanceDB + SQLite |
| FR-011 可观测性 | `lib/llm/trace.py` | **可复用** |

### 1.2 可复用组件

- **`RAGEngine.search()`** (`rag_engine.py:344`): LangGraph 检索节点
- **`RAGEngine._build_qa_prompt()`** (`rag_engine.py:311`): 生成节点 prompt 构建
- **`RAGEngine._SYSTEM_PROMPT`** (`rag_engine.py:37-47`): 系统 prompt
- **`BaseLLMClient.chat()`** (`llm/base.py:44`): LLM 生成节点
- **`LLMClientFactory.create_qa_llm()`** (`llm/factory.py:28`): 记忆提取 LLM
- **`trace_span`** (`llm/trace.py:129`): 节点追踪
- **`asyncio.to_thread()`** (`ask.py:113`): sync graph 桥接模式
- **`_migrate_db()`** (`database.py:187`): 数据库迁移模式
- **`_auto_classify_loop()`** (`app.py:92`): 后台任务模式

### 1.3 现有数据流

```
POST /api/ask/chat
  → create_conversation() + add_message(user)
  → engine.ask(question) via asyncio.to_thread
      → _hybrid_search(question) → vector + bm25 + rrf + rerank
      → _build_qa_prompt(config, question, results)
      → llm_client.chat([system, user_prompt])   ← 仅 2 条 messages，无历史/记忆
      → parse_citations(answer)
  → SSE streaming (4-char chunks, simulated)
  → add_message(assistant) + persist_trace() + auto quality detection
```

**关键发现**: `engine.ask(question)` 仅传 question 字符串，LLM messages 始终只有 2 条。

### 1.4 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/memory/__init__.py` | **新增** | 模块导出 |
| `lib/memory/service.py` | **新增** | `MemoryService` — Mem0 包装 + 降级 + 活跃度管理 |
| `lib/memory/config.py` | **新增** | 记忆配置（TTL 默认值、衰减参数、检索上限） |
| `lib/memory/prompts.py` | **新增** | 精算审核事实提取 prompt + 用户画像更新 prompt |
| `lib/memory/embeddings.py` | **新增** | `EmbeddingBridge` — LlamaIndex → LangChain 接口适配，无新配置 |
| `lib/rag_engine/graph.py` | **新增** | LangGraph StateGraph + 节点函数 |
| `api/routers/memory.py` | **新增** | 记忆管理 API（含用户画像查询） |
| `api/schemas/memory.py` | **新增** | 记忆 + 用户画像 Pydantic schemas |
| `api/routers/ask.py` | **修改** | chat 端点接入 LangGraph |
| `api/app.py` | **修改** | 初始化记忆服务和 LangGraph |
| `api/dependencies.py` | **修改** | 新增 `get_memory_service()`、`init_ask_graph()`、`get_ask_graph()` |
| `api/database.py` | **修改** | 新增 memory_metadata 表、user_profiles 表、conversations 加 user_id |

---

## 二、技术选型

### 2.1 LangGraph — 工作流编排

| 维度 | 说明 |
|------|------|
| **选择理由** | 生产验证最充分(47M+下载)，图编排支持条件路由/人机协作 |
| **状态定义** | `TypedDict`（LangGraph 原生类型） |
| **依赖注入** | `context_schema` + `Runtime[GraphContext]`（v1.0 GA，2025-10 稳定） |
| **Sync 模式** | sync 节点 + `graph.invoke()`，通过 `asyncio.to_thread()` 桥接 FastAPI |
| **追踪** | 节点内 `trace_span`，不引入 LangChain CallbackHandler |
| **依赖** | `langgraph>=1.0.0`（已安装 1.0.2，自动拉入 langchain-core） |

### 2.2 Mem0 — 记忆管理

| 维度 | 说明 |
|------|------|
| **选择理由** | 内建冲突检测(ADD/UPDATE/DELETE/NOOP)，自定义提取 prompt，用户隔离 |
| **LLM** | `provider: "openai"` + Zhipu `https://open.bigmodel.cn/api/paas/v4/` + `glm-4-flash`（已验证兼容） |
| **Embedding** | `provider: "langchain"` + 项目现有 `JinaEmbeddingAdapter`（见 2.3 节） |
| **向量存储** | `provider: "langchain"` + `langchain_community.vectorstores.LanceDB` → 项目现有 LanceDB |
| **TTL** | 不原生支持，通过 metadata + SQLite memory_metadata 表 + 定时清理自建 |
| **降级** | `MemoryService` 包装层，初始化失败时降级为无记忆模式 |

### 2.3 Embedding：复用项目统一配置

**配置来源**：Mem0 的 embedding 与 RAG 引擎共用 `settings.json` 的 `llm.embed` 配置，通过 `LLMClientFactory.create_embed_model()` 创建实例，不引入任何新配置项。

**接口适配**：Mem0 的 `langchain` embedder/vector_store provider 要求 LangChain `Embeddings` 接口（`embed_query()` + `embed_documents()`），项目现有 embedding 是 LlamaIndex 接口（`_get_query_embedding()` + `_get_text_embedding()`）。`EmbeddingBridge` 仅做接口方法映射，不含任何配置逻辑：

```python
# lib/memory/embeddings.py
from langchain_core.embeddings import Embeddings
from lib.llm.factory import LLMClientFactory

class EmbeddingBridge(Embeddings):
    """LlamaIndex → LangChain 接口适配，embedding 模型由 settings.json llm.embed 决定"""

    def __init__(self):
        self._adapter = LLMClientFactory.create_embed_model()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._adapter._get_text_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._adapter._get_query_embedding(text)
```

**为什么不能直接用 Mem0 的 `provider: "ollama"`**：Mem0 的 Ollama embedder 不添加 Jina v5 的 `search_query:`/`passage:` prefix，而 Jina v5 非对称检索依赖这些 prefix，缺少会导致检索质量显著下降。通过 `EmbeddingBridge` 桥接到项目现有的 `JinaEmbeddingAdapter`，prefix 由适配器自动处理。

### 2.4 LanceDB — 向量存储（通过 LangChain 桥接）

Mem0 不原生支持 LanceDB。embedder 和 vector_store 均通过 `provider: "langchain"` 桥接，共用同一个 `EmbeddingBridge` 实例。

```python
config = {
    "llm": {
        "provider": "openai",
        "config": {
            "model": "glm-4-flash",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4/",
            "temperature": 0.1,
        }
    },
    "embedder": {
        "provider": "langchain",
        "config": {
            "model": embedding_lc,  # EmbeddingBridge 实例，内部调用 LLMClientFactory.create_embed_model()
        }
    },
    "vector_store": {
        "provider": "langchain",
        "config": {
            "client": lancedb_store
        }
    },
    "custom_fact_extraction_prompt": AUDIT_FACT_EXTRACTION_PROMPT,
    "version": "v1.1",
}
memory = Memory.from_config(config)
```

### 2.5 依赖分析

| 依赖 | 版本 | 新增? | 说明 |
|------|------|-------|------|
| `langgraph` | 1.0.2 (已安装) | 否 | |
| `langchain-core` | 1.0.2 (已安装) | 否 | langgraph 自动拉入 |
| `langchain-community` | 0.4.1 (已安装) | 否 | 提供 LanceDB wrapper |
| `mem0ai` | 未安装 | **是** | 唯一需新增的包，会拉入 qdrant-client、posthog 等 |
| `lancedb` | 0.21.1 (已安装) | 否 | |

`langchain_community.vectorstores.LanceDB` 已验证可用。langchain-community 与 LlamaIndex 已验证共存无冲突。Mem0 的 `langchain` embedder provider 和 `langchain` vector_store provider 均通过 langchain-community 桥接，embedding 统一使用 Jina v5（1024 维），与 RAG 引擎共享同一向量空间。

---

## 三、数据流设计

### 3.1 记忆架构总览

```
┌─────────────────────────────────────────────────────┐
│                    用户查询                            │
└──────────┬──────────────────────┬────────────────────┘
           │                      │
     ┌─────▼─────┐         ┌──────▼──────┐
     │ 语义记忆    │         │  情节记忆     │
     │ (RAG 知识库) │         │ (Mem0 向量库) │
     │ 法规/条款    │         │ 用户专属历史   │
     │ 所有用户共享  │         │ 按 user_id 隔离│
     └─────┬─────┘         └──────┬──────┘
           │                      │
           │    ┌─────────────────┤
           │    │  程序性记忆       │
           │    │ (System Prompt)  │
           │    │ 审核流程规则      │
           │    └────────┬────────┘
           │             │
     ┌─────▼─────────────▼─────────┐
     │         LLM 生成回答          │
     └─────────────────────────────┘
```

**三种记忆类型的职责边界**：
- **语义记忆**：现有 RAG 引擎的法规知识库（LanceDB `insurance_kb` collection），由 `_hybrid_search()` 处理，本项目不改动
- **情节记忆**：Mem0 管理的长期记忆（LanceDB `memories` collection），由 `retrieve_memory` / `extract_memory` 节点处理
- **程序性记忆**：LangGraph 节点编排逻辑 + `_SYSTEM_PROMPT` 中的审核规则，不需要检索，直接注入

### 3.2 短期记忆与长期记忆

**短期记忆**（会话内）：当前会话的消息历史，通过 SQLite `messages` 表持久化，LLM 调用时保留最近 N 轮对话。当前系统已有此能力（`add_message()` 持久化），本 feature 不改动短期记忆机制。

**长期记忆**（跨会话）：通过 Mem0 + LanceDB `memories` collection 持久化。每次对话结束时自动提取值得长期保存的信息（审核结论、用户偏好、关键事实），写入 Mem0 向量库。新会话开始时通过语义检索召回相关记忆。

### 3.3 新数据流

```
POST /api/ask/chat
  → create_conversation(user_id) + add_message(user)
  → graph.invoke(state, context) via asyncio.to_thread
      → node: retrieve_memory  ─┐  并行双检索
      → node: rag_search       ─┘  retrieve_memory: Mem0.search → memory_context（情节记忆）
                                  rag_search: RAGEngine.search → search_results（语义记忆）
      → node: route            — 有结果→generate，无结果→clarify
      → node: generate         — prompt(法规+记忆+问题) + LLM → answer（融合两路输入）
      → node: extract_memory   — Mem0.add(conversation, user_id) → 情节记忆写入 [失败不阻塞]
      → node: update_profile   — 更新用户画像（偏好、关注领域）[失败不阻塞]
  → SSE streaming
  → add_message(assistant) + persist_trace() + auto quality detection
```

**并行双检索设计依据**：RAG 提供静态法规知识（"世界知道什么"），Memory 提供动态用户上下文（"我知道关于这个用户什么"）。两者相互独立，写入不同 State 字段（`search_results` / `memory_context`），无数据依赖，适合并行执行以降低延迟。参考：[Memory 与 RAG 的双检索源架构](https://mp.weixin.qq.com/s/Vc0xspNbH8UQ9Ue5EG5Ing)、[RAG 系统中的记忆增强](https://mp.weixin.qq.com/s/We7DOn_LN4LmH9Oqad99YA)。

### 3.4 关键数据结构

#### LangGraph State

```python
class AskState(TypedDict):
    question: str
    mode: str                              # "qa" | "search"（与 ChatRequest.mode 一致）
    user_id: str
    conversation_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str
    # --- 以下字段兼容 engine.ask() 返回值 ---
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]
```

#### GraphContext

```python
@dataclass
class GraphContext:
    rag_engine: RAGEngine
    llm_client: BaseLLMClient
    memory_service: MemoryService
```

#### 数据库新增

```sql
-- 记忆元数据（TTL、活跃度、软删除）
CREATE TABLE IF NOT EXISTS memory_metadata (
    mem0_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    category TEXT DEFAULT 'fact',           -- fact | preference | audit_conclusion
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    last_accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
    access_count INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_metadata(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_metadata(expires_at);

-- 用户画像（结构化概要）
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    focus_areas TEXT DEFAULT '[]',          -- JSON: ["免责条款", "等待期"]
    preference_tags TEXT DEFAULT '[]',      -- JSON: ["重疾险", "寿险"]
    audit_stats TEXT DEFAULT '{}',          -- JSON: {"total_audits": 5, "product_types": [...]}
    summary TEXT DEFAULT '',                -- LLM 生成的画像摘要
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default';
```

---

## 四、LangGraph 工作流设计

### 4.1 初始工作流（并行双检索 + 线性后处理）

```
                     ┌→ retrieve_memory ─┐
START ───────────────┤                  ├→ generate → extract_memory → update_profile → END
                     └→ rag_search ─────┘
```

`retrieve_memory` 和 `rag_search` 并行执行，两者均从 START 出发，写入不同 State 字段，无数据依赖。

### 4.2 扩展工作流（条件路由）

```
                     ┌→ retrieve_memory ─┐
START ───────────────┤                  ├→ route(passthrough) ─┬→ generate → extract_memory → update_profile → END
                     └→ rag_search ─────┘                      └→ clarify → END
```

`route` 是 passthrough 节点（返回空 dict），LangGraph 在所有入边完成后执行，此时 `search_results` 和 `memory_context` 均已写入，可正确判断路由。

### 4.3 节点函数

```python
def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆检索 — 从 Mem0 向量库中检索与当前查询相关的用户历史记忆"""
    memory_svc = runtime.context.memory_service
    with trace_span("memory_retrieve", "memory") as span:
        memories = memory_svc.search(state["question"], state["user_id"], limit=3)
        if memories:
            lines = [f"- {m['memory']} (记录于 {m['created_at'][:10]})" for m in memories]
            return {"memory_context": "\n".join(lines)}
        return {"memory_context": ""}

def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """语义记忆检索 — 从现有 RAG 知识库检索法规条款"""
    engine = runtime.context.rag_engine
    with trace_span("graph_retrieve", "rag") as span:
        results = engine.search(state["question"])
        return {"search_results": results}

def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """LLM 生成 — 融合语义记忆（RAG）+ 情节记忆（Mem0）+ 程序性记忆（System Prompt）"""
    engine = runtime.context.rag_engine
    llm = runtime.context.llm_client
    with trace_span("graph_generate", "llm") as span:
        user_prompt, _ = RAGEngine._build_qa_prompt(engine.config.generation, state["question"], state["search_results"])
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": f"【用户历史信息】\n{state['memory_context']}"} if state["memory_context"] else None,
            {"role": "user", "content": user_prompt},
        ]
        messages = [m for m in messages if m]
        answer = llm.chat(messages)
        return {"answer": str(answer)}

def extract_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆写入 — 从对话中提取事实，经 Mem0 冲突检测后持久化"""
    memory_svc = runtime.context.memory_service
    conversation = [
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": state["answer"]},
    ]
    try:
        memory_svc.add(conversation, state["user_id"], metadata={"conversation_id": state["conversation_id"]})
    except Exception:
        pass
    return {}

def update_profile(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """用户画像更新 — 检查对话中是否出现新的用户偏好或关注领域，更新结构化概要"""
    memory_svc = runtime.context.memory_service
    try:
        memory_svc.update_profile(state["question"], state["answer"], state["user_id"])
    except Exception:
        pass
    return {}

def route_by_results(state: AskState) -> Literal["generate", "clarify"]:
    return "clarify" if not state["search_results"] else "generate"
```

---

## 五、Mem0 集成设计

### 5.1 MemoryService 降级包装

```python
class MemoryService:
    def __init__(self, memory: Optional[Memory] = None, db_path: str = "./data/actuary_sleuth.db"):
        self._memory = memory
        self._available = memory is not None
        self._db_path = db_path

    @classmethod
    def create(cls, db_path: str = "./data/actuary_sleuth.db") -> "MemoryService":
        try:
            from mem0 import Memory
            from lib.memory.embeddings import EmbeddingBridge
            # config 在 create() 内部构建（LlmConfig + EmbeddingBridge + LanceDB）
            # 完整实现见 plan.md File #5 service.py
            memory = Memory.from_config(config)  # config 变量在 try 块内构建
            return cls(memory, db_path)
        except Exception as e:
            logger.warning(f"Mem0 初始化失败，运行无记忆模式: {e}")
            return cls(None, db_path)

    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        if not self._available:
            return []
        try:
            results = self._memory.search(query, user_id=user_id, limit=limit).get("results", [])
            # 更新活跃度：被检索命中 = 仍有价值
            self._update_access_stats([m["id"] for m in results if "id" in m])
            return results
        except Exception:
            return []

    def add(self, messages, user_id: str, metadata=None) -> List[str]:
        if not self._available:
            return []
        try:
            result = self._memory.add(messages, user_id=user_id, metadata=metadata or {})
            ids = result.get("results", {}).get("ids", [])
            # 写入元数据
            for mid in ids:
                self._insert_metadata(mid, user_id, metadata)
            return ids
        except Exception:
            return []

    def delete(self, memory_id: str) -> bool: ...
    def get_all(self, user_id: str) -> List[Dict]: ...

    def update_profile(self, question: str, answer: str, user_id: str) -> None:
        """LLM 提取对话中的关注领域和偏好标签，合并到 user_profiles 表"""
        ...

    def _extract_profile_tags(self, question: str, answer: str) -> Dict:
        """用 QA LLM 从对话中提取 focus_areas 和 preference_tags"""
        ...

    def _update_access_stats(self, memory_ids: List[str]) -> None:
        """更新记忆活跃度（last_accessed_at + access_count），被检索命中时调用"""
        ...

    def _insert_metadata(self, mem0_id: str, user_id: str, metadata: dict) -> None:
        """写入 memory_metadata 记录，含 TTL 和活跃度初始值"""
        ...

    def cleanup_expired(self) -> int:
        """清理过期记忆 + 活跃度衰减清理。返回清理条数"""
        ...
```

### 5.2 TTL 过期 + 活跃度衰减机制

Mem0 不原生支持 TTL 和活跃度衰减。通过 memory_metadata 表 + 定时清理实现双层管理策略：

**TTL 过期**：基于 `expires_at` 字段，到期自动软删除。写入时根据记忆类别设置默认 TTL：
- `fact`（审核事实）：30 天
- `preference`（用户偏好）：90 天
- `audit_conclusion`（审核结论）：永久

**活跃度衰减**：参照艾宾浩斯遗忘曲线，长期未被检索命中的记忆逐渐降低权重：
- `access_count` 记录被检索命中次数
- `last_accessed_at` 记录最近一次被检索时间
- 超过 60 天未被命中的记忆标记为低活跃，定期清理时优先删除

**被使用=仍有价值**：记忆被检索命中时自动续期（重置 `last_accessed_at`），模拟人类记忆的"巩固"机制。

**冗余消除**：由 Mem0 内建的 NOOP 操作处理——当新提取的记忆与现有记忆一致时自动跳过，不重复写入。

**未来扩展**（当前不实现，记忆量级 100-1000 条暂不需要）：
- **重要度排序**：记忆量超限时按重要度（关键事实 > 审核结论 > 一般偏好 > 临时信息）保留 Top N，关键事实（如过敏信息、合同条款）永久保留
- **审计日志**：记忆删除操作记录审计轨迹（操作类型、操作时间、记忆内容快照），用于合规审查。当前场景（精算审核工具）暂无强合规要求

```python
# 定时清理（复用 _auto_classify_loop 模式，每天运行一次）
async def _memory_cleanup_loop():
    while True:
        await asyncio.sleep(86400)
        memory_svc.cleanup_expired()
```

### 5.3 用户画像

用户画像是长期记忆的特殊子类型——从大量对话中提炼的**结构化概要**，而非逐条对话记录。每次对话结束时增量更新：

```python
# user_profiles 表结构（见 3.4 节 SQL）
# 示例画像
{
    "user_id": "actuary_zhang",
    "focus_areas": ["免责条款", "等待期", "费率计算"],       -- 高频检索领域
    "preference_tags": ["重疾险", "寿险"],                 -- 偏好产品类型
    "audit_stats": {
        "total_audits": 12,
        "product_types": {"重疾险": 7, "寿险": 3, "意外险": 2}
    },
    "summary": "资深精算师，主要审核重疾险产品，重点关注免责条款和等待期合规性"
}
```

用户画像在 `retrieve_memory` 节点中与情节记忆一起注入 System Prompt，让 LLM 在回答时考虑用户的具体情况。

### 5.4 精算审核事实提取 Prompt

```python
AUDIT_FACT_EXTRACTION_PROMPT = """\
请仅提取与保险产品审核相关的事实：产品名称、条款问题、定价疑虑、法规引用、免责分析、等待期问题、审核发现。

Input: 你好。
Output: {"facts": []}

Input: 该重疾产品等待期180天，超过《健康保险管理办法》90天上限。
Output: {"facts": ["重疾产品等待期180天", "《健康保险管理办法》规定等待期上限90天"]}

Input: 费率表使用2010年生命表CL1-2010，而非CL1-2023。
Output: {"facts": ["费率表使用过时生命表CL1-2010", "当前应使用CL1-2023"]}

请以 JSON 格式输出。
"""
```

---

## 六、API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory/list` | 获取用户所有记忆（含类型标签和活跃度） |
| GET | `/api/memory/search` | 语义搜索记忆 |
| DELETE | `/api/memory/{memory_id}` | 删除单条记忆 |
| DELETE | `/api/memory/batch` | 批量删除记忆 |
| POST | `/api/memory/add` | 手动添加记忆 |
| GET | `/api/memory/profile` | 获取当前用户画像 |
| PUT | `/api/memory/profile` | 手动更新用户画像 |

现有端点变更：`POST /api/ask/chat` 的 `ChatRequest` 新增 `user_id` 字段（默认 "default"）。

---

## 七、可观测性

| Span Name | Category | 说明 |
|-----------|----------|------|
| `graph_root` | root | 图执行根 span |
| `memory_retrieve` | memory | 情节记忆检索 |
| `graph_retrieve` | rag | 语义记忆（法规）检索 |
| `graph_generate` | llm | LLM 生成（融合三路记忆） |
| `memory_extract` | memory | 情节记忆提取写入 |
| `profile_update` | memory | 用户画像更新 |

---

## 八、参考实现

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Context Overview](https://docs.langchain.com/oss/python/concepts/context)
- [Mem0 LangChain Vector Store](https://docs.mem0.ai/components/vectordbs/dbs/langchain)
- [Mem0 Custom Fact Extraction](https://docs.mem0.ai/open-source/features/custom-fact-extraction-prompt)
- [Mem0 OSS Configuration](https://docs.mem0.ai/open-source/configuration)
- [Mem0 OpenAI Embedder Config](https://docs.mem0.ai/components/embedders/config)
