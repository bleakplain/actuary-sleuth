# database.py 模块拆分与事务安全 - 技术调研报告

生成时间: 2026-04-28
源规格: .claude/specs/026-db-split-transaction/spec.md

## 执行摘要

`scripts/api/database.py` 包含 1605 行代码、65+ 个函数，是整个 API 层的数据访问核心。经过深入分析发现：（1）函数按 12 个功能域清晰分布，拆分可行性高；（2）5 个函数存在事务安全隐患，其中 `create_snapshot` 和 `restore_snapshot` 风险最高；（3）`_migrate_db()` 中 3 个表重建步骤因 SQLite DDL 隐式提交而无法回滚；（4）现有测试覆盖了 session/feedback/trace/eval_config 等领域，但事务回滚和迁移原子性完全无测试覆盖。建议采用分阶段拆分策略，拆分与事务修复同步进行。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 按功能域拆分 | `scripts/api/database.py` | 单文件 1605 行，需拆分 |
| FR-002 向后兼容 | `scripts/api/routers/*.py`, `scripts/lib/rag_engine/graph.py` 等 | 7 个文件直接导入 |
| FR-003 create_snapshot 事务修复 | `database.py` L693-715 | FS+DB 不一致，高风险 |
| FR-004 restore_snapshot 事务修复 | `database.py` L727-735 | DELETE+INSERT 无显式事务，高风险 |
| FR-005 remove_snapshot 事务修复 | `database.py` L827-840 | DB 先删后删文件，中风险 |
| FR-006 activate_eval_config 事务修复 | `database.py` L843-851 | 两步 UPDATE 无显式事务，中风险 |
| FR-007 _migrate_db 事务修复 | `database.py` L238-378 | DDL 隐式提交，高风险 |

### 1.2 可复用组件

- `get_connection()`: `lib.common.database.get_connection` — 连接池 context manager，自动 commit/rollback，所有模块共用
- `_deserialize_json_fields()`: JSON 字段反序列化工具，多模块共用
- `_SAMPLE_INSERT_SQL` / `_sample_insert_values()`: 评估样本插入模板，eval_samples 和 eval_snapshots 模块共用
- `_has_eval_run_refs()`: 评测运行引用检查，eval_configs 和 eval_snapshots 模块共用

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `scripts/api/db/__init__.py` | 新增 | 重新导出所有函数，保持向后兼容 |
| `scripts/api/db/schema.py` | 新增 | DDL + 迁移逻辑（含事务修复） |
| `scripts/api/db/session.py` | 新增 | 会话/消息管理（9 个函数） |
| `scripts/api/db/eval_samples.py` | 新增 | 评估样本 CRUD（10 个函数） |
| `scripts/api/db/eval_snapshots.py` | 新增 | 快照管理（7 个函数，含事务修复） |
| `scripts/api/db/eval_configs.py` | 新增 | 评测配置（7 个函数，含事务修复） |
| `scripts/api/db/eval_runs.py` | 新增 | 评测运行（12 个函数） |
| `scripts/api/db/feedback.py` | 新增 | 反馈管理（6 个函数） |
| `scripts/api/db/traces.py` | 新增 | 追踪持久化（8 个函数） |
| `scripts/api/db/human_reviews.py` | 新增 | 人工审核（3 个函数） |
| `scripts/api/db/compliance.py` | 新增 | 合规报告（3 个函数） |
| `scripts/api/db/documents.py` | 新增 | 文档解析（4 个函数） |
| `scripts/api/db/common.py` | 新增 | 共享工具（JSON 序列化等） |
| `scripts/api/database.py` | 修改 | 改为兼容层，从 `api.db` 重新导出 |
| `scripts/api/routers/*.py` | 修改 | 更新导入路径 |

---

## 二、技术选型研究

### 2.1 拆分策略对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 包拆分 + `__init__.py` 重导出 | 向后兼容好，零业务代码修改 | 增加一层间接 | 渐进式重构 | ✅ |
| 直接拆分 + 全局更新导入 | 无间接层，更干净 | 需修改所有消费方导入 | 一次性重构 | ❌ |
| 保留 database.py + 分模块内聚 | 不破坏任何现有导入 | 文件仍存在，只是薄代理 | 最小改动 | ❌ |

