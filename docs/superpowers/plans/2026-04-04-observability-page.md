# Observability Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Trace viewing page at `/observability` and extend AskPage's conversation list with search and batch delete.

**Architecture:** Backend adds database query functions and a new `/api/observability` router. Frontend adds a new ObservabilityPage with left-right split layout (TraceList + TraceDetail reusing TracePanel). AskPage's ChatPanel gets a search input and batch delete capability.

**Tech Stack:** Python/FastAPI/SQLite (backend), React/TypeScript/Ant Design/Zustand (frontend), pytest (testing)

---

### Task 1: Backend — Database functions for conversation search and batch delete

**Files:**
- Modify: `scripts/api/database.py`

- [ ] **Step 1: Write the failing test**

Create test file `scripts/tests/api/test_observability_db.py`:

```python
"""Observability 数据库函数测试。"""
import pytest
from scripts.tests.api.conftest import *


class TestConversationSearch:
    def test_search_conversations_no_filter(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="", page=1, size=10)
        assert rows[1] == 3  # total count

    def test_search_conversations_by_title(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="等待期", page=1, size=10)
        assert rows[1] == 2
        titles = [r["title"] for r in rows[0]]
        assert "健康保险等待期" in titles
        assert "等待期相关问题" in titles

    def test_search_conversations_pagination(self, _patch_database, make_conversation):
        import api.database as db
        for i in range(5):
            make_conversation(f"conv_{i}", f"对话 {i}")
        rows = db.search_conversations(search="", page=1, size=2)
        assert len(rows[0]) == 2
        assert rows[1] == 5


class TestBatchDeleteConversations:
    def test_batch_delete(self, _patch_database, make_conversation, make_message):
        import api.database as db
        make_conversation("conv_del1", "删除1")
        make_message("conv_del1", "user", "问题1")
        make_message("conv_del1", "assistant", "回答1")
        make_conversation("conv_del2", "删除2")
        make_message("conv_del2", "user", "问题2")
        make_conversation("conv_keep", "保留")
        deleted = db.batch_delete_conversations(["conv_del1", "conv_del2"])
        assert deleted == 2
        remaining = db.get_conversations()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "conv_keep"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'` or `ImportError` / `AttributeError` for missing functions

- [ ] **Step 3: Write minimal implementation**

In `scripts/api/database.py`, add these two functions after the existing `delete_conversation` function (around line 175):

```python
def search_conversations(search: str = "", page: int = 1, size: int = 20) -> tuple:
    """分页搜索会话，按标题模糊匹配。返回 (rows, total_count)。"""
    where = ""
    params: list = []
    if search:
        where = "WHERE c.title LIKE ?"
        params.append(f"%{search}%")
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM conversations c {where}", params
        ).fetchone()["cnt"]
        offset = (page - 1) * size
        rows = conn.execute(f"""
            SELECT c.id, c.title, c.created_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            {where}
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [size, offset]).fetchall()
        return [dict(r) for r in rows], total


def batch_delete_conversations(ids: list) -> int:
    """批量删除会话及其消息。返回删除的会话数。"""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        cur = conn.execute(
            f"DELETE FROM messages WHERE conversation_id IN ({placeholders})", ids
        )
        conn.execute(
            f"DELETE FROM conversations WHERE id IN ({placeholders})", ids
        )
        return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/api/database.py scripts/tests/api/test_observability_db.py
git commit -m "feat: add search_conversations and batch_delete_conversations DB functions"
```

---

### Task 2: Backend — Database functions for trace search, detail, and cleanup

**Files:**
- Modify: `scripts/api/database.py`
- Modify: `scripts/tests/api/test_observability_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/api/test_observability_db.py`:

```python
class TestTraceSearch:
    def _create_trace(self, trace_id="t1", message_id=1, conversation_id="conv_a", status="ok"):
        import api.database as db
        db.save_trace(trace_id, message_id, conversation_id)
        db.save_spans([{
            "trace_id": trace_id, "span_id": f"{trace_id}-1",
            "parent_span_id": None, "name": "root", "category": "root",
            "input": {"question": "test"}, "output": {"answer": "ok"},
            "start_time": 1000.0, "end_time": 1001.5, "duration_ms": 1500.0,
            "status": status, "error": None,
        }])

    def test_search_traces_no_filter(self, _patch_database):
        import api.database as db
        for i in range(3):
            self._create_trace(f"t{i}", message_id=i + 1)
        rows, total = db.search_traces(page=1, size=10)
        assert total == 3

    def test_search_traces_by_trace_id(self, _patch_database):
        import api.database as db
        self._create_trace("abc123", message_id=1)
        self._create_trace("def456", message_id=2)
        rows, total = db.search_traces(trace_id="abc123", page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "abc123"

    def test_search_traces_by_conversation_id(self, _patch_database):
        import api.database as db
        self._create_trace("t1", conversation_id="conv_x")
        self._create_trace("t2", conversation_id="conv_y")
        rows, total = db.search_traces(conversation_id="conv_x", page=1, size=10)
        assert total == 1

    def test_search_traces_by_status(self, _patch_database):
        import api.database as db
        self._create_trace("t1", status="ok")
        self._create_trace("t2", status="error")
        rows, total = db.search_traces(status="error", page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "t2"

    def test_search_traces_by_date_range(self, _patch_database, monkeypatch):
        import api.database as db
        # Insert traces then query with broad date range
        self._create_trace("t1")
        rows, total = db.search_traces(start_date="2020-01-01", end_date="2099-12-31", page=1, size=10)
        assert total == 1

    def test_search_traces_pagination(self, _patch_database):
        import api.database as db
        for i in range(5):
            self._create_trace(f"t{i}", message_id=i + 1)
        rows, total = db.search_traces(page=1, size=2)
        assert len(rows) == 2
        assert total == 5

    def test_search_traces_has_duration(self, _patch_database):
        import api.database as db
        self._create_trace("t1", message_id=1)
        rows, _ = db.search_traces(page=1, size=10)
        assert rows[0]["total_duration_ms"] == 1500.0


class TestGetTraceByTraceId:
    def test_get_existing_trace(self, _patch_database):
        import api.database as db
        self._create_trace("abc123", message_id=1)
        trace = db.get_trace_by_trace_id("abc123")
        assert trace is not None
        assert trace["trace_id"] == "abc123"
        assert trace["summary"]["span_count"] == 1

    def test_get_missing_trace(self, _patch_database):
        import api.database as db
        trace = db.get_trace_by_trace_id("nonexistent")
        assert trace is None


class TestBatchDeleteTraces:
    def test_batch_delete_cascade_spans(self, _patch_database):
        import api.database as db
        self._create_trace("t_del1", message_id=1)
        self._create_trace("t_del2", message_id=2)
        self._create_trace("t_keep", message_id=3)
        deleted = db.batch_delete_traces(["t_del1", "t_del2"])
        assert deleted == 2
        rows, total = db.search_traces(page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "t_keep"


class TestCleanupTraces:
    def test_count_and_cleanup(self, _patch_database, monkeypatch):
        import api.database as db
        # All traces created with default status "ok"
        self._create_trace("t1", status="ok")
        self._create_trace("t2", status="ok")
        self._create_trace("t3", status="error")
        count = db.count_traces_for_cleanup(start_date="2020-01-01", end_date="2099-12-31", status="ok")
        assert count == 2
        deleted = db.cleanup_traces(start_date="2020-01-01", end_date="2099-12-31", status="ok")
        assert deleted == 2
        _, remaining = db.search_traces(page=1, size=10)
        assert remaining == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_db.py -v`
