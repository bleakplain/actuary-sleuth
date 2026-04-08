# Eval Config Management Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify eval config model to flat ID-based versioning, promote config management from Drawer to independent Tab, add config comparison, and clarify config-evaluation association.

**Architecture:** Remove name-based grouping from eval_configs (no more name+version composite key). Each config is an independent entity with auto-incrementing version number. Global `is_active` flag marks exactly one config as the active evaluation config. Frontend: promote config management from Drawer to a first-class Tab in EvalPage; simplify eval history config selection to a dropdown.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Ant Design (frontend), SQLite (database)

---

### Task 1: Simplify eval_configs database schema

**Files:**
- Modify: `scripts/api/database.py:79-87` (schema definition)
- Modify: `scripts/api/database.py:486-579` (config CRUD functions)
- Modify: `scripts/api/database.py:192-219` (migration)
- Test: `scripts/tests/api/test_eval_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/api/test_eval_config.py`:

```python
"""eval_configs 表扁平版本管理测试。"""
import pytest
from api.database import (
    insert_eval_config, get_eval_configs, get_eval_config,
    get_active_config, activate_eval_config, remove_eval_config,
    _ensure_default_config,
)


@pytest.fixture()
def db(_patch_database):
    """确保 eval_configs 表存在，插入默认配置。"""
    _ensure_default_config()
    yield


class TestInsertEvalConfig:
    def test_auto_increment_version(self, db):
        c1 = insert_eval_config("第一个配置", {"retrieval": {"vector_top_k": 10}})
        c2 = insert_eval_config("第二个配置", {"retrieval": {"vector_top_k": 20}})
        configs = get_eval_configs()
        versions = [c["version"] for c in configs]
        assert c1["version"] == 1
        assert c2["version"] == 2
        assert versions == [2, 1]  # DESC order

    def test_first_insert_version_is_1(self, db):
        c = insert_eval_config("初始配置", {})
        assert c == 1

    def test_stores_config_json(self, db):
        config = {"retrieval": {"vector_top_k": 15}, "rerank": {"enable_rerank": False}}
        cid = insert_eval_config("测试", config)
        result = get_eval_config(cid)
        assert result["config_json"]["retrieval"]["vector_top_k"] == 15
        assert result["config_json"]["rerank"]["enable_rerank"] is False

    def test_description_defaults_empty(self, db):
        cid = insert_eval_config("无描述", {})
        result = get_eval_config(cid)
        assert result["description"] == ""


class TestGetEvalConfigs:
    def test_returns_all_configs_desc(self, db):
        insert_eval_config("A", {})
        insert_eval_config("B", {})
        configs = get_eval_configs()
        assert len(configs) == 3  # default + A + B
        assert configs[0]["version"] >= configs[1]["version"]


class TestActivateEvalConfig:
    def test_only_one_active(self, db):
        c1 = insert_eval_config("配置1", {})
        c2 = insert_eval_config("配置2", {})
        activate_eval_config(c2)
        cfg1 = get_eval_config(c1)
        cfg2 = get_eval_config(c2)
        assert cfg1["is_active"] == 0
        assert cfg2["is_active"] == 1

    def test_get_active_config(self, db):
        c = insert_eval_config("新配置", {})
        activate_eval_config(c)
        active = get_active_config()
        assert active is not None
        assert active["id"] == c

    def test_default_config_is_active(self, db):
        active = get_active_config()
        assert active is not None


class TestRemoveEvalConfig:
    def test_cannot_delete_active(self, db):
        active = get_active_config()
        assert active is not None
        result = remove_eval_config(active["id"])
        assert result is False

    def test_delete_inactive(self, db):
        c = insert_eval_config("可删除", {})
        result = remove_eval_config(c)
        assert result is True
        assert get_eval_config(c) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -m pytest tests/api/test_eval_config.py -v`
Expected: FAIL — current `insert_eval_config` uses name-based versioning, `get_active_config` requires name param.

- [ ] **Step 3: Update database schema and CRUD functions**

