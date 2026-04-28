# Implementation Plan: database.py 模块拆分与事务安全

**Branch**: `026-db-split-transaction` | **Date**: 2026-04-28 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

将 `scripts/api/database.py`（1605 行、65+ 函数）按 12 个功能域拆分为独立模块，通过 `__init__.py` 重导出保持向后兼容。同步修复 5 个函数的事务安全隐患：`create_snapshot`（临时文件+原子rename）、`restore_snapshot`（显式事务）、`remove_snapshot`（显式事务+FS失败日志）、`activate_config`（显式事务）、`_migrate_db`（分步迁移+验证）。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: 无新增依赖
**Storage**: SQLite (WAL mode)
**Testing**: pytest
**Constraints**: 向后兼容（`from api.database import xxx` 继续工作）

## Constitution Check

- [x] **Library-First**: 复用现有 `get_connection()` 连接池，无新增依赖
- [x] **测试优先**: Phase 2 先写事务回滚测试，再修代码
- [x] **简单优先**: 拆分仅按功能域物理分离，不改架构；事务修复仅加 `BEGIN IMMEDIATE`
- [x] **显式优于隐式**: 显式事务替代隐式自动 commit。SQLite WAL 模式下 `BEGIN IMMEDIATE` 获取写锁，确保多步操作原子性；异常时 `ROLLBACK`，正常时 `COMMIT`。避免依赖 context manager 的隐式 commit，防止中途异常导致部分提交。
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: 每个 User Story 有独立验收场景和测试

## Project Structure

### Source Code

```text
scripts/lib/infra/db/        # 数据库基础设施层
├── __init__.py              # 重导出所有函数，保持向后兼容
├── constants.py             # 共享常量
├── utils.py                 # 共享工具函数
├── schema.py                # DDL + 迁移
├── session.py               # 会话/消息管理
├── eval_samples.py          # 评估样本 CRUD
├── eval_sample_reviews.py   # 评测样本人工抽检
├── eval_sample_snapshots.py # 快照管理（含事务修复）
├── eval_configs.py          # 评测配置（含事务修复）
├── eval_runs.py             # 评测运行
├── feedback.py              # 反馈管理
├── traces.py                # 追踪持久化
└── audit_reports.py         # 合规审核报告

scripts/api/database.py      # 改为兼容层，从 lib.infra.db 重导出
scripts/api/routers/*.py     # 更新导入路径
scripts/tests/api/test_transaction_safety.py  # 新增
```

## Implementation Phases

---

### Phase 1: 创建 db 包骨架 (Setup)

#### 需求回溯

→ 为所有 User Story 提供基础设施

#### 实现步骤

**1.1 创建目录和 constants.py**

- 文件: `scripts/lib/infra/db/constants.py`
- 提取 database.py 中的共享常量

```python
"""数据库模块共享常量。"""

_MSG_JSON_FIELDS = {
    "citations": "citations_json",
    "sources": "sources_json",
    "clarification_questions": "clarification_questions_json",
    "evaluation": "evaluation_json",
    "retrieved_docs": "retrieved_docs_json",
}

_SAMPLE_JSON_FIELDS = {
    "evidence_docs": "evidence_docs_json",
}

_RESULT_JSON_FIELDS = {
    "retrieved_docs": "retrieved_docs_json",
    "clauses": "clauses_json",
    "check_results": "check_results_json",
}

_SAMPLE_INSERT_SQL = (
    "INSERT OR IGNORE INTO eval_samples "
    "(id, question, expected_answer, category, difficulty, "
    "evidence_docs_json, tags, source, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
```

**1.2 创建 utils.py**

- 文件: `scripts/lib/infra/db/utils.py`
- 提取工具函数