Expected: FAIL — functions not defined

- [ ] **Step 3: Write minimal implementation**

In `scripts/api/database.py`, add after the existing `get_trace` function (around line 370):

```python
def search_traces(
    trace_id: str = "",
    conversation_id: str = "",
    message_id: int = 0,
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple:
    """分页搜索 trace 列表。返回 (rows, total_count)。
    每行包含 trace_id, message_id, conversation_id, created_at, status, total_duration_ms。
    """
    clauses: list[str] = []
    params: list = []
    if trace_id:
        clauses.append("t.trace_id = ?")
        params.append(trace_id)
    if conversation_id:
        clauses.append("t.conversation_id = ?")
        params.append(conversation_id)
    if message_id:
        clauses.append("t.message_id = ?")
        params.append(message_id)
    if status:
        clauses.append("s_agg.has_error = ?")
        params.append(status)
    if start_date:
        clauses.append("t.created_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("t.created_at <= ?")
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM traces t {where}", params
        ).fetchone()["cnt"]

        offset = (page - 1) * size
        rows = conn.execute(f"""
            SELECT t.trace_id, t.message_id, t.conversation_id, t.created_at,
                   COALESCE(s_agg.total_duration_ms, 0) AS total_duration_ms,
                   COALESCE(s_agg.has_error, 'ok') AS status,
                   s_agg.span_count
            FROM traces t
            LEFT JOIN (
                SELECT trace_id,
                       MAX(duration_ms) AS total_duration_ms,
                       MAX(CASE WHEN status = 'error' THEN 'error' ELSE 'ok' END) AS has_error,
                       COUNT(*) AS span_count
                FROM spans
                GROUP BY trace_id
            ) s_agg ON s_agg.trace_id = t.trace_id
            {where}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
        """, params + [size, offset]).fetchall()
        return [dict(r) for r in rows], total


def get_trace_by_trace_id(trace_id: str):
    """通过 trace_id 获取完整 trace 数据（含 span 树）。"""
    with get_connection() as conn:
        trace_row = conn.execute(
            "SELECT trace_id FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if trace_row is None:
            return None

        span_rows = conn.execute(
            "SELECT span_id, parent_span_id, name, category, input_json, output_json, "
            "metadata_json, start_time, end_time, duration_ms, status, error "
            "FROM spans WHERE trace_id = ? ORDER BY start_time",
            (trace_id,),
        ).fetchall()

        span_dicts = [_deserialize_json_fields(dict(r), _SPAN_JSON_FIELDS) for r in span_rows]

    span_map: Dict[str, Dict] = {s["span_id"]: {**s, "children": []} for s in span_dicts}
    roots: List[Dict] = []
    for s in span_dicts:
        parent_id = s.get("parent_span_id")
        if parent_id and parent_id in span_map:
            span_map[parent_id]["children"].append(span_map[s["span_id"]])
        else:
            roots.append(span_map[s["span_id"]])

    root = roots[0] if roots else None
    if root is None:
        return None

    root_meta = root.get("metadata") or {}
    llm_count = root_meta.get("llm_call_count", 0)
    error_count = sum(1 for s in span_dicts if s["status"] == "error")

    return {
        "trace_id": trace_id,
        "root": root,
        "spans": span_dicts,
        "summary": {
            "total_duration_ms": root.get("duration_ms") or 0,
            "span_count": len(span_dicts),
            "llm_call_count": llm_count,
            "error_count": error_count,
        },
    }


def batch_delete_traces(trace_ids: list) -> int:
    """批量删除 trace 及其 spans。返回删除的 trace 数。"""
    if not trace_ids:
        return 0
    placeholders = ",".join("?" for _ in trace_ids)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM spans WHERE trace_id IN ({placeholders})", trace_ids
        )
        cur = conn.execute(
            f"DELETE FROM traces WHERE trace_id IN ({placeholders})", trace_ids
        )
        return cur.rowcount


def count_traces_for_cleanup(start_date: str, end_date: str, status: str = "") -> int:
    """预览符合条件的 trace 数量。"""
    clauses: list[str] = []
    params: list = []
    if start_date:
        clauses.append("t.created_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("t.created_at <= ?")
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    if status:
        clauses.append("s_agg.has_error = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_connection() as conn:
        row = conn.execute(f"""
            SELECT COUNT(*) AS cnt FROM traces t
            LEFT JOIN (
                SELECT trace_id,
                       MAX(CASE WHEN status = 'error' THEN 'error' ELSE 'ok' END) AS has_error
                FROM spans GROUP BY trace_id
            ) s_agg ON s_agg.trace_id = t.trace_id
            {where}
        """, params).fetchone()
        return row["cnt"]


def cleanup_traces(start_date: str, end_date: str, status: str = "") -> int:
    """按条件批量清理 trace 及其 spans。返回删除的 trace 数。"""
    # Find matching trace_ids first
    clauses: list[str] = []
    params: list = []
    if start_date:
        clauses.append("t.created_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("t.created_at <= ?")
        params.append(end_date + " 23:59:59" if len(end_date) == 10 else end_date)
    if status:
        clauses.append("s_agg.has_error = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT t.trace_id FROM traces t
            LEFT JOIN (
                SELECT trace_id,
                       MAX(CASE WHEN status = 'error' THEN 'error' ELSE 'ok' END) AS has_error
                FROM spans GROUP BY trace_id
            ) s_agg ON s_agg.trace_id = t.trace_id
            {where}
        """, params).fetchall()

        trace_ids = [r["trace_id"] for r in rows]
        if not trace_ids:
            return 0

        return batch_delete_traces(trace_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/api/database.py scripts/tests/api/test_observability_db.py
git commit -m "feat: add trace search, detail, batch delete, and cleanup DB functions"
```

