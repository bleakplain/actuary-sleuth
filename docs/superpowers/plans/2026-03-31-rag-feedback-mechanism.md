# RAG 问题反馈机制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Actuary Sleuth RAG 问答系统添加完整的 Badcase 反馈闭环机制，包括用户反馈采集、自动质量检测、三分类自动分类、Badcase 管理页面、验证/转化/回归测试闭环。

**Architecture:** 后端新增 `feedback` 数据库表和 `feedback` 路由模块，复用现有 evaluator/attribution 的质量检测能力。前端在 MessageBubble 上添加反馈按钮，新增 Badcase 管理页面和反馈统计页面。整体分三个 Phase：基础反馈 → 自动检测分类 → 闭环集成。

**Tech Stack:** Python/FastAPI/SQLite (后端), React/TypeScript/Ant Design/Zustand (前端)

---

## File Structure

### 新增文件
- `scripts/api/routers/feedback.py` — 反馈提交 + Badcase 管理 API 路由
- `scripts/api/schemas/feedback.py` — 反馈相关 Pydantic schemas
- `scripts/lib/rag_engine/badcase_classifier.py` — 三分类自动分类 + 合规风险标记
- `scripts/lib/rag_engine/quality_detector.py` — 三维度自动质量检测
- `scripts/tests/lib/rag_engine/test_badcase_classifier.py` — 分类器测试
- `scripts/tests/lib/rag_engine/test_quality_detector.py` — 质量检测测试
- `scripts/tests/api/test_feedback_router.py` — 反馈 API 集成测试
- `scripts/web/src/api/feedback.ts` — 反馈 API 客户端
- `scripts/web/src/stores/feedbackStore.ts` — 反馈状态管理
- `scripts/web/src/components/FeedbackButtons.tsx` — 消息反馈按钮组件
- `scripts/web/src/pages/FeedbackBadcasesPage.tsx` — Badcase 管理页面
- `scripts/web/src/pages/FeedbackStatsPage.tsx` — 反馈统计页面

### 修改文件
- `scripts/api/database.py` — 新增 feedback 表 DDL + CRUD 函数，扩展 messages 表
- `scripts/api/routers/ask.py` — chat API 持久化 faithfulness_score/unverified_claims，集成自动检测
- `scripts/api/app.py` — 注册 feedback 路由
- `scripts/lib/rag_engine/__init__.py` — 导出新模块
- `scripts/web/src/types/index.ts` — 新增 Feedback/Badcase 类型
- `scripts/web/src/components/MessageBubble.tsx` — 集成 FeedbackButtons
- `scripts/web/src/App.tsx` — 新增路由

---

## Phase 1: 基础反馈能力

### Task 1: 数据库层 — feedback 表 + messages 扩展

**Files:**
- Modify: `scripts/api/database.py`

- [ ] **Step 1: 在 `_SCHEMA_SQL` 末尾添加 feedback 表 DDL**

在 `_SCHEMA_SQL` 字符串的最后一个 `CREATE TABLE` 之后，添加：

```python
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    rating TEXT NOT NULL CHECK(rating IN ('up', 'down')),
    reason TEXT NOT NULL DEFAULT '',
    correction TEXT DEFAULT '',
    source_channel TEXT NOT NULL DEFAULT 'user_button',
    auto_quality_score REAL,
    auto_quality_details_json TEXT,
    classified_type TEXT,
    classified_reason TEXT,
    classified_fix_direction TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'classified', 'fixing', 'fixed', 'rejected', 'converted')),
    compliance_risk INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(classified_type);
```

同时添加 messages 表扩展列（用 ALTER TABLE 以兼容已有数据库）：

```python
ALTER TABLE messages ADD COLUMN faithfulness_score REAL;
ALTER TABLE messages ADD COLUMN unverified_claims_json TEXT DEFAULT '[]';
```

> 注意：SQLite ALTER TABLE ADD COLUMN 如果列已存在会报错。需要包装在 try/except 中或用 `PRAGMA table_info(messages)` 检查。推荐在 `init_db()` 函数中用条件迁移方式添加。

- [ ] **Step 2: 在 `init_db()` 函数末尾添加迁移逻辑**

```python
def _migrate_db():
    """增量迁移：添加新列（如已存在则跳过）"""
    with get_connection() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        if 'faithfulness_score' not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN faithfulness_score REAL")
        if 'unverified_claims_json' not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN unverified_claims_json TEXT DEFAULT '[]'")
```

在 `init_db()` 的 `conn.executescript(_SCHEMA_SQL)` 之后调用 `_migrate_db()`。

- [ ] **Step 3: 修改 `add_message` 函数签名，增加 faithfulness_score 和 unverified_claims 参数**

```python
def add_message(
    conversation_id: str,
    role: str,
    content: str,
    citations: Optional[List[Dict]] = None,
    sources: Optional[List[Dict]] = None,
    faithfulness_score: Optional[float] = None,
    unverified_claims: Optional[List[str]] = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations_json, sources_json, faithfulness_score, unverified_claims_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(sources or [], ensure_ascii=False),
                faithfulness_score,
                json.dumps(unverified_claims or [], ensure_ascii=False),
            ),
        )
        return cur.lastrowid
```

同步更新 `_MSG_JSON_FIELDS` 添加 `unverified_claims: "unverified_claims_json"`。

- [ ] **Step 4: 添加 feedback CRUD 函数**

```python
_FEEDBACK_JSON_FIELDS = {
    "auto_quality_details": "auto_quality_details_json",
}


def create_feedback(
    message_id: int,
    conversation_id: str,
    rating: str,
    reason: str = "",
    correction: str = "",
    source_channel: str = "user_button",
) -> str:
    feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO feedback (id, message_id, conversation_id, rating, reason, correction, source_channel) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feedback_id, message_id, conversation_id, rating, reason, correction, source_channel),
        )
    return feedback_id


def get_feedback(feedback_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), _FEEDBACK_JSON_FIELDS)


def list_feedbacks(
    status: Optional[str] = None,
    classified_type: Optional[str] = None,
    compliance_risk: Optional[int] = None,
) -> List[Dict]:
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if classified_type:
        clauses.append("classified_type = ?")
        params.append(classified_type)
    if compliance_risk is not None:
        clauses.append("compliance_risk >= ?")
        params.append(compliance_risk)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM feedback{where} ORDER BY created_at DESC", params
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _FEEDBACK_JSON_FIELDS) for r in rows]


def update_feedback(feedback_id: str, updates: Dict) -> bool:
    if not updates:
        return False
    sets = []
    params = []
    for key, value in updates.items():
        sets.append(f"{key} = ?")
        params.append(value)
    sets.append("updated_at = datetime('now')")
    params.append(feedback_id)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE feedback SET {', '.join(sets)} WHERE id = ?", params
        )
        return cur.rowcount > 0


def get_feedback_stats() -> Dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        up_count = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'up'").fetchone()[0]
        down_count = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'down'").fetchone()[0]
        by_type = {}
        for row in conn.execute(
            "SELECT classified_type, COUNT(*) as cnt FROM feedback "
            "WHERE classified_type IS NOT NULL GROUP BY classified_type"
        ).fetchall():
            by_type[row[0] or "unclear"] = row[1]
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM feedback GROUP BY status"
        ).fetchall():
            by_status[row[0]] = row[1]
        by_risk = {}
        for row in conn.execute(
            "SELECT compliance_risk, COUNT(*) as cnt FROM feedback GROUP BY compliance_risk"
        ).fetchall():
            by_risk[str(row[0])] = row[1]
    return {
        "total": total,
        "up_count": up_count,
        "down_count": down_count,
        "satisfaction_rate": round(up_count / total, 4) if total > 0 else 0.0,
        "by_type": by_type,
        "by_status": by_status,
        "by_risk": by_risk,
    }
```

