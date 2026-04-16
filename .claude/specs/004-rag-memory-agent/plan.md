# Implementation Plan: RAG 记忆增强与 Agent 框架

**Branch**: `004-rag-memory-agent` | **Date**: 2026-04-07 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

为 Actuary Sleuth 系统引入记忆能力和 Agent 工作流编排：
- **LangGraph** 编排审核工作流（并行双检索：记忆检索 ∥ 法规检索 → 生成 → 记忆提取 → 画像更新）
- **Mem0** 管理记忆生命周期（事实提取、冲突检测 ADD/UPDATE/DELETE/NOOP）
- **LanceDB** 统一向量存储（通过 LangChain 桥接，Embedding 复用 `settings.json` 的 `llm.embed`）
- **三层记忆架构**：语义记忆（现有 RAG）+ 情节记忆（Mem0）+ 程序性记忆（System Prompt）
- **用户画像**：结构化概要（关注领域、偏好标签、审核统计），每次对话后增量更新
- **记忆管理**：TTL 过期 + 活跃度衰减 + 软删除，Mem0 不可用时降级运行

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: langgraph 1.0.2 (已安装), langchain-community 0.4.1 (已安装), mem0ai (需新增)
**Storage**: SQLite (memory_metadata, user_profiles) + LanceDB (memories collection)
**Testing**: pytest
**Performance Goals**: Mem0 不可用时 1 秒内降级；记忆注入后平均对话轮次减少
**Constraints**: 保持 SQLite + LanceDB，保持 Zhipu/Ollama LLM，零新增 embedding 配置

## Constitution Check

- [x] **Library-First**: 复用 LangGraph/Mem0/LangChain 社区库；复用项目 RAGEngine/LLMClient/trace_span/LLMClientFactory；Embedding 复用 `settings.json` 的 `llm.embed` 配置
- [x] **测试优先**: 每个新增模块均包含单元测试
- [x] **简单优先**: 初始工作流为并行双检索 + 线性后处理（两路独立检索无数据依赖，天然适合并行），条件路由按需启用；`EmbeddingBridge` 仅 10 行接口适配，不引入新配置
- [x] **显式优于隐式**: 记忆检索/提取/画像更新均为独立 LangGraph 节点，数据流清晰可追踪
- [x] **可追溯性**: 每个文件回溯到 spec.md 的 User Story 和 Functional Requirement
- [x] **独立可测试**: 基础设施、LangGraph 工作流、MemoryService、TTL 清理、管理 API 均可独立测试

## Project Structure

```text
scripts/lib/memory/                    # 新增模块
├── __init__.py
├── config.py                          # 记忆配置（TTL 默认值、衰减参数）
├── embeddings.py                      # EmbeddingBridge（LlamaIndex → LangChain 接口适配）
├── prompts.py                         # 事实提取 prompt + 画像更新 prompt
└── service.py                         # MemoryService（Mem0 包装 + 降级 + 活跃度 + 画像）

scripts/lib/rag_engine/
└── graph.py                           # 新增：LangGraph StateGraph + 节点函数

scripts/api/
├── routers/
│   ├── ask.py                         # 修改：chat 端点接入 LangGraph
│   └── memory.py                      # 新增：记忆管理 API
├── schemas/
│   ├── ask.py                         # 修改：ChatRequest 新增 user_id
│   └── memory.py                      # 新增：记忆 + 画像 Pydantic schemas
├── app.py                             # 修改：初始化记忆服务 + 注册路由 + 清理任务
├── dependencies.py                    # 修改：新增 get_memory_service()
└── database.py                        # 修改：新增表 + conversations 加 user_id

scripts/tests/lib/memory/              # 新增测试
├── test_service.py
├── test_embeddings.py
└── test_graph.py
```

---

## File Specifications

> 每个文件展示终态完整内容。实现时按 Phase 顺序创建，Phase 仅决定执行先后，不决定代码形态。

---

### 1. `scripts/lib/memory/__init__.py`（新增）

```python
```

空模块。

---

### 2. `scripts/lib/memory/config.py`（新增）

→ 对应 FR-006（TTL 过期）

```python
"""记忆模块配置。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryConfig:
    """记忆服务配置"""

    # TTL 默认值（天），-1 表示永久
    ttl_fact: int = 30
    ttl_preference: int = 90
    ttl_audit_conclusion: int = -1

    # 活跃度衰减
    inactive_threshold_days: int = 60

    # 检索限制
    memory_search_limit: int = 3
    memory_context_max_chars: int = 2000
```

---

### 3. `scripts/lib/memory/embeddings.py`（新增）

→ 对应 FR-010（现有存储）、research.md Section 2.3

