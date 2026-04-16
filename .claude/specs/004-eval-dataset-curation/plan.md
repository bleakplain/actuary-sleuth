# Implementation Plan: 评测数据集人工审核与维护

**Branch**: `004-eval-dataset-curation` | **Date**: 2026-04-08
**Source**: research.md (兼容模式)

## Summary

为 RAG 评测模块新增**人工审核工作台**，让精算师在审核 eval case 时可以手动搜索知识库、一键引用法规条文、维护条文级引用（RegulationRef），最终产出审核通过的"准"评测数据集。

**核心设计决策**：
1. 引用粒度 — 条文级 `RegulationRef`（doc_name, article, excerpt, chunk_id），长 chunk 暂不处理
2. KB 搜索触发 — 纯手动，精算师点按钮搜索
3. 审核流程 — 单级，仅 pending / approved
4. 修改迭代 — 编辑即归 pending，支持无限次修改
5. 元数据溯源 — `created_by` 区分人工/LLM 生成，`kb_version` 绑定 KB 版本

## Technical Context

- **Language**: Python 3.x + TypeScript
- **Framework**: FastAPI (backend) + React + Ant Design (frontend)
- **Storage**: SQLite (eval_samples 表)
- **KB Search**: RAGEngine.search() 已就绪，chunk metadata 含 article_number
- **Testing**: pytest (backend)

## Constitution Check

- [x] **Library-First**: 复用 RAGEngine.search() 做知识库检索，复用 Ant Design 组件做 UI，不引入新框架
- [x] **测试优先**: 后端数据模型和 API 有单元测试覆盖
- [x] **简单优先**: 仅 pending/approved 两状态；纯手动搜索不搞自动推荐；不新建页面，在现有 EvalPage 新增 Tab
- [x] **显式优于隐式**: 审核状态变更明确写入 DB，不依赖隐式逻辑
- [x] **可追溯性**: reviewer + reviewed_at 记录审核人/时间
- [x] **独立可测试**: 后端 API 独立于前端，可 curl 验证

## Project Structure

```
.claude/specs/004-eval-dataset-curation/
├── research.md
└── plan.md                  # 本文件
```

### 涉及修改的文件

```
scripts/lib/rag_engine/eval_dataset.py   — 新增 RegulationRef, ReviewStatus, EvalSample 扩展字段
scripts/api/database.py                  — DDL 迁移 + CRUD 函数
scripts/api/schemas/eval.py              — 新增/修改 schema
scripts/api/routers/eval.py              — 新增审核 + KB 搜索 API
scripts/web/src/types/index.ts           — EvalSample 类型扩展
scripts/web/src/api/eval.ts              — 新增 API 调用函数
scripts/web/src/pages/EvalPage.tsx       — 新增审核 Tab + KB 搜索面板
scripts/tests/lib/rag_engine/test_eval_dataset.py — 数据模型测试
```

---

## Implementation Phases

### Phase 1: 数据模型与存储层

#### 1.1 扩展 EvalSample 数据模型

- 文件: `scripts/lib/rag_engine/eval_dataset.py`

新增 `RegulationRef`、`ReviewStatus`，扩展 `EvalSample`：

```python
@dataclass(frozen=True)
class RegulationRef:
    """条文级法规引用 — 从 RAGEngine.search() 结果直接构建"""
    doc_name: str
    article: str
    excerpt: str
    relevance: float = 1.0
    chunk_id: str = ""  # 预留：当前 chunker metadata 无此字段，暂为空

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'RegulationRef':
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


class ReviewStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"


@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: QuestionType
    difficulty: str
    topic: str
    # ── 审核字段 ──
    regulation_refs: List[RegulationRef] = ()
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    # ── 元数据溯源字段（基于 RAG 评测最佳实践）──
    created_by: str = "human"       # "human" | "llm" — 区分人工/LLM 生成
    kb_version: str = ""            # 绑定 KB 版本标识，空=未绑定

    def to_dict(self) -> dict:
        d = asdict(self)
        d['question_type'] = self.question_type.value
        d['review_status'] = self.review_status.value
        d['regulation_refs'] = [r.to_dict() for r in self.regulation_refs]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'EvalSample':
        valid = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in valid}
        d['question_type'] = QuestionType(d['question_type'])
        if 'review_status' in d and d['review_status']:
            d['review_status'] = ReviewStatus(d['review_status'])
        else:
            d['review_status'] = ReviewStatus.PENDING
        if 'regulation_refs' in d and d['regulation_refs']:
            d['regulation_refs'] = [RegulationRef.from_dict(r) for r in d['regulation_refs']]
        else:
            d['regulation_refs'] = []
        return cls(**d)
```