**选择理由**：包拆分 + 重导出既保持向后兼容，又让各模块物理独立，是最安全的渐进式方案。

### 2.2 事务修复策略对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 显式 `BEGIN IMMEDIATE` 事务 | SQLite 原生支持，写锁保护 | 需手动管理 COMMIT/ROLLBACK | DB 内多步操作 | ✅ |
| 临时文件 + 原子 rename | FS 原子性保证 | 仅同文件系统有效 | FS+DB 场景 | ✅ (create_snapshot) |
| 软删除 + 后台清理 | 可恢复，安全 | 增加清理逻辑 | 删除操作 | ❌ (过度设计) |
| 乐观锁 + 重试 | 无锁等待 | SQLite 不适合高并发 | 高并发场景 | ❌ |

### 2.3 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| `lib.common.database.get_connection` | 现有 | 连接池管理 | 无变更 |
| `lib.config.get_eval_snapshots_dir` | 现有 | 快照目录配置 | 延迟导入，无变更 |
| `lib.rag_engine.config.RAGConfig` | 现有 | 默认评测配置 | 延迟导入，无变更 |

无新增外部依赖。

---

## 三、数据流分析

### 3.1 现有数据流

```
app.py lifespan
  └─ init_db() ── get_connection() ── executescript(_SCHEMA_SQL) ── _migrate_db()

routers/ask.py
  └─ create_session() ── get_connection() ── INSERT sessions
  └─ add_message() ── get_connection() ── INSERT messages
  └─ save_trace() + save_spans() ── get_connection() ── INSERT traces/spans

routers/eval.py
  └─ create_snapshot() ── get_eval_samples() ── FS write ── get_connection() ── INSERT eval_snapshots
  └─ restore_snapshot() ── get_snapshot_samples() ── get_connection() ── DELETE + INSERT eval_samples
  └─ remove_snapshot() ── get_connection() ── DELETE eval_snapshots ── FS delete
  └─ activate_eval_config() ── get_connection() ── UPDATE × 2 eval_configs
```

### 3.2 新增/变更的数据流

拆分后数据流不变，仅物理模块不同：

```
routers/ask.py
  └─ from api.db import create_session  # 代替 from api.database

routers/eval.py
  └─ from api.db.eval_samples import get_eval_samples     # 可选：更精确导入
  └─ from api.db.eval_snapshots import create_snapshot     # 可选
  └─ from api.db import create_snapshot                   # 也可：兼容层
```

事务修复后的数据流变化：

```
create_snapshot (修复后):
  └─ get_eval_samples() ── FS write (临时目录) ── BEGIN IMMEDIATE ── INSERT ── COMMIT ── os.rename()

restore_snapshot (修复后):
  └─ get_snapshot_samples() ── BEGIN IMMEDIATE ── DELETE + INSERT ── COMMIT

activate_eval_config (修复后):
  └─ BEGIN IMMEDIATE ── UPDATE × 2 ── COMMIT
```

### 3.3 关键数据结构