```python
"""LlamaIndex → LangChain Embedding 接口适配。"""
from langchain_core.embeddings import Embeddings
from lib.llm.factory import LLMClientFactory


class EmbeddingBridge(Embeddings):
    """将 LlamaIndex Embedding 桥接为 LangChain Embeddings 接口。

    Embedding 模型由 settings.json 的 llm.embed 配置决定，通过
    LLMClientFactory.create_embed_model() 创建，不引入任何新配置项。
    """

    def __init__(self):
        self._adapter = LLMClientFactory.create_embed_model()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._adapter._get_text_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._adapter._get_query_embedding(text)
```

---

### 4. `scripts/lib/memory/prompts.py`（新增）

→ 对应 FR-002（对话记忆提取）

```python
"""记忆提取和画像更新 Prompt。"""

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

PROFILE_EXTRACTION_PROMPT = """\
从精算审核对话中提取用户的关注领域和偏好产品类型。
仅提取明确提及的内容，不要推断。

Input:
用户: 这个重疾险的等待期条款合规吗？
助手: 根据《健康保险管理办法》，等待期不得超过90天。
Output: {"focus_areas": ["等待期"], "preference_tags": ["重疾险"]}

Input:
用户: 帮我看看这份意外险的免责条款
助手: 该意外险免责条款第7条将先天性疾病列入免责范围，与《保险法》规定不符。
Output: {"focus_areas": ["免责条款"], "preference_tags": ["意外险"]}

Input:
用户: 你好
助手: 你好，请问有什么可以帮您？
Output: {"focus_areas": [], "preference_tags": []}

请以 JSON 格式输出，仅输出 JSON。
"""
```

---

### 5. `scripts/lib/memory/service.py`（新增）

→ 对应 US-2（对话摘要记忆）、US-3（用户偏好记忆）、US-5（记忆过期清理）、FR-002/003/005/006/007/008