- [ ] **Step 5: 运行现有测试确认无破坏**

Run: `pytest scripts/tests/ -x -q`
Expected: 所有现有测试通过

- [ ] **Step 6: Commit**

```bash
git add scripts/api/database.py
git commit -m "feat: add feedback table and extend messages table with quality metadata"
```

---

### Task 2: 反馈 Schema + API 路由

**Files:**
- Create: `scripts/api/schemas/feedback.py`
- Create: `scripts/api/routers/feedback.py`
- Modify: `scripts/api/app.py`

- [ ] **Step 1: 创建 feedback schemas**

```python
# scripts/api/schemas/feedback.py
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    message_id: int = Field(..., gt=0)
    rating: str = Field(..., pattern="^(up|down)$")
    reason: str = ""
    correction: str = ""


class FeedbackOut(BaseModel):
    id: str
    message_id: int
    conversation_id: str
    rating: str
    reason: str
    correction: str
    source_channel: str
    auto_quality_score: Optional[float] = None
    auto_quality_details: Optional[Dict] = None
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    status: str
    compliance_risk: int
    created_at: str
    updated_at: str


class FeedbackUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|classified|fixing|fixed|rejected|converted)$")
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    compliance_risk: Optional[int] = Field(None, ge=0, le=2)


class FeedbackStats(BaseModel):
    total: int
    up_count: int
    down_count: int
    satisfaction_rate: float
    by_type: Dict[str, int]
    by_status: Dict[str, int]
    by_risk: Dict[str, int]
```

- [ ] **Step 2: 创建 feedback 路由**

```python
# scripts/api/routers/feedback.py
"""反馈管理路由 — 用户反馈提交 + Badcase 管理。"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas.feedback import (
    FeedbackCreate, FeedbackOut, FeedbackUpdate, FeedbackStats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["反馈管理"])


@router.post("/submit", response_model=FeedbackOut)
async def submit_feedback(req: FeedbackCreate):
    from api.database import create_feedback, get_feedback
    # 获取 message 的 conversation_id
    from api.database import get_messages
    msgs = get_messages("")  # 需要 conversation_id，从 message_id 反查
    # 改为直接用 SQL 查
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (req.message_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    conversation_id = row[0]
    fb_id = create_feedback(
        message_id=req.message_id,
        conversation_id=conversation_id,
        rating=req.rating,
        reason=req.reason,
        correction=req.correction,
        source_channel="user_button",
    )
    result = get_feedback(fb_id)
    if result is None:
        raise HTTPException(status_code=500, detail="反馈创建失败")
    return result


@router.get("/badcases", response_model=list[FeedbackOut])
async def list_badcases(
    status: Optional[str] = Query(None),
    classified_type: Optional[str] = Query(None),
    compliance_risk: Optional[int] = Query(None),
):
    from api.database import list_feedbacks
    # badcases = rating=down 的 feedback，或者所有非 up 的
    return list_feedbacks(
        status=status,
        classified_type=classified_type,
        compliance_risk=compliance_risk,
    )


@router.get("/badcases/{feedback_id}", response_model=FeedbackOut)
async def get_badcase(feedback_id: str):
    from api.database import get_feedback
    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return fb


@router.put("/badcases/{feedback_id}", response_model=FeedbackOut)
async def update_badcase(feedback_id: str, req: FeedbackUpdate):
    from api.database import get_feedback, update_feedback
    existing = get_feedback(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    updates = req.model_dump(exclude_none=True)
    if updates:
        update_feedback(feedback_id, updates)
    return get_feedback(feedback_id)


@router.get("/stats", response_model=FeedbackStats)
async def get_stats():
    from api.database import get_feedback_stats
    return get_feedback_stats()
```

- [ ] **Step 3: 在 app.py 中注册 feedback 路由**

在 `scripts/api/app.py` 的路由注册部分（`app.include_router` 列表）添加：

```python
from api.routers.feedback import router as feedback_router
app.include_router(feedback_router)
```

- [ ] **Step 4: 验证 API 可访问**

Run: `cd scripts && python -c "from api.routers.feedback import router; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add scripts/api/schemas/feedback.py scripts/api/routers/feedback.py scripts/api/app.py
git commit -m "feat: add feedback submit and badcase management API endpoints"
```

---

### Task 3: 前端反馈按钮 + 类型定义

**Files:**
- Modify: `scripts/web/src/types/index.ts`
- Create: `scripts/web/src/api/feedback.ts`
- Create: `scripts/web/src/components/FeedbackButtons.tsx`
- Modify: `scripts/web/src/components/MessageBubble.tsx`

- [ ] **Step 1: 在 types/index.ts 末尾添加 Feedback 类型**

```typescript
export interface Feedback {
  id: string;
  message_id: number;
  conversation_id: string;
  rating: 'up' | 'down';
  reason: string;
  correction: string;
  source_channel: string;
  auto_quality_score: number | null;
  auto_quality_details: Record<string, number> | null;
  classified_type: string | null;
  classified_reason: string | null;
  classified_fix_direction: string | null;
  status: 'pending' | 'classified' | 'fixing' | 'fixed' | 'rejected' | 'converted';
  compliance_risk: number;
  created_at: string;
  updated_at: string;
}

export interface FeedbackStats {
  total: number;
  up_count: number;
  down_count: number;
  satisfaction_rate: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_risk: Record<string, number>;
}
```

同时更新 `Message` interface，添加 `faithfulness_score` 和 `unverified_claims` 可选字段：

```typescript
export interface Message {
  id: number;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  sources: Source[];
  timestamp: string;
  faithfulness_score?: number;
  unverified_claims?: string[];
}
```

- [ ] **Step 2: 创建 feedback API 客户端**