```python
# common.py - 共享常量（从 database.py 提取）
_MSG_JSON_FIELDS = {"citations": "citations_json", "sources": "sources_json", ...}
_SAMPLE_JSON_FIELDS = {"evidence_docs": "evidence_docs_json", ...}
_RESULT_JSON_FIELDS = {"retrieved_docs": "retrieved_docs_json", ...}
_SAMPLE_INSERT_SQL = "INSERT OR IGNORE INTO eval_samples ..."
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [x] **SQLite WAL 模式下 DDL 可回滚** — 验证结果：**部分可回滚**。ALTER TABLE ADD COLUMN 可回滚，但 CREATE TABLE / DROP TABLE / RENAME TABLE 是**隐式提交**，无法回滚。→ `_migrate_db()` 中的表重建步骤（L279-298, L329-342, L354-371）本质上非原子。
- [x] **`get_connection()` 上下文管理器异常时自动 rollback** — 验证结果：**正确**。`connection_pool.py` L108 行 `conn.rollback()` 在异常路径执行。
- [x] **`executescript()` 隐式提交** — 验证结果：**正确**。`init_db()` 中 `conn.executescript(_SCHEMA_SQL)` 会隐式提交每条 DDL，但 `_SCHEMA_SQL` 全部是 `CREATE IF NOT EXISTS`，幂等安全。
- [ ] **`os.rename()` 在 macOS 同一文件系统上原子** — 需运行时验证。Linux 上保证原子，macOS 上 HFS+/APFS 通常也是。
- [ ] **并发 `create_snapshot()` 版本号冲突** — 需验证 `BEGIN IMMEDIATE` 是否足以防止。

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 拆分后 `from api.database import xxx` 失败 | 低 | 高 | `database.py` 改为兼容层，从 `api.db` 重导出 |
| `_migrate_db()` 表重建中途失败，DDL 无法回滚 | 低 | 高 | 分步迁移：先 CREATE 新表，验证数据迁移成功后再 DROP 旧表 |
| `create_snapshot()` 并发版本号冲突 | 低 | 中 | 使用 `BEGIN IMMEDIATE` 获取写锁 |
| `remove_snapshot()` 文件删除失败产生孤儿文件 | 中 | 低 | 记录日志，提供手动清理命令 |
| `feedback` 表外键无 CASCADE，删 session 留孤立记录 | 中 | 中 | 拆分时添加 `ON DELETE CASCADE`（需迁移） |
| 循环依赖：`lib/` 层延迟导入 `api.database` | 存在 | 低 | 拆分不影响，保持延迟导入模式 |

---

## 五、依赖关系详图

### 5.1 消费方按功能域分组

**Session 域** → `routers/ask.py`, `lib/rag_engine/graph.py`, `lib/common/middleware.py`

**Message 域** → `routers/ask.py`, `lib/rag_engine/graph.py`

**Eval Samples 域** → `routers/eval.py`, `routers/feedback.py`, `lib/rag_engine/eval_dataset.py`

**Eval Snapshots 域** → `routers/eval.py`

**Eval Configs 域** → `routers/eval.py`, `app.py`, `tests/api/test_eval_config.py`

**Eval Runs 域** → `routers/eval.py`

**Feedback 域** → `routers/ask.py`, `routers/feedback.py`

**Trace 域** → `routers/ask.py`, `routers/observability.py`

**Compliance 域** → `routers/compliance.py`

**Documents 域** → `routers/compliance.py`

### 5.2 需要修改导入的文件

| 文件 | 当前导入 | 修改后 |
|------|---------|--------|
| `api/app.py` | `from api.database import init_db, _ensure_default_config` | `from api.db import init_db, _ensure_default_config` |
| `api/routers/ask.py` | `from api.database import ...` (15 个) | `from api.db import ...` |
| `api/routers/eval.py` | `from api.database import ...` (31 个) | `from api.db import ...` |
| `api/routers/feedback.py` | `from api.database import ...` (7 个) | `from api.db import ...` |
| `api/routers/observability.py` | `from api.database import ...` (5 个) | `from api.db import ...` |
| `api/routers/compliance.py` | `from api.database import ...` (5 个) | `from api.db import ...` |
| `lib/rag_engine/graph.py` | `from api.database import get_messages, save_session_context` | `from api.db import ...` |
| `lib/common/middleware.py` | `from api.database import get_session_context` | `from api.db import ...` |
| `lib/rag_engine/eval_dataset.py` | `from api.database import get_eval_samples` | `from api.db import ...` |
| `tests/api/test_eval_config.py` | `from api.database import ...` (7 个) | `from api.db import ...` |
| `tests/api/test_product_doc.py` | `from api.database import ...` (4 个) | `from api.db import ...` |
| `tests/api/test_observability_db.py` | `from api.database import ...` | `from api.db import ...` |
| `tests/api/test_feedback.py` | 通过 API 测试，无直接导入 | 无需修改 |

---

## 六、事务问题详细分析

### 6.1 create_snapshot() — 高风险

**问题**：FS 写入（L701-702）先于 DB 写入（L704-711），两个操作不在同一事务中。并发时版本号竞争。

**修复方案**：临时文件 + 显式事务 + 原子 rename

```python
def create_snapshot(name: str, description: str = "") -> str:
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    samples = get_eval_samples()
    hash_code = _compute_hash_code(samples)

    temp_dir = os.path.join(_get_snapshots_base_dir(), f".tmp_{snapshot_id}")
    temp_file = os.path.join(temp_dir, "samples.json")
    final_dir = os.path.join(_get_snapshots_base_dir(), snapshot_id)
    final_file = os.path.join(final_dir, "samples.json")

    try:
        # 阶段1: 写入临时位置
        os.makedirs(temp_dir, exist_ok=True)
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(samples, f, ensure_ascii=False)

        # 阶段2: DB 记录（显式事务，防止版本号竞争）
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM eval_snapshots").fetchone()
                next_version = row[0] + 1
                conn.execute(
                    "INSERT INTO eval_snapshots (...) VALUES (...)",
                    (snapshot_id, name, description, len(samples), final_file, next_version, hash_code),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        # 阶段3: 原子 rename（DB 已提交，rename 失败可手动修复）
        os.rename(temp_dir, final_dir)

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return snapshot_id
```

### 6.2 restore_snapshot() — 高风险

**问题**：`DELETE FROM eval_samples`（L732）后逐条 INSERT（L733-734），中途失败依赖自动 rollback，但无显式事务锁保护。

**修复方案**：显式事务

```python
def restore_snapshot(snapshot_id: str) -> int:
    samples = get_snapshot_samples(snapshot_id)
    if samples is None:
        return 0
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM eval_samples")
            for s in samples:
                conn.execute(_SAMPLE_INSERT_SQL, _sample_insert_values(s))
            conn.execute("COMMIT")
            return len(samples)
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

### 6.3 remove_snapshot() — 中风险

**问题**：DB 删除先 commit（L828-835 上下文退出），FS 删除后执行（L836-839），`ignore_errors=True` 静默失败。

**修复方案**：DB 先删 + FS 删除失败记录日志（保持现有顺序，因为文件删不掉比 DB 记录删不掉更容易手动修复）

```python
def remove_snapshot(snapshot_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _has_eval_run_refs(conn, "dataset_version", f"snapshot:{snapshot_id}"):
                conn.execute("ROLLBACK")
                return False
            row = conn.execute(
                "SELECT file_path FROM eval_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return False
            file_path = row["file_path"]
            conn.execute("DELETE FROM eval_snapshots WHERE id = ?", (snapshot_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    if file_path:
        snap_dir = os.path.dirname(file_path)
        if os.path.isdir(snap_dir):
            try:
                shutil.rmtree(snap_dir)
            except Exception as e:
                logger.warning(f"快照文件清理失败: {snap_dir}, error={e}")
    return True
```

### 6.4 activate_eval_config() — 中风险

**问题**：两步 UPDATE 间无显式事务锁。

**修复方案**：显式事务

```python
def activate_eval_config(config_id: int) -> bool:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT id FROM eval_configs WHERE id = ?", (config_id,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            conn.execute("UPDATE eval_configs SET is_active = 0 WHERE is_active = 1")
            conn.execute("UPDATE eval_configs SET is_active = 1 WHERE id = ?", (config_id,))
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

### 6.5 _migrate_db() — 高风险（DDL 隐式提交）

**问题**：3 个表重建步骤（eval_configs L279-298, eval_snapshots L329-342, user_profiles L354-371）使用 CREATE new → INSERT → DROP old → RENAME 模式，DDL 隐式提交使 rollback 无效。

**修复方案**：分步迁移 + 验证

```python
def _migrate_db():
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # ALTER TABLE ADD COLUMN 操作（可回滚）
            _migrate_columns(conn)
            # CREATE TABLE IF NOT EXISTS（幂等，安全）
            _migrate_new_tables(conn)
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"Migration failed: {e}")
            raise

    # 表重建操作（DDL 隐式提交，单独执行）
    _migrate_eval_configs_table()
    _migrate_eval_snapshots_table()
    _migrate_user_profiles_table()