**关键**：新字段均有默认值，现有 `from_dict` 完全向后兼容，已有的 150+ 条 eval sample 无需迁移数据。

#### 1.2 SQLite DDL 迁移

- 文件: `scripts/api/database.py`

在 `_migrate_db()` 中新增列：

```python
# eval_samples 表新增审核字段 + 元数据溯源字段
sample_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_samples)").fetchall()}
if 'regulation_refs_json' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN regulation_refs_json TEXT NOT NULL DEFAULT '[]'")
if 'review_status' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
if 'reviewer' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN reviewer TEXT NOT NULL DEFAULT ''")
if 'reviewed_at' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN reviewed_at TEXT NOT NULL DEFAULT ''")
if 'review_comment' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN review_comment TEXT NOT NULL DEFAULT ''")
if 'created_by' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN created_by TEXT NOT NULL DEFAULT 'human'")
if 'kb_version' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN kb_version TEXT NOT NULL DEFAULT ''")
```

#### 1.3 更新 JSON 字段映射和 CRUD 函数

- 文件: `scripts/api/database.py`

```python
_SAMPLE_JSON_FIELDS = {
    "evidence_docs": "evidence_docs_json",
    "evidence_keywords": "evidence_keywords_json",
    "regulation_refs": "regulation_refs_json",  # 新增
}
```

更新 `upsert_eval_sample` — 在 VALUES 和 ON CONFLICT SET 中加入新字段：

```python
def upsert_eval_sample(sample: Dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO eval_samples
                (id, question, ground_truth, evidence_docs_json, evidence_keywords_json,
                 question_type, difficulty, topic, created_at, updated_at,
                 regulation_refs_json, review_status, reviewer, reviewed_at, review_comment,
                 created_by, kb_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                question = excluded.question,
                ground_truth = excluded.ground_truth,
                evidence_docs_json = excluded.evidence_docs_json,
                evidence_keywords_json = excluded.evidence_keywords_json,
                question_type = excluded.question_type,
                difficulty = excluded.difficulty,
                topic = excluded.topic,
                updated_at = excluded.updated_at,
                regulation_refs_json = excluded.regulation_refs_json,
                review_status = excluded.review_status,
                reviewer = excluded.reviewer,
                reviewed_at = excluded.reviewed_at,
                review_comment = excluded.review_comment,
                created_by = excluded.created_by,
                kb_version = excluded.kb_version
        """, (
            sample["id"], sample["question"], sample.get("ground_truth", ""),
            json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
            json.dumps(sample.get("evidence_keywords", []), ensure_ascii=False),
            sample.get("question_type", "factual"),
            sample.get("difficulty", "medium"),
            sample.get("topic", ""),
            now, now,
            json.dumps(sample.get("regulation_refs", []), ensure_ascii=False),
            sample.get("review_status", "pending"),
            sample.get("reviewer", ""),
            sample.get("reviewed_at", ""),
            sample.get("review_comment", ""),
            sample.get("created_by", "human"),
            sample.get("kb_version", ""),
        ))
```

#### 1.4 数据模型测试

- 文件: `scripts/tests/lib/rag_engine/test_eval_dataset.py`

新增测试用例：