In `scripts/api/database.py`:

**Schema** (line 79-87) — remove `name` column:

```sql
CREATE TABLE IF NOT EXISTS eval_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**insert_eval_config** (replace line 489-506):

```python
def insert_eval_config(description: str, config: Dict) -> int:
    """创建评测配置新版本，自动 version+1。"""
    with get_connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM eval_configs").fetchone()
        next_version = row[0] + 1
        conn.execute(
            "INSERT INTO eval_configs (version, description, config_json) VALUES (?, ?, ?)",
            (next_version, description, json.dumps(config, ensure_ascii=False)),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
```

**get_eval_configs** (replace line 509-522):

```python
def get_eval_configs() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, description, is_active, created_at FROM eval_configs "
            "ORDER BY version DESC",
        ).fetchall()
        return [dict(r) for r in rows]
```

**get_eval_config** (keep line 525-534, remove `name` from SELECT):

```python
def get_eval_config(config_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, version, description, config_json, is_active, created_at "
            "FROM eval_configs WHERE id = ?",
            (config_id,),
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), {"config_json": "config_json"})
```

**get_active_config** (replace line 537-546, remove name param):

```python
def get_active_config() -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, version, description, config_json, is_active, created_at "
            "FROM eval_configs WHERE is_active = 1",
        ).fetchone()
        if row is None:
            return None
        return _deserialize_json_fields(dict(row), {"config_json": "config_json"})
```

**remove_eval_config** (replace line 549-558):

```python
def remove_eval_config(config_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_active FROM eval_configs WHERE id = ?", (config_id,),
        ).fetchone()
        if row is None:
            return False
        if row["is_active"]:
            return False
        conn.execute("DELETE FROM eval_configs WHERE id = ?", (config_id,))
        return True
```

**activate_eval_config** (replace line 562-569):

```python
def activate_eval_config(config_id: int) -> bool:
    """将指定配置设为激活版本，其他版本自动停用。"""
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM eval_configs WHERE id = ?", (config_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE eval_configs SET is_active = 0 WHERE is_active = 1")
        conn.execute("UPDATE eval_configs SET is_active = 1 WHERE id = ?", (config_id,))
        return True
```

**_ensure_default_config** (replace line 573-579):

```python
def _ensure_default_config():
    """启动时检查，如果 eval_configs 为空则插入默认配置。"""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM eval_configs").fetchone()[0]
        if count > 0:
            return
    from lib.rag_engine.config import RAGConfig
    insert_eval_config("默认配置", RAGConfig().to_dict())
    # 激活第一个配置
    with get_connection() as conn:
        conn.execute("UPDATE eval_configs SET is_active = 1 WHERE id = (SELECT id FROM eval_configs LIMIT 1)")