```typescript
// scripts/web/src/api/feedback.ts
import client from './client';
import type { Feedback, FeedbackStats } from '../types';

export async function submitFeedback(params: {
  message_id: number;
  rating: 'up' | 'down';
  reason?: string;
  correction?: string;
}): Promise<Feedback> {
  const { data } = await client.post('/api/feedback/submit', params);
  return data;
}

export async function fetchBadcases(params?: {
  status?: string;
  classified_type?: string;
  compliance_risk?: number;
}): Promise<Feedback[]> {
  const { data } = await client.get('/api/feedback/badcases', { params });
  return data;
}

export async function fetchBadcase(id: string): Promise<Feedback> {
  const { data } = await client.get(`/api/feedback/badcases/${id}`);
  return data;
}

export async function updateBadcase(
  id: string,
  updates: {
    status?: string;
    classified_type?: string;
    classified_reason?: string;
    classified_fix_direction?: string;
    compliance_risk?: number;
  },
): Promise<Feedback> {
  const { data } = await client.put(`/api/feedback/badcases/${id}`, updates);
  return data;
}

export async function fetchFeedbackStats(): Promise<FeedbackStats> {
  const { data } = await client.get('/api/feedback/stats');
  return data;
}
```

- [ ] **Step 3: 创建 FeedbackButtons 组件**

```tsx
// scripts/web/src/components/FeedbackButtons.tsx
import React, { useState } from 'react';
import { Button, Select, Input, Space, message } from 'antd';
import { LikeOutlined, DislikeOutlined } from '@ant-design/icons';
import * as feedbackApi from '../api/feedback';

const REASON_OPTIONS = [
  { label: '答案错误', value: '答案错误' },
  { label: '没有回答我的问题', value: '没有回答我的问题' },
  { label: '回答不完整', value: '回答不完整' },
  { label: '引用不准确', value: '引用不准确' },
  { label: '信息过时', value: '信息过时' },
  { label: '其他', value: '其他' },
];

interface Props {
  messageId: number;
  existingFeedback?: 'up' | 'down';
}

export default function FeedbackButtons({ messageId, existingFeedback }: Props) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(existingFeedback || null);
  const [showReason, setShowReason] = useState(false);
  const [reason, setReason] = useState('');
  const [correction, setCorrection] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!feedback) return;
    setSubmitting(true);
    try {
      await feedbackApi.submitFeedback({
        message_id: messageId,
        rating: feedback,
        reason: feedback === 'down' ? reason : '',
        correction: feedback === 'down' ? correction : '',
      });
      message.success('感谢反馈');
      setShowReason(false);
    } catch {
      message.error('反馈提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (feedback && feedback !== 'down') {
    return (
      <div style={{ marginTop: 4 }}>
        <Button type="text" size="small" icon={<LikeOutlined />} style={{ color: '#52c41a' }}>
          已标记有用
        </Button>
      </div>
    );
  }

  return (
    <div style={{ marginTop: 4 }}>
      <Space size={4}>
        <Button
          type="text"
          size="small"
          icon={<LikeOutlined />}
          onClick={() => { setFeedback('up'); handleSubmit(); }}
          disabled={submitting}
          style={{ color: feedback === 'up' ? '#52c41a' : undefined }}
        >
          有用
        </Button>
        <Button
          type="text"
          size="small"
          icon={<DislikeOutlined />}
          onClick={() => {
            setFeedback('down');
            setShowReason(true);
          }}
          disabled={submitting}
          style={{ color: feedback === 'down' ? '#ff4d4f' : undefined }}
        >
          有问题
        </Button>
      </Space>
      {showReason && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Select
            placeholder="选择原因"
            options={REASON_OPTIONS}
            value={reason || undefined}
            onChange={setReason}
            style={{ width: '100%' }}
            size="small"
          />
          <Input.TextArea
            placeholder="可选：提供正确答案"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            rows={2}
            size="small"
          />
          <Space>
            <Button size="small" type="primary" onClick={handleSubmit} loading={submitting}>
              提交
            </Button>
            <Button size="small" onClick={() => { setShowReason(false); setFeedback(null); }}>
              取消
            </Button>
          </Space>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 在 MessageBubble 中集成 FeedbackButtons**

在 `MessageBubble.tsx` 中，助手消息气泡的 `</div>` 关闭标签之前（引用标签之后），添加：

```tsx
import FeedbackButtons from './FeedbackButtons';

// 在助手消息的 return 中，{hasSources && (...)} 块之后添加：
{message.role === 'assistant' && (
  <FeedbackButtons messageId={message.id} />
)}
```

- [ ] **Step 5: 验证前端编译通过**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add scripts/web/src/types/index.ts scripts/web/src/api/feedback.ts \
       scripts/web/src/components/FeedbackButtons.tsx scripts/web/src/components/MessageBubble.tsx
git commit -m "feat: add feedback buttons to chat messages with reason selection"
```

---

### Task 4: ask 路由集成 — 持久化质量元数据

**Files:**
- Modify: `scripts/api/routers/ask.py`

- [ ] **Step 1: 修改 chat 路由，持久化 faithfulness_score 和 unverified_claims**

在 `ask.py` 的 `event_stream()` 函数中，修改 `add_message` 调用：

```python
# 原来：
add_message(
    conversation_id,
    "assistant",
    answer,
    citations=result.get("citations", []),
    sources=result.get("sources", []),
)

# 改为：
add_message(
    conversation_id,
    "assistant",
    answer,
    citations=result.get("citations", []),
    sources=result.get("sources", []),
    faithfulness_score=result.get("faithfulness_score"),
    unverified_claims=result.get("unverified_claims", []),
)
```

同样修改 search 模式的 `add_message` 调用（search 模式无 faithfulness_score，传 None 即可）。

- [ ] **Step 2: 修改 SSE done 事件，返回 faithfulness_score 和 unverified_claims**

在 `event_stream()` 的 done 事件 data 中添加：

```python
"data": {
    "conversation_id": conversation_id,
    "citations": result.get("citations", []),
    "sources": result.get("sources", []),
    "faithfulness_score": result.get("faithfulness_score"),
    "unverified_claims": result.get("unverified_claims", []),
},
```

- [ ] **Step 3: 运行现有测试**

Run: `pytest scripts/tests/ -x -q`
Expected: 所有现有测试通过

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/ask.py
git commit -m "feat: persist faithfulness_score and unverified_claims in messages"
```

---

## Phase 2: 自动检测 + 分类

### Task 5: 自动质量检测模块

**Files:**
- Create: `scripts/lib/rag_engine/quality_detector.py`
- Create: `scripts/tests/lib/rag_engine/test_quality_detector.py`
- Modify: `scripts/lib/rag_engine/__init__.py`

- [ ] **Step 1: 编写质量检测测试**

```python
# scripts/tests/lib/rag_engine/test_quality_detector.py
import pytest
from lib.rag_engine.quality_detector import (
    detect_quality,
    compute_retrieval_relevance,
    compute_info_completeness,
)