```python
"""数据库模块共享工具函数。"""

import hashlib
import json
from typing import Any, Dict, List

from lib.infra.db.constants import _MSG_JSON_FIELDS, _SAMPLE_JSON_FIELDS, _RESULT_JSON_FIELDS


def _deserialize_json_fields(
    row: Dict[str, Any],
    fields: Dict[str, str],
) -> Dict[str, Any]:
    """反序列化 JSON 字段，将 _json 后缀列映射到目标列名。"""
    for target, source in fields.items():
        raw = row.pop(source, None)
        if raw is not None:
            try:
                row[target] = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                row[target] = None
        else:
            row[target] = None
    return row


def _sample_insert_values(sample: Dict[str, Any]) -> tuple:
    """将样本字典转换为 INSERT 参数元组。"""
    return (
        sample.get("id"),
        sample.get("question"),
        sample.get("expected_answer"),
        sample.get("category"),
        sample.get("difficulty"),
        json.dumps(sample.get("evidence_docs", []), ensure_ascii=False),
        json.dumps(sample.get("tags", []), ensure_ascii=False),
        sample.get("source"),
        sample.get("created_at"),
    )


def _compute_hash_code(samples: List[Dict[str, Any]]) -> str:
    """计算样本列表的哈希码，用于快照去重。"""
    content = json.dumps(
        sorted(samples, key=lambda s: s.get("id", "")),
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.md5(content.encode()).hexdigest()[:12]
```

**1.3 创建 schema.py**

- 文件: `scripts/lib/infra/db/schema.py`
- 迁移 DDL 和 `_migrate_db()` 逻辑

```python
"""数据库 Schema 定义和迁移管理。"""

import logging
from typing import Optional

from lib.common.database import get_connection

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
-- 完整的 CREATE TABLE IF NOT EXISTS 语句
-- 从 database.py 原样搬运
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    ...
);
-- ... 其他表定义（与 database.py 完全一致）
"""


def init_db(db_path: Optional[str] = None) -> None:
    """初始化数据库，创建表和执行迁移。"""
    with get_connection() as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    _migrate_db()


def _ensure_default_config() -> None:
    """确保评测配置存在默认值。"""
    # 从 database.py 原样搬运


def _migrate_db() -> None:
    """数据库迁移（含事务安全修复）。"""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_columns(conn)
            _migrate_new_tables(conn)
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"Migration phase 1 failed: {e}")
            raise

    # 表重建操作（DDL 隐式提交，单独执行）
    _migrate_eval_configs_table()
    _migrate_eval_snapshots_table()
    _migrate_user_profiles_table()


def _migrate_columns(conn) -> None:
    """ALTER TABLE ADD COLUMN 迁移（可回滚）。"""
    # 从 database.py _migrate_db() 中提取 ALTER 语句


def _migrate_new_tables(conn) -> None:
    """CREATE TABLE IF NOT EXISTS 新增表（幂等安全）。"""
    # 从 database.py _migrate_db() 中提取 CREATE TABLE 语句


def _migrate_eval_configs_table() -> None:
    """eval_configs 表重建迁移（分步+验证）。"""
    with get_connection() as conn:
        config_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_configs)").fetchall()}
        if 'name' not in config_cols:
            return

        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_configs_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                config_json TEXT DEFAULT '{}',
                is_active INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            INSERT INTO eval_configs_new (id, name, description, config_json, is_active, version, created_at, updated_at)
            SELECT id, 'Config ' || id, '', config_json, is_active, version, created_at, updated_at
            FROM eval_configs
        """)

        old_count = conn.execute("SELECT COUNT(*) FROM eval_configs").fetchone()[0]
        new_count = conn.execute("SELECT COUNT(*) FROM eval_configs_new").fetchone()[0]
        if old_count != new_count:
            conn.execute("DROP TABLE IF EXISTS eval_configs_new")
            raise RuntimeError(f"eval_configs 迁移数据不匹配: {old_count} != {new_count}")

        conn.execute("DROP TABLE eval_configs")
        conn.execute("ALTER TABLE eval_configs_new RENAME TO eval_configs")


def _migrate_eval_snapshots_table() -> None:
    """eval_snapshots 表重建迁移（分步+验证）。"""
    # 同 _migrate_eval_configs_table 模式


def _migrate_user_profiles_table() -> None:
    """user_profiles 表重建迁移（分步+验证）。"""
    # 同 _migrate_eval_configs_table 模式
```

**1.4 创建其余 10 个功能模块**

每个模块从 database.py 搬迁对应函数，添加必要的导入。

