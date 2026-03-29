# RAG Web 平台 - 后端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 FastAPI 构建 RAG 法规知识平台后端 API，复用现有 `scripts/lib/rag_engine/`，提供法规问答、知识库管理、评估管理、合规检查四大模块。

**Architecture:** FastAPI 作为 API 层，SQLite 持久化对话/评估/合规数据，SSE 流式问答，异步任务轮询。不修改现有 `scripts/lib/` 核心逻辑，仅在 `scripts/api/` 中做薄封装。

**Tech Stack:** Python 3, FastAPI, SSE, SQLite (复用现有 `lib/common/database.py` 连接池), asyncio

**Design Spec:** `docs/superpowers/specs/2026-03-29-rag-web-platform-design.md`

---

## 文件结构总览

```
scripts/api/
├── __init__.py
├── app.py                    # FastAPI 入口，lifespan 管理 RAGEngine
├── dependencies.py           # 共享依赖：get_db, get_rag_engine
├── database.py               # 建表 DDL，数据访问函数
├── exceptions.py             # API 异常定义
├── schemas/
│   ├── __init__.py
│   ├── ask.py                # 问答相关 Pydantic 模型
│   ├── knowledge.py          # 知识库相关 Pydantic 模型
│   ├── eval.py               # 评估相关 Pydantic 模型
│   └── compliance.py         # 合规检查相关 Pydantic 模型
├── routers/
│   ├── __init__.py
│   ├── ask.py                # /api/ask/* 路由
│   ├── knowledge.py          # /api/kb/* 路由
│   ├── eval.py               # /api/eval/* 路由
│   └── compliance.py         # /api/compliance/* 路由
└── tasks.py                  # 异步任务管理（导入、评估）

scripts/tests/api/
├── __init__.py
├── conftest.py               # 测试 fixture：测试数据库、mock engine
├── test_database.py          # 数据访问层测试
├── test_ask.py               # 问答路由测试
├── test_knowledge.py         # 知识库路由测试
├── test_eval.py              # 评估路由测试
└── test_compliance.py        # 合规检查路由测试
```

---

## Task 1: 项目骨架与依赖安装

**Files:**
- Create: `scripts/api/__init__.py`
- Create: `scripts/api/app.py`
- Modify: `scripts/requirements.txt` (追加 fastapi, uvicorn, sse-starlette, python-multipart)

- [ ] **Step 1: 安装 FastAPI 依赖**

```bash
pip install fastapi uvicorn sse-starlette python-multipart
```

- [ ] **Step 2: 创建 `scripts/api/__init__.py`**

```python
```

- [ ] **Step 3: 创建最小 FastAPI 入口 `scripts/api/app.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化资源（RAGEngine 将在后续 Task 中添加）
    yield
    # 关闭时清理资源


app = FastAPI(
    title="Actuary Sleuth - 法规知识平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
```

- [ ] **Step 4: 验证服务可启动**

```bash
cd scripts && python -m uvicorn api.app:app --host 0.0.0.0 --port 8000 &
sleep 2 && curl -s http://localhost:8000/api/health
kill %1
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add scripts/api/__init__.py scripts/api/app.py
git commit -m "feat(api): scaffold FastAPI application with health endpoint"
```

---

## Task 2: 数据库层 - 建表与数据访问

**Files:**
- Create: `scripts/api/database.py`
- Create: `scripts/api/dependencies.py`
- Create: `scripts/tests/api/__init__.py`
- Create: `scripts/tests/api/conftest.py`
- Create: `scripts/tests/api/test_database.py`

- [ ] **Step 1: 创建 `scripts/api/database.py` — DDL 和数据访问函数**

复用现有 `lib/common/database.py` 的 `get_connection()` 连接池，新建 API 专属表。