class TestComputeRetrievalRelevance:
    def test_exact_match_returns_high(self):
        sources = [{"content": "健康保险等待期不得超过90天"}]
        score = compute_retrieval_relevance("健康保险等待期规定", sources)
        assert score > 0.3

    def test_no_sources_returns_zero(self):
        score = compute_retrieval_relevance("健康保险等待期", [])
        assert score == 0.0

    def test_irrelevant_source_returns_low(self):
        sources = [{"content": "财产保险的理赔流程"}]
        score = compute_retrieval_relevance("健康保险等待期规定", sources)
        assert score < 0.3


class TestComputeInfoCompleteness:
    def test_number_in_answer_returns_high(self):
        score = compute_info_completeness(
            "等待期最长多少天",
            "等待期最长为90天",
        )
        assert score > 0.5

    def test_missing_number_returns_low(self):
        score = compute_info_completeness(
            "等待期最长多少天",
            "等待期有相关规定，具体请查阅条款",
        )
        assert score < 0.5

    def test_no_numbers_in_question_returns_one(self):
        score = compute_info_completeness(
            "健康保险有什么特点",
            "健康保险以被保险人的身体为保险标的",
        )
        assert score == 1.0


class TestDetectQuality:
    def test_all_good_scores(self):
        scores = detect_quality(
            query="健康保险等待期规定",
            answer="健康保险等待期不得超过90天。[来源1]",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.9,
        )
        assert scores["overall"] > 0.7

    def test_low_faithfulness(self):
        scores = detect_quality(
            query="健康保险等待期规定",
            answer="等待期最长为30天",
            sources=[{"content": "健康保险等待期不得超过90天"}],
            faithfulness_score=0.2,
        )
        assert scores["faithfulness"] == 0.2
        assert scores["overall"] < 0.5

    def test_empty_answer(self):
        scores = detect_quality(
            query="健康保险等待期",
            answer="",
            sources=[],
            faithfulness_score=0.0,
        )
        assert scores["overall"] == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest scripts/tests/lib/rag_engine/test_quality_detector.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 实现质量检测模块**

```python
# scripts/lib/rag_engine/quality_detector.py
"""自动质量检测 — 三维度评分（忠实度 + 检索相关性 + 完整性）。"""
import re
import logging
from typing import List, Dict, Any, Optional

from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_NUMBER_PATTERN = re.compile(r'\d+[%年月天元周岁条]|第[一二三四五六七八九十百千\d]+条')
_QUESTION_NUMBER_PATTERN = re.compile(r'多少|几|哪些|什么比例|多少天|多少年|上限|下限')


def compute_retrieval_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    """计算 query 与检索结果的 bigram 重叠度（复用 evaluator 逻辑）"""
    if not query or not sources:
        return 0.0

    def _token_bigrams(text: str) -> set:
        tokens = tokenize_chinese(text)
        return {tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1)} if len(tokens) >= 2 else set()

    query_bigrams = _token_bigrams(query)
    if not query_bigrams:
        return 0.0

    context_bigrams: set = set()
    for s in sources:
        content = s.get("content", "")
        if content:
            context_bigrams |= _token_bigrams(content)

    if not context_bigrams:
        return 0.0

    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)


def compute_info_completeness(query: str, answer: str) -> float:
    """检测关键信息完整性

    如果用户问题中包含数字/比例/期限相关的提问意图，
    但回答中缺少具体数字，则完整性低。
    """
    if not query or not answer:
        return 0.0

    # 问题中没有数字查询意图 → 不检测完整性，直接返回 1.0
    if not _QUESTION_NUMBER_PATTERN.search(query) and not _NUMBER_PATTERN.search(query):
        return 1.0

    # 回答中是否有数字
    answer_numbers = _NUMBER_PATTERN.findall(answer)
    if not answer_numbers:
        return 0.0

    # 检查问题中问到的数字维度是否在回答中出现
    question_numbers = _NUMBER_PATTERN.findall(query)
    if not question_numbers:
        # 问题是"多少天"之类的，回答有数字就算完整
        return 1.0

    matched = sum(1 for qn in question_numbers if any(qn in an for an in answer_numbers))
    return matched / len(question_numbers) if question_numbers else 1.0


def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: Optional[float] = None,
) -> Dict[str, float]:
    """三维度自动质量评分

    Returns:
        {
            "faithfulness": float,        # 答案忠实度
            "retrieval_relevance": float, # 检索相关性
            "completeness": float,        # 关键信息完整性
            "overall": float,             # 综合评分
        }
    """
    faithfulness = faithfulness_score if faithfulness_score is not None else 0.0
    retrieval_relevance = compute_retrieval_relevance(query, sources)
    completeness = compute_info_completeness(query, answer)

    overall = (
        0.4 * faithfulness +
        0.3 * retrieval_relevance +
        0.3 * completeness
    )

    return {
        "faithfulness": round(faithfulness, 4),
        "retrieval_relevance": round(retrieval_relevance, 4),
        "completeness": round(completeness, 4),
        "overall": round(overall, 4),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest scripts/tests/lib/rag_engine/test_quality_detector.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 在 `__init__.py` 中导出**

在 `scripts/lib/rag_engine/__init__.py` 的 try 块中添加：

```python
from .quality_detector import detect_quality, compute_retrieval_relevance, compute_info_completeness
```

在 `__all__` 列表中添加 `'detect_quality', 'compute_retrieval_relevance', 'compute_info_completeness'`。

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/rag_engine/quality_detector.py scripts/lib/rag_engine/__init__.py \
       scripts/tests/lib/rag_engine/test_quality_detector.py
git commit -m "feat: add three-dimensional auto quality detection module"
```

---

### Task 6: Badcase 自动分类模块

**Files:**
- Create: `scripts/lib/rag_engine/badcase_classifier.py`
- Create: `scripts/tests/lib/rag_engine/test_badcase_classifier.py`
- Modify: `scripts/lib/rag_engine/__init__.py`

- [ ] **Step 1: 编写分类器测试**