```python
"""记忆服务 — Mem0 包装 + 降级 + 活跃度管理 + 用户画像。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryService:
    """Mem0 包装层，提供降级、活跃度管理和用户画像。"""

    def __init__(self, memory: Optional[Any] = None, db_path: str = "./data/actuary_sleuth.db"):
        self._memory = memory
        self._available = memory is not None
        self._db_path = db_path

    @classmethod
    def create(cls, db_path: str = "./data/actuary_sleuth.db") -> "MemoryService":
        """创建记忆服务，Mem0 初始化失败时降级为无记忆模式。"""
        try:
            from mem0 import Memory
            from lib.memory.embeddings import EmbeddingBridge
            from lib.memory.prompts import AUDIT_FACT_EXTRACTION_PROMPT
            from langchain_community.vectorstores import LanceDB as LCLanceDB
            from lib.config import get_config

            cfg = get_config()
            qa_cfg = cfg.qa  # 复用 qa 场景的 LLM 配置

            embedding_lc = EmbeddingBridge()
            lancedb_store = LCLanceDB(
                uri="./data/lancedb",
                table_name="memories",
                embedding=embedding_lc,
            )

            base_url = qa_cfg.get("base_url", "").rstrip("/")
            config = {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": qa_cfg.get("model", "glm-4-flash"),
                        "api_key": qa_cfg.get("api_key"),
                        "openai_base_url": base_url,
                        "temperature": 0.1,
                    }
                },
                "embedder": {
                    "provider": "langchain",
                    "config": {"model": embedding_lc}
                },
                "vector_store": {
                    "provider": "langchain",
                    "config": {"client": lancedb_store}
                },
                "custom_fact_extraction_prompt": AUDIT_FACT_EXTRACTION_PROMPT,
                "version": "v1.1",
            }
            memory = Memory.from_config(config)
            logger.info("Mem0 初始化成功")
            return cls(memory, db_path)
        except Exception as e:
            logger.warning(f"Mem0 初始化失败，运行无记忆模式: {e}")
            return cls(None, db_path)

    @property
    def available(self) -> bool:
        return self._available

    # ── 记忆 CRUD ──────────────────────────────────────

    def search(self, query: str, user_id: str, limit: int = 3) -> List[Dict]:
        """检索与查询相关的用户记忆，命中后更新访问统计。"""
        if not self._available:
            return []
        try:
            result = self._memory.search(query, user_id=user_id, limit=limit)
            memories = result.get("results", [])
            self._update_access_stats([m["id"] for m in memories if "id" in m])
            return memories
        except Exception:
            logger.debug("记忆检索失败", exc_info=True)
            return []

    def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
        """写入记忆，Mem0 自动处理 ADD/UPDATE/DELETE/NOOP 冲突。"""
        if not self._available:
            return []
        try:
            result = self._memory.add(messages, user_id=user_id, metadata=metadata or {})
            ids = result.get("results", {}).get("ids", [])
            for mid in ids:
                self._insert_metadata(mid, user_id, metadata)
            return ids
        except Exception:
            logger.debug("记忆写入失败", exc_info=True)
            return []

    def delete(self, memory_id: str) -> bool:
        """删除记忆（Mem0 物理删除 + 元数据软删除）。"""
        if not self._available:
            return False
        try:
            self._memory.delete(memory_id)
            self._soft_delete_metadata(memory_id)
            return True
        except Exception:
            return False

    def get_all(self, user_id: str) -> List[Dict]:
        """获取用户全部记忆。"""
        if not self._available:
            return []
        try:
            result = self._memory.get_all(user_id=user_id)
            return result.get("results", [])
        except Exception:
            return []

    # ── TTL 清理 ───────────────────────────────────────

    def cleanup_expired(self) -> int:
        """清理过期记忆 + 活跃度衰减清理。返回清理条数。"""
        from lib.memory.config import MemoryConfig
        cfg = MemoryConfig()
        cleaned = 0

        if not self._available:
            return 0

        try:
            with self._get_conn() as conn:
                # TTL 过期清理
                now = datetime.now().isoformat()
                expired = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE expires_at IS NOT NULL AND expires_at < ? AND is_deleted = 0",
                    (now,),
                ).fetchall()
                for (mem_id,) in expired:
                    try:
                        self._memory.delete(mem_id)
                        self._soft_delete_metadata(mem_id)
                        cleaned += 1
                    except Exception:
                        pass

                # 活跃度衰减清理：超过 inactive_threshold_days 未被检索命中
                threshold = (datetime.now() - timedelta(days=cfg.inactive_threshold_days)).isoformat()
                inactive = conn.execute(
                    "SELECT mem0_id FROM memory_metadata "
                    "WHERE last_accessed_at < ? AND access_count = 0 AND is_deleted = 0",
                    (threshold,),
                ).fetchall()
                for (mem_id,) in inactive:
                    try:
                        self._memory.delete(mem_id)
                        self._soft_delete_metadata(mem_id)
                        cleaned += 1
                    except Exception:
                        pass

        except Exception:
            logger.debug("记忆清理失败", exc_info=True)

        return cleaned

    # ── 用户画像 ───────────────────────────────────────

    def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户画像。"""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT focus_areas, preference_tags, audit_stats, summary FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": user_id,
                    "focus_areas": json.loads(row[0]),
                    "preference_tags": json.loads(row[1]),
                    "audit_stats": json.loads(row[2]),
                    "summary": row[3],
                }
        except Exception:
            return None

    def update_profile(self, question: str, answer: str, user_id: str) -> None:
        """增量更新用户画像：LLM 提取关注领域/偏好，累加审核统计。"""
        try:
            # LLM 提取本次对话的关注领域和偏好
            extracted = self._extract_profile_tags(question, answer)
            new_areas = extracted.get("focus_areas", [])
            new_tags = extracted.get("preference_tags", [])

            with self._get_conn() as conn:
                existing = conn.execute(
                    "SELECT focus_areas, preference_tags, audit_stats FROM user_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

                if existing:
                    focus_areas = json.loads(existing[0])
                    preference_tags = json.loads(existing[1])
                    audit_stats = json.loads(existing[2])
                else:
                    focus_areas, preference_tags, audit_stats = [], [], {}

                # 合并新标签（去重）
                focus_areas = list(set(focus_areas) | set(new_areas))
                preference_tags = list(set(preference_tags) | set(new_tags))
                audit_stats["total_audits"] = audit_stats.get("total_audits", 0) + 1

                conn.execute(
                    "INSERT INTO user_profiles (user_id, focus_areas, preference_tags, audit_stats, updated_at) "
                    "VALUES (?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "focus_areas = excluded.focus_areas, "
                    "preference_tags = excluded.preference_tags, "
                    "audit_stats = excluded.audit_stats, "
                    "updated_at = excluded.updated_at",
                    (user_id, json.dumps(focus_areas), json.dumps(preference_tags), json.dumps(audit_stats)),
                )
        except Exception:
            logger.debug("用户画像更新失败", exc_info=True)

    def _extract_profile_tags(self, question: str, answer: str) -> Dict:
        """用 LLM 从对话中提取关注领域和偏好标签。"""
        try:
            from lib.llm.factory import LLMClientFactory
            from lib.memory.prompts import PROFILE_EXTRACTION_PROMPT

            llm = LLMClientFactory.create_qa_llm()
            prompt = f"{PROFILE_EXTRACTION_PROMPT}\n\nInput:\n用户: {question}\n助手: {answer}\nOutput: "
            result = llm.generate(prompt)
            # 提取 JSON（LLM 可能输出 ```json 包裹）
            text = str(result).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except Exception:
            logger.debug("画像标签提取失败", exc_info=True)
            return {"focus_areas": [], "preference_tags": []}

    # ── 内部方法 ───────────────────────────────────────

    def _get_conn(self):
        from lib.common.database import get_connection
        return get_connection()

    def _update_access_stats(self, memory_ids: List[str]) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE memory_metadata SET last_accessed_at = datetime('now'), "
                    "access_count = access_count + 1 WHERE mem0_id IN ({})".format(
                        ",".join("?" for _ in memory_ids)
                    ),
                    memory_ids,
                )
        except Exception:
            pass

    def _insert_metadata(self, mem0_id: str, user_id: str, metadata: Optional[Dict]) -> None:
        from lib.memory.config import MemoryConfig
        cfg = MemoryConfig()
        category = (metadata or {}).get("category", "fact")

        ttl_map = {
            "fact": cfg.ttl_fact,
            "preference": cfg.ttl_preference,
            "audit_conclusion": cfg.ttl_audit_conclusion,
        }
        ttl_days = ttl_map.get(category, cfg.ttl_fact)
        expires_at = None
        if ttl_days > 0:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO memory_metadata (mem0_id, user_id, conversation_id, category, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (mem0_id, user_id, (metadata or {}).get("conversation_id"), category, expires_at),
                )
        except Exception:
            pass

    def _soft_delete_metadata(self, mem0_id: str) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "UPDATE memory_metadata SET is_deleted = 1 WHERE mem0_id = ?", (mem0_id,)
                )
        except Exception:
            pass