```python
"""API 数据库层 — 建表 DDL 和数据访问函数。

复用 lib.common.database.get_connection() 连接池，
不创建独立连接。
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from lib.common.database import get_connection
from lib.common.exceptions import DatabaseError


# ── DDL ──────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS eval_samples (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    ground_truth TEXT NOT NULL DEFAULT '',
    evidence_docs_json TEXT NOT NULL DEFAULT '[]',
    evidence_keywords_json TEXT NOT NULL DEFAULT '[]',
    question_type TEXT NOT NULL DEFAULT 'factual',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    topic TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_snapshots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sample_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS eval_snapshot_items (
    snapshot_id TEXT NOT NULL REFERENCES eval_snapshots(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL REFERENCES eval_samples(id) ON DELETE CASCADE,
    PRIMARY KEY (snapshot_id, sample_id)
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('retrieval', 'generation', 'full')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT
);

CREATE TABLE IF NOT EXISTS eval_sample_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    retrieved_docs_json TEXT NOT NULL DEFAULT '[]',
    generated_answer TEXT NOT NULL DEFAULT '',
    retrieval_metrics_json TEXT NOT NULL DEFAULT '{}',
    generation_metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_sample_results(run_id);

CREATE TABLE IF NOT EXISTS compliance_reports (
    id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL CHECK(mode IN ('product', 'document')),
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db():
    """执行建表 DDL。应用启动时调用一次。"""
    with get_connection() as conn:
        conn.executescript(_SCHEMA_SQL)


# ── 对话 (conversations / messages) ──────────────────

def create_conversation(conversation_id: str, title: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, title) VALUES (?, ?)",
            (conversation_id, title),
        )


def get_conversations() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_messages(conversation_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, citations_json, sources_json, timestamp "
            "FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["citations"] = json.loads(d.pop("citations_json"))
            d["sources"] = json.loads(d.pop("sources_json"))
            results.append(d)
        return results


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    citations: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations_json, sources_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def delete_conversation(conversation_id: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        msg_count = cur.rowcount
        conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        return msg_count


# ── 评估数据集 (eval_samples / eval_snapshots) ──────

def get_eval_samples(
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clauses = []
    params: list = []
    if question_type:
        clauses.append("question_type = ?")
        params.append(question_type)
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM eval_samples{where} ORDER BY id", params
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["evidence_docs"] = json.loads(d.pop("evidence_docs_json"))
            d["evidence_keywords"] = json.loads(d.pop("evidence_keywords_json"))
            results.append(d)
        return results


def get_eval_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_samples WHERE id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["evidence_docs"] = json.loads(d.pop("evidence_docs_json"))
        d["evidence_keywords"] = json.loads(d.pop("evidence_keywords_json"))
        return d


def upsert_eval_sample(sample: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO eval_samples
                (id, question, ground_truth, evidence_docs_json, evidence_keywords_json,
                 question_type, difficulty, topic, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                ground_truth = excluded.ground_truth,
                evidence_docs_json = excluded.evidence_docs_json,
                evidence_keywords_json = excluded.evidence_keywords_json,
                question_type = excluded.question_type,
                difficulty = excluded.difficulty,
                topic = excluded.topic,
                updated_at = excluded.updated_at
        """, (
            sample["id"], sample["question"], sample.get("ground_truth", ""),
            json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
            json.dumps(sample.get("evidence_keywords", []), ensure_ascii=False),
            sample.get("question_type", "factual"),
            sample.get("difficulty", "medium"),
            sample.get("topic", ""),
            now, now,
        ))


def delete_eval_sample(sample_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM eval_samples WHERE id = ?", (sample_id,)
        )
        return cur.rowcount > 0


def eval_sample_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM eval_samples").fetchone()
        return row["cnt"]


def import_eval_samples(samples: List[Dict[str, Any]]) -> int:
    """批量导入，跳过已存在的 id。返回新增数量。"""
    count = 0
    for s in samples:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO eval_samples "
                "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
                "question_type, difficulty, topic, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (
                    s["id"], s["question"], s.get("ground_truth", ""),
                    json.dumps(s.get("evidence_docs", []), ensure_ascii=False),
                    json.dumps(s.get("evidence_keywords", []), ensure_ascii=False),
                    s.get("question_type", "factual"),
                    s.get("difficulty", "medium"),
                    s.get("topic", ""),
                ),
            )
            if cur.rowcount > 0:
                count += 1
    return count


# ── 快照 ─────────────────────────────────────────────

def create_snapshot(name: str, description: str = "") -> str:
    import uuid
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        cnt = conn.execute("SELECT COUNT(*) AS cnt FROM eval_samples").fetchone()["cnt"]
        conn.execute(
            "INSERT INTO eval_snapshots (id, name, description, sample_count) VALUES (?, ?, ?, ?)",
            (snapshot_id, name, description, cnt),
        )
        conn.execute(
            "INSERT INTO eval_snapshot_items (snapshot_id, sample_id) "
            "SELECT ?, id FROM eval_samples",
            (snapshot_id,),
        )
    return snapshot_id


def get_snapshots() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_snapshots ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def restore_snapshot(snapshot_id: str) -> int:
    """回滚到指定快照：删除当前数据，复制快照数据。返回恢复条数。"""
    with get_connection() as conn:
        # 清空当前
        conn.execute("DELETE FROM eval_samples")
        # 从快照恢复
        items = conn.execute(
            "SELECT sample_id FROM eval_snapshot_items WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        count = 0
        for item in items:
            # 由于原始数据已删除，需要从其他地方恢复
            # 这里改为从 snapshot_items 关联恢复（需要存储完整数据）
            pass
        # 更简洁的实现：snapshot 存完整 JSON
        snap = conn.execute(
            "SELECT samples_json FROM eval_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if snap and snap["samples_json"]:
            for s in json.loads(snap["samples_json"]):
                conn.execute(
                    "INSERT OR IGNORE INTO eval_samples "
                    "(id, question, ground_truth, evidence_docs_json, evidence_keywords_json, "
                    "question_type, difficulty, topic, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (
                        s["id"], s["question"], s.get("ground_truth", ""),
                        json.dumps(s.get("evidence_docs", []), ensure_ascii=False),
                        json.dumps(s.get("evidence_keywords", []), ensure_ascii=False),
                        s.get("question_type", "factual"),
                        s.get("difficulty", "medium"),
                        s.get("topic", ""),
                    ),
                )
                count += 1
        return count


# ── 评估运行 (eval_runs / eval_sample_results) ──────

def create_eval_run(run_id: str, mode: str, config: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO eval_runs (id, mode, status, config_json) VALUES (?, ?, 'pending', ?)",
            (run_id, mode, json.dumps(config, ensure_ascii=False)),
        )


def update_eval_run_status(
    run_id: str, status: str, progress: int = 0, total: int = 0
) -> None:
    with get_connection() as conn:
        sets = ["status = ?"]
        params: list = [status]
        if status == "running":
            sets.append("progress = ?")
            sets.append("total = ?")
            params.extend([progress, total])
        elif status in ("completed", "failed"):
            sets.append("finished_at = datetime('now')")
            sets.append("progress = total")
        params.append(run_id)
        conn.execute(
            f"UPDATE eval_runs SET {', '.join(sets)} WHERE id = ?", params
        )


def save_eval_report(run_id: str, report: Dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET report_json = ? WHERE id = ?",
            (json.dumps(report, ensure_ascii=False), run_id),
        )


def save_sample_result(
    run_id: str,
    sample_id: str,
    retrieved_docs: Optional[List] = None,
    generated_answer: str = "",
    retrieval_metrics: Optional[Dict] = None,
    generation_metrics: Optional[Dict] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO eval_sample_results "
            "(run_id, sample_id, retrieved_docs_json, generated_answer, "
            "retrieval_metrics_json, generation_metrics_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id, sample_id,
                json.dumps(retrieved_docs or [], ensure_ascii=False),
                generated_answer,
                json.dumps(retrieval_metrics or {}, ensure_ascii=False),
                json.dumps(generation_metrics or {}, ensure_ascii=False),
            ),
        )


def get_eval_run(run_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("config_json"):
            d["config"] = json.loads(d.pop("config_json"))
        if d.get("report_json"):
            d["report"] = json.loads(d.pop("report_json"))
        return d


def get_eval_runs() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, mode, status, progress, total, started_at, finished_at, config_json "
            "FROM eval_runs ORDER BY started_at DESC"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("config_json"):
                d["config"] = json.loads(d.pop("config_json"))
            results.append(d)
        return results


def get_sample_results(run_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_sample_results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["retrieved_docs"] = json.loads(d.pop("retrieved_docs_json"))
            d["retrieval_metrics"] = json.loads(d.pop("retrieval_metrics_json"))
            d["generation_metrics"] = json.loads(d.pop("generation_metrics_json"))
            results.append(d)
        return results


# ── 合规报告 ─────────────────────────────────────────

def save_compliance_report(
    report_id: str,
    product_name: str,
    category: str,
    mode: str,
    result: Dict[str, Any],
) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO compliance_reports (id, product_name, category, mode, result_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (report_id, product_name, category, mode,
             json.dumps(result, ensure_ascii=False)),
        )


def get_compliance_reports() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM compliance_reports ORDER BY created_at DESC"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["result"] = json.loads(d.pop("result_json"))
            results.append(d)
        return results


def get_compliance_report(report_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM compliance_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        return d
```

注意：`restore_snapshot` 需要快照存储完整数据。修正 DDL，在 `eval_snapshots` 中增加 `samples_json` 列。在 `_SCHEMA_SQL` 的 `eval_snapshots` 建表语句中添加：

```sql
samples_json TEXT
```

同步修正 `create_snapshot` 函数，在创建快照时保存当前所有样本的完整 JSON：

```python
def create_snapshot(name: str, description: str = "") -> str:
    import uuid
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        samples = get_eval_samples()  # 获取当前全部样本
        samples_json = json.dumps(samples, ensure_ascii=False)
        cnt = len(samples)
        conn.execute(
            "INSERT INTO eval_snapshots (id, name, description, sample_count, samples_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, name, description, cnt, samples_json),
        )
    return snapshot_id
```

- [ ] **Step 2: 创建 `scripts/api/dependencies.py` — 共享依赖注入**

```python
"""FastAPI 共享依赖。"""

from lib.common.database import close_pool


def get_db():
    """数据库连接（由路由层按需使用，database.py 内部已管理连接池）。"""
    from api.database import get_connection
    with get_connection() as conn:
        yield conn


def on_shutdown():
    """应用关闭时清理连接池。"""
    close_pool()
```

- [ ] **Step 3: 创建测试 fixture `scripts/tests/api/conftest.py`**

```python
"""API 测试公共 fixture。"""

import os
import sqlite3
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _setup_api_path(monkeypatch):
    """确保 scripts/ 在 sys.path 中。"""
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def api_client(tmp_path):
    """创建使用临时数据库的 TestClient。"""
    db_path = tmp_path / "test_api.db"

    # mock 数据库路径
    from unittest.mock import patch

    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None):
        # 强制重建连接池
        from lib.common import database as db_mod
        db_mod._connection_pool = None

        from api.database import init_db
        init_db()

        from api.app import app
        with TestClient(app) as client:
            yield client

    # 清理
    try:
        from lib.common import database as db_mod
        db_mod.close_pool()
    except Exception:
        pass
```

- [ ] **Step 4: 创建 `scripts/tests/api/test_database.py`**