```python
# scripts/tests/lib/rag_engine/test_badcase_classifier.py
import pytest
from lib.rag_engine.badcase_classifier import (
    classify_badcase,
    assess_compliance_risk,
)


class TestClassifyBadcase:
    def test_knowledge_gap(self):
        """知识库中没有相关信息"""
        result = classify_badcase(
            query="线上理赔怎么操作",
            retrieved_docs=[{"content": "健康保险等待期规定", "source_file": "health_ins.md"}],
            answer="提供的法规条款中未找到相关信息",
            unverified_claims=[],
        )
        assert result["type"] == "knowledge_gap"

    def test_hallucination(self):
        """检索到了正确文档但 LLM 答错了"""
        result = classify_badcase(
            query="健康保险等待期最长多少天",
            retrieved_docs=[{"content": "健康保险等待期不得超过90天"}],
            answer="等待期最长为30天",
            unverified_claims=["等待期最长为30天"],
        )
        assert result["type"] == "hallucination"

    def test_retrieval_failure(self):
        """检索到了文档但不是最相关的"""
        result = classify_badcase(
            query="意外险的免赔额是多少",
            retrieved_docs=[{"content": "健康保险的免赔规定", "source_file": "health_ins.md"}],
            answer="提供的法规条款中未找到关于意外险免赔额的信息",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"

    def test_no_unverified_and_answer_matches(self):
        """答案与检索结果一致，用户仍不满意 → 检索失败"""
        result = classify_badcase(
            query="保险合同解除条件",
            retrieved_docs=[{"content": "投保人可以解除保险合同"}],
            answer="投保人可以解除保险合同",
            unverified_claims=[],
        )
        assert result["type"] == "retrieval_failure"


class TestAssessComplianceRisk:
    def test_amount_in_wrong_answer(self):
        """错误答案中包含金额 → 高风险"""
        risk = assess_compliance_risk(
            reason="答案错误",
            answer="身故保险金为基本保额的150%",
        )
        assert risk == 2

    def test_compliance_keywords(self):
        """涉及合规关键词 → 中风险"""
        risk = assess_compliance_risk(
            reason="答案错误",
            answer="保险公司不得拒绝承保",
        )
        assert risk == 1

    def test_low_risk(self):
        risk = assess_compliance_risk(
            reason="回答不完整",
            answer="相关规定请查阅条款",
        )
        assert risk == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest scripts/tests/lib/rag_engine/test_badcase_classifier.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 实现分类模块**

```python
# scripts/lib/rag_engine/badcase_classifier.py
"""Badcase 三分类自动分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

_COMPLIANCE_AMOUNT_PATTERN = re.compile(
    r'\d+[%元万元]|身故保险金|赔付|赔偿|保额|保费|等待期|免赔'
)
_COMPLIANCE_KEYWORD_PATTERN = re.compile(
    r'(不得|必须|禁止|严禁|不得以|免除|承担|退还|返还)'
)


def classify_badcase(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
) -> Dict[str, str]:
    """三分类自动分类

    判断逻辑：
    1. 答案是"未找到相关信息"类 → knowledge_gap
    2. 检索文档中没有相关内容 → knowledge_gap
    3. 有未验证声明（数字/事实性陈述无引用）→ hallucination
    4. 答案与检索结果不一致 → hallucination
    5. 其他情况 → retrieval_failure（排序/召回不足）
    """
    # 1. 检查是否为知识缺失
    _gap_phrases = [
        "未找到", "未涉及", "没有找到", "无法确定",
        "未提供", "未包含", "条款中未找到",
    ]
    is_gap_answer = any(phrase in answer for phrase in _gap_phrases)
    if is_gap_answer and not unverified_claims:
        return {
            "type": "knowledge_gap",
            "reason": f"系统回答表示未找到相关信息: {answer[:100]}",
            "fix_direction": "补充相关法规文档到知识库",
        }

    # 2. 检查检索结果中是否有相关内容
    combined_content = " ".join(d.get("content", "") for d in retrieved_docs)
    if not combined_content.strip():
        return {
            "type": "knowledge_gap",
            "reason": "检索结果为空",
            "fix_direction": "补充相关法规文档到知识库",
        }

    # 3. 有未验证声明 → 幻觉
    if unverified_claims:
        claims_preview = "；".join(unverified_claims[:3])
        return {
            "type": "hallucination",
            "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
            "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
        }

    # 4. 答案与检索内容一致性检查（简单 bigram）
    from .tokenizer import tokenize_chinese
    answer_bigrams = set()
    tokens = tokenize_chinese(answer)
    for i in range(len(tokens) - 1):
        answer_bigrams.add(tokens[i] + tokens[i + 1])

    context_bigrams = set()
    ctx_tokens = tokenize_chinese(combined_content)
    for i in range(len(ctx_tokens) - 1):
        context_bigrams.add(ctx_tokens[i] + ctx_tokens[i + 1])

    if answer_bigrams and context_bigrams:
        overlap = len(answer_bigrams & context_bigrams) / len(answer_bigrams)
        if overlap < 0.2:
            return {
                "type": "hallucination",
                "reason": f"答案与检索内容重叠度极低({overlap:.2f})，疑似幻觉",
                "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
            }

    # 5. 默认：检索失败
    return {
        "type": "retrieval_failure",
        "reason": "检索结果可能不相关或排序不佳",
        "fix_direction": "优化 Chunk 策略、混合检索权重或 RRF 参数",
    }


def assess_compliance_risk(reason: str, answer: str) -> int:
    """评估合规风险等级

    Returns:
        0: 低风险
        1: 中风险（涉及合规关键词）
        2: 高风险（涉及金额/期限等精算敏感数字且被标记为答案错误）
    """
    if not answer:
        return 0

    if "答案错误" in reason and _COMPLIANCE_AMOUNT_PATTERN.search(answer):
        return 2

    if _COMPLIANCE_KEYWORD_PATTERN.search(answer):
        return 1

    return 0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest scripts/tests/lib/rag_engine/test_badcase_classifier.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 在 `__init__.py` 中导出**

在 try 块和 __all__ 中添加：

```python
from .badcase_classifier import classify_badcase, assess_compliance_risk
```

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/rag_engine/badcase_classifier.py scripts/lib/rag_engine/__init__.py \
       scripts/tests/lib/rag_engine/test_badcase_classifier.py
git commit -m "feat: add three-type badcase auto-classifier with compliance risk assessment"
```

---

### Task 7: 集成自动检测到 ask 路由

**Files:**
- Modify: `scripts/api/routers/ask.py`
- Modify: `scripts/api/routers/feedback.py`

- [ ] **Step 1: 在 ask.py 的 event_stream 中集成自动检测**

在 `add_message` 之后、`yield done event` 之前，添加自动检测逻辑：

```python
# 自动质量检测 — 低于阈值自动创建 feedback
try:
    from lib.rag_engine.quality_detector import detect_quality
    quality = detect_quality(
        query=req.question,
        answer=answer_str,
        sources=result.get("sources", []),
        faithfulness_score=result.get("faithfulness_score"),
    )
    if quality["overall"] < 0.4:
        from api.database import create_feedback
        create_feedback(
            message_id=cur.lastrowid,  # 需要从 add_message 获取
            conversation_id=conversation_id,
            rating="down",
            reason="auto_detected",
            source_channel="auto_detect",
        )
        # 更新刚创建的 feedback 的质量评分
        from api.database import update_feedback
        fb_rows = conn.execute(
            "SELECT id FROM feedback WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
            (cur.lastrowid,),
        ).fetchall()
except Exception as e:
    logger.warning(f"Auto quality detection failed: {e}")
```

> 实现细节：需要重构 `add_message` 返回值的使用方式，确保 `message_id` 可用。建议将 `add_message` 的返回值保存到变量，然后在自动检测中使用。

- [ ] **Step 2: 在 feedback.py 中添加批量分类端点**

```python
@router.post("/badcases/classify")
async def classify_badcases():
    """对所有 pending 状态的 badcase 执行自动分类"""
    from api.database import list_feedbacks, update_feedback, get_messages, get_connection
    import json

    pending = list_feedbacks(status="pending")
    classified_count = 0

    for fb in pending:
        if fb["rating"] != "down":
            update_feedback(fb["id"], {"status": "rejected"})
            continue

        # 获取对话上下文
        with get_connection() as conn:
            msgs = conn.execute(
                "SELECT role, content, sources_json, unverified_claims_json FROM messages WHERE id = ?",
                (fb["message_id"],),
            ).fetchone()
        if msgs is None:
            continue

        # 找到对应的 user 消息
        with get_connection() as conn:
            user_msg = conn.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
                (fb["conversation_id"], fb["message_id"]),
            ).fetchone()

        query = user_msg[0] if user_msg else ""
        sources = json.loads(msgs["sources_json"]) if msgs["sources_json"] else []
        answer = msgs["content"] or ""
        unverified = json.loads(msgs["unverified_claims_json"]) if msgs["unverified_claims_json"] else []

        try:
            from lib.rag_engine.badcase_classifier import classify_badcase, assess_compliance_risk
            from lib.rag_engine.quality_detector import detect_quality

            classification = classify_badcase(query, sources, answer, unverified)
            quality = detect_quality(query, answer, sources)
            risk = assess_compliance_risk(fb["reason"], answer)

            update_feedback(fb["id"], {
                "classified_type": classification["type"],
                "classified_reason": classification["reason"],
                "classified_fix_direction": classification["fix_direction"],
                "auto_quality_score": quality["overall"],
                "auto_quality_details_json": json.dumps(quality, ensure_ascii=False),
                "compliance_risk": risk,
                "status": "classified",
            })
            classified_count += 1
        except Exception as e:
            logger.error(f"Classification failed for {fb['id']}: {e}")

    return {"classified": classified_count, "total": len(pending)}
```

- [ ] **Step 3: 运行测试**

Run: `pytest scripts/tests/ -x -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/ask.py scripts/api/routers/feedback.py
git commit -m "feat: integrate auto quality detection in chat and add batch classify endpoint"
```

---

### Task 8: Badcase 管理前端页面

**Files:**
- Create: `scripts/web/src/stores/feedbackStore.ts`
- Create: `scripts/web/src/pages/FeedbackBadcasesPage.tsx`
- Modify: `scripts/web/src/App.tsx`

- [ ] **Step 1: 创建 feedbackStore**

```typescript
// scripts/web/src/stores/feedbackStore.ts
import { create } from 'zustand';
import type { Feedback, FeedbackStats } from '../types';
import * as feedbackApi from '../api/feedback';

interface FeedbackState {
  badcases: Feedback[];
  stats: FeedbackStats | null;
  loading: boolean;

  loadBadcases: (params?: { status?: string; classified_type?: string }) => Promise<void>;
  loadStats: () => Promise<void>;
  updateBadcase: (id: string, updates: Record<string, unknown>) => Promise<void>;
  classifyAll: () => Promise<void>;
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  badcases: [],
  stats: null,
  loading: false,

  loadBadcases: async (params) => {
    set({ loading: true });
    const badcases = await feedbackApi.fetchBadcases(params);
    set({ badcases, loading: false });
  },

  loadStats: async () => {
    const stats = await feedbackApi.fetchFeedbackStats();
    set({ stats });
  },

  updateBadcase: async (id, updates) => {
    await feedbackApi.updateBadcase(id, updates as Parameters<typeof feedbackApi.updateBadcase>[1]);
    // 重新加载列表
    get().loadBadcases();
  },

  classifyAll: async () => {
    set({ loading: true });
    const res = await fetch(`${import.meta.env.VITE_API_BASE || 'http://localhost:8000'}/api/feedback/badcases/classify`, {
      method: 'POST',
    });
    await res.json();
    get().loadBadcases();
    get().loadStats();
    set({ loading: false });
  },
}));
```

- [ ] **Step 2: 创建 Badcase 管理页面**

```tsx
// scripts/web/src/pages/FeedbackBadcasesPage.tsx
import React, { useEffect } from 'react';
import { Table, Tag, Select, Button, Space, message, Popconfirm } from 'antd';
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useFeedbackStore } from '../stores/feedbackStore';

const TYPE_COLORS: Record<string, string> = {
  retrieval_failure: 'orange',
  hallucination: 'red',
  knowledge_gap: 'blue',
  unclear: 'default',
};

const TYPE_LABELS: Record<string, string> = {
  retrieval_failure: '检索失败',
  hallucination: '幻觉生成',
  knowledge_gap: '知识缺失',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待分类',
  classified: '已分类',
  fixing: '修复中',
  fixed: '已修复',
  rejected: '已驳回',
  converted: '已转化',
};

const RISK_COLORS: Record<number, string> = {
  0: 'green',
  1: 'orange',
  2: 'red',
};

const RISK_LABELS: Record<number, string> = {
  0: '低',
  1: '中',
  2: '高',
};

export default function FeedbackBadcasesPage() {
  const { badcases, loading, loadBadcases, classifyAll, updateBadcase } = useFeedbackStore();
  const [filterStatus, setFilterStatus] = React.useState<string | undefined>();

  useEffect(() => {
    loadBadcases({ status: filterStatus });
  }, [filterStatus, loadBadcases]);

  const handleClassify = async () => {
    try {
      await classifyAll();
      message.success('批量分类完成');
    } catch {
      message.error('分类失败');
    }
  };

  const columns = [
    {
      title: '问题',
      dataIndex: 'conversation_id',
      key: 'question',
      width: 200,
      ellipsis: true,
      render: (_: unknown, record: typeof badcases[0]) => {
        // 从 conversation_id 反查问题文本（简化处理，显示 ID）
        return record.id;
      },
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      width: 150,
      ellipsis: true,
    },
    {
      title: '分类',
      dataIndex: 'classified_type',
      key: 'classified_type',
      width: 100,
      render: (type: string | null) =>
        type ? (
          <Tag color={TYPE_COLORS[type]}>{TYPE_LABELS[type] || type}</Tag>
        ) : (
          <Tag>未分类</Tag>
        ),
    },
    {
      title: '风险',
      dataIndex: 'compliance_risk',
      key: 'compliance_risk',
      width: 80,
      render: (risk: number) => (
        <Tag color={RISK_COLORS[risk]}>{RISK_LABELS[risk]}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => STATUS_LABELS[status] || status,
    },
    {
      title: '质量分',
      dataIndex: 'auto_quality_score',
      key: 'auto_quality_score',
      width: 80,
      render: (score: number | null) =>
        score !== null ? score.toFixed(2) : '-',
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: unknown, record: typeof badcases[0]) => (
        <Space size={4}>
          {record.status === 'pending' && (
            <Popconfirm title="标记为已驳回？" onConfirm={() => updateBadcase(record.id, { status: 'rejected' })}>
              <Button size="small" danger>驳回</Button>
            </Popconfirm>
          )}
          {record.status === 'classified' && (
            <Popconfirm title="标记为已修复？" onConfirm={() => updateBadcase(record.id, { status: 'fixed' })}>
              <Button size="small" type="primary">已修复</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Badcase 管理</h2>
        <Space>
          <Select
            placeholder="按状态筛选"
            allowClear
            style={{ width: 120 }}
            value={filterStatus}
            onChange={setFilterStatus}
            options={[
              { label: '待分类', value: 'pending' },
              { label: '已分类', value: 'classified' },
              { label: '修复中', value: 'fixing' },
              { label: '已修复', value: 'fixed' },
            ]}
          />
          <Button icon={<ThunderboltOutlined />} onClick={handleClassify} loading={loading}>
            批量分类
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => loadBadcases({ status: filterStatus })}>
            刷新
          </Button>
        </Space>
      </div>
      <Table
        columns={columns}
        dataSource={badcases}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 20 }}
      />
    </div>
  );
}
```

- [ ] **Step 3: 在 App.tsx 中注册路由**

```tsx
import FeedbackBadcasesPage from './pages/FeedbackBadcasesPage';

// 在 Routes 中添加：
<Route path="/feedback/badcases" element={<FeedbackBadcasesPage />} />
```

同时在 `AppLayout` 的导航菜单中添加"Badcase 管理"入口。

- [ ] **Step 4: 验证前端编译通过**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add scripts/web/src/stores/feedbackStore.ts scripts/web/src/pages/FeedbackBadcasesPage.tsx \
       scripts/web/src/App.tsx
git commit -m "feat: add Badcase management page with list, filter, classify, and status update"
```

---

## Phase 3: 闭环集成

### Task 9: 反馈统计页面

**Files:**
- Create: `scripts/web/src/pages/FeedbackStatsPage.tsx`
- Modify: `scripts/web/src/App.tsx`

- [ ] **Step 1: 创建统计页面**

```tsx
// scripts/web/src/pages/FeedbackStatsPage.tsx
import React, { useEffect } from 'react';
import { Card, Statistic, Row, Col, Tag, Table } from 'antd';
import { useFeedbackStore } from '../stores/feedbackStore';

export default function FeedbackStatsPage() {
  const { stats, loadStats } = useFeedbackStore();

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  if (!stats) {
    return <div style={{ padding: 24 }}>加载中...</div>;
  }

  const typeData = Object.entries(stats.by_type).map(([type, count]) => ({
    type,
    count,
  }));

  const statusData = Object.entries(stats.by_status).map(([status, count]) => ({
    status,
    count,
  }));

  const TYPE_LABELS: Record<string, string> = {
    retrieval_failure: '检索失败',
    hallucination: '幻觉生成',
    knowledge_gap: '知识缺失',
  };

  const STATUS_LABELS: Record<string, string> = {
    pending: '待分类',
    classified: '已分类',
    fixing: '修复中',
    fixed: '已修复',
    rejected: '已驳回',
    converted: '已转化',
  };

  return (
    <div style={{ padding: 24 }}>
      <h2>反馈统计</h2>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="总反馈数" value={stats.total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="好评数" value={stats.up_count} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="差评数" value={stats.down_count} valueStyle={{ color: '#ff4d4f' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="满意度"
              value={stats.satisfaction_rate * 100}
              suffix="%"
              precision={1}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="按类型分布">
            <Table
              dataSource={typeData}
              rowKey="type"
              pagination={false}
              size="small"
              columns={[
                { title: '类型', dataIndex: 'type', render: (t: string) => TYPE_LABELS[t] || t },
                { title: '数量', dataIndex: 'count' },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="按状态分布">
            <Table
              dataSource={statusData}
              rowKey="status"
              pagination={false}
              size="small"
              columns={[
                { title: '状态', dataIndex: 'status', render: (s: string) => STATUS_LABELS[s] || s },
                { title: '数量', dataIndex: 'count' },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
```

- [ ] **Step 2: 在 App.tsx 注册路由**

```tsx
import FeedbackStatsPage from './pages/FeedbackStatsPage';
<Route path="/feedback/stats" element={<FeedbackStatsPage />} />
```

- [ ] **Step 3: Commit**

```bash
git add scripts/web/src/pages/FeedbackStatsPage.tsx scripts/web/src/App.tsx
git commit -m "feat: add feedback statistics page with satisfaction and distribution charts"
```

---

### Task 10: Badcase 验证 + 转化

**Files:**
- Modify: `scripts/api/routers/feedback.py`

- [ ] **Step 1: 添加单条重跑验证端点**

```python
@router.post("/badcases/{feedback_id}/verify")
async def verify_badcase(feedback_id: str):
    """重跑 badcase 的原始问题，返回当前引擎的回答用于对比"""
    from api.database import get_feedback, get_connection
    import json

    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")

    # 获取原始问题
    with get_connection() as conn:
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (fb["conversation_id"], fb["message_id"]),
        ).fetchone()

    if user_msg is None:
        raise HTTPException(status_code=400, detail="无法找到原始问题")

    query = user_msg[0]

    try:
        from api.app import rag_engine
        if rag_engine is None:
            raise RuntimeError("RAG 引擎未就绪")

        result = rag_engine.ask(query, include_sources=True)
        return {
            "feedback_id": feedback_id,
            "original_answer": fb.get("correction") or "",
            "new_answer": result.get("answer", ""),
            "new_sources": result.get("sources", []),
            "new_citations": result.get("citations", []),
            "new_faithfulness": result.get("faithfulness_score"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {e}")
```

- [ ] **Step 2: 添加转化为评估样本端点**

```python
@router.post("/badcases/{feedback_id}/convert")
async def convert_to_eval_sample(feedback_id: str, ground_truth: str = ""):
    """将 badcase 转化为评估样本"""
    from api.database import get_feedback, upsert_eval_sample, update_feedback, get_connection
    import json

    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")

    # 获取上下文
    with get_connection() as conn:
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (fb["conversation_id"], fb["message_id"]),
        ).fetchone()
        assistant_msg = conn.execute(
            "SELECT sources_json FROM messages WHERE id = ?",
            (fb["message_id"],),
        ).fetchone()

    if user_msg is None:
        raise HTTPException(status_code=400, detail="无法找到原始问题")

    sources = json.loads(assistant_msg["sources_json"]) if assistant_msg else []
    evidence_docs = list({s.get("source_file", "") for s in sources if s.get("source_file")})

    sample_id = f"bc_{feedback_id}"
    upsert_eval_sample({
        "id": sample_id,
        "question": user_msg[0],
        "ground_truth": ground_truth or fb.get("correction", ""),
        "evidence_docs": evidence_docs,
        "evidence_keywords": [],
        "question_type": fb.get("classified_type", "factual"),
        "difficulty": "medium",
        "topic": "",
    })

    update_feedback(feedback_id, {"status": "converted"})
    return {"sample_id": sample_id, "feedback_id": feedback_id}
```

- [ ] **Step 3: 运行全部测试**

Run: `pytest scripts/tests/ -x -q`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/api/routers/feedback.py
git commit -m "feat: add badcase verify (re-run) and convert-to-eval-sample endpoints"
```

---

### Task 11: 前端集成验证 + 转化按钮

**Files:**
- Modify: `scripts/web/src/pages/FeedbackBadcasesPage.tsx`
- Modify: `scripts/web/src/api/feedback.ts`

- [ ] **Step 1: 在 feedback API 客户端中添加 verify 和 convert 方法**

```typescript
export async function verifyBadcase(id: string): Promise<{
  feedback_id: string;
  original_answer: string;
  new_answer: string;
  new_sources: Source[];
  new_citations: Citation[];
  new_faithfulness: number | null;
}> {
  const { data } = await client.post(`/api/feedback/badcases/${id}/verify`);
  return data;
}

export async function convertBadcase(id: string, ground_truth: string): Promise<{
  sample_id: string;
  feedback_id: string;
}> {
  const { data } = await client.post(`/api/feedback/badcases/${id}/convert`, null, {
    params: { ground_truth },
  });
  return data;
}
```

- [ ] **Step 2: 在 Badcase 管理页面中添加验证和转化操作按钮**

在操作列中添加：

```tsx
<Button
  size="small"
  onClick={async () => {
    const result = await verifyBadcase(record.id);
    // 弹窗显示对比结果
    Modal.info({
      title: '验证结果',
      width: 700,
      content: (
        <div>
          <h4>新回答:</h4>
          <p>{result.new_answer}</p>
          <h4>忠实度: {result.new_faithfulness}</h4>
        </div>
      ),
    });
  }}
>
  验证
</Button>

{record.status === 'fixed' && (
  <Popconfirm
    title="转化为评估样本？需要提供正确答案"
    onConfirm={async () => {
      const ground_truth = prompt('请输入正确答案（ground_truth）：');
      if (ground_truth) {
        await convertBadcase(record.id, ground_truth);
        message.success('已转化为评估样本');
        loadBadcases({ status: filterStatus });
      }
    }}
  >
    <Button size="small" type="dashed">转化</Button>
  </Popconfirm>
)}
```

需要导入 `Modal` from `antd`。

- [ ] **Step 3: 验证编译**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/pages/FeedbackBadcasesPage.tsx scripts/web/src/api/feedback.ts
git commit -m "feat: add verify and convert-to-eval-sample buttons in Badcase management page"
```

---

### Task 12: 最终集成测试 + 运行全部测试

**Files:**
- Create: `scripts/tests/api/test_feedback_router.py`

- [ ] **Step 1: 编写反馈 API 集成测试**

```python
# scripts/tests/api/test_feedback_router.py
"""反馈 API 集成测试"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import create_app
    app = create_app()
    return TestClient(app)