```

---

### 6. `scripts/lib/rag_engine/graph.py`（新增）

→ 对应 US-1（跨会话审核上下文延续）、US-6（Agent 工作流编排）、FR-001/004/011

```python
"""LangGraph 审核工作流。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

from lib.llm.trace import trace_span

logger = logging.getLogger(__name__)


# ── 状态定义 ──────────────────────────────────────────


class AskState(TypedDict):
    """LangGraph 工作流状态。

    输出字段兼容 engine.ask() 的返回结构，确保 event_stream 无需修改。
    """

    question: str
    mode: str  # "qa" | "search"（与 ChatRequest.mode 一致）
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


@dataclass
class GraphContext:
    """LangGraph 依赖注入上下文。"""

    rag_engine: Any  # RAGEngine
    llm_client: Any  # BaseLLMClient
    memory_service: Any  # MemoryService


# ── 节点函数 ──────────────────────────────────────────


def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆检索 + 用户画像注入 — 从 Mem0 和 user_profiles 中检索历史上下文。"""
    from lib.memory.config import MemoryConfig
    memory_svc = runtime.context.memory_service
    max_chars = MemoryConfig().memory_context_max_chars
    with trace_span("memory_retrieve", "memory") as span:
        parts = []

        # 情节记忆
        memories = memory_svc.search(state["question"], state["user_id"])
        if memories:
            lines = [f"- {m['memory']} (记录于 {m['created_at'][:10]})" for m in memories]
            parts.append("\n".join(lines))

        # 用户画像
        profile = memory_svc.get_profile(state["user_id"])
        if profile:
            profile_lines = []
            if profile.get("focus_areas"):
                profile_lines.append(f"关注领域: {', '.join(profile['focus_areas'])}")
            if profile.get("preference_tags"):
                profile_lines.append(f"偏好类型: {', '.join(profile['preference_tags'])}")
            if profile.get("summary"):
                profile_lines.append(f"画像摘要: {profile['summary']}")
            if profile_lines:
                parts.append("【用户画像】\n" + "\n".join(profile_lines))

        context = "\n\n".join(parts)
        if len(context) > max_chars:
            context = context[:max_chars] + "..."
        return {"memory_context": context}


def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """语义记忆检索 — 从现有 RAG 知识库检索法规条款。"""
    engine = runtime.context.rag_engine
    with trace_span("graph_retrieve", "rag") as span:
        results = engine.search(state["question"])
        return {"search_results": results}


def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """LLM 生成 — 融合语义记忆（RAG）+ 情节记忆（Mem0）+ 程序性记忆（System Prompt）。"""
    engine = runtime.context.rag_engine
    llm = runtime.context.llm_client
    with trace_span("graph_generate", "llm", model=getattr(llm, 'model', '')) as span:
        from lib.rag_engine.rag_engine import RAGEngine, _SYSTEM_PROMPT
        from lib.rag_engine.attribution import parse_citations

        user_prompt, included_count = RAGEngine._build_qa_prompt(
            engine.config.generation, state["question"], state["search_results"]
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
        ]
        if state.get("memory_context"):
            messages.append({"role": "system", "content": f"【用户历史信息】\n{state['memory_context']}"})
        messages.append({"role": "user", "content": user_prompt})

        span.input = {
            "question": state["question"],
            "context_chunk_count": len(state["search_results"]),
            "has_memory_context": bool(state.get("memory_context")),
        }
        answer = llm.chat(messages)
        answer_str = str(answer)

        # 引用解析（与现有 _do_ask 保持一致）
        included_sources = state["search_results"][:included_count] if state["search_results"] else []
        attribution = parse_citations(answer_str, included_sources)

        result = {
            "answer": answer_str,
            "sources": state["search_results"],
            "citations": [
                {"source_idx": c.source_idx, "law_name": c.law_name, "article_number": c.article_number, "content": c.content}
                for c in attribution.citations
            ],
            "unverified_claims": attribution.unverified_claims,
            "content_mismatches": attribution.content_mismatches,
        }
        span.output = {"answer_length": len(answer_str), "citation_count": len(attribution.citations)}
        return result