```python
"""数据库层单元测试。"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _setup_path():
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def db(tmp_path):
    """初始化测试数据库。"""
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()
        yield
        db_mod.close_pool()


class TestConversations:
    def test_create_and_get_conversations(self, db):
        from api.database import create_conversation, get_conversations
        create_conversation("conv-1", "测试对话")
        convs = get_conversations()
        assert len(convs) == 1
        assert convs[0]["id"] == "conv-1"
        assert convs[0]["title"] == "测试对话"
        assert convs[0]["message_count"] == 0

    def test_add_and_get_messages(self, db):
        from api.database import (
            create_conversation, add_message, get_messages,
        )
        create_conversation("conv-1")
        add_message("conv-1", "user", "健康保险等待期多久？")
        add_message(
            "conv-1", "assistant", "根据法规，等待期不超过180天。",
            citations=[{"source_idx": 0, "law_name": "保险法", "article_number": "第X条", "content": "..."}],
            sources=[{"law_name": "保险法", "article_number": "第X条", "content": "..."}],
        )
        msgs = get_messages("conv-1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert len(msgs[1]["citations"]) == 1
        assert len(msgs[1]["sources"]) == 1

    def test_delete_conversation(self, db):
        from api.database import (
            create_conversation, add_message, delete_conversation,
            get_conversations,
        )
        create_conversation("conv-1")
        add_message("conv-1", "user", "test")
        deleted = delete_conversation("conv-1")
        assert deleted == 1
        assert len(get_conversations()) == 0


class TestEvalSamples:
    def test_upsert_and_get(self, db):
        from api.database import upsert_eval_sample, get_eval_sample, get_eval_samples
        sample = {
            "id": "f001",
            "question": "健康保险等待期最长多少天？",
            "ground_truth": "180天",
            "evidence_docs": ["05_健康保险产品开发.md"],
            "evidence_keywords": ["等待期", "180天"],
            "question_type": "factual",
            "difficulty": "easy",
            "topic": "健康保险",
        }
        upsert_eval_sample(sample)
        result = get_eval_sample("f001")
        assert result is not None
        assert result["question"] == sample["question"]
        assert result["evidence_docs"] == ["05_健康保险产品开发.md"]

    def test_filter_by_type(self, db):
        from api.database import upsert_eval_sample, get_eval_samples
        upsert_eval_sample({
            "id": "f001", "question": "q1", "question_type": "factual",
            "difficulty": "easy", "topic": "",
        })
        upsert_eval_sample({
            "id": "m001", "question": "q2", "question_type": "multi_hop",
            "difficulty": "hard", "topic": "",
        })
        factual = get_eval_samples(question_type="factual")
        assert len(factual) == 1
        assert factual[0]["id"] == "f001"

    def test_delete_sample(self, db):
        from api.database import upsert_eval_sample, delete_eval_sample, get_eval_sample
        upsert_eval_sample({"id": "f001", "question": "q1"})
        assert delete_eval_sample("f001") is True
        assert get_eval_sample("f001") is None

    def test_import_samples(self, db):
        from api.database import import_eval_samples, eval_sample_count
        samples = [
            {"id": "f001", "question": "q1"},
            {"id": "f002", "question": "q2"},
        ]
        count = import_eval_samples(samples)
        assert count == 2
        assert eval_sample_count() == 2

    def test_import_idempotent(self, db):
        from api.database import import_eval_samples, eval_sample_count
        samples = [{"id": "f001", "question": "q1"}]
        import_eval_samples(samples)
        import_eval_samples(samples)
        assert eval_sample_count() == 1


class TestSnapshots:
    def test_create_and_list(self, db):
        from api.database import (
            upsert_eval_sample, create_snapshot, get_snapshots,
        )
        upsert_eval_sample({"id": "f001", "question": "q1"})
        snap_id = create_snapshot("v1", "初始版本")
        snaps = get_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["id"] == snap_id
        assert snaps[0]["sample_count"] == 1
        assert snaps[0]["name"] == "v1"

    def test_restore_snapshot(self, db):
        from api.database import (
            upsert_eval_sample, create_snapshot, restore_snapshot,
            get_eval_samples, delete_eval_sample,
        )
        upsert_eval_sample({"id": "f001", "question": "q1"})
        upsert_eval_sample({"id": "f002", "question": "q2"})
        snap_id = create_snapshot("v1")
        delete_eval_sample("f002")
        assert len(get_eval_samples()) == 1
        restored = restore_snapshot(snap_id)
        assert restored == 2
        assert len(get_eval_samples()) == 2


class TestEvalRuns:
    def test_create_and_get(self, db):
        from api.database import create_eval_run, get_eval_run
        create_eval_run("run-1", "full", {"top_k": 5})
        run = get_eval_run("run-1")
        assert run is not None
        assert run["mode"] == "full"
        assert run["status"] == "pending"
        assert run["config"]["top_k"] == 5

    def test_update_status(self, db):
        from api.database import create_eval_run, update_eval_run_status, get_eval_run
        create_eval_run("run-1", "retrieval", {})
        update_eval_run_status("run-1", "running", progress=5, total=30)
        run = get_eval_run("run-1")
        assert run["status"] == "running"
        assert run["progress"] == 5
        assert run["total"] == 30

    def test_save_and_get_report(self, db):
        from api.database import (
            create_eval_run, save_eval_report, get_eval_run,
        )
        create_eval_run("run-1", "full", {})
        report = {"retrieval": {"precision_at_k": 0.8}, "generation": {}}
        save_eval_report("run-1", report)
        run = get_eval_run("run-1")
        assert run["report"]["retrieval"]["precision_at_k"] == 0.8


class TestComplianceReports:
    def test_save_and_get(self, db):
        from api.database import save_compliance_report, get_compliance_report, get_compliance_reports
        result = {
            "summary": {"compliant": 3, "non_compliant": 1, "attention": 0},
            "items": [{"param": "等待期", "status": "compliant"}],
        }
        save_compliance_report("cr-1", "产品A", "健康险", "product", result)
        report = get_compliance_report("cr-1")
        assert report is not None
        assert report["result"]["summary"]["compliant"] == 3
        reports = get_compliance_reports()
        assert len(reports) == 1
```

- [ ] **Step 5: 运行数据库测试**

```bash
cd scripts && python -m pytest tests/api/test_database.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/api/database.py scripts/api/dependencies.py \
       scripts/api/__init__.py scripts/tests/api/ \
       scripts/requirements.txt
git commit -m "feat(api): add database layer with DDL and data access functions"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `scripts/api/schemas/__init__.py`
- Create: `scripts/api/schemas/ask.py`
- Create: `scripts/api/schemas/knowledge.py`
- Create: `scripts/api/schemas/eval.py`
- Create: `scripts/api/schemas/compliance.py`

- [ ] **Step 1: 创建 `scripts/api/schemas/ask.py`**

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="对话 ID，为空则新建对话")
    mode: str = Field("qa", pattern="^(qa|search)$", description="qa=智能问答, search=精确检索")


class CitationOut(BaseModel):
    source_idx: int
    law_name: str
    article_number: str
    content: str


class SourceOut(BaseModel):
    law_name: str
    article_number: str = ""
    category: str = ""
    content: str
    source_file: str = ""
    hierarchy_path: str = ""


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    citations: List[CitationOut] = []
    sources: List[SourceOut] = []
    timestamp: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int = 0


class ChatSSEEvent(BaseModel):
    """SSE 事件结构（JSON 序列化后发送）。"""
    type: str  # "token" | "done" | "sources" | "error"
    data: Any = None
```

- [ ] **Step 2: 创建 `scripts/api/schemas/knowledge.py`**

```python
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    name: str
    file_path: str
    clause_count: int = 0
    file_size: int = 0
    indexed_at: Optional[str] = None
    status: str = "indexed"


class ImportRequest(BaseModel):
    file_path: Optional[str] = Field(None, description="服务器端文件路径")
    file_pattern: str = Field("*.md", description="文件匹配模式")


class RebuildRequest(BaseModel):
    file_pattern: str = Field("*.md", description="文件匹配模式")
    force: bool = Field(False, description="是否强制重建")


class IndexStatus(BaseModel):
    vector_db: Dict[str, Any] = {}
    bm25: Dict[str, Any] = {}
    document_count: int = 0


class TaskStatus(BaseModel):
    task_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    progress: str = ""
    result: Optional[Dict[str, Any]] = None
```

- [ ] **Step 3: 创建 `scripts/api/schemas/eval.py`**

```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class EvalSampleCreate(BaseModel):
    id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    ground_truth: str = ""
    evidence_docs: List[str] = []
    evidence_keywords: List[str] = []
    question_type: str = Field("factual", pattern="^(factual|multi_hop|negative|colloquial)$")
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    topic: str = ""


class EvalSampleOut(BaseModel):
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: str
    difficulty: str
    topic: str
    created_at: str
    updated_at: str


class ImportSamplesRequest(BaseModel):
    samples: List[EvalSampleCreate]


class EvalRunRequest(BaseModel):
    mode: str = Field("full", pattern="^(retrieval|generation|full)$")
    top_k: int = Field(5, ge=1, le=20)
    chunking: str = Field("semantic", pattern="^(semantic|fixed)$")


class CompareRequest(BaseModel):
    baseline_id: str
    compare_id: str


class SnapshotCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
```