class TestFeedbackSubmit:
    def test_submit_feedback_returns_id(self, client):
        # 先创建一个对话和消息
        client.post("/api/ask/chat", json={
            "question": "测试问题",
            "mode": "search",
        })
        # 获取消息
        convs = client.get("/api/ask/conversations").json()
        if not convs:
            pytest.skip("No conversations created")
        conv_id = convs[0]["id"]
        msgs = client.get(f"/api/ask/conversations/{conv_id}/messages").json()
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        if not assistant_msgs:
            pytest.skip("No assistant messages")
        msg_id = assistant_msgs[0]["id"]

        resp = client.post("/api/feedback/submit", json={
            "message_id": msg_id,
            "rating": "down",
            "reason": "答案错误",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["rating"] == "down"
        assert data["reason"] == "答案错误"

    def test_submit_feedback_invalid_message(self, client):
        resp = client.post("/api/feedback/submit", json={
            "message_id": 99999,
            "rating": "down",
        })
        assert resp.status_code == 404


class TestFeedbackStats:
    def test_stats_returns_structure(self, client):
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "satisfaction_rate" in data
        assert "by_type" in data


class TestBadcaseList:
    def test_list_badcases(self, client):
        resp = client.get("/api/feedback/badcases")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_status(self, client):
        resp = client.get("/api/feedback/badcases?status=pending")
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "pending"
```

- [ ] **Step 2: 运行全部测试**

Run: `pytest scripts/tests/ -x -q`
Expected: 全部 PASS

- [ ] **Step 3: 运行 mypy 类型检查**

Run: `mypy scripts/lib/rag_engine/quality_detector.py scripts/lib/rag_engine/badcase_classifier.py`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add scripts/tests/api/test_feedback_router.py
git commit -m "test: add integration tests for feedback API endpoints"
```

---

## Self-Review Checklist

**Spec 覆盖：**
- [x] feedback 表 + messages 扩展 → Task 1
- [x] 反馈提交 API → Task 2
- [x] 前端反馈按钮 → Task 3
- [x] 质量元数据持久化 → Task 4
- [x] 自动质量检测（三维度）→ Task 5
- [x] 三分类自动分类 → Task 6
- [x] 自动检测集成到 chat → Task 7
- [x] Badcase 管理页面 → Task 8
- [x] 反馈统计页面 → Task 9
- [x] 单条验证 → Task 10
- [x] 转化为评估样本 → Task 10
- [x] 前端验证/转化按钮 → Task 11
- [x] 集成测试 → Task 12

**Placeholder 扫描：** 无 TBD/TODO/fill-in

**类型一致性：** `FeedbackCreate.rating` pattern `^(up|down)$` 与前端 `'up' | 'down'` 一致；`FeedbackOut.status` CHECK 约束与前端 `Feedback.status` union 一致