def extract_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """情节记忆写入 — 从对话中提取事实，经 Mem0 冲突检测后持久化。失败不阻塞。"""
    memory_svc = runtime.context.memory_service
    conversation = [
        {"role": "user", "content": state["question"]},
        {"role": "assistant", "content": state["answer"]},
    ]
    try:
        memory_svc.add(
            conversation, state["user_id"],
            metadata={"conversation_id": state["conversation_id"]},
        )
    except Exception:
        logger.debug("记忆提取失败，跳过", exc_info=True)
    return {}


def update_profile_node(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    """用户画像更新 — 检查对话中是否出现新的用户偏好或关注领域。失败不阻塞。"""
    memory_svc = runtime.context.memory_service
    try:
        memory_svc.update_profile(state["question"], state["answer"], state["user_id"])
    except Exception:
        logger.debug("用户画像更新失败，跳过", exc_info=True)
    return {}


def route_by_results(state: AskState) -> Literal["generate", "clarify"]:
    """条件路由：RAG 检索无结果时进入澄清节点，避免浪费 LLM 调用。"""
    return "clarify" if not state["search_results"] else "generate"


# ── 图构建 ────────────────────────────────────────────


def create_ask_graph():
    """创建审核问答工作流图（并行双检索 + 线性后处理）。

    retrieve_memory（情节记忆）和 rag_search（语义记忆）并行执行，
    两者写入不同 State 字段，无数据依赖，天然适合并行以降低延迟。
    generate 融合两路结果后进入后处理链（extract_memory → update_profile）。
    """
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_profile_node)

    # START → retrieve_memory + rag_search 并行（fan-out）
    graph.add_edge(START, "retrieve_memory")
    graph.add_edge(START, "rag_search")
    # 两路汇合 → generate（LangGraph 自动等待所有入边完成）
    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")
    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("update_profile", END)

    return graph.compile()


def create_ask_graph_with_clarify():
    """创建带条件路由的审核问答工作流图。

    并行双检索后通过 route 节点做条件路由：
    - 有 RAG 结果 → generate → extract_memory → update_profile → END
    - 无 RAG 结果 → clarify → END
    """
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("route", lambda s: {})  # passthrough，等待两路并行完成
    graph.add_node("generate", generate)
    graph.add_node("clarify", lambda s: {
        "answer": "未找到相关法规条款，请尝试换个描述方式。",
        "sources": [], "citations": [], "unverified_claims": [], "content_mismatches": [],
    })
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_profile_node)

    # START → retrieve_memory + rag_search 并行（fan-out）
    graph.add_edge(START, "retrieve_memory")
    graph.add_edge(START, "rag_search")
    # 两路汇合 → route passthrough（LangGraph 自动等待所有入边完成）
    graph.add_edge("retrieve_memory", "route")
    graph.add_edge("rag_search", "route")
    # route → conditional: 有结果走 generate，无结果走 clarify
    graph.add_conditional_edges("route", route_by_results, {
        "generate": "generate",
        "clarify": "clarify",
    })
    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("clarify", END)
    graph.add_edge("update_profile", END)

    return graph.compile()
```

---

### 7. `scripts/api/database.py`（修改）

→ 对应 FR-005（用户隔离）、FR-006（TTL 过期）

**修改 `_migrate_db()` 函数，在末尾追加：**

```python
# 记忆元数据表
conn.execute("""
CREATE TABLE IF NOT EXISTS memory_metadata (
    mem0_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    category TEXT DEFAULT 'fact',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    last_accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
    access_count INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_metadata(user_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_metadata(expires_at)")

# 用户画像表
conn.execute("""
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    focus_areas TEXT DEFAULT '[]',
    preference_tags TEXT DEFAULT '[]',
    audit_stats TEXT DEFAULT '{}',
    summary TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")

# conversations 表加 user_id
conv_cols = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
if 'user_id' not in conv_cols:
    conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
```

**修改 `create_conversation()` 签名：**

```python
def create_conversation(conversation_id: str, title: str = "", user_id: str = "default") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, title, user_id) VALUES (?, ?, ?)",
            (conversation_id, title, user_id),
        )