---

### Task 3: Backend — Observability API router

**Files:**
- Create: `scripts/api/routers/observability.py`
- Create: `scripts/api/schemas/observability.py`
- Modify: `scripts/api/app.py` (register router)
- Create: `scripts/tests/api/test_observability_api.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/api/test_observability_api.py`:

```python
"""Observability API 路由测试。"""
import pytest
from typing import Any, Dict, Generator
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient


@pytest.fixture()
def app_client(
    _patch_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from api.routers import observability
    test_app.include_router(observability.router)

    with TestClient(test_app) as client:
        yield client


def _create_trace_data(api_db):
    """Helper: create conversation + message + trace + spans."""
    api_db.create_conversation("conv_test", "测试会话")
    msg_id = api_db.add_message("conv_test", "user", "什么是等待期？")
    api_db.add_message("conv_test", "assistant", "等待期是指...")
    api_db.save_trace("trace_abc123", msg_id, "conv_test")
    api_db.save_spans([{
        "trace_id": "trace_abc123", "span_id": "trace_abc123-1",
        "parent_span_id": None, "name": "root", "category": "root",
        "input": {"question": "什么是等待期？"}, "output": {"answer": "等待期是指..."},
        "start_time": 1000.0, "end_time": 1002.0, "duration_ms": 2000.0,
        "status": "ok", "error": None,
    }])


class TestTraceListAPI:
    def test_list_traces_empty(self, app_client):
        resp = app_client.get("/api/observability/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_traces_with_data(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["trace_id"] == "trace_abc123"
        assert data["items"][0]["total_duration_ms"] == 2000.0

    def test_list_traces_filter_by_trace_id(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?trace_id=trace_abc123")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_traces_filter_by_trace_id_miss(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?trace_id=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_traces_filter_by_status(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?status=ok")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestTraceDetailAPI:
    def test_get_trace_detail(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces/trace_abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "trace_abc123"
        assert data["summary"]["span_count"] == 1

    def test_get_trace_not_found(self, app_client):
        resp = app_client.get("/api/observability/traces/nonexistent")
        assert resp.status_code == 404


class TestTraceCleanupAPI:
    def test_cleanup_preview(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.post("/api/observability/traces/cleanup", json={
            "start_date": "2020-01-01", "end_date": "2099-12-31", "preview": True,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_cleanup_execute(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.post("/api/observability/traces/cleanup", json={
            "start_date": "2020-01-01", "end_date": "2099-12-31", "preview": False,
        })
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
        # Verify trace is gone
        resp2 = app_client.get("/api/observability/traces")
        assert resp2.json()["total"] == 0

    def test_batch_delete_traces(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.delete("/api/observability/traces?ids=trace_abc123")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_api.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create schema file**

Create `scripts/api/schemas/observability.py`:

```python
from typing import Optional, List
from pydantic import BaseModel, Field


class TraceListItem(BaseModel):
    trace_id: str
    message_id: Optional[int] = None
    conversation_id: Optional[str] = None
    created_at: str
    status: str = "ok"
    total_duration_ms: float = 0
    span_count: int = 0


class TraceListResponse(BaseModel):
    items: List[TraceListItem] = []
    total: int = 0


class CleanupRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    status: str = ""
    preview: bool = True
```

- [ ] **Step 4: Create router file**

Create `scripts/api/routers/observability.py`:

```python
"""可测性路由 — Trace 查看与清理。"""

from fastapi import APIRouter, HTTPException, Query

from api.database import (
    search_traces,
    get_trace_by_trace_id,
    batch_delete_traces,
    count_traces_for_cleanup,
    cleanup_traces,
)
from api.schemas.observability import TraceListResponse, CleanupRequest