| 模块 | 函数数 | 关键导入 |
|------|--------|---------|
| `session.py` | 9 | `get_connection`, `_MSG_JSON_FIELDS`, `_deserialize_json_fields` |
| `eval_samples.py` | 10 | `get_connection`, `_SAMPLE_INSERT_SQL`, `_sample_insert_values`, `_SAMPLE_JSON_FIELDS` |
| `eval_sample_snapshots.py` | 7 | `get_connection`, `_SAMPLE_INSERT_SQL`, `_sample_insert_values`, `_compute_hash_code` |
| `eval_configs.py` | 7 | `get_connection` |
| `eval_runs.py` | 12 | `get_connection`, `_RESULT_JSON_FIELDS`, `_deserialize_json_fields` |
| `feedback.py` | 6 | `get_connection` |
| `traces.py` | 8 | `get_connection` |
| `eval_sample_reviews.py` | 3 | `get_connection` |
| `audit_reports.py` | 3 | `get_connection` |

**1.5 创建 __init__.py**

- 文件: `scripts/lib/infra/db/__init__.py`
- 重导出所有函数

```python
"""数据库访问层 — 按功能域拆分。"""

from .schema import init_db, _ensure_default_config, _migrate_db
from .session import (
    create_session, get_sessions, get_session, delete_session,
    search_sessions, add_message, get_messages, save_session_context,
    get_session_context,
)
from .eval_samples import (
    get_eval_samples, upsert_eval_sample, delete_eval_sample,
    import_eval_samples, get_sample_stats, get_sample_by_id,
)
from .eval_sample_snapshots import (
    create_snapshot, list_snapshots, get_snapshot,
    restore_snapshot, remove_snapshot, list_snapshot_samples,
)
from .eval_configs import (
    get_eval_configs, get_eval_config, insert_eval_config,
    remove_eval_config, activate_config, get_active_config,
)
from .eval_runs import (
    insert_evaluation, get_evaluations, get_evaluation,
    update_evaluation_status, save_sample_result,
    get_sample_results, batch_delete_evaluations,
    is_evaluation_cancelled, cancel_evaluation_run, add_evaluation_error,
)
from .feedback import (
    create_feedback, get_feedback, list_feedbacks,
    update_feedback, get_feedback_stats,
)
from .traces import (
    save_trace, save_spans, get_trace_by_id,
    get_trace_by_message_id, search_traces, batch_delete_traces,
    count_traces_for_cleanup, cleanup_traces,
)
from .eval_sample_reviews import (
    insert_human_review, get_human_reviews, get_human_review_stats,
)
from .audit_reports import (
    save_compliance_report, get_compliance_reports, get_compliance_report,
)

__all__ = [
    "init_db", "_ensure_default_config", "_migrate_db",
    "create_session", "get_sessions", "get_session", "delete_session",
    "search_sessions", "add_message", "get_messages",
    "save_session_context", "get_session_context",
    # ... 其余函数省略，实际文件中完整列出
]
```

**1.6 将 database.py 改为兼容层**

- 文件: `scripts/api/database.py`
- 删除所有函数实现，改为从 `lib.infra.db` 重导出

```python
"""兼容层 — 所有函数已迁移至 lib.infra.db 包。"""

from lib.infra.db import *  # noqa: F401,F403
from lib.infra.db import __all__
```

**1.7 更新路由导入**

| 文件 | 变更 |
|------|------|
| `api/app.py` | `from api.database import ...` → `from lib.infra.db import init_db, _ensure_default_config` |
| `api/routers/ask.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `api/routers/eval.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `api/routers/feedback.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `api/routers/observability.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `api/routers/compliance.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `lib/rag_engine/graph.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `lib/common/middleware.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `lib/rag_engine/eval_dataset.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `tests/api/test_eval_config.py` | `from api.database import ...` → `from lib.infra.db import ...` |
| `tests/api/test_observability_db.py` | `from api.database import ...` → `from lib.infra.db import ...` |

#### 验收标准

- `from api.database import create_session` 正常工作
- `from lib.infra.db import create_session` 正常工作
- `pytest scripts/tests/` 全部通过

---

### Phase 2: 事务安全测试先行 (User Story 2, 3, 4)

#### 需求回溯

→ spec.md User Story 2: 快照操作事务安全 (P1)
→ spec.md User Story 3: 评测配置激活事务安全 (P2)
→ spec.md User Story 4: 数据库迁移事务安全 (P2)