```python
def test_regulation_ref_roundtrip():
    ref = RegulationRef(
        doc_name="健康保险管理办法.txt",
        article="第27条",
        excerpt="健康保险的产品设计应当...",
        relevance=0.92,
    )
    d = ref.to_dict()
    restored = RegulationRef.from_dict(d)
    assert restored == ref

def test_eval_sample_with_review_fields():
    sample = EvalSample(
        id="test001",
        question="测试问题",
        ground_truth="测试答案",
        evidence_docs=["保险法.txt"],
        evidence_keywords=["等待期"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="测试",
        regulation_refs=[RegulationRef(
            doc_name="保险法.txt", article="第18条",
            excerpt="保险合同中...", relevance=0.9,
        )],
        review_status=ReviewStatus.APPROVED,
        reviewer="张精算师",
        reviewed_at="2026-04-08T10:00:00+00:00",
    )
    d = sample.to_dict()
    restored = EvalSample.from_dict(d)
    assert restored.review_status == ReviewStatus.APPROVED
    assert len(restored.regulation_refs) == 1
    assert restored.regulation_refs[0].article == "第18条"

def test_eval_sample_backward_compatible():
    """没有新字段的旧数据仍能正常反序列化"""
    old_data = {
        "id": "f001",
        "question": "健康保险的等待期有什么规定？",
        "ground_truth": "既往症人群的等待期...",
        "evidence_docs": ["05_健康保险产品开发.md"],
        "evidence_keywords": ["等待期"],
        "question_type": "factual",
        "difficulty": "easy",
        "topic": "健康保险",
    }
    sample = EvalSample.from_dict(old_data)
    assert sample.review_status == ReviewStatus.PENDING
    assert sample.regulation_refs == []
```

---

### Phase 2: 后端 API

#### 2.1 扩展 Pydantic Schema

- 文件: `scripts/api/schemas/eval.py`

```python
class RegulationRefSchema(BaseModel):
    doc_name: str
    article: str
    excerpt: str
    relevance: float = 1.0
    chunk_id: str = ""

class EvalSampleCreate(BaseModel):
    id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    ground_truth: str = ""
    evidence_docs: List[str] = []
    evidence_keywords: List[str] = []
    question_type: str = Field("factual", pattern="^(factual|multi_hop|negative|colloquial)$")
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    topic: str = ""
    regulation_refs: List[RegulationRefSchema] = []
    review_status: str = Field("pending", pattern="^(pending|approved)$")
    reviewer: str = ""
    review_comment: str = ""
    created_by: str = Field("human", pattern="^(human|llm)$")
    kb_version: str = ""

class EvalSampleOut(BaseModel):
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: str
    difficulty: str
    topic: str
    regulation_refs: List[RegulationRefSchema]
    review_status: str
    reviewer: str
    reviewed_at: str
    review_comment: str
    created_by: str
    kb_version: str
    created_at: str
    updated_at: str

class ReviewSampleRequest(BaseModel):
    """审核通过请求"""
    reviewer: str = ""
    comment: str = ""

class KbSearchRequest(BaseModel):
    """知识库搜索请求"""
    query: str = Field(..., min_length=1)
    top_k: int = Field(10, ge=1, le=50)

class KbSearchResult(BaseModel):
    """知识库搜索结果条目"""
    doc_name: str
    article: str
    excerpt: str
    relevance: float
    hierarchy_path: str = ""
    chunk_id: str = ""
```

#### 2.2 审核状态流转 API

- 文件: `scripts/api/routers/eval.py`

```python
@router.patch("/dataset/samples/{sample_id}/review")
async def approve_sample(sample_id: str, req: ReviewSampleRequest):
    """审核通过 — 将状态设为 approved"""
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    now = datetime.now(timezone.utc).isoformat()
    existing["review_status"] = "approved"
    existing["reviewer"] = req.reviewer
    existing["reviewed_at"] = now
    existing["review_comment"] = req.comment
    upsert_eval_sample(existing)
    return get_eval_sample(sample_id)
```

**注意**：编辑 case 内容（question/ground_truth/regulation_refs）走已有的 `PUT /dataset/samples/{id}` 接口，在后端自动将 `review_status` 重置为 `pending`。

修改 `update_eval_sample` 路由：

```python
@router.put("/dataset/samples/{sample_id}", response_model=EvalSampleOut)
async def update_eval_sample(sample_id: str, sample: EvalSampleCreate):
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    update_data = sample.model_dump()
    update_data["id"] = sample_id
    # 任何内容编辑自动回到 pending
    update_data["review_status"] = "pending"
    update_data["reviewer"] = ""
    update_data["reviewed_at"] = ""
    upsert_eval_sample(update_data)
    return get_eval_sample(sample_id)
```