```

表重建函数使用验证模式：

```python
def _migrate_eval_configs_table():
    with get_connection() as conn:
        config_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_configs)").fetchall()}
        if 'name' not in config_cols:
            return  # 无需迁移

        conn.execute("CREATE TABLE IF NOT EXISTS eval_configs_new (...)")
        conn.execute("INSERT INTO eval_configs_new ... SELECT ... FROM eval_configs")

        # 验证数据迁移成功
        old_count = conn.execute("SELECT COUNT(*) FROM eval_configs").fetchone()[0]
        new_count = conn.execute("SELECT COUNT(*) FROM eval_configs_new").fetchone()[0]
        if old_count != new_count:
            conn.execute("DROP TABLE IF EXISTS eval_configs_new")
            raise RuntimeError(f"eval_configs 迁移数据不匹配: {old_count} != {new_count}")

        conn.execute("DROP TABLE eval_configs")
        conn.execute("ALTER TABLE eval_configs_new RENAME TO eval_configs")
```

---

## 七、测试覆盖分析

### 7.1 现有测试文件清单

| 文件 | 测试数 | 覆盖域 |
|------|--------|--------|
| `tests/api/test_observability_db.py` | 15 | session search, batch delete, trace CRUD |
| `tests/api/test_feedback.py` | 18 | feedback 全流程 |
| `tests/api/test_eval_config.py` | 10 | eval config 版本管理 |
| `tests/api/test_observability_api.py` | 10 | trace API 端点 |
| `tests/api/test_product_doc.py` | 2 | parsed_document CRUD |

### 7.2 测试覆盖缺口

| 领域 | 缺失测试 |
|------|---------|
| 事务回滚 | `create_snapshot` DB 失败时 FS 清理 |
| 事务回滚 | `restore_snapshot` INSERT 中途失败时原数据保留 |
| 事务回滚 | `activate_eval_config` 并发激活竞争 |
| 迁移原子性 | `_migrate_db` 中途失败时 schema 回滚 |
| 连接池 | timeout/overflow 场景 |
| message CRUD | 无独立测试文件 |

### 7.3 建议新增的测试

```python
# tests/api/test_transaction_safety.py