- [ ] **Step 4: 创建 `scripts/api/schemas/compliance.py`**

```python
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ProductCheckRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="产品名称")
    category: str = Field(..., min_length=1, description="险种类型")
    params: Dict[str, Any] = Field(..., description="产品参数键值对")


class DocumentCheckRequest(BaseModel):
    document_content: str = Field(..., min_length=1, description="条款文档内容")
    product_name: Optional[str] = Field(None, description="产品名称（可选）")


class ComplianceItem(BaseModel):
    param: str
    value: Any = None
    requirement: str = ""
    status: str = Field(..., pattern="^(compliant|non_compliant|attention)$")
    source: Optional[str] = None
    suggestion: Optional[str] = None


class ComplianceReportOut(BaseModel):
    id: str
    product_name: str
    category: str
    mode: str
    result: Dict[str, Any]
    created_at: str
```

- [ ] **Step 5: Commit**

```bash
git add scripts/api/schemas/
git commit -m "feat(api): add Pydantic schemas for all API modules"
```

---

## Task 4: 法规问答路由 (/api/ask/*)

**Files:**
- Create: `scripts/api/routers/__init__.py`
- Create: `scripts/api/routers/ask.py`
- Modify: `scripts/api/app.py` (注册路由、lifespan 初始化 RAGEngine)
- Create: `scripts/tests/api/test_ask.py`

- [ ] **Step 1: 创建 `scripts/api/routers/__init__.py`**

```python
```

- [ ] **Step 2: 创建 `scripts/api/routers/ask.py`**

```python
"""法规问答路由 — 对话式问答 + 精确检索。"""

import json
import uuid
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.schemas.ask import (
    ChatRequest, ConversationOut, MessageOut, ChatSSEEvent,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ask", tags=["法规问答"])


def _get_engine():
    """延迟获取 RAGEngine 单例（由 app lifespan 初始化）。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise HTTPException(status_code=503, detail="RAG 引擎尚未就绪")
    return rag_engine


@router.post("/chat")
async def chat(req: ChatRequest):
    """流式问答接口。返回 SSE 事件流。"""

    # 对话管理
    conversation_id = req.conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
    from api.database import create_conversation, add_message, get_eval_sample
    create_conversation(conversation_id, title=req.question[:50])

    # 保存用户消息
    add_message(conversation_id, "user", req.question)

    engine = _get_engine()

    if req.mode == "search":
        # 精确检索模式：直接返回结构化结果
        try:
            results = engine.search(req.question)
            content = json.dumps(results, ensure_ascii=False)
            add_message(conversation_id, "assistant", content, sources=results)
            return {
                "conversation_id": conversation_id,
                "mode": "search",
                "content": content,
                "sources": results,
            }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    # QA 模式：SSE 流式
    async def event_stream():
        try:
            answer_parts = []
            # 在线程中运行同步 ask()
            result = await asyncio.to_thread(engine.ask, req.question)

            # 逐字符发送（模拟流式）
            answer = result.get("answer", "")
            chunk_size = 4  # 每次发送的字符数
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i : i + chunk_size]
                answer_parts.append(chunk)
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "token", "data": chunk}, ensure_ascii=False
                    ),
                }
                await asyncio.sleep(0.01)

            # 发送完成事件，附带 citations 和 sources
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "done",
                        "data": {
                            "conversation_id": conversation_id,
                            "citations": result.get("citations", []),
                            "sources": result.get("sources", []),
                            "faithfulness_score": result.get("faithfulness_score"),
                        },
                    },
                    ensure_ascii=False,
                ),
            }

            # 保存助手回复
            add_message(
                conversation_id,
                "assistant",
                answer,
                citations=result.get("citations", []),
                sources=result.get("sources", []),
            )
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_stream())


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations():
    from api.database import get_conversations
    return get_conversations()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str):
    from api.database import get_messages
    msgs = get_messages(conversation_id)
    if not msgs:
        raise HTTPException(status_code=404, detail="对话不存在")
    return msgs


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    from api.database import delete_conversation
    count = delete_conversation(conversation_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"deleted_messages": count}
```

- [ ] **Step 3: 更新 `scripts/api/app.py` — 注册路由和 lifespan**

```python
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# RAGEngine 全局单例，由 lifespan 初始化
rag_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_engine
    from api.database import init_db
    init_db()
    logger.info("数据库初始化完成")

    try:
        from lib.rag_engine import create_qa_engine
        rag_engine = create_qa_engine()
        rag_engine.initialize()
        logger.info("RAG 引擎初始化完成")
    except Exception as e:
        logger.warning(f"RAG 引擎初始化失败（问答功能不可用）: {e}")

    yield

    if rag_engine is not None:
        rag_engine.cleanup()
        logger.info("RAG 引擎已清理")

    from api.dependencies import on_shutdown
    on_shutdown()


app = FastAPI(
    title="Actuary Sleuth - 法规知识平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from api.routers import ask, knowledge, eval as eval_router, compliance
app.include_router(ask.router)
app.include_router(knowledge.router)
app.include_router(eval_router.router)
app.include_router(compliance.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "rag_engine": rag_engine is not None}
```

注意：此时 `knowledge`, `eval`, `compliance` 路由文件还不存在。先创建空占位文件使 app 可启动。

创建 `scripts/api/routers/knowledge.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/kb", tags=["知识库管理"])
```

创建 `scripts/api/routers/eval.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/eval", tags=["评估管理"])
```

创建 `scripts/api/routers/compliance.py`:
```python
from fastapi import APIRouter
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])
```

- [ ] **Step 4: 创建 `scripts/tests/api/test_ask.py`**

```python
"""问答路由测试。"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture(autouse=True)
def _setup_path():
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def client(tmp_path):
    from unittest.mock import patch, MagicMock
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        # Mock RAGEngine
        mock_engine = MagicMock()
        mock_engine.search.return_value = [
            {"law_name": "保险法", "article_number": "第一条", "content": "测试内容",
             "category": "保险", "source_file": "test.md", "hierarchy_path": ""}
        ]
        mock_engine.ask.return_value = {
            "answer": "根据法规，等待期不超过180天。",
            "citations": [{"source_idx": 0, "law_name": "保险法", "article_number": "第一条", "content": "..."}],
            "sources": [{"law_name": "保险法", "article_number": "第一条", "content": "...",
                         "category": "", "source_file": "test.md", "hierarchy_path": ""}],
        }

        with patch("api.app.rag_engine", mock_engine):
            from api.app import app
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestSearchMode:
    def test_search_returns_results(self, client):
        resp = client.post("/api/ask/chat", json={
            "question": "等待期多久",
            "mode": "search",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "search"
        assert len(data["sources"]) == 1


class TestConversationManagement:
    def test_list_empty_conversations(self, client):
        resp = client.get("/api/ask/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_conversation_created_after_chat(self, client):
        client.post("/api/ask/chat", json={"question": "测试问题"})
        resp = client.get("/api/ask/conversations")
        convs = resp.json()
        assert len(convs) == 1

    def test_get_conversation_messages(self, client):
        resp = client.post("/api/ask/chat", json={"question": "测试", "mode": "search"})
        conv_id = resp.json()["conversation_id"]
        resp = client.get(f"/api/ask/conversations/{conv_id}/messages")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 2  # user + assistant

    def test_delete_conversation(self, client):
        resp = client.post("/api/ask/chat", json={"question": "测试", "mode": "search"})
        conv_id = resp.json()["conversation_id"]
        resp = client.delete(f"/api/ask/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted_messages"] == 2

    def test_delete_nonexistent_conversation(self, client):
        resp = client.delete("/api/ask/conversations/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 5: 运行问答测试**

```bash
cd scripts && python -m pytest tests/api/test_ask.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/api/routers/ scripts/api/app.py scripts/tests/api/test_ask.py
git commit -m "feat(api): add ask router with chat SSE and conversation management"
```

---

## Task 5: 知识库管理路由 (/api/kb/*)

**Files:**
- Modify: `scripts/api/routers/knowledge.py` (完整实现)
- Create: `scripts/tests/api/test_knowledge.py`

- [ ] **Step 1: 实现 `scripts/api/routers/knowledge.py`**

```python
"""知识库管理路由 — 文档列表、导入、重建、预览。"""