#### 2.3 审核统计 API

- 文件: `scripts/api/routers/eval.py`

```python
@router.get("/dataset/review-stats")
async def get_review_stats():
    """返回审核状态统计"""
    samples = get_eval_samples()
    total = len(samples)
    pending = sum(1 for s in samples if s.get("review_status") != "approved")
    approved = total - pending
    return {
        "total": total,
        "pending": pending,
        "approved": approved,
    }
```

#### 2.4 KB 搜索 API

- 文件: `scripts/api/routers/eval.py`

```python
@router.post("/dataset/kb-search")
async def search_knowledge_base(req: KbSearchRequest):
    """手动搜索知识库 — 返回条文级结果"""
    try:
        engine = get_rag_engine()
        results = engine.search(req.query, top_k=req.top_k)
        return [
            KbSearchResult(
                doc_name=r.get("metadata", {}).get("source_file", ""),
                article=r.get("metadata", {}).get("article_number", ""),
                excerpt=r.get("text", "")[:500],
                relevance=r.get("score", 0.0),
                hierarchy_path=r.get("metadata", {}).get("hierarchy_path", ""),
                chunk_id=r.get("metadata", {}).get("chunk_id", ""),
            )
            for r in results
            if r.get("text")
        ]
    except Exception as e:
        logger.error(f"KB 搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"知识库搜索失败: {str(e)}")
```

需要引入依赖：

```python
from api.dependencies import get_rag_engine
```

#### 2.5 list_eval_samples 支持 review_status 过滤

- 文件: `scripts/api/routers/eval.py`

```python
@router.get("/dataset", response_model=list[EvalSampleOut])
async def list_eval_samples(
    question_type: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None, pattern="^(pending|approved)$"),
):
    return get_eval_samples(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
        review_status=review_status,
    )
```

- 文件: `scripts/api/database.py` — `get_eval_samples` 增加 `review_status` 参数

---

### Phase 3: 前端审核工作台

#### 3.1 TypeScript 类型扩展

- 文件: `scripts/web/src/types/index.ts`

```typescript
export interface RegulationRef {
  doc_name: string;
  article: string;
  excerpt: string;
  relevance: number;
  chunk_id: string;
}

export interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: 'factual' | 'multi_hop' | 'negative' | 'colloquial';
  difficulty: 'easy' | 'medium' | 'hard';
  topic: string;
  // 审核字段
  regulation_refs: RegulationRef[];
  review_status: 'pending' | 'approved';
  reviewer: string;
  reviewed_at: string;
  review_comment: string;
  // 元数据溯源字段
  created_by: 'human' | 'llm';
  kb_version: string;
  // 时间戳
  created_at: string;
  updated_at: string;
}
```

#### 3.2 前端 API 函数

- 文件: `scripts/web/src/api/eval.ts`

```typescript
export async function approveSample(id: string, reviewer: string, comment: string): Promise<EvalSample> {
  const { data } = await client.patch(`/api/eval/dataset/samples/${id}/review`, { reviewer, comment });
  return data;
}

export async function fetchReviewStats(): Promise<{ total: number; pending: number; approved: number }> {
  const { data } = await client.get('/api/eval/dataset/review-stats');
  return data;
}

export async function searchKnowledgeBase(query: string, topK = 10): Promise<{
  doc_name: string; article: string; excerpt: string; relevance: number; hierarchy_path: string; chunk_id: string;
}[]> {
  const { data } = await client.post('/api/eval/dataset/kb-search', { query, top_k: topK });
  return data;
}
```

#### 3.3 EvalPage 新增"审核"Tab

- 文件: `scripts/web/src/pages/EvalPage.tsx`

在现有 `activeTab` 体系中新增 `"review"` Tab，核心布局：