class TestSnapshotTransactionSafety:
    def test_create_snapshot_db_failure_cleans_temp_file(self, monkeypatch):
        """create_snapshot DB 写入失败时，临时文件被清理"""

    def test_restore_snapshot_failure_preserves_original(self, monkeypatch):
        """restore_snapshot 中途失败时，原有样本数据保留"""

    def test_remove_snapshot_fs_failure_logs_warning(self, monkeypatch):
        """remove_snapshot 文件删除失败时记录日志"""

class TestEvalConfigTransactionSafety:
    def test_activate_eval_config_atomic(self, monkeypatch):
        """activate_eval_config 两步 UPDATE 原子性"""

    def test_activate_eval_config_concurrent(self):
        """并发 activate_eval_config 不会产生双活跃配置"""
```

---

## 八、Schema 与 ER 关系

```
sessions (1) ──CASCADE──> (N) messages
  |                            |
  +──────── (无 CASCADE) ──> (N) feedback
  +──────── (无 CASCADE) ──> (N) feedback (via session_id)

eval_runs (1) ──CASCADE──> (N) eval_sample_results
eval_runs (1) ──CASCADE──> (N) human_reviews

eval_samples     (独立表)
eval_snapshots   (独立表)
eval_configs     (独立表)
compliance_reports (独立表)
parsed_documents  (独立表)

traces ──(逻辑关联, trace_id)──> spans
traces ──(逻辑关联, message_id)──> messages
```

**注意**：`feedback` 表的两个外键无 `ON DELETE CASCADE`，删除 session/message 会留下孤立记录。

---

## 九、总结

### 9.1 主要发现

1. database.py 函数按 12 个功能域清晰分布，拆分边界明确
2. 仅 1 个函数（`add_evaluation_error`）使用显式事务，其余 50+ 个依赖自动 commit
3. 5 个函数存在事务安全隐患，2 个高风险（快照操作）
4. `_migrate_db()` 中 3 个表重建步骤因 DDL 隐式提交无法回滚
5. 现有测试无事务回滚和迁移原子性覆盖

### 9.2 关键风险

1. **DDL 隐式提交**是 `_migrate_db()` 的最大风险，需分步迁移 + 验证
2. **FS+DB 不一致**是快照操作的核心问题，需临时文件 + 原子 rename
3. **循环依赖**（`lib/` 延迟导入 `api.database`）在拆分后需保持

### 9.3 下一步行动

1. 执行 `/gen-plan` 生成技术实现方案
2. 预计改动：新增 13 个模块文件，修改 12+ 个导入文件，新增 1 个测试文件