import os
import uuid
import asyncio
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from api.schemas.knowledge import (
    DocumentOut, ImportRequest, RebuildRequest, IndexStatus, TaskStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb", tags=["知识库管理"])

# 异步任务状态存储（内存，进程重启后丢失）
_tasks: Dict[str, Dict[str, Any]] = {}


def _get_config():
    from lib.rag_engine.config import get_config
    return get_config()


def _get_regulations_dir() -> Path:
    config = _get_config()
    return Path(config.regulations_dir)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents():
    """列出已索引的法规文档。"""
    reg_dir = _get_regulations_dir()
    documents = []
    if reg_dir.exists():
        for f in sorted(reg_dir.glob("*.md")):
            stat = f.stat()
            # 粗略估算条款数（以"第X条"为标记）
            content = f.read_text(encoding="utf-8", errors="ignore")
            clause_count = content.count("第") - content.count("第一百") * 0  # 简化
            documents.append(DocumentOut(
                name=f.name,
                file_path=str(f.relative_to(reg_dir.parent)),
                clause_count=len([l for l in content.split("\n") if l.strip().startswith("第")]),
                file_size=stat.st_size,
            ))
    return documents


@router.post("/documents/import")
async def import_documents(req: ImportRequest):
    """导入法规文档（指定路径或模式）。"""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {"status": "pending", "progress": "", "result": None}

    async def _run_import():
        try:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = "正在导入..."

            config = _get_config()
            from lib.rag_engine.data_importer import RegulationDataImporter
            importer = RegulationDataImporter(config)

            if req.file_path:
                result = importer.parse_single_file(req.file_path)
                importer.import_to_vector_db([result])
            else:
                result = importer.import_all(file_pattern=req.file_pattern)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = result if isinstance(result, dict) else {"stats": result}
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)

    asyncio.create_task(_run_import())
    return {"task_id": task_id, "status": "pending"}


@router.post("/documents/rebuild")
async def rebuild_index(req: RebuildRequest):
    """重建知识库索引。"""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {"status": "pending", "progress": "", "result": None}

    async def _run_rebuild():
        try:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = "正在重建索引..."

            config = _get_config()
            from lib.rag_engine.data_importer import RegulationDataImporter
            importer = RegulationDataImporter(config)
            result = importer.rebuild_knowledge_base(file_pattern=req.file_pattern)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = result
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)

    asyncio.create_task(_run_rebuild())
    return {"task_id": task_id, "status": "pending"}


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """查询异步任务状态。"""
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatus(
        task_id=task_id,
        status=task["status"],
        progress=task.get("progress", ""),
        result=task.get("result"),
    )


@router.get("/documents/{document_name}/preview")
async def preview_document(document_name: str):
    """预览法规文档内容。"""
    reg_dir = _get_regulations_dir()
    file_path = reg_dir / document_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    # 截取前 5000 字符
    return {"name": document_name, "content": content[:5000], "total_chars": len(content)}


@router.get("/status", response_model=IndexStatus)
async def get_index_status():
    """获取索引状态。"""
    try:
        config = _get_config()

        from lib.rag_engine.index_manager import VectorIndexManager
        vm = VectorIndexManager(config)
        vector_stats = vm.get_index_stats()

        from lib.rag_engine.bm25_index import BM25Index
        bm25_path = Path(config.vector_db_path) / "bm25_index"
        bm25_index = BM25Index.load(bm25_path) if bm25_path.exists() else None

        return IndexStatus(
            vector_db=vector_stats,
            bm25={
                "loaded": bm25_index is not None,
                "doc_count": bm25_index.doc_count if bm25_index else 0,
            } if bm25_index else {"loaded": False, "doc_count": 0},
            document_count=vector_stats.get("doc_count", 0),
        )
    except Exception as e:
        return IndexStatus(vector_db={"status": "error", "error": str(e)})
```

- [ ] **Step 2: 创建 `scripts/tests/api/test_knowledge.py`**

```python
"""知识库管理路由测试。"""