```

---

### 8. `scripts/api/schemas/ask.py`（修改）

→ 对应 FR-005（用户隔离）

**`ChatRequest` 新增 `user_id` 字段：**

```python
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="对话 ID，为空则新建对话")
    mode: str = Field("qa", pattern="^(qa|search)$", description="qa=智能问答, search=精确检索")
    debug: Optional[bool] = Field(None, description="是否记录 trace 调试信息，默认读取配置")
    user_id: str = Field("default", description="用户 ID，用于记忆隔离")
```

---

### 9. `scripts/api/schemas/memory.py`（新增）

→ 对应 US-4（记忆管理界面）、FR-007（管理 API）

```python
"""记忆和用户画像 Pydantic schemas。"""
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: str
    memory: str
    user_id: str
    created_at: str
    category: str = "fact"


class UserProfile(BaseModel):
    user_id: str
    focus_areas: list[str] = Field(default_factory=list)
    preference_tags: list[str] = Field(default_factory=list)
    audit_stats: dict = Field(default_factory=dict)
    summary: str = ""


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 5


class MemoryAddRequest(BaseModel):
    content: str
    category: str = "fact"


class MemoryBatchDeleteRequest(BaseModel):
    memory_ids: list[str]


class ProfileUpdateRequest(BaseModel):
    focus_areas: list[str] | None = None
    preference_tags: list[str] | None = None
    summary: str | None = None
```

---

### 10. `scripts/api/routers/memory.py`（新增）

→ 对应 US-4（记忆管理界面）、FR-007（管理 API）

```python
"""记忆管理 API。"""
import logging

from fastapi import APIRouter, HTTPException