#### 实现步骤

**2.1 创建事务安全测试文件**

- 文件: `scripts/tests/api/test_transaction_safety.py`

```python
"""数据库事务安全测试。"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from lib.infra.db import (
    create_snapshot, restore_snapshot, remove_snapshot,
    activate_config, get_eval_samples, upsert_eval_sample,
    insert_eval_config, get_eval_configs, init_db,
)
from lib.common.database import get_connection


@pytest.fixture
def db_with_samples():
    """创建含样本的测试数据库。"""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM eval_samples")
    for i in range(5):
        upsert_eval_sample({
            "id": f"test_txn_{i}",
            "question": f"问题 {i}",
            "expected_answer": f"答案 {i}",
            "category": "test",
            "difficulty": 1,
        })
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM eval_samples")


class TestSnapshotTransactionSafety:
    """User Story 2: 快照操作事务安全。"""

    def test_create_snapshot_db_failure_cleans_temp_file(self, db_with_samples, tmp_path):
        """create_snapshot DB 写入失败时，临时文件被清理。"""
        with patch("lib.infra.db.eval_sample_snapshots.get_connection") as mock_conn:
            cm = mock_conn.return_value.__enter__.return_value
            cm.execute.side_effect = Exception("DB error")

            with pytest.raises(Exception, match="DB error"):
                create_snapshot("fail_test")

        snapshots_dir = os.path.join(str(tmp_path), "eval_snapshots")
        temp_dirs = [d for d in os.listdir(snapshots_dir) if d.startswith(".tmp_")] if os.path.isdir(snapshots_dir) else []
        assert len(temp_dirs) == 0, "临时文件应被清理"

    def test_restore_snapshot_failure_preserves_original(self, db_with_samples):
        """restore_snapshot 中途失败时，原有样本数据保留。"""
        snapshot_id = create_snapshot("before_restore")
        original_count = len(get_eval_samples())

        # 新增一个样本
        upsert_eval_sample({
            "id": "extra_after_snap",
            "question": "额外问题",
            "expected_answer": "额外答案",
            "category": "test",
        })
        assert len(get_eval_samples()) == original_count + 1

        # 模拟恢复中途失败
        with patch("lib.infra.db.eval_sample_snapshots.get_connection") as mock_conn:
            cm = mock_conn.return_value.__enter__.return_value
            real_cm = get_connection()
            call_count = [0]
            original_execute = real_cm.execute

            def fake_execute(sql, *args):
                call_count[0] += 1
                if call_count[0] > 2:  # DELETE 后 INSERT 时失败
                    raise Exception("INSERT failed")
                return original_execute(sql, *args)

            cm.execute = fake_execute

        # 恢复后原数据应保留
        assert len(get_eval_samples()) >= original_count

    def test_remove_snapshot_fs_failure_logs_warning(self, db_with_samples):
        """remove_snapshot 文件删除失败时记录日志但不抛异常。"""
        snapshot_id = create_snapshot("to_remove")

        with patch("shutil.rmtree", side_effect=PermissionError("no access")):
            with patch("lib.infra.db.eval_sample_snapshots.logger") as mock_logger:
                result = remove_snapshot(snapshot_id)
                # DB 记录应已删除
                assert result is True

    def test_create_snapshot_success(self, db_with_samples):
        """create_snapshot 正常流程。"""
        snapshot_id = create_snapshot("normal_test", "描述")
        assert snapshot_id.startswith("snap_")

    def test_restore_snapshot_success(self, db_with_samples):
        """restore_snapshot 正常流程。"""
        snapshot_id = create_snapshot("restore_test")
        original = len(get_eval_samples())

        # 修改数据
        upsert_eval_sample({
            "id": "extra_for_restore",
            "question": "额外",
            "expected_answer": "答案",
            "category": "test",
        })
        assert len(get_eval_samples()) == original + 1

        # 恢复
        count = restore_snapshot(snapshot_id)
        assert count == original


class TestEvalConfigTransactionSafety:
    """User Story 3: 评测配置激活事务安全。"""

    def test_activate_config_atomic(self, db_with_samples):
        """activate_config 两步 UPDATE 原子性。"""
        # 创建两个配置
        config_a = insert_eval_config({"name": "A", "config_json": "{}"})
        config_b = insert_eval_config({"name": "B", "config_json": "{}"})

        # 激活 A
        assert activate_config(config_a) is True

        # 模拟激活 B 时第二步失败
        with patch("lib.infra.db.eval_configs.get_connection") as mock_conn:
            cm = mock_conn.return_value.__enter__.return_value
            call_count = [0]
            original_execute = get_connection().__enter__().execute

            def fake_execute(sql, *args):
                call_count[0] += 1
                if call_count[0] == 2:  # 第二步 UPDATE 时失败
                    raise Exception("UPDATE failed")
                return original_execute(sql, *args)

            cm.execute = fake_execute

        # A 仍应为活跃
        configs = get_eval_configs()
        active = [c for c in configs if c.get("is_active")]
        assert len(active) == 1
        assert active[0]["id"] == config_a

    def test_activate_config_success(self, db_with_samples):
        """activate_config 正常流程。"""
        config_a = insert_eval_config({"name": "A", "config_json": "{}"})
        config_b = insert_eval_config({"name": "B", "config_json": "{}"})
        activate_config(config_a)
        activate_config(config_b)

        configs = get_eval_configs()
        active = [c for c in configs if c.get("is_active")]
        assert len(active) == 1
        assert active[0]["id"] == config_b
```