router = APIRouter(prefix="/api/observability", tags=["可测性"])


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    trace_id: str = Query("", description="精确匹配 trace ID"),
    conversation_id: str = Query("", description="精确匹配 conversation ID"),
    message_id: int = Query(0, description="精确匹配 message ID"),
    status: str = Query("", description="状态过滤: ok / error"),
    start_date: str = Query("", description="起始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="截止日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = search_traces(
        trace_id=trace_id,
        conversation_id=conversation_id,
        message_id=message_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )
    return TraceListResponse(items=items, total=total)


@router.get("/traces/{trace_id}")
async def get_trace_detail(trace_id: str):
    trace = get_trace_by_trace_id(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.delete("/traces")
async def delete_traces(ids: str = Query(..., description="逗号分隔的 trace ID 列表")):
    trace_ids = [tid.strip() for tid in ids.split(",") if tid.strip()]
    deleted = batch_delete_traces(trace_ids)
    return {"deleted": deleted}


@router.post("/traces/cleanup")
async def cleanup_traces_endpoint(req: CleanupRequest):
    if req.preview:
        count = count_traces_for_cleanup(req.start_date, req.end_date, req.status)
        return {"count": count}
    deleted = cleanup_traces(req.start_date, req.end_date, req.status)
    return {"deleted": deleted}
```

- [ ] **Step 5: Register router in app.py**

In `scripts/api/app.py`, add the import and registration after the existing router imports (line 120-126):

Add to the import line:
```python
from api.routers import ask, knowledge, eval as eval_router, compliance, kb_version, feedback, observability
```

Add after line 126:
```python
app.include_router(observability.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_observability_api.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run all existing tests to verify no regressions**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add scripts/api/routers/observability.py scripts/api/schemas/observability.py scripts/api/app.py scripts/tests/api/test_observability_api.py
git commit -m "feat: add observability API router with trace list, detail, and cleanup endpoints"
```

---

### Task 4: Backend — Extend AskPage conversation API with search and batch delete

**Files:**
- Modify: `scripts/api/routers/ask.py`
- Modify: `scripts/tests/api/test_ask.py`

- [ ] **Step 1: Write the failing tests**

Add to existing `scripts/tests/api/test_ask.py` (or create a new test section at the end):

```python
class TestConversationSearch:
    def test_search_conversations(self, app_client, make_conversation):
        make_conversation("conv_a", "健康保险等待期")
        make_conversation("conv_b", "免责条款")
        resp = app_client.get("/api/ask/conversations?search=等待期")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "健康保险等待期"

    def test_search_conversations_empty(self, app_client, make_conversation):
        make_conversation("conv_a", "测试")
        resp = app_client.get("/api/ask/conversations?search=不存在")
        assert resp.status_code == 200
        assert resp.json() == []


class TestBatchDeleteConversations:
    def test_batch_delete(self, app_client, make_conversation, make_message):
        make_conversation("conv_del1", "删除1")
        make_message("conv_del1", "user", "问题1")
        make_conversation("conv_del2", "删除2")
        make_conversation("conv_keep", "保留")
        resp = app_client.delete("/api/ask/conversations?ids=conv_del1,conv_del2")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2
        # Verify remaining
        resp2 = app_client.get("/api/ask/conversations")
        assert len(resp2.json()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_ask.py -v -k "TestConversationSearch or TestBatchDelete"`
Expected: FAIL — query param not handled / endpoint not found

- [ ] **Step 3: Modify ask.py router**

In `scripts/api/routers/ask.py`:

1. Add `search_conversations` and `batch_delete_conversations` to imports from `api.database`
2. Add `Query` to fastapi imports
3. Modify the `list_conversations` endpoint:

```python
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(search: str = Query("", description="按标题模糊搜索")):
    if search:
        rows, _ = search_conversations(search=search, page=1, size=100)
        return rows
    return get_conversations()
```

4. Add batch delete endpoint:

```python
@router.delete("/conversations")
async def batch_remove_conversations(ids: str = Query(..., description="逗号分隔的会话 ID")):
    conversation_ids = [cid.strip() for cid in ids.split(",") if cid.strip()]
    deleted = batch_delete_conversations(conversation_ids)
    return {"deleted": deleted}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/api/test_ask.py -v`
Expected: ALL PASS (existing + new tests)

- [ ] **Step 5: Run all tests**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/api/routers/ask.py scripts/tests/api/test_ask.py
git commit -m "feat: add conversation search and batch delete to ask API"
```

---

### Task 5: Frontend — Types and API client for observability

**Files:**
- Modify: `scripts/web/src/types/index.ts`
- Create: `scripts/web/src/api/observability.ts`

- [ ] **Step 1: Add types to types/index.ts**

Append to the end of `scripts/web/src/types/index.ts`:

```typescript
// ── Observability ──

export interface TraceListItem {
  trace_id: string;
  message_id: number | null;
  conversation_id: string | null;
  created_at: string;
  status: 'ok' | 'error';
  total_duration_ms: number;
  span_count: number;
}

export interface TraceListResponse {
  items: TraceListItem[];
  total: number;
}

export interface CleanupRequest {
  start_date: string;
  end_date: string;
  status: string;
  preview: boolean;
}

export interface CleanupResponse {
  count?: number;
  deleted?: number;
}
```

- [ ] **Step 2: Create API client**

Create `scripts/web/src/api/observability.ts`:

```typescript
import client from './client';
import type { TraceListResponse, TraceData, CleanupRequest, CleanupResponse } from '../types';

export interface TraceSearchParams {
  trace_id?: string;
  conversation_id?: string;
  message_id?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  size?: number;
}

export async function fetchTraces(params: TraceSearchParams = {}): Promise<TraceListResponse> {
  const { data } = await client.get('/api/observability/traces', { params });
  return data;
}

export async function fetchTraceDetail(traceId: string): Promise<TraceData> {
  const { data } = await client.get(`/api/observability/traces/${traceId}`);
  return data;
}

export async function batchDeleteTraces(ids: string[]): Promise<{ deleted: number }> {
  const { data } = await client.delete('/api/observability/traces', {
    params: { ids: ids.join(',') },
  });
  return data;
}

export async function cleanupTraces(req: CleanupRequest): Promise<CleanupResponse> {
  const { data } = await client.post('/api/observability/traces/cleanup', req);
  return data;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /mnt/d/work/actuary-sleuth/scripts/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/types/index.ts scripts/web/src/api/observability.ts
git commit -m "feat: add observability types and API client"
```

---

### Task 6: Frontend — Extend AskPage conversation list with search and batch delete

**Files:**
- Modify: `scripts/web/src/components/ChatPanel.tsx`
- Modify: `scripts/web/src/api/ask.ts`
- Modify: `scripts/web/src/stores/askStore.ts`

- [ ] **Step 1: Add search API to ask.ts**

In `scripts/web/src/api/ask.ts`, modify the `fetchConversations` function to accept an optional search parameter:

```typescript
export async function fetchConversations(search?: string): Promise<Conversation[]> {
  const { data } = await client.get('/api/ask/conversations', {
    params: search ? { search } : undefined,
  });
  return data;
}
```

Add batch delete function:

```typescript
export async function batchDeleteConversations(ids: string[]): Promise<{ deleted: number }> {
  const { data } = await client.delete('/api/ask/conversations', {
    params: { ids: ids.join(',') },
  });
  return data;
}
```

- [ ] **Step 2: Update askStore to support search and batch delete**

In `scripts/web/src/stores/askStore.ts`:

Add to the `AskState` interface:
```typescript
  conversationSearch: string;
  setConversationSearch: (search: string) => void;
  batchDeleteConversations: (ids: string[]) => Promise<void>;
```

Add to the store implementation:
```typescript
  conversationSearch: "",

  setConversationSearch: (search: string) => {
    set({ conversationSearch: search });
    get().loadConversations(search);
  },

  batchDeleteConversations: async (ids: string[]) => {
    await askApi.batchDeleteConversations(ids);
    const { currentConversationId } = get();
    if (ids.includes(currentConversationId || "")) {
      set({ currentConversationId: null, messages: [], activeTraceMessageId: null, traceLoading: false });
    }
    get().loadConversations(get().conversationSearch || undefined);
  },
```

Modify `loadConversations` to accept optional search:
```typescript
  loadConversations: async (search?: string) => {
    const conversations = await askApi.fetchConversations(search);
    set({ conversations });
  },
```

- [ ] **Step 3: Update ChatPanel.tsx with search input and batch delete**

In `scripts/web/src/components/ChatPanel.tsx`, import `Checkbox` and `batchDeleteConversations`:

Add to imports:
```typescript
import { Input, Button, Radio, Space, Popconfirm, Switch, Checkbox, message } from 'antd';
import { SendOutlined, DeleteOutlined, CloseOutlined, BugOutlined, SearchOutlined } from '@ant-design/icons';
```

Extract `conversationSearch`, `setConversationSearch`, `batchDeleteConversations` from the store.

Replace the conversation list section (the `<div style={{ width: 220, ... }}` block) with:

```tsx
<div
  style={{
    width: 220,
    borderRight: '1px solid #f0f0f0',
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
  }}
>
  <div style={{ padding: '8px 12px', fontWeight: 600, fontSize: 14 }}>
    对话历史
  </div>
  <div style={{ padding: '0 8px 8px' }}>
    <Input
      placeholder="搜索会话..."
      prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
      size="small"
      allowClear
      value={conversationSearch}
      onChange={(e) => setConversationSearch(e.target.value)}
    />
  </div>
  {selectedConvIds.length > 0 && (
    <div style={{ padding: '0 8px 8px' }}>
      <Popconfirm
        title={`确定删除选中的 ${selectedConvIds.length} 个会话？`}
        onConfirm={handleBatchDelete}
      >
        <Button type="primary" danger size="small" icon={<DeleteOutlined />} block>
          删除 ({selectedConvIds.length})
        </Button>
      </Popconfirm>
    </div>
  )}
  <div style={{ flex: 1, overflow: 'auto' }}>
    {conversations.map((conv) => (
      <div
        key={conv.id}
        onClick={() => selectConversation(conv.id)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          background: currentConversationId === conv.id ? '#e6f4ff' : '#fff',
          borderBottom: '1px solid #f5f5f5',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Checkbox
          checked={selectedConvIds.includes(conv.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => {
            if (e.target.checked) {
              setSelectedConvIds([...selectedConvIds, conv.id]);
            } else {
              setSelectedConvIds(selectedConvIds.filter((id) => id !== conv.id));
            }
          }}
          style={{ marginRight: 4 }}
        />
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
            fontSize: 13,
          }}
        >
          {conv.title || conv.id}
        </span>
        <Popconfirm
          title="确定删除？"
          onConfirm={(e) => {
            e?.stopPropagation();
            deleteConversation(conv.id);
          }}
          onCancel={(e) => e?.stopPropagation()}
        >
          <Button
            type="text"
            size="small"
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
            style={{ color: '#999' }}
          />
        </Popconfirm>
      </div>
    ))}
  </div>
</div>
```

Add state for selected conversation IDs and batch delete handler:

```typescript
const [selectedConvIds, setSelectedConvIds] = React.useState<string[]>([]);

const handleBatchDelete = () => {
  batchDeleteConversations(selectedConvIds);
  setSelectedConvIds([]);
  message.success('已删除');
};
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /mnt/d/work/actuary-sleuth/scripts/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add scripts/web/src/components/ChatPanel.tsx scripts/web/src/api/ask.ts scripts/web/src/stores/askStore.ts
git commit -m "feat: add conversation search and batch delete to AskPage"
```

---

### Task 7: Frontend — ObservabilityPage with TraceView (list + detail)

**Files:**
- Create: `scripts/web/src/pages/ObservabilityPage.tsx`
- Create: `scripts/web/src/components/observability/TraceView.tsx`
- Create: `scripts/web/src/components/observability/TraceList.tsx`
- Create: `scripts/web/src/components/observability/TraceDetail.tsx`
- Create: `scripts/web/src/components/observability/CleanupDialog.tsx`
- Create: `scripts/web/src/stores/observabilityStore.ts`
- Modify: `scripts/web/src/App.tsx` (add route)
- Modify: `scripts/web/src/components/AppLayout.tsx` (add nav item)

- [ ] **Step 1: Create observabilityStore**

Create `scripts/web/src/stores/observabilityStore.ts`:

```typescript
import { create } from 'zustand';
import type { TraceListItem, TraceData, TraceSearchParams } from '../types';
import * as api from '../api/observability';

interface ObservabilityState {
  traceList: TraceListItem[];
  traceTotal: number;
  tracePage: number;
  traceParams: TraceSearchParams;
  selectedTraceId: string | null;
  traceDetail: TraceData | null;
  traceLoading: boolean;

  loadTraces: (params?: TraceSearchParams) => Promise<void>;
  selectTrace: (traceId: string) => void;
  setPage: (page: number) => void;
  clearSelection: () => void;
  deleteTraces: (ids: string[]) => Promise<void>;
}

export const useObservabilityStore = create<ObservabilityState>((set, get) => ({
  traceList: [],
  traceTotal: 0,
  tracePage: 1,
  traceParams: {},
  selectedTraceId: null,
  traceDetail: null,
  traceLoading: false,

  loadTraces: async (params?: TraceSearchParams) => {
    const merged = { ...get().traceParams, ...params, page: params?.page ?? get().tracePage };
    set({ traceParams: merged });
    const resp = await api.fetchTraces(merged);
    set({ traceList: resp.items, traceTotal: resp.total });
  },

  selectTrace: (traceId: string) => {
    set({ selectedTraceId: traceId, traceLoading: true });
    api.fetchTraceDetail(traceId)
      .then((detail) => set({ traceDetail: detail, traceLoading: false }))
      .catch(() => set({ traceDetail: null, traceLoading: false }));
  },

  setPage: (page: number) => {
    set({ tracePage: page });
    get().loadTraces({ page });
  },

  clearSelection: () => {
    set({ selectedTraceId: null, traceDetail: null });
  },

  deleteTraces: async (ids: string[]) => {
    await api.batchDeleteTraces(ids);
    const { selectedTraceId } = get();
    if (selectedTraceId && ids.includes(selectedTraceId)) {
      set({ selectedTraceId: null, traceDetail: null });
    }
    get().loadTraces();
  },
}));
```

- [ ] **Step 2: Create CleanupDialog component**

Create `scripts/web/src/components/observability/CleanupDialog.tsx`:

```tsx
import { useState } from 'react';
import { Modal, DatePicker, Select, Button, Space, Typography, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { cleanupTraces } from '../../api/observability';
import type { CleanupResponse } from '../../types';
import dayjs, { Dayjs } from 'dayjs';

interface Props {
  open: boolean;
  onClose: () => void;
  onCleanupDone: () => void;
}

export default function CleanupDialog({ open, onClose, onCleanupDone }: Props) {
  const [startDate, setStartDate] = useState<Dayjs | null>(null);
  const [endDate, setEndDate] = useState<Dayjs | null>(null);
  const [status, setStatus] = useState<string>('');
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const handlePreview = async () => {
    setLoading(true);
    try {
      const result: CleanupResponse = await cleanupTraces({
        start_date: startDate?.format('YYYY-MM-DD') || '',
        end_date: endDate?.format('YYYY-MM-DD') || '',
        status,
        preview: true,
      });
      setPreviewCount(result.count ?? 0);
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async () => {
    setLoading(true);
    try {
      const result: CleanupResponse = await cleanupTraces({
        start_date: startDate?.format('YYYY-MM-DD') || '',
        end_date: endDate?.format('YYYY-MM-DD') || '',
        status,
        preview: false,
      });
      message.success(`已清理 ${result.deleted} 条 trace`);
      onCleanupDone();
      handleClose();
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setStartDate(null);
    setEndDate(null);
    setStatus('');
    setPreviewCount(null);
    onClose();
  };

  return (
    <Modal
      title="批量清理 Trace"
      open={open}
      onCancel={handleClose}
      footer={null}
      width={440}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <div style={{ marginBottom: 4, fontSize: 13, color: '#595959' }}>时间范围</div>
          <DatePicker.RangePicker
            value={[startDate, endDate]}
            onChange={(dates) => {
              setStartDate(dates?.[0] ?? null);
              setEndDate(dates?.[1] ?? null);
            }}
            style={{ width: '100%' }}
          />
        </div>
        <div>
          <div style={{ marginBottom: 4, fontSize: 13, color: '#595959' }}>状态</div>
          <Select
            value={status || undefined}
            onChange={setStatus}
            placeholder="全部"
            allowClear
            style={{ width: '100%' }}
            options={[
              { label: '全部', value: '' },
              { label: '成功 (ok)', value: 'ok' },
              { label: '错误 (error)', value: 'error' },
            ]}
          />
        </div>

        <Button onClick={handlePreview} loading={loading} block>
          预览影响数量
        </Button>

        {previewCount !== null && (
          <div style={{
            padding: '8px 12px', background: previewCount > 0 ? '#fff7e6' : '#f6ffed',
            borderRadius: 6, fontSize: 13,
          }}>
            <Typography.Text type={previewCount > 0 ? 'warning' : 'success'}>
              {previewCount > 0
                ? `将清理 ${previewCount} 条 trace 及其 span 数据`
                : '没有符合条件的 trace'}
            </Typography.Text>
          </div>
        )}

        {previewCount !== null && previewCount > 0 && (
          <Button
            type="primary"
            danger
            icon={<DeleteOutlined />}
            onClick={handleExecute}
            loading={loading}
            block
          >
            确认清理
          </Button>
        )}
      </Space>
    </Modal>
  );
}
```

- [ ] **Step 3: Create TraceList component**

Create `scripts/web/src/components/observability/TraceList.tsx`:

```tsx
import { useState } from 'react';
import { Input, Select, Button, Checkbox, Badge, Space, DatePicker, Popconfirm, message } from 'antd';
import { SearchOutlined, DeleteOutlined, ClearOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { TraceListItem } from '../../types';
import { useObservabilityStore } from '../../stores/observabilityStore';
import dayjs, { Dayjs } from 'dayjs';

export default function TraceList() {
  const {
    traceList, traceTotal, tracePage,
    selectedTraceId, selectTrace,
    loadTraces, setPage, deleteTraces,
  } = useObservabilityStore();

  const [traceIdFilter, setTraceIdFilter] = useState('');
  const [convIdFilter, setConvIdFilter] = useState('');
  const [msgIdFilter, setMsgIdFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [cleanupOpen, setCleanupOpen] = useState(false);

  const handleSearch = () => {
    setSelectedIds([]);
    setPage(1);
    loadTraces({
      trace_id: traceIdFilter || undefined,
      conversation_id: convIdFilter || undefined,
      message_id: msgIdFilter ? parseInt(msgIdFilter) : undefined,
      status: statusFilter || undefined,
      start_date: dateRange?.[0]?.format('YYYY-MM-DD') || undefined,
      end_date: dateRange?.[1]?.format('YYYY-MM-DD') || undefined,
      page: 1,
    });
  };

  const handleClear = () => {
    setTraceIdFilter('');
    setConvIdFilter('');
    setMsgIdFilter('');
    setStatusFilter('');
    setDateRange(null);
    setSelectedIds([]);
    setPage(1);
    loadTraces({ page: 1 });
  };

  const handleBatchDelete = () => {
    deleteTraces(selectedIds);
    setSelectedIds([]);
    message.success('已删除');
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => checked ? [...prev, id] : prev.filter((x) => x !== id));
  };

  const allSelected = traceList.length > 0 && traceList.every((t) => selectedIds.includes(t.trace_id));

  return (
    <div style={{ width: 360, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '10px 12px', fontWeight: 600, fontSize: 14, borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span><ThunderboltOutlined style={{ marginRight: 6 }} />Trace 列表</span>
        <Button type="link" size="small" onClick={() => setCleanupOpen(true)} style={{ padding: 0, fontSize: 12 }}>
          <DeleteOutlined /> 清理
        </Button>
      </div>

      {/* Search & Filters */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', overflow: 'auto', flexShrink: 0 }}>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Input placeholder="Trace ID" size="small" value={traceIdFilter} onChange={(e) => setTraceIdFilter(e.target.value)} allowClear />
          <Input placeholder="Conversation ID" size="small" value={convIdFilter} onChange={(e) => setConvIdFilter(e.target.value)} allowClear />
          <Input placeholder="Message ID" size="small" value={msgIdFilter} onChange={(e) => setMsgIdFilter(e.target.value)} allowClear />
          <Select placeholder="状态" size="small" value={statusFilter || undefined} onChange={setStatusFilter} allowClear style={{ width: '100%' }} options={[
            { label: '成功 (ok)', value: 'ok' },
            { label: '错误 (error)', value: 'error' },
          ]} />
          <DatePicker.RangePicker size="small" style={{ width: '100%' }} value={dateRange} onChange={(dates) => setDateRange(dates as [Dayjs | null, Dayjs | null] | null)} />
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button size="small" icon={<ClearOutlined />} onClick={handleClear}>重置</Button>
            <Button size="small" type="primary" icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
          </Space>
        </Space>
      </div>

      {/* Batch actions */}
      {selectedIds.length > 0 && (
        <div style={{ padding: '6px 12px', borderBottom: '1px solid #f0f0f0' }}>
          <Popconfirm title={`确定删除 ${selectedIds.length} 条 trace？`} onConfirm={handleBatchDelete}>
            <Button type="primary" danger size="small" icon={<DeleteOutlined />} block>
              删除选中 ({selectedIds.length})
            </Button>
          </Popconfirm>
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {traceList.length > 0 && (
          <div style={{ padding: '4px 12px', borderBottom: '1px solid #f5f5f5' }}>
            <Checkbox checked={allSelected} onChange={(e) => {
              setSelectedIds(e.target.checked ? traceList.map((t) => t.trace_id) : []);
            }} style={{ fontSize: 11, color: '#8c8c8c' }}>
              全选
            </Checkbox>
          </div>
        )}
        {traceList.map((item) => (
          <div
            key={item.trace_id}
            onClick={() => selectTrace(item.trace_id)}
            style={{
              padding: '6px 12px',
              cursor: 'pointer',
              background: selectedTraceId === item.trace_id ? '#e6f4ff' : '#fff',
              borderBottom: '1px solid #f5f5f5',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Checkbox
              checked={selectedIds.includes(item.trace_id)}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => toggleSelect(item.trace_id, e.target.checked)}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <Badge status={item.status === 'error' ? 'error' : 'success'} />
                <span style={{ fontSize: 12, fontFamily: "'SF Mono', monospace", overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.trace_id}
                </span>
              </div>
              <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>
                {(item.total_duration_ms / 1000).toFixed(1)}s · {item.span_count} spans · {item.created_at?.slice(5, 16)}
              </div>
            </div>
          </div>
        ))}
        {traceList.length === 0 && (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: '#bfbfbf', fontSize: 12 }}>
            暂无 Trace 数据
          </div>
        )}
      </div>

      {/* Pagination */}
      {traceTotal > 20 && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: '#8c8c8c' }}>
          <span>共 {traceTotal} 条</span>
          <Space size={4}>
            <Button size="small" disabled={tracePage <= 1} onClick={() => setPage(tracePage - 1)}>上一页</Button>
            <span>{tracePage}</span>
            <Button size="small" disabled={tracePage * 20 >= traceTotal} onClick={() => setPage(tracePage + 1)}>下一页</Button>
          </Space>
        </div>
      )}

      {/* Cleanup dialog rendered by parent */}
    </div>
  );
}
```

Note: The `cleanupOpen` state and `CleanupDialog` import/rendering will be handled in TraceView. Adjust TraceList to accept `onCleanupOpen` callback:

Replace the cleanup button and state in TraceList:
```tsx
// Remove: const [cleanupOpen, setCleanupOpen] = useState(false);
// Change button to:
interface Props { onCleanupOpen: () => void; }
export default function TraceList({ onCleanupOpen }: Props) {
  // ...
  <Button type="link" size="small" onClick={onCleanupOpen} ...>清理</Button>
  // Remove CleanupDialog rendering from this component
}
```

- [ ] **Step 4: Create TraceDetail component**

Create `scripts/web/src/components/observability/TraceDetail.tsx`:

```tsx
import TracePanel from '../TracePanel';
import { CopyOutlined } from '@ant-design/icons';
import { useObservabilityStore } from '../../stores/observabilityStore';

function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <CopyOutlined
      style={{ fontSize: 11, color: '#d9d9d9', cursor: 'pointer', marginLeft: 4 }}
      onClick={() => handleCopy()}
      title={copied ? '已复制' : '复制'}
    />
  );
}

import React from 'react';

export default function TraceDetail() {
  const { selectedTraceId, traceDetail, traceLoading, traceList, clearSelection } = useObservabilityStore();

  if (!selectedTraceId) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#bfbfbf' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.25 }}>&#x1f50d;</div>
          <div style={{ fontSize: 13 }}>选择一条 Trace 查看详情</div>
        </div>
      </div>
    );
  }

  const selectedItem = traceList.find((t) => t.trace_id === selectedTraceId);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Info header */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid #f0f0f0', fontSize: 12, color: '#8c8c8c' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span>
            <span style={{ color: '#bfbfbf' }}>trace_id:</span>{' '}
            <span style={{ fontFamily: "'SF Mono', monospace", color: '#262626' }}>{selectedTraceId}</span>
            <CopyBtn text={selectedTraceId} />
          </span>
          {selectedItem?.conversation_id && (
            <span>
              <span style={{ color: '#bfbfbf' }}>conversation_id:</span>{' '}
              <span style={{ fontFamily: "'SF Mono', monospace" }}>{selectedItem.conversation_id}</span>
              <CopyBtn text={selectedItem.conversation_id} />
            </span>
          )}
          {selectedItem?.message_id != null && (
            <span>
              <span style={{ color: '#bfbfbf' }}>message_id:</span>{' '}
              <span style={{ fontFamily: "'SF Mono", monospace' }}>{selectedItem.message_id}</span>
              <CopyBtn text={String(selectedItem.message_id)} />
            </span>
          )}
          {selectedItem?.created_at && (
            <span>
              <span style={{ color: '#bfbfbf' }}>created_at:</span>{' '}
              <span>{selectedItem.created_at}</span>
            </span>
          )}
        </div>
      </div>

      {/* TracePanel */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <TracePanel trace={traceDetail} loading={traceLoading} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create TraceView container**

Create `scripts/web/src/components/observability/TraceView.tsx`:

```tsx
import { useState, useEffect } from 'react';
import TraceList from './TraceList';
import TraceDetail from './TraceDetail';
import CleanupDialog from './CleanupDialog';
import { useObservabilityStore } from '../../stores/observabilityStore';

export default function TraceView() {
  const { loadTraces } = useObservabilityStore();
  const [cleanupOpen, setCleanupOpen] = useState(false);

  useEffect(() => {
    loadTraces();
  }, [loadTraces]);

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <TraceList onCleanupOpen={() => setCleanupOpen(true)} />
      <TraceDetail />
      <CleanupDialog
        open={cleanupOpen}
        onClose={() => setCleanupOpen(false)}
        onCleanupDone={() => loadTraces()}
      />
    </div>
  );
}
```

- [ ] **Step 6: Create ObservabilityPage**

Create `scripts/web/src/pages/ObservabilityPage.tsx`:

```tsx
import TraceView from '../components/observability/TraceView';

export default function ObservabilityPage() {
  return (
    <div style={{ height: 'calc(100vh - 64px - 32px)' }}>
      <TraceView />
    </div>
  );
}
```

- [ ] **Step 7: Add route and navigation**

In `scripts/web/src/App.tsx`, add:
```tsx
import ObservabilityPage from './pages/ObservabilityPage';
```

Add route inside the `<Route element={<AppLayout />}>` block:
```tsx
<Route path="/observability" element={<ObservabilityPage />} />
```

In `scripts/web/src/components/AppLayout.tsx`, add:
```tsx
import { ExperimentOutlined } from '@ant-design/icons';
```

Add to `menuItems` array (after feedback item):
```tsx
{ key: '/observability', icon: <ExperimentOutlined />, label: '可测性' },
```

- [ ] **Step 8: Verify TypeScript compiles**

Run: `cd /mnt/d/work/actuary-sleuth/scripts/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 9: Commit**

```bash
git add scripts/web/src/pages/ObservabilityPage.tsx \
        scripts/web/src/components/observability/ \
        scripts/web/src/stores/observabilityStore.ts \
        scripts/web/src/App.tsx \
        scripts/web/src/components/AppLayout.tsx
git commit -m "feat: add ObservabilityPage with Trace list, detail, and cleanup"
```

---

### Task 8: Full integration test and type check

- [ ] **Step 1: Run all backend tests**

Run: `cd /mnt/d/work/actuary-sleuth && python -m pytest scripts/tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run frontend type check**

Run: `cd /mnt/d/work/actuary-sleuth/scripts/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Run frontend build**

Run: `cd /mnt/d/work/actuary-sleuth/scripts/web && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix: resolve integration issues"
```