from api.dependencies import get_memory_service
from api.schemas.memory import (
    MemoryAddRequest,
    MemoryBatchDeleteRequest,
    MemoryItem,
    MemoryListResponse,
    MemorySearchRequest,
    ProfileUpdateRequest,
    UserProfile,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/list", response_model=MemoryListResponse)
def list_memories(user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        return MemoryListResponse(memories=[])
    results = svc.get_all(user_id)
    return MemoryListResponse(
        memories=[MemoryItem(id=m["id"], memory=m["memory"], user_id=user_id, created_at=m.get("created_at", ""), category=m.get("metadata", {}).get("category", "fact")) for m in results]
    )


@router.get("/search", response_model=MemoryListResponse)
def search_memories(req: MemorySearchRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        return MemoryListResponse(memories=[])
    results = svc.search(req.query, user_id, limit=req.limit)
    return MemoryListResponse(
        memories=[MemoryItem(id=m["id"], memory=m["memory"], user_id=user_id, created_at=m.get("created_at", ""), category=m.get("metadata", {}).get("category", "fact")) for m in results]
    )


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    success = svc.delete(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="记忆不存在或删除失败")
    return {"status": "ok"}


@router.delete("/batch")
def batch_delete_memories(req: MemoryBatchDeleteRequest):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    results = []
    for mid in req.memory_ids:
        results.append(svc.delete(mid))
    return {"deleted": sum(results), "total": len(req.memory_ids)}


@router.post("/add", response_model=MemoryItem)
def add_memory(req: MemoryAddRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    ids = svc.add(
        [{"role": "user", "content": req.content}],
        user_id,
        metadata={"category": req.category},
    )
    if not ids:
        raise HTTPException(status_code=500, detail="记忆写入失败")
    return MemoryItem(id=ids[0], memory=req.content, user_id=user_id, created_at="", category=req.category)


@router.get("/profile", response_model=UserProfile | None)
def get_profile(user_id: str = "default"):
    svc = get_memory_service()
    if not svc:
        return None
    profile = svc.get_profile(user_id)
    if not profile:
        return None
    return UserProfile(**profile)


@router.put("/profile", response_model=UserProfile)
def update_profile(req: ProfileUpdateRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    import json
    from api.database import get_connection
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT focus_areas, preference_tags, summary FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="用户画像不存在")
        updates = {}
        if req.focus_areas is not None:
            updates["focus_areas"] = json.dumps(req.focus_areas)
        if req.preference_tags is not None:
            updates["preference_tags"] = json.dumps(req.preference_tags)
        if req.summary is not None:
            updates["summary"] = req.summary
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE user_profiles SET {set_clause}, updated_at = datetime('now') WHERE user_id = ?",
                (*updates.values(), user_id),
            )
    profile = svc.get_profile(user_id)
    return UserProfile(**profile)
```

---

### 11. `scripts/api/dependencies.py`（修改）

→ 对应 FR-008（降级运行）

**终态完整内容：**

```python
"""FastAPI 共享依赖。"""

from fastapi import HTTPException

_memory_service = None
_ask_graph = None


def on_shutdown():
    """应用关闭时清理连接池。"""
    from lib.common.database import close_pool
    close_pool()


def get_rag_engine():
    """获取 RAG 引擎实例，未初始化时返回 503。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise HTTPException(status_code=503, detail="RAG 引擎未初始化")
    return rag_engine


def init_memory_service():
    """初始化记忆服务，失败时降级为无记忆模式。"""
    global _memory_service
    from lib.memory.service import MemoryService
    _memory_service = MemoryService.create()
    return _memory_service


def get_memory_service():
    """获取记忆服务实例。"""
    return _memory_service


def init_ask_graph():
    """编译 LangGraph 工作流图（启动时编译一次，复用）。"""
    global _ask_graph
    from lib.rag_engine.graph import create_ask_graph
    _ask_graph = create_ask_graph()
    return _ask_graph


def get_ask_graph():
    """获取已编译的 LangGraph 工作流图。"""
    return _ask_graph
```

---

### 12. `scripts/api/routers/ask.py`（修改）

→ 对应 US-1（跨会话审核上下文延续）、FR-001（记忆检索注入）

**修改 `chat()` 函数：**

1. 新增 import：
```python
from api.dependencies import get_memory_service, get_ask_graph
from lib.rag_engine.graph import AskState, GraphContext
```

2. `create_conversation` 调用增加 `user_id`：
```python
create_conversation(conversation_id, title=req.question[:50], user_id=req.user_id)
```

3. `event_stream()` 中将 `result = await asyncio.to_thread(engine.ask, req.question)` 替换为 LangGraph 调用：

```python
memory_svc = get_memory_service()
graph = get_ask_graph()

state = AskState(
    question=req.question,
    mode=req.mode,
    user_id=req.user_id,
    conversation_id=conversation_id,
    search_results=[],
    memory_context="",
    answer="",
    sources=[],
    citations=[],
    unverified_claims=[],
    content_mismatches=[],
    faithfulness_score=None,
    error=None,
)
context = GraphContext(
    rag_engine=engine,
    llm_client=engine._llm_client,
    memory_service=memory_svc,
)
result = await asyncio.to_thread(graph.invoke, state, context=context)
```

> **兼容性保证**：`graph.invoke` 返回的 `AskState` 字段完全覆盖 `engine.ask()` 的返回结构（`answer`, `sources`, `citations`, `unverified_claims`, `content_mismatches`, `faithfulness_score`），`event_stream()` 中的 `result.get()` 调用无需任何修改。

---

### 13. `scripts/api/app.py`（修改）

→ 对应 FR-008（降级运行）、US-5（记忆过期清理）

**修改 `lifespan()` 函数：**

1. 新增 import（文件顶部附近）：
```python
from api.routers.memory import router as memory_router
```

2. `lifespan()` 中 `init_db()` 之后新增记忆服务初始化：
```python
from api.dependencies import init_memory_service, init_ask_graph
memory_service = init_memory_service()
```

3. `lifespan()` 中 RAG 引擎初始化之后（`rag_engine.initialize()` 之后）编译 LangGraph：
```python
from api.dependencies import init_ask_graph
init_ask_graph()
```

4. `lifespan()` 中 `yield` 之前新增记忆清理任务（复用 `_auto_classify_loop` 模式）：
```python
memory_cleanup_task = asyncio.create_task(_memory_cleanup_loop())
```

5. `yield` 之后新增取消：
```python
memory_cleanup_task.cancel()
```

6. 新增清理循环函数（与 `_auto_classify_loop` 同级）：
```python
async def _memory_cleanup_loop():
    """每日清理过期记忆。"""
    import asyncio
    from api.dependencies import get_memory_service
    while True:
        await asyncio.sleep(86400)
        svc = get_memory_service()
        if svc and svc.available:
            try:
                count = svc.cleanup_expired()
                if count:
                    logger.info(f"清理过期记忆 {count} 条")
            except Exception:
                pass
```

7. 注册路由：
```python
app.include_router(memory_router)
```

---

### 14. `scripts/tests/lib/memory/test_embeddings.py`（新增）

```python
"""EmbeddingBridge 集成测试（需要 Ollama 运行）。"""
import pytest
from lib.memory.embeddings import EmbeddingBridge


def test_embed_query_returns_vector():
    bridge = EmbeddingBridge()
    result = bridge.embed_query("等待期规定")
    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(x, float) for x in result)


def test_embed_documents_returns_vectors():
    bridge = EmbeddingBridge()
    result = bridge.embed_documents(["等待期90天", "免责条款"])
    assert len(result) == 2
    assert all(len(v) == 1024 for v in result)
```

---

### 15. `scripts/tests/lib/memory/test_service.py`（新增）

```python
"""MemoryService 单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
from lib.memory.service import MemoryService


@pytest.fixture
def unavailable_service():
    return MemoryService(memory=None)


def test_search_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.search("test", "user1") == []


def test_add_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.add([], "user1") == []


def test_delete_unavailable_returns_false(unavailable_service):
    assert unavailable_service.delete("mem_123") is False


def test_available_property(unavailable_service):
    assert unavailable_service.available is False


@patch("lib.memory.service.Memory")
def test_create_success(mock_memory_cls):
    mock_instance = MagicMock()
    mock_memory_cls.from_config.return_value = mock_instance
    svc = MemoryService.create()
    assert svc.available is True
```

---

### 16. `scripts/tests/lib/memory/test_graph.py`（新增）

```python
"""LangGraph 工作流单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
from lib.rag_engine.graph import create_ask_graph, AskState, GraphContext, retrieve_memory


@pytest.fixture
def mock_context():
    memory_svc = MagicMock()
    memory_svc.search.return_value = [
        {"memory": "重疾产品等待期180天", "created_at": "2026-04-01T10:00:00"},
    ]
    engine = MagicMock()
    engine.search.return_value = [{"content": "等待期不得超过90天"}]
    engine.config = MagicMock()
    llm = MagicMock()
    llm.chat.return_value = "根据法规，等待期不得超过90天。"
    return GraphContext(rag_engine=engine, llm_client=llm, memory_service=memory_svc)


def test_retrieve_memory_returns_context(mock_context):
    state = AskState(
        question="等待期是多少", mode="qa", user_id="test",
        conversation_id="conv_1", search_results=[], memory_context="",
        answer="", sources=[], citations=[], unverified_claims=[], content_mismatches=[],
        faithfulness_score=None, error=None,
    )
    from langgraph.runtime import Runtime
    result = retrieve_memory(state, runtime=Runtime(context=mock_context))
    assert "重疾产品等待期180天" in result["memory_context"]


def test_graph_end_to_end(mock_context):
    from unittest.mock import MagicMock as MC
    graph = create_ask_graph()
    state = AskState(
        question="等待期", mode="qa", user_id="test",
        conversation_id="conv_1", search_results=[], memory_context="",
        answer="", sources=[], citations=[], unverified_claims=[], content_mismatches=[],
        faithfulness_score=None, error=None,
    )
    with patch("lib.rag_engine.graph.trace_span") as mock_span:
        mock_span.return_value.__enter__ = MC()
        mock_span.return_value.__exit__ = MC(return_value=False)
        result = graph.invoke(state, context=mock_context)
    assert result["answer"] != ""
```

---

## Execution Order

```
Phase 1 (基础设施)
├── lib/memory/__init__.py
├── lib/memory/config.py
├── lib/memory/embeddings.py
├── lib/memory/prompts.py
├── api/database.py（迁移 + create_conversation）
└── tests/lib/memory/test_embeddings.py
    ↓
Phase 2 (LangGraph + 记忆检索注入)
├── lib/rag_engine/graph.py
├── api/schemas/ask.py（user_id）
├── api/routers/ask.py（LangGraph 接入）
├── api/dependencies.py（记忆服务）
├── api/app.py（初始化 + 清理任务）
└── tests/lib/memory/test_graph.py
    ↓
Phase 3 (MemoryService + 管理 API)
├── lib/memory/service.py
├── api/schemas/memory.py
├── api/routers/memory.py
└── tests/lib/memory/test_service.py
```

Phase 2 和 Phase 3 之间有依赖（graph.py 引用 MemoryService），但 graph.py 通过 `runtime.context.memory_service` 间接引用，类型为 `Any`，因此可以先创建 graph.py，再创建 service.py。最终集成在 Phase 2 的 `app.py` 初始化中完成。

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | — | — |

---

## Appendix

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 跨会话审核上下文延续 | 新会话中提问历史审核话题，系统能检索到历史记忆并注入回答 | `test_graph.py` |
| US-2 对话摘要记忆 | 对话结束后自动提取审核相关事实，忽略闲聊，冲突时执行 UPDATE | `test_service.py` |
| US-3 用户偏好记忆 | 多次对话后用户画像包含正确的关注领域和偏好标签 | `test_service.py` |
| US-4 记忆管理界面 | 可查看/删除/手动添加记忆，可查看/更新用户画像 | API 手动测试 |
| US-5 记忆过期清理 | TTL 到期记忆被自动软删除，长期未命中记忆被衰减清理 | `test_service.py` |
| US-6 Agent 工作流编排 | LangGraph 按图执行，条件路由正确分流，可观测性记录每个节点 | `test_graph.py` |