import os
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_path():
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def client(tmp_path):
    from unittest.mock import patch, MagicMock

    # 创建模拟法规目录
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    (refs_dir / "01_保险法.md").write_text("# 保险法\n\n第一条 为了规范保险活动...", encoding="utf-8")
    (refs_dir / "02_健康险.md").write_text("# 健康保险管理办法\n\n第一条 ...", encoding="utf-8")

    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)
    mock_config.regulations_dir = str(refs_dir)

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.rag_engine.config.get_config", return_value=mock_config):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestListDocuments:
    def test_list_documents(self, client):
        resp = client.get("/api/kb/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 2
        assert docs[0]["name"] == "01_保险法.md"

    def test_document_has_metadata(self, client):
        resp = client.get("/api/kb/documents")
        doc = resp.json()[0]
        assert "file_size" in doc
        assert "clause_count" in doc
        assert doc["file_size"] > 0


class TestPreviewDocument:
    def test_preview_existing(self, client):
        resp = client.get("/api/kb/documents/01_保险法.md/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert "保险法" in data["content"]
        assert data["total_chars"] > 0

    def test_preview_nonexistent(self, client):
        resp = client.get("/api/kb/documents/nonexistent.md/preview")
        assert resp.status_code == 404


class TestTaskStatus:
    def test_nonexistent_task(self, client):
        resp = client.get("/api/kb/tasks/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 3: 运行知识库测试**

```bash
cd scripts && python -m pytest tests/api/test_knowledge.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/knowledge.py scripts/tests/api/test_knowledge.py
git commit -m "feat(api): add knowledge base management router"
```

---

## Task 6: 评估数据集管理路由 (/api/eval/dataset/*)

**Files:**
- Modify: `scripts/api/routers/eval.py` (数据集管理部分)
- Create: `scripts/tests/api/test_eval.py` (数据集部分)

- [ ] **Step 1: 实现 `scripts/api/routers/eval.py` — 数据集管理路由**

```python
"""评估管理路由 — 数据集 CRUD + 快照 + 评估运行。"""

import uuid
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas.eval import (
    EvalSampleCreate, EvalSampleOut, ImportSamplesRequest,
    EvalRunRequest, CompareRequest, SnapshotCreate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/eval", tags=["评估管理"])

# 异步评估任务状态
_eval_tasks: dict = {}


# ── 数据集管理 ───────────────────────────────────────

def _ensure_default_dataset():
    """首次启动时从现有 JSON 导入默认数据集。"""
    from api.database import eval_sample_count
    if eval_sample_count() > 0:
        return
    try:
        from lib.rag_engine import load_eval_dataset
        samples = load_eval_dataset()
        from api.database import import_eval_samples
        count = import_eval_samples([s.to_dict() for s in samples])
        if count > 0:
            logger.info(f"已导入 {count} 条默认评测数据")
    except Exception as e:
        logger.warning(f"导入默认数据集失败: {e}")


# 在模块加载时尝试导入
_ensure_default_dataset()


@router.get("/dataset", response_model=list[EvalSampleOut])
async def list_eval_samples(
    question_type: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
):
    from api.database import get_eval_samples
    return get_eval_samples(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
    )


@router.post("/dataset/samples", response_model=EvalSampleOut)
async def create_eval_sample(sample: EvalSampleCreate):
    from api.database import upsert_eval_sample, get_eval_sample
    upsert_eval_sample(sample.model_dump())
    result = get_eval_sample(sample.id)
    if result is None:
        raise HTTPException(status_code=500, detail="创建失败")
    return result


@router.put("/dataset/samples/{sample_id}", response_model=EvalSampleOut)
async def update_eval_sample(sample_id: str, sample: EvalSampleCreate):
    from api.database import get_eval_sample, upsert_eval_sample
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    update_data = sample.model_dump()
    update_data["id"] = sample_id
    upsert_eval_sample(update_data)
    return get_eval_sample(sample_id)


@router.delete("/dataset/samples/{sample_id}")
async def delete_eval_sample(sample_id: str):
    from api.database import delete_eval_sample
    if not delete_eval_sample(sample_id):
        raise HTTPException(status_code=404, detail="样本不存在")
    return {"deleted": True}


@router.post("/dataset/import")
async def import_dataset(req: ImportSamplesRequest):
    from api.database import import_eval_samples
    samples = [s.model_dump() for s in req.samples]
    count = import_eval_samples(samples)
    return {"imported": count, "total": len(samples), "skipped": len(samples) - count}


@router.post("/dataset/snapshots")
async def create_snapshot(req: SnapshotCreate):
    from api.database import create_snapshot
    snap_id = create_snapshot(req.name, req.description)
    return {"snapshot_id": snap_id, "name": req.name}


@router.get("/dataset/snapshots")
async def list_snapshots():
    from api.database import get_snapshots
    return get_snapshots()


@router.post("/dataset/snapshots/{snapshot_id}/restore")
async def restore_snapshot(snapshot_id: str):
    from api.database import restore_snapshot, get_snapshots
    snap_ids = [s["id"] for s in get_snapshots()]
    if snapshot_id not in snap_ids:
        raise HTTPException(status_code=404, detail="快照不存在")
    count = restore_snapshot(snapshot_id)
    return {"restored": count}
```

- [ ] **Step 2: 创建 `scripts/tests/api/test_eval.py` — 数据集测试**

```python
"""评估路由测试 — 数据集管理部分。"""

import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _setup_path():
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("api.routers.eval._ensure_default_dataset"):  # 跳过自动导入
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestEvalSamplesCRUD:
    def test_create_sample(self, client):
        resp = client.post("/api/eval/dataset/samples", json={
            "id": "f001",
            "question": "健康保险等待期最长多少天？",
            "ground_truth": "180天",
            "question_type": "factual",
            "difficulty": "easy",
            "topic": "健康保险",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "f001"

    def test_list_samples(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1", "question_type": "factual",
        })
        resp = client.get("/api/eval/dataset")
        assert len(resp.json()) == 1

    def test_filter_by_type(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1", "question_type": "factual",
        })
        client.post("/api/eval/dataset/samples", json={
            "id": "m001", "question": "q2", "question_type": "multi_hop",
        })
        resp = client.get("/api/eval/dataset?question_type=factual")
        assert len(resp.json()) == 1

    def test_update_sample(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1",
        })
        resp = client.put("/api/eval/dataset/samples/f001", json={
            "id": "f001", "question": "q1-updated",
        })
        assert resp.status_code == 200
        assert resp.json()["question"] == "q1-updated"

    def test_update_nonexistent(self, client):
        resp = client.put("/api/eval/dataset/samples/nonexistent", json={
            "id": "nonexistent", "question": "q",
        })
        assert resp.status_code == 404

    def test_delete_sample(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1",
        })
        resp = client.delete("/api/eval/dataset/samples/f001")
        assert resp.status_code == 200
        assert len(client.get("/api/eval/dataset").json()) == 0

    def test_import_samples(self, client):
        resp = client.post("/api/eval/dataset/import", json={
            "samples": [
                {"id": "f001", "question": "q1"},
                {"id": "f002", "question": "q2"},
            ]
        })
        assert resp.json()["imported"] == 2


class TestSnapshots:
    def test_create_and_list(self, client):
        client.post("/api/eval/dataset/samples", json={"id": "f001", "question": "q1"})
        resp = client.post("/api/eval/dataset/snapshots", json={
            "name": "v1", "description": "初始版本",
        })
        assert resp.status_code == 200
        snap_id = resp.json()["snapshot_id"]

        resp = client.get("/api/eval/dataset/snapshots")
        assert len(resp.json()) == 1

    def test_restore(self, client):
        client.post("/api/eval/dataset/samples", json={"id": "f001", "question": "q1"})
        client.post("/api/eval/dataset/samples", json={"id": "f002", "question": "q2"})
        resp = client.post("/api/eval/dataset/snapshots", json={"name": "v1"})
        snap_id = resp.json()["snapshot_id"]

        client.delete("/api/eval/dataset/samples/f002")
        assert len(client.get("/api/eval/dataset").json()) == 1

        resp = client.post(f"/api/eval/dataset/snapshots/{snap_id}/restore")
        assert resp.json()["restored"] == 2
        assert len(client.get("/api/eval/dataset").json()) == 2
```

- [ ] **Step 3: 运行评估数据集测试**

```bash
cd scripts && python -m pytest tests/api/test_eval.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/eval.py scripts/tests/api/test_eval.py
git commit -m "feat(api): add eval dataset management router with snapshots"
```

---

## Task 7: 评估运行路由 (/api/eval/runs/*)

**Files:**
- Modify: `scripts/api/routers/eval.py` (追加评估运行路由)
- Modify: `scripts/tests/api/test_eval.py` (追加运行测试)

- [ ] **Step 1: 在 `scripts/api/routers/eval.py` 末尾追加评估运行路由**

```python
# ── 评估运行 ─────────────────────────────────────────


@router.post("/runs")
async def create_eval_run(req: EvalRunRequest):
    """触发评估运行。"""
    run_id = f"eval_{uuid.uuid4().hex[:8]}"

    from api.database import create_eval_run
    create_eval_run(run_id, req.mode, {
        "top_k": req.top_k,
        "chunking": req.chunking,
    })

    _eval_tasks[run_id] = {"status": "pending"}

    async def _run_eval():
        try:
            _eval_tasks[run_id]["status"] = "running"

            from api.app import rag_engine
            if rag_engine is None:
                raise RuntimeError("RAG 引擎未就绪")

            from api.database import (
                get_eval_samples, update_eval_run_status,
                save_eval_report, save_sample_result,
            )
            from lib.rag_engine.evaluator import (
                RetrievalEvaluator, GenerationEvaluator,
            )
            from lib.rag_engine.eval_dataset import EvalSample, QuestionType

            samples_data = get_eval_samples()
            samples = [
                EvalSample(
                    id=s["id"],
                    question=s["question"],
                    ground_truth=s["ground_truth"],
                    evidence_docs=s["evidence_docs"],
                    evidence_keywords=s["evidence_keywords"],
                    question_type=QuestionType(s["question_type"]),
                    difficulty=s["difficulty"],
                    topic=s["topic"],
                )
                for s in samples_data
            ]
            total = len(samples)
            update_eval_run_status(run_id, "running", progress=0, total=total)

            # 检索评估
            if req.mode in ("retrieval", "full"):
                ret_eval = RetrievalEvaluator(rag_engine)
                ret_report, ret_details = ret_eval.evaluate_batch(samples, top_k=req.top_k)
                for detail in ret_details:
                    sample_id = detail.get("sample_id", "")
                    save_sample_result(
                        run_id, sample_id,
                        retrieval_metrics=detail,
                    )
                    current = _eval_tasks[run_id].get("progress", 0) + 1
                    _eval_tasks[run_id]["progress"] = current
                    update_eval_run_status(run_id, "running", progress=current, total=total)

            # 生成评估
            gen_report = None
            if req.mode in ("generation", "full"):
                gen_eval = GenerationEvaluator(rag_engine=rag_engine)
                gen_report = gen_eval.evaluate_batch(samples, rag_engine=rag_engine)
                # 逐题保存生成结果
                for i, sample in enumerate(samples):
                    result = rag_engine.ask(sample.question)
                    gen_detail = gen_eval.evaluate(
                        sample,
                        [s.get("content", "") for s in result.get("sources", [])],
                        result.get("answer", ""),
                    )
                    save_sample_result(
                        run_id, sample.id,
                        retrieved_docs=result.get("sources", []),
                        generated_answer=result.get("answer", ""),
                        generation_metrics=gen_detail,
                    )

            # 构建完整报告
            report = {}
            if req.mode in ("retrieval", "full"):
                report["retrieval"] = ret_report.to_dict() if hasattr(ret_report, "to_dict") else vars(ret_report)
            if gen_report is not None:
                report["generation"] = gen_report.to_dict() if hasattr(gen_report, "to_dict") else vars(gen_report)
            report["total_samples"] = total
            report["failed_samples"] = []

            save_eval_report(run_id, report)
            update_eval_run_status(run_id, "completed")
            _eval_tasks[run_id]["status"] = "completed"

        except Exception as e:
            logger.error(f"Eval run {run_id} failed: {e}")
            update_eval_run_status(run_id, "failed")
            _eval_tasks[run_id]["status"] = "failed"
            _eval_tasks[run_id]["error"] = str(e)

    asyncio.create_task(_run_eval())
    return {"run_id": run_id, "status": "pending"}


@router.get("/runs/{run_id}/status")
async def get_eval_run_status(run_id: str):
    from api.database import get_eval_run
    run = get_eval_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    return {
        "run_id": run["id"],
        "mode": run["mode"],
        "status": run["status"],
        "progress": run["progress"],
        "total": run["total"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
    }


@router.get("/runs/{run_id}/report")
async def get_eval_report(run_id: str):
    from api.database import get_eval_run
    run = get_eval_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"评估尚未完成，当前状态: {run['status']}")
    return run.get("report", {})


@router.get("/runs/{run_id}/details")
async def get_eval_details(run_id: str):
    from api.database import get_eval_run, get_sample_results
    run = get_eval_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    results = get_sample_results(run_id)
    return {
        "run_id": run_id,
        "mode": run["mode"],
        "status": run["status"],
        "total_samples": run["total"],
        "details": results,
    }


@router.get("/runs")
async def list_eval_runs():
    from api.database import get_eval_runs
    return get_eval_runs()


@router.post("/runs/compare")
async def compare_eval_runs(req: CompareRequest):
    from api.database import get_eval_run

    baseline = get_eval_run(req.baseline_id)
    compare = get_eval_run(req.compare_id)
    if baseline is None or compare is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")

    baseline_report = baseline.get("report", {})
    compare_report = compare.get("report", {})

    diff = {}
    improved = []
    regressed = []

    for key in ["retrieval", "generation"]:
        b = baseline_report.get(key, {})
        c = compare_report.get(key, {})
        if not b or not c:
            continue
        for metric in ["precision_at_k", "recall_at_k", "mrr", "ndcg",
                        "faithfulness", "answer_relevancy", "answer_correctness"]:
            b_val = b.get(metric)
            c_val = c.get(metric)
            if b_val is None or c_val is None:
                continue
            delta = c_val - b_val
            pct = (delta / b_val * 100) if b_val != 0 else 0
            diff[f"{key}.{metric}"] = {
                "baseline": b_val,
                "compare": c_val,
                "delta": round(delta, 4),
                "pct_change": round(pct, 2),
            }
            if delta > 0:
                improved.append(f"{key}.{metric}")
            elif delta < 0:
                regressed.append(f"{key}.{metric}")

    return {
        "baseline_id": req.baseline_id,
        "compare_id": req.compare_id,
        "metrics_diff": diff,
        "improved": improved,
        "regressed": regressed,
    }


@router.get("/runs/{run_id}/export")
async def export_eval_report(run_id: str, format: str = "json"):
    from api.database import get_eval_run
    run = get_eval_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="评估尚未完成")

    report = run.get("report", {})
    if format == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "timestamp": run["started_at"],
            "report": report,
        })
    elif format == "md":
        from fastapi.responses import PlainTextResponse
        lines = [f"# 评估报告 {run_id}", f"模式: {run['mode']}", f"时间: {run['started_at']}", ""]
        for section, metrics in report.items():
            if isinstance(metrics, dict):
                lines.append(f"## {section}")
                for k, v in metrics.items():
                    if isinstance(v, (int, float)):
                        lines.append(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}")
        from fastapi.responses import Response
        return Response(content="\n".join(lines), media_type="text/markdown")
    else:
        raise HTTPException(status_code=400, detail="不支持的格式，可选: json, md")
```

- [ ] **Step 2: 在 `scripts/tests/api/test_eval.py` 末尾追加运行测试**

```python
class TestEvalRuns:
    def test_create_run(self, client):
        resp = client.post("/api/eval/runs", json={
            "mode": "retrieval", "top_k": 5,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
        run_id = resp.json()["run_id"]

        resp = client.get(f"/api/eval/runs/{run_id}/status")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "retrieval"

    def test_list_runs(self, client):
        client.post("/api/eval/runs", json={"mode": "retrieval"})
        resp = client.get("/api/eval/runs")
        assert len(resp.json()) == 1

    def test_nonexistent_run(self, client):
        resp = client.get("/api/eval/runs/nonexistent/status")
        assert resp.status_code == 404

    def test_compare_runs(self, client):
        # 创建两个完成状态的 run（直接写入数据库模拟）
        from api.database import create_eval_run, save_eval_report
        create_eval_run("run-a", "full", {})
        save_eval_report("run-a", {
            "retrieval": {"precision_at_k": 0.6, "recall_at_k": 0.5},
            "generation": {"faithfulness": 0.8},
        })
        create_eval_run("run-b", "full", {})
        save_eval_report("run-b", {
            "retrieval": {"precision_at_k": 0.8, "recall_at_k": 0.6},
            "generation": {"faithfulness": 0.9},
        })

        resp = client.post("/api/eval/runs/compare", json={
            "baseline_id": "run-a",
            "compare_id": "run-b",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["improved"]) >= 1
```

- [ ] **Step 3: 运行评估测试**

```bash
cd scripts && python -m pytest tests/api/test_eval.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/eval.py scripts/tests/api/test_eval.py
git commit -m "feat(api): add eval run router with async execution and comparison"
```

---

## Task 8: 合规检查路由 (/api/compliance/*)

**Files:**
- Modify: `scripts/api/routers/compliance.py` (完整实现)
- Create: `scripts/tests/api/test_compliance.py`

- [ ] **Step 1: 实现 `scripts/api/routers/compliance.py`**

```python
"""合规检查路由 — 产品参数检查 + 条款文档审查。"""

import uuid
import json
import asyncio
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from api.schemas.compliance import (
    ProductCheckRequest, DocumentCheckRequest, ComplianceReportOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])

# 合规检查 prompt 模板
_COMPLIANCE_PROMPT_PRODUCT = """你是一位保险法规合规专家。请根据以下产品参数和相关法规条款，逐项检查该产品是否符合法规要求。

## 产品信息
- 产品名称：{product_name}
- 险种类型：{category}
- 产品参数：{params_json}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<参数名称>",
            "value": "<产品实际值>",
            "requirement": "<法规要求>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源>",
            "suggestion": "<修改建议，仅不合规时填写>"
        }}
    ]
}}

注意：
1. 每个参数都要检查，未找到明确法规要求的标注为 attention
2. source 必须使用 [来源X] 格式引用法规条款
3. 仅输出 JSON，不要附加其他文字
"""

_COMPLIANCE_PROMPT_DOCUMENT = """你是一位保险法规合规专家。请审查以下保险条款文档，检查是否符合相关法规要求。

## 条款文档内容
{document_content}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<检查项名称>",
            "value": "<条款中的实际内容>",
            "requirement": "<法规要求>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源>",
            "suggestion": "<修改建议>"
        }}
    ],
    "extracted_params": {{
        "<参数名>": "<提取值>"
    }}
}}

注意：
1. 先提取条款中的关键参数，再逐项检查合规性
2. 检查项包括但不限于：等待期、免赔额、保险期间、缴费方式、免责条款等
3. source 必须使用 [来源X] 格式引用法规条款
4. 仅输出 JSON，不要附加其他文字
"""


def _get_engine():
    from api.app import rag_engine
    if rag_engine is None:
        raise HTTPException(status_code=503, detail="RAG 引擎尚未就绪")
    return rag_engine


def _run_compliance_check(engine, prompt: str) -> Dict[str, Any]:
    """执行合规检查：检索法规 → LLM 判断 → 解析结果。"""
    # 从 prompt 中提取查询关键词用于检索
    result = engine.ask(prompt, include_sources=True)
    answer = result.get("answer", "")

    # 尝试解析 LLM 返回的 JSON
    try:
        # 提取 JSON 块
        json_start = answer.find("{")
        json_end = answer.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(answer[json_start:json_end])
        else:
            parsed = {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": []}
    except json.JSONDecodeError:
        parsed = {
            "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
            "items": [],
            "raw_answer": answer,
        }

    parsed["sources"] = result.get("sources", [])
    parsed["citations"] = result.get("citations", [])
    return parsed


@router.post("/check/product", response_model=ComplianceReportOut)
async def check_product(req: ProductCheckRequest):
    """产品参数合规检查。"""
    engine = _get_engine()

    # 构建查询
    query = f"{req.category} 保险产品合规要求 {req.product_name}"
    search_results = engine.search(query, top_k=10)

    context = "\n\n".join(
        f"[来源{i+1}] {r.get('law_name', '')} {r.get('article_number', '')}\n{r.get('content', '')}"
        for i, r in enumerate(search_results)
    )

    prompt = _COMPLIANCE_PROMPT_PRODUCT.format(
        product_name=req.product_name,
        category=req.category,
        params_json=json.dumps(req.params, ensure_ascii=False),
        context=context,
    )

    try:
        result = await asyncio.to_thread(_run_compliance_check, engine, prompt)
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        raise HTTPException(status_code=500, detail=f"合规检查失败: {e}")

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    from api.database import save_compliance_report
    save_compliance_report(report_id, req.product_name, req.category, "product", result)

    return ComplianceReportOut(
        id=report_id,
        product_name=req.product_name,
        category=req.category,
        mode="product",
        result=result,
        created_at="",
    )


@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    """条款文档合规审查。"""
    engine = _get_engine()

    # 先用 LLM 提取关键信息用于检索
    extract_prompt = f"请从以下保险条款中提取关键参数（险种类型、等待期、免赔额等），以 JSON 格式输出：\n\n{req.document_content[:3000]}"
    from lib.llm.factory import LLMClientFactory
    llm = LLMClientFactory.get_qa_llm()
    extracted = llm.chat([{"role": "user", "content": extract_prompt}])

    # 用提取的信息检索法规
    query = f"保险合规要求 {extracted[:200]}"
    search_results = engine.search(query, top_k=10)

    context = "\n\n".join(
        f"[来源{i+1}] {r.get('law_name', '')} {r.get('article_number', '')}\n{r.get('content', '')}"
        for i, r in enumerate(search_results)
    )

    prompt = _COMPLIANCE_PROMPT_DOCUMENT.format(
        document_content=req.document_content[:5000],
        context=context,
    )

    try:
        result = await asyncio.to_thread(_run_compliance_check, engine, prompt)
    except Exception as e:
        logger.error(f"Document check failed: {e}")
        raise HTTPException(status_code=500, detail=f"条款审查失败: {e}")

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    product_name = req.product_name or "未命名产品"
    from api.database import save_compliance_report
    save_compliance_report(report_id, product_name, "", "document", result)

    return ComplianceReportOut(
        id=report_id,
        product_name=product_name,
        category="",
        mode="document",
        result=result,
        created_at="",
    )


@router.get("/reports", response_model=list[ComplianceReportOut])
async def list_compliance_reports():
    from api.database import get_compliance_reports
    return get_compliance_reports()


@router.get("/reports/{report_id}", response_model=ComplianceReportOut)
async def get_compliance_report(report_id: str):
    from api.database import get_compliance_report
    report = get_compliance_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report
```

- [ ] **Step 2: 创建 `scripts/tests/api/test_compliance.py`**

```python
"""合规检查路由测试。"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture(autouse=True)
def _setup_path():
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    if scripts_dir not in os.sys.path:
        os.sys.path.insert(0, scripts_dir)


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    # Mock RAGEngine
    mock_engine = MagicMock()
    mock_engine.search.return_value = [
        {"law_name": "保险法", "article_number": "第一条", "content": "法规内容",
         "category": "", "source_file": "test.md", "hierarchy_path": ""}
    ]
    mock_engine.ask.return_value = {
        "answer": json.dumps({
            "summary": {"compliant": 2, "non_compliant": 0, "attention": 1},
            "items": [
                {"param": "等待期", "value": "90天", "requirement": "≤180天",
                 "status": "compliant", "source": "[来源1]"},
                {"param": "免赔额", "value": "0元", "requirement": "无限制",
                 "status": "compliant", "source": "[来源1]"},
                {"param": "犹豫期", "value": "10天", "requirement": "≥15天",
                 "status": "attention", "source": "未找到明确法规限制"},
            ],
        }, ensure_ascii=False),
        "sources": mock_engine.search.return_value,
        "citations": [],
    }

    # Mock LLM for document check
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"category": "健康险", "waiting_period": "90天"}'

    with patch("lib.common.database.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("api.app.rag_engine", mock_engine), \
         patch("lib.llm.factory.LLMClientFactory.get_qa_llm", return_value=mock_llm):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestProductCheck:
    def test_check_product(self, client):
        resp = client.post("/api/compliance/check/product", json={
            "product_name": "测试健康险A",
            "category": "健康险",
            "params": {"等待期": "90天", "免赔额": "0元", "保险期间": "1年"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "product"
        assert data["product_name"] == "测试健康险A"
        assert data["result"]["summary"]["compliant"] >= 1


class TestDocumentCheck:
    def test_check_document(self, client):
        resp = client.post("/api/compliance/check/document", json={
            "document_content": "# 测试健康保险条款\n\n等待期：自合同生效日起90天\n免赔额：0元",
            "product_name": "测试产品B",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "document"


class TestReportHistory:
    def test_list_reports(self, client):
        # 先创建一个报告
        client.post("/api/compliance/check/product", json={
            "product_name": "测试产品", "category": "健康险", "params": {},
        })
        resp = client.get("/api/compliance/reports")
        assert len(resp.json()) == 1

    def test_get_report(self, client):
        resp = client.post("/api/compliance/check/product", json={
            "product_name": "测试产品", "category": "健康险", "params": {},
        })
        report_id = resp.json()["id"]
        resp = client.get(f"/api/compliance/reports/{report_id}")
        assert resp.status_code == 200

    def test_nonexistent_report(self, client):
        resp = client.get("/api/compliance/reports/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 3: 运行合规检查测试**

```bash
cd scripts && python -m pytest tests/api/test_compliance.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/compliance.py scripts/tests/api/test_compliance.py
git commit -m "feat(api): add compliance check router with product and document modes"
```

---

## Task 9: 集成验证与启动脚本

**Files:**
- Modify: `scripts/requirements.txt`
- Create: `scripts/run_api.py` (启动入口)

- [ ] **Step 1: 更新 `scripts/requirements.txt`，追加依赖**

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sse-starlette>=1.6.0
python-multipart>=0.0.6
```

- [ ] **Step 2: 创建 `scripts/run_api.py`**

```python
#!/usr/bin/env python3
"""启动 RAG 法规知识平台 API 服务。"""

import sys
import os
import uvicorn

if __name__ == "__main__":
    # 确保 scripts/ 在 sys.path
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
```

- [ ] **Step 3: 运行全部 API 测试**

```bash
cd scripts && python -m pytest tests/api/ -v
```

Expected: ALL PASS

- [ ] **Step 4: 启动服务验证健康检查**

```bash
cd scripts && python run_api.py &
sleep 3 && curl -s http://localhost:8000/api/health
kill %1
```

Expected: `{"status":"ok","rag_engine":true}`

- [ ] **Step 5: Commit**

```bash
git add scripts/run_api.py scripts/requirements.txt
git commit -m "feat(api): add run script and update dependencies"
```

---

## Self-Review Checklist

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 法规问答：SSE 流式 + 对话管理 + 精确检索 | Task 4 |
| 2 | 知识库：文档列表 + 导入 + 重建 + 预览 + 状态 | Task 5 |
| 3 | 评估数据集：CRUD + 筛选 + 批量导入 + 快照回滚 | Task 6 |
| 4 | 评估运行：异步执行 + 状态轮询 + 报告 + 对比 + 导出 | Task 7 |
| 5 | 合规检查：产品参数 + 条款文档 + 报告历史 | Task 8 |
| 6 | 数据库：SQLite 建表 + 所有数据访问函数 + 测试 | Task 2 |
| 7 | Pydantic schemas：所有请求/响应模型 | Task 3 |
| 8 | 不修改现有 `scripts/lib/` 核心逻辑 | 全部 Task |
| 9 | 复用现有 `get_connection()` 连接池 | Task 2 |
| 10 | 一期不做用户认证 | 设计约束已遵守 |
| 11 | SSE 仅用于问答，其他用轮询 | Task 4/5/7 |