```
┌──────────────────────────────────────────────────────────────────┐
│  [数据集] [审核] [运行] [配置]                                     │
├──────────────────────────────────────────────────────────────────┤
│  审核 Tab                                                        │
│                                                                  │
│  ┌─ 样本列表 ─────────────────────┐  ┌─ 审核面板 ────────────────┐│
│  │ 待审核: 120  已通过: 35         │  │                          ││
│  │ [筛选: 全部/待审核/已通过]       │  │  ID: f001               ││
│  │                                │  │  问题: 健康保险等待期...   ││
│  │ ⏳ f001 健康保险的等待期...      │  │                          ││
│  │ ✅ f002 分红型保险死亡保险...   │  │  Ground Truth:           ││
│  │ ⏳ f003 普通型人身保险佣金...    │  │  [可编辑文本区域]         ││
│  │ ...                            │  │                          ││
│  │                                │  │  已引用法规:              ││
│  │                                │  │  📎 保险法 §18  [✕]      ││
│  │                                │  │                          ││
│  │                                │  │  [🔍 搜索法规] ___ [搜索] ││
│  │                                │  │  ┌─ 搜索结果 ──────────┐ ││
│  │                                │  │  │ 保险法 §18  0.92    │ ││
│  │                                │  │  │ [引用]              │ ││
│  │                                │  │  │ 健康险办法 §12 0.85 │ ││
│  │                                │  │  │ [引用]              │ ││
│  │                                │  │  └────────────────────┘ ││
│  │                                │  │                          ││
│  │                                │  │  备注: [____]            ││
│  │                                │  │  审核人: [____]          ││
│  │                                │  │  [保存] [✓ 审核通过]      ││
│  └────────────────────────────────┘  └──────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

**交互流程**：
1. 左侧列表显示所有样本，带审核状态 Tag（pending/approved）
2. 点击样本 → 右侧面板加载详情
3. 精算师编辑 ground_truth / 补充 evidence → 点"保存"（自动归 pending）
4. 精算师点"搜索法规" → 输入关键词 → 展示搜索结果
5. 点搜索结果旁的"引用" → 添加到 regulation_refs
6. 审核满意 → 点"审核通过" → 状态变为 approved

**组件拆分建议**（在 EvalPage.tsx 内用函数组件拆分，不新建文件）：
- `ReviewTab` — 审核 Tab 主组件
- `ReviewList` — 左侧样本列表
- `ReviewPanel` — 右侧审核面板
- `KbSearchPanel` — KB 搜索子面板

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| EvalPage.tsx 组件体量大 | 不新建独立页面 | 新建 ReviewPage 需复制大量路由/状态/依赖管理代码，成本更高。在 EvalPage 内用函数组件拆分已足够 |

---

## Appendix

### 执行顺序建议

```
Phase 1 (数据层) ──→ Phase 2 (API) ──→ Phase 3 (前端)
     │                      │                    │
     ├─ 1.1 数据模型         ├─ 2.1 Schema        ├─ 3.1 TS 类型
     ├─ 1.2 DDL 迁移        ├─ 2.2 审核 API       ├─ 3.2 API 函数
     ├─ 1.3 CRUD 更新        ├─ 2.3 统计 API       ├─ 3.3 审核 Tab
     └─ 1.4 测试            └─ 2.4 KB 搜索 API    └─ 3.4 样本列表过滤
                            └─ 2.5 列表过滤
```

### 验收标准

| 阶段 | 验收标准 | 验证方式 |
|------|---------|---------|
| Phase 1.1 | RegulationRef 序列化/反序列化正确，EvalSample 向后兼容 | pytest |
| Phase 1.2 | SQLite 迁移成功，新字段默认值正确 | 手动检查 DB |
| Phase 2.2 | PATCH /review 将状态设为 approved，PUT 自动归 pending | curl |
| Phase 2.4 | POST /kb-search 返回条文级结果（含 article_number） | curl |
| Phase 3.3 | 精算师可在审核 Tab 中搜索 KB、引用法规、审核通过 | 手动 E2E |

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| RAGEngine 实例在审核场景下未初始化 | 复用 `api/dependencies.py:get_rag_engine()` 懒加载 |
| EvalPage.tsx 过大影响维护 | 用函数组件拆分 ReviewTab 内部逻辑 |
| 现有 evaluator 读取 EvalSample 不兼容新字段 | from_dict 有默认值兜底，完全兼容 |