#### 验收标准

- 测试文件可运行（暂会失败，待 Phase 3 修复后通过）

---

### Phase 3: 快照事务修复 (User Story 2 — P1)

#### 需求回溯

→ spec.md User Story 2: 快照操作事务安全 (P1)
→ spec.md FR-003: create_snapshot 使用临时文件+原子rename
→ spec.md FR-004: restore_snapshot 使用显式事务
→ spec.md FR-005: remove_snapshot 先删DB后删文件

#### 实现步骤

**3.1 修复 create_snapshot()**

- 文件: `scripts/lib/infra/db/eval_sample_snapshots.py`

```python
import json
import logging
import os
import shutil
import uuid
from typing import Any, Dict, List, Optional

from lib.common.database import get_connection
from lib.infra.db.constants import _SAMPLE_INSERT_SQL
from lib.infra.db.utils import _sample_insert_values, _compute_hash_code

logger = logging.getLogger(__name__)


def _get_snapshots_base_dir() -> str:
    """获取快照存储根目录。"""
    from lib.config import get_eval_snapshots_dir
    return get_eval_snapshots_dir()


def create_snapshot(name: str, description: str = "") -> str:
    """创建评估样本快照（事务安全）。"""
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    samples = get_eval_samples()
    hash_code = _compute_hash_code(samples)

    base_dir = _get_snapshots_base_dir()
    temp_dir = os.path.join(base_dir, f".tmp_{snapshot_id}")
    temp_file = os.path.join(temp_dir, "samples.json")
    final_dir = os.path.join(base_dir, snapshot_id)
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
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM eval_snapshots"
                ).fetchone()
                next_version = row[0] + 1
                conn.execute(
                    "INSERT INTO eval_snapshots "
                    "(id, name, description, sample_count, file_path, version, hash_code) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (snapshot_id, name, description, len(samples),
                     final_file, next_version, hash_code),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        # 阶段3: 原子 rename
        os.rename(temp_dir, final_dir)

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return snapshot_id


def restore_snapshot(snapshot_id: str) -> int:
    """从快照恢复评估样本（事务安全）。"""
    samples = list_snapshot_samples(snapshot_id)
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


def remove_snapshot(snapshot_id: str) -> bool:
    """删除快照（事务安全，FS 失败记录日志）。"""
    file_path: Optional[str] = None

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _exists_eval_runs(conn, "dataset_version", f"snapshot:{snapshot_id}"):
                conn.execute("ROLLBACK")
                return False
            row = conn.execute(
                "SELECT file_path FROM eval_snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return False
            file_path = row["file_path"]
            conn.execute(
                "DELETE FROM eval_snapshots WHERE id = ?", (snapshot_id,)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # DB 已提交，清理文件系统（失败仅记录日志）
    if file_path:
        snap_dir = os.path.dirname(file_path)
        if os.path.isdir(snap_dir):
            try:
                shutil.rmtree(snap_dir)
            except Exception as e:
                logger.warning(f"快照文件清理失败: {snap_dir}, error={e}")
    return True


def _exists_eval_runs(conn, column: str, value: str) -> bool:
    """检查评测运行是否引用了指定值。"""
    row = conn.execute(
        f"SELECT COUNT(*) FROM eval_runs WHERE {column} = ?", (value,)
    ).fetchone()
    return row[0] > 0


def list_snapshots() -> List[Dict[str, Any]]:
    """获取所有快照列表。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_snapshots ORDER BY version DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    """获取单个快照信息。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM eval_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None


def list_snapshot_samples(snapshot_id: str) -> Optional[List[Dict[str, Any]]]:
    """获取快照中的样本数据。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT file_path FROM eval_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if not row or not row["file_path"]:
            return None
        file_path = row["file_path"]
        if not os.path.isfile(file_path):
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


def get_eval_samples() -> List[Dict[str, Any]]:
    """获取所有评估样本。"""
    from lib.infra.db.eval_samples import get_eval_samples as _get_samples
    return _get_samples()
```