```

- [ ] **Step 4: Add migration for existing databases**

In `_migrate_db()` (after line 219), add:

```python
        # Migrate eval_configs: remove name column, make is_active global
        config_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_configs)").fetchall()}
        if 'name' in config_cols:
            # SQLite doesn't support DROP COLUMN before 3.35.0,
            # so we recreate the table without name.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS eval_configs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                INSERT INTO eval_configs_new (id, version, description, config_json, is_active, created_at)
                SELECT id, version, description, config_json,
                       CASE WHEN rowid = (SELECT rowid FROM eval_configs WHERE is_active = 1 LIMIT 1) THEN 1 ELSE 0 END,
                       created_at
                FROM eval_configs
            """)
            conn.execute("DROP TABLE eval_configs")
            conn.execute("ALTER TABLE eval_configs_new RENAME TO eval_configs")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts && python -m pytest tests/api/test_eval_config.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/api/database.py scripts/tests/api/test_eval_config.py
git commit -m "refactor: simplify eval_configs to flat ID-based versioning without name grouping"
```

---

### Task 2: Update API schemas and router for new config model

**Files:**
- Modify: `scripts/api/schemas/eval.py:42-50` (EvalConfigCreate)
- Modify: `scripts/api/routers/eval.py:126-151,388-431` (router functions)

- [ ] **Step 1: Update EvalConfigCreate schema**

In `scripts/api/schemas/eval.py`, replace `EvalConfigCreate` (line 42-50):

```python
class EvalConfigCreate(BaseModel):
    description: str = ""
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)

    def to_config_dict(self) -> dict:
        return config_to_dict(self.retrieval, self.rerank, self.generation)
```

- [ ] **Step 2: Update _build_eval_record and _load_config**

In `scripts/api/routers/eval.py`, replace `_build_eval_record` (line 129-141):

```python
def _build_eval_record(config: RAGConfig, mode: str, total_samples: int,
                       judge_model="", config_id=None, config_version=None) -> Dict:
    result = config.to_dict()
    result["evaluation"] = {"mode": mode, "judge_model": judge_model}
    result["dataset"] = {"total_samples": total_samples}
    if config_id is not None:
        result["dataset"]["config_id"] = config_id
    if config_version is not None:
        result["dataset"]["config_version"] = config_version
    return result
```

Replace `_load_config` (line 144-150):

```python
def _load_config(config_id: int):
    """从 eval_configs 表加载 RAGConfig。"""
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise ValueError(f"配置不存在: {config_id}")
    config = RAGConfig.from_dict(cfg["config_json"])
    return config, cfg["version"]
```

Update the caller in `create_evaluation` (around line 165):

```python
            config, config_version = _load_config(req.config_id)
```

And the `_build_eval_record` call (around line 183):

```python
                _build_eval_record(config, req.mode, total,
                                   judge_model, req.config_id, config_version),
```

- [ ] **Step 3: Update config CRUD router endpoints**

In `scripts/api/routers/eval.py`, replace the config endpoints (line 388-431):

```python
@router.get("/configs")
async def list_eval_configs():
    return get_eval_configs()


@router.get("/configs/active")
async def get_active_eval_config():
    cfg = get_active_config()
    if cfg is None:
        raise HTTPException(status_code=404, detail="无激活的评测配置")
    return cfg


@router.post("/configs")
async def add_eval_config(req: EvalConfigCreate):
    config_id = insert_eval_config(req.description, req.to_config_dict())
    return {"id": config_id, "version": get_eval_config(config_id)["version"]}


@router.delete("/configs/{config_id}")
async def delete_eval_config(config_id: int):
    if not remove_eval_config(config_id):
        raise HTTPException(status_code=400, detail="只能删除非激活版本的配置")


@router.get("/configs/{config_id}")
async def get_single_eval_config(config_id: int):
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    return cfg


@router.post("/configs/{config_id}/activate")
async def activate_config(config_id: int):
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    if not activate_eval_config(config_id):
        raise HTTPException(status_code=500, detail="激活失败")
    return {"id": config_id, "version": cfg["version"]}
```

- [ ] **Step 4: Update router imports**

Remove unused imports. The `get_active_config` import changes (no longer takes name param).

- [ ] **Step 5: Run all tests**

Run: `cd scripts && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/api/schemas/eval.py scripts/api/routers/eval.py
git commit -m "refactor: update API schemas and router for flat config model"
```

---

### Task 3: Update frontend types and API layer

**Files:**
- Modify: `scripts/web/src/types/index.ts:108-120` (EvalConfig interface)
- Modify: `scripts/web/src/api/eval.ts:47-82` (config API functions)

- [ ] **Step 1: Update EvalConfig interface**

In `scripts/web/src/types/index.ts`, replace `EvalConfig` (line 108-120):

```typescript
export interface EvalConfig {
  id: number;
  version: number;
  description: string;
  is_active: number;
  created_at: string;
  config_json?: {
    retrieval?: Record<string, string | number | boolean>;
    rerank?: Record<string, string | number | boolean>;
    generation?: Record<string, string | number | boolean>;
  };
}
```

- [ ] **Step 2: Update config API functions**

In `scripts/web/src/api/eval.ts`, replace config API section (line 47-82):

```typescript
// ── 评测配置 ──────────────────────────────────────────

export async function fetchEvalConfigs(): Promise<EvalConfig[]> {
  const { data } = await client.get('/api/eval/configs');
  return data;
}

export async function fetchActiveConfig(): Promise<EvalConfig> {
  const { data } = await client.get('/api/eval/configs/active');
  return data;
}

export async function deleteEvalConfig(configId: number): Promise<void> {
  await client.delete(`/api/eval/configs/${configId}`);
}

export async function fetchEvalConfig(configId: number): Promise<EvalConfig> {
  const { data } = await client.get(`/api/eval/configs/${configId}`);
  return data;
}

export async function activateEvalConfig(configId: number): Promise<{ id: number; version: number }> {
  const { data } = await client.post(`/api/eval/configs/${configId}/activate`);
  return data;
}

export async function createEvalConfig(config: {
  description?: string;
  retrieval?: Record<string, unknown>;
  rerank?: Record<string, unknown>;
  generation?: Record<string, unknown>;
}): Promise<{ id: number; version: number }> {
  const { data } = await client.post('/api/eval/configs', config);
  return data;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: No errors (or only pre-existing errors)

- [ ] **Step 4: Commit**

```bash
git add scripts/web/src/types/index.ts scripts/web/src/api/eval.ts
git commit -m "refactor: update frontend types and API for flat config model"
```

---

### Task 4: Promote config management to independent Tab

**Files:**
- Modify: `scripts/web/src/pages/EvalPage.tsx` (major refactor)

This is the largest task. The EvalPage currently has 2 Tabs (`dataset`, `runs`) with a Drawer for config management. We need to:
1. Add `configs` Tab
2. Move config CRUD from Drawer into the Tab
3. Simplify eval history config selection (Drawer → Select dropdown)
4. Remove the Drawer and related state

- [ ] **Step 1: Remove Drawer-related state and handlers**

Remove these state variables (around line 76-81):
- `configDrawerOpen`
- `rightPanelMode`
- `selectedVersion`
- `selectedVersionConfigJson`
- `expandedConfigName`

Remove these handlers (line 410-548):
- `configGroups` memo
- `open_config_drawer`
- `select_version`
- `handle_clone`
- `handle_new_config`
- `handle_save_config`
- `handle_activate`
- `handle_delete_config`

Remove the Drawer JSX block (line 1014-1255).

Remove unused imports: `Drawer`, `Collapse`.

- [ ] **Step 2: Add config Tab state and handlers**

Add new state variables:

```typescript
// Config Tab state
const [configList, setConfigList] = useState<EvalConfig[]>([]);
const [viewingConfig, setViewingConfig] = useState<EvalConfig | null>(null);
const [viewingConfigJson, setViewingConfigJson] = useState<EvalConfig['config_json'] | null>(null);
const [editingConfig, setEditingConfig] = useState<boolean>(false);
const [compareIds, setCompareIds] = useState<number[]>([]);
const [compareResult, setCompareResult] = useState<{ param: string; values: (string | number | boolean)[] }[] | null>(null);
```

Add new handlers (replace the removed ones):

```typescript
const refresh_configs = useCallback(async () => {
  const configs = await evalApi.fetchEvalConfigs();
  setConfigList(configs);
  return configs;
}, []);

useEffect(() => {
  if (activeTab === 'configs') refresh_configs();
}, [activeTab, refresh_configs]);

const view_config = async (config: EvalConfig) => {
  setViewingConfig(config);
  setEditingConfig(false);
  try {
    const full = await evalApi.fetchEvalConfig(config.id);
    setViewingConfigJson(full.config_json || null);
  } catch {
    message.error('加载配置详情失败');
  }
};

const start_new_config = () => {
  setViewingConfig(null);
  setViewingConfigJson(null);
  setEditingConfig(true);
  editForm.setFieldsValue({
    description: '',
    retrieval_vector_top_k: 20,
    retrieval_keyword_top_k: 20,
    retrieval_rrf_k: 60,
    retrieval_max_chunks_per_article: 3,
    retrieval_min_rrf_score: 0,
    rerank_enable_rerank: true,
    rerank_reranker_type: 'gguf',
    rerank_rerank_top_k: 5,
    rerank_min_score: 0,
    generation_max_context_chars: 12000,
  });
};

const clone_config = () => {
  if (!viewingConfig || !viewingConfigJson) return;
  setEditingConfig(true);
  const cj = viewingConfigJson;
  editForm.setFieldsValue({
    description: viewingConfig.description,
    retrieval_vector_top_k: cj?.retrieval?.vector_top_k ?? 20,
    retrieval_keyword_top_k: cj?.retrieval?.keyword_top_k ?? 20,
    retrieval_rrf_k: cj?.retrieval?.rrf_k ?? 60,
    retrieval_max_chunks_per_article: cj?.retrieval?.max_chunks_per_article ?? 3,
    retrieval_min_rrf_score: cj?.retrieval?.min_rrf_score ?? 0,
    rerank_enable_rerank: cj?.rerank?.enable_rerank ?? true,
    rerank_reranker_type: cj?.rerank?.reranker_type ?? 'gguf',
    rerank_rerank_top_k: cj?.rerank?.rerank_top_k ?? 5,
    rerank_min_score: cj?.rerank?.rerank_min_score ?? 0,
    generation_max_context_chars: cj?.generation?.max_context_chars ?? 12000,
  });
};

const save_config = async () => {
  try {
    const values = await editForm.validateFields();
    await evalApi.createEvalConfig({
      description: values.description || '',
      retrieval: {
        vector_top_k: values.retrieval_vector_top_k,
        keyword_top_k: values.retrieval_keyword_top_k,
        rrf_k: values.retrieval_rrf_k,
        max_chunks_per_article: values.retrieval_max_chunks_per_article,
        min_rrf_score: values.retrieval_min_rrf_score,
      },
      rerank: {
        enable_rerank: values.rerank_enable_rerank,
        reranker_type: values.rerank_reranker_type,
        rerank_top_k: values.rerank_rerank_top_k,
        rerank_min_score: values.rerank_min_score,
      },
      generation: {
        max_context_chars: values.generation_max_context_chars,
      },
    });
    message.success('配置创建成功');
    await refresh_configs();
    setEditingConfig(false);
    setViewingConfig(null);
  } catch (err) {
    message.error(`保存配置失败: ${err}`);
  }
};

const activate_config = async (configId: number) => {
  try {
    await evalApi.activateEvalConfig(configId);
    message.success('已切换为当前生效配置');
    await refresh_configs();
    if (viewingConfig?.id === configId) {
      const updated = await evalApi.fetchEvalConfig(configId);
      setViewingConfig(updated);
    }
  } catch (err) {
    message.error(`切换失败: ${err}`);
  }
};

const delete_config = async (configId: number) => {
  try {
    await evalApi.deleteEvalConfig(configId);
    message.success('配置已删除');
    if (selectedConfigId === configId) setSelectedConfigId(null);
    if (viewingConfig?.id === configId) {
      setViewingConfig(null);
      setViewingConfigJson(null);
    }
    await refresh_configs();
  } catch (err) {
    message.error(`删除失败: ${err}`);
  }
};

const toggle_compare = (configId: number) => {
  setCompareIds((prev) =>
    prev.includes(configId)
      ? prev.filter((id) => id !== configId)
      : prev.length < 2
        ? [...prev, configId]
        : prev,
  );
  setCompareResult(null);
};

const run_compare = async () => {
  if (compareIds.length !== 2) return;
  const [c1, c2] = await Promise.all(
    compareIds.map((id) => evalApi.fetchEvalConfig(id)),
  );
  const j1 = c1.config_json || {};
  const j2 = c2.config_json || {};
  const allKeys = new Set([...Object.keys(j1), ...Object.keys(j2)]);
  const rows: { param: string; values: (string | number | boolean)[] }[] = [];
  for (const section of ['retrieval', 'rerank', 'generation']) {
    const s1 = j1[section] || {};
    const s2 = j2[section] || {};
    for (const key of Object.keys({ ...s1, ...s2 })) {
      rows.push({
        param: `${section}.${key}`,
        values: [s1[key] ?? '-', s2[key] ?? '-'],
      });
    }
  }
  setCompareResult(rows);
};
```

- [ ] **Step 3: Add configs Tab JSX**

Add to the Tabs `items` array, between `dataset` and `runs`:

```typescript
{
  key: 'configs',
  label: '配置管理',
  children: (
    <Row gutter={16}>
      <Col span={10}>
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={start_new_config}>
            新建配置
          </Button>
          <Space>
            <Checkbox
              checked={compareIds.length > 0}
              indeterminate={compareIds.length === 1}
              onChange={(e) => { if (!e.target.checked) setCompareIds([]); setCompareResult(null); }}
            >
              对比模式
            </Checkbox>
            {compareIds.length === 2 && (
              <Button size="small" icon={<SwapOutlined />} onClick={run_compare}>对比</Button>
            )}
          </Space>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto', maxHeight: 'calc(100vh - 220px)' }}>
          {configList.length === 0 ? (
            <Text type="secondary">暂无配置</Text>
          ) : (
            configList.map((cfg) => (
              <Card
                key={cfg.id}
                size="small"
                hoverable
                style={{
                  cursor: 'pointer',
                  borderLeft: cfg.is_active ? '3px solid #52c41a' : '3px solid transparent',
                  background: viewingConfig?.id === cfg.id ? '#e6f4ff' : undefined,
                }}
                onClick={() => compareIds.length > 0 ? toggle_compare(cfg.id) : view_config(cfg)}
                bodyStyle={{ padding: '8px 12px' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>
                    {compareIds.length > 0 && (
                      <Checkbox
                        checked={compareIds.includes(cfg.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggle_compare(cfg.id)}
                        style={{ marginRight: 8 }}
                      />
                    )}
                    <Text strong>v{cfg.version}</Text>
                    {cfg.description && (
                      <Text type="secondary" style={{ marginLeft: 8 }}>{cfg.description}</Text>
                    )}
                  </span>
                  <Space size={4}>
                    {cfg.is_active ? <Tag color="green">生效中</Tag> : null}
                    <Text type="secondary" style={{ fontSize: 12 }}>{cfg.created_at?.slice(0, 10)}</Text>
                  </Space>
                </div>
              </Card>
            ))
          )}
        </div>
      </Col>

      <Col span={14}>
        {compareResult && (
          <Card title="配置对比" size="small">
            <Table
              dataSource={compareResult.map((r, i) => ({ key: i, ...r }))}
              columns={[
                { title: '参数', dataIndex: 'param', key: 'param', width: 200 },
                {
                  title: `v${configList.find((c) => c.id === compareIds[0])?.version}`,
                  dataIndex: 'values', key: 'v1', width: 120,
                  render: (_: unknown, r: { values: (string | number | boolean)[] }) => (
                    <span style={{ color: r.values[0] !== r.values[1] ? '#1677ff' : undefined }}>
                      {String(r.values[0])}
                    </span>
                  ),
                },
                {
                  title: `v${configList.find((c) => c.id === compareIds[1])?.version}`,
                  dataIndex: 'values', key: 'v2', width: 120,
                  render: (_: unknown, r: { values: (string | number | boolean)[] }) => (
                    <span style={{ color: r.values[0] !== r.values[1] ? '#1677ff' : undefined }}>
                      {String(r.values[1])}
                    </span>
                  ),
                },
              ]}
              pagination={false}
              size="small"
            />
          </Card>
        )}

        {!compareResult && !editingConfig && viewingConfig && viewingConfigJson && (
          <>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="版本">v{viewingConfig.version}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {viewingConfig.is_active ? <Tag color="green">生效中</Tag> : <Tag>未激活</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="说明" span={2}>{viewingConfig.description || '-'}</Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>{viewingConfig.created_at}</Descriptions.Item>
            </Descriptions>

            <Card size="small" title="检索参数" style={{ marginTop: 16 }}>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="向量 Top-K">{viewingConfigJson.retrieval?.vector_top_k}</Descriptions.Item>
                <Descriptions.Item label="关键词 Top-K">{viewingConfigJson.retrieval?.keyword_top_k}</Descriptions.Item>
                <Descriptions.Item label="RRF K">{viewingConfigJson.retrieval?.rrf_k}</Descriptions.Item>
                <Descriptions.Item label="单篇最大 Chunk">{viewingConfigJson.retrieval?.max_chunks_per_article}</Descriptions.Item>
                <Descriptions.Item label="最小 RRF 分数">{viewingConfigJson.retrieval?.min_rrf_score}</Descriptions.Item>
              </Descriptions>
            </Card>

            <Card size="small" title="重排序参数" style={{ marginTop: 12 }}>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="启用重排序">{viewingConfigJson.rerank?.enable_rerank ? '是' : '否'}</Descriptions.Item>
                <Descriptions.Item label="重排序器">{viewingConfigJson.rerank?.reranker_type}</Descriptions.Item>
                <Descriptions.Item label="重排序 Top-K">{viewingConfigJson.rerank?.rerank_top_k}</Descriptions.Item>
                <Descriptions.Item label="最小重排序分数">{viewingConfigJson.rerank?.rerank_min_score}</Descriptions.Item>
              </Descriptions>
            </Card>

            <Card size="small" title="生成参数" style={{ marginTop: 12 }}>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="最大上下文字符数">{viewingConfigJson.generation?.max_context_chars}</Descriptions.Item>
              </Descriptions>
            </Card>

            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between' }}>
              <Space>
                <Button icon={<CopyOutlined />} onClick={clone_config}>克隆并编辑</Button>
                {!viewingConfig.is_active && (
                  <Popconfirm title="将此配置设为当前生效？" onConfirm={() => activate_config(viewingConfig!.id)}>
                    <Button icon={<CheckCircleOutlined />}>设为生效</Button>
                  </Popconfirm>
                )}
              </Space>
              {!viewingConfig.is_active && (
                <Popconfirm title="确定删除此配置？" onConfirm={() => delete_config(viewingConfig!.id)}>
                  <Button danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              )}
            </div>
          </>
        )}

        {!compareResult && editingConfig && (
          <>
            <Text strong>{viewingConfig ? `克隆 v${viewingConfig.version}` : '新建配置'}</Text>
            <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
              <Form.Item name="description" label="配置说明">
                <Input placeholder="如：关闭 reranker 的配置" />
              </Form.Item>

              <Divider orientation="left" plain>检索参数</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="retrieval_vector_top_k" label="向量 Top-K">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="retrieval_keyword_top_k" label="关键词 Top-K">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="retrieval_rrf_k" label="RRF K">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="retrieval_max_chunks_per_article" label="单篇最大 Chunk">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="retrieval_min_rrf_score" label="最小 RRF 分数">
                    <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" plain>重排序参数</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="rerank_enable_rerank" label="启用重排序" valuePropName="checked">
                    <Switch checkedChildren="开" unCheckedChildren="关" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="rerank_reranker_type" label="重排序器">
                    <Select options={[
                      { value: 'gguf', label: 'GGUF' },
                      { value: 'llm', label: 'LLM' },
                      { value: 'none', label: 'None' },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="rerank_rerank_top_k" label="重排序 Top-K">
                    <InputNumber min={1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="rerank_rerank_min_score" label="最小重排序分数">
                    <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" plain>生成参数</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="generation_max_context_chars" label="最大上下文字符数">
                    <InputNumber min={500} max={50000} step={1000} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item style={{ marginBottom: 0, marginTop: 8 }}>
                <Space>
                  <Button type="primary" onClick={save_config}>保存</Button>
                  <Button onClick={() => { setEditingConfig(false); setViewingConfig(null); }}>取消</Button>
                </Space>
              </Form.Item>
            </Form>
          </>
        )}

        {!compareResult && !editingConfig && !viewingConfig && (
          <div style={{ textAlign: 'center', paddingTop: 80 }}>
            <Text type="secondary">选择左侧的配置查看详情，或新建配置</Text>
          </div>
        )}
      </Col>
    </Row>
  ),
},
```

- [ ] **Step 4: Simplify eval history Tab — replace Drawer button with Select**

In the `runs` Tab children, replace the config button area (around line 688-702):

Replace:
```tsx
<Button
  icon={<SettingOutlined />}
  onClick={open_config_drawer}
  type={selectedConfigId ? 'default' : 'dashed'}
>
  {selectedConfigId
    ? (() => {
        const cfg = evalConfigs.find((c) => c.id === selectedConfigId);
        return cfg ? `${cfg.name} (v${cfg.version})` : '选择配置';
      })()
    : '选择配置'}
</Button>
```

With:
```tsx
<Select
  style={{ width: 200 }}
  placeholder="选择评测配置"
  value={selectedConfigId}
  onChange={setSelectedConfigId}
  options={evalConfigs.map((c) => ({
    value: c.id,
    label: (
      <span>
        v{c.version}{c.description ? ` ${c.description}` : ''}
        {c.is_active ? ' (生效中)' : ''}
      </span>
    ),
  }))}
/>
```

Also update the `useEffect` that loads configs for the runs tab to also load for the configs tab:

```typescript
useEffect(() => {
  if (activeTab === 'runs' || activeTab === 'configs') {
    if (evalConfigs.length === 0) {
      evalApi.fetchEvalConfigs().then(setEvalConfigs).catch(() => {});
    }
  }
}, [activeTab]);
```

And auto-select active config on first load:

```typescript
useEffect(() => {
  if (evalConfigs.length > 0 && selectedConfigId === null) {
    const active = evalConfigs.find((c) => c.is_active);
    if (active) setSelectedConfigId(active.id);
  }
}, [evalConfigs, selectedConfigId]);
```

- [ ] **Step 5: Remove unused imports**

Remove: `Drawer`, `Collapse` from antd imports.
Remove: `SettingOutlined` from icon imports (if no longer used).

- [ ] **Step 6: Verify the app builds**

Run: `cd scripts/web && npx tsc --noEmit && npm run build`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add scripts/web/src/pages/EvalPage.tsx
git commit -m "refactor: promote config management to independent Tab with compare support"
```

---

### Task 5: Add config column to evaluation history table

**Files:**
- Modify: `scripts/web/src/pages/EvalPage.tsx` (evaluationColumns)

- [ ] **Step 1: Add config version column to evaluation table**

In `evaluationColumns` (around line 550-572), add a config column after the mode column:

```typescript
{
  title: '配置', dataIndex: 'config', key: 'config', width: 100,
  render: (_: unknown, e: Evaluation) => {
    const cv = e.config?.dataset?.config_version;
    return cv ? <Tag>v{cv}</Tag> : <Text type="secondary">-</Text>;
  },
},
```

- [ ] **Step 2: Verify build**

Run: `cd scripts/web && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add scripts/web/src/pages/EvalPage.tsx
git commit -m "feat: add config version column to evaluation history table"
```

---

### Task 6: Run full test suite and verify

- [ ] **Step 1: Run backend tests**

Run: `cd scripts && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run frontend build**

Run: `cd scripts/web && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Manual smoke test**

1. Start the dev server
2. Navigate to EvalPage → 配置管理 Tab
3. Verify: default config exists with "生效中" tag
4. Create a new config, verify it appears with v2
5. Activate v2, verify v1 loses "生效中" tag
6. Select two configs, enter compare mode, verify diff table
7. Go to 评测历史 Tab, verify Select shows configs with "生效中" label
8. Run an evaluation, verify config column shows version