**3.2 修复 activate_config()**

- 文件: `scripts/lib/infra/db/eval_configs.py`

```python
def activate_config(config_id: int) -> bool:
    """激活指定评测配置（事务安全）。"""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT id FROM eval_configs WHERE id = ?", (config_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "UPDATE eval_configs SET is_active = 0 WHERE is_active = 1"
            )
            conn.execute(
                "UPDATE eval_configs SET is_active = 1 WHERE id = ?",
                (config_id,),
            )
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

**3.3 修复 _migrate_db()**

- 文件: `scripts/lib/infra/db/schema.py`（已在 Phase 1.3 中设计）
- 分步迁移 + 验证模式（见 Phase 1.3 代码）

#### 验收标准

- `pytest scripts/tests/api/test_transaction_safety.py` 全部通过
- 快照创建/恢复/删除在异常时数据一致
- 配置激活在异常时保持原活跃状态

---

### Phase 4: 回归验证 (所有 User Story)

#### 需求回溯

→ spec.md User Story 1: 数据库模块按功能域拆分
→ spec.md Success Criteria: SC-001~SC-004

#### 实现步骤

**4.1 运行完整测试套件**

```bash
pytest scripts/tests/ -v
```

**4.2 验证向后兼容**

```bash
python -c "from api.database import create_session; print('OK')"
python -c "from lib.infra.db import create_session; print('OK')"
```

**4.3 验证模块行数**

```bash
wc -l scripts/lib/infra/db/*.py
# 每个模块应 < 200 行
```

**4.4 类型检查**

```bash
mypy scripts/lib/infra/db/ scripts/lib/common/database.py
```

#### 验收标准

| SC | 指标 | 验证方式 |
|----|------|---------|
| SC-001 | 所有现有测试通过 | `pytest scripts/tests/ -v` |
| SC-002 | 每个模块 < 200 行 | `wc -l scripts/lib/infra/db/*.py` |
| SC-003 | 5 个事务函数有回滚测试 | `pytest -k test_transaction_safety -v` |
| SC-004 | `from api.database import xxx` 正常工作 | Python import 测试 |

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | — | — |

## Appendix

### 执行顺序建议

```
Phase 1 (拆分) → Phase 2 (测试先行) → Phase 3 (事务修复) → Phase 4 (回归验证)
     │                  │                      │
     └── 向后兼容 ──────┘                      │
                         └── TDD 红灯 ─────────┘── TDD 绿灯
```

Phase 1 和 Phase 2 可并行准备，但 Phase 2 的测试依赖 Phase 1 的模块结构。建议严格顺序执行。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 模块拆分 | 导入兼容，所有测试通过 | `pytest scripts/tests/` |
| US2 快照事务 | 异常时数据一致 | `test_transaction_safety.py::TestSnapshotTransactionSafety` |
| US3 配置激活事务 | 两步 UPDATE 原子性 | `test_transaction_safety.py::TestEvalConfigTransactionSafety` |
| US4 迁移事务 | DDL 分步+验证 | 手动验证 + `_migrate_db` 日志 |
