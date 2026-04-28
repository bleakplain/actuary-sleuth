# Feature Specification: database.py 模块拆分与事务安全

**Feature Branch**: `026-db-split-transaction`
**Created**: 2026-04-28
**Status**: Draft
**Input**: api/database.py 有 1605 行 65+ 函数，难以维护；部分事务操作缺少回滚保护，存在数据不一致风险

## User Scenarios & Testing

### User Story 1 - 数据库模块按功能域拆分 (Priority: P1)

开发者维护数据库访问层时，能在独立的小模块中定位和修改函数，而非在一个 1600+ 行的单文件中滚动查找。拆分后所有现有导入 `from api.database import xxx` 继续正常工作，无需修改业务代码。

**Why this priority**: 拆分是后续事务修复的前提，且单文件过大是日常开发的直接痛点。

**Independent Test**: 运行现有测试套件，所有测试通过；导入 `from api.db import create_session` 和 `from api.database import create_session` 均成功。

**Acceptance Scenarios**:

1. **Given** database.py 已拆分为 `api/db/` 包, **When** 路由文件使用 `from api.db import create_session`, **Then** 导入成功且函数行为不变
2. **Given** database.py 已拆分, **When** 使用旧路径 `from api.database import create_session`, **Then** 仍可正常导入（向后兼容）
3. **Given** 各功能模块独立, **When** 修改 feedback 相关函数, **Then** 不影响 session/eval 等其他模块的测试
4. **Given** 拆分完成, **When** 运行 `pytest scripts/tests/`, **Then** 所有测试通过

---

### User Story 2 - 快照操作事务安全 (Priority: P1)

开发者执行快照创建/恢复/删除时，如果中途发生异常，数据库和文件系统保持一致状态：不会出现孤儿文件、数据丢失或不完整记录。

**Why this priority**: 快照操作涉及数据删除和覆盖，数据丢失风险最高。

**Independent Test**: 在快照操作中途模拟异常，验证回滚后数据完整。

**Acceptance Scenarios**:

1. **Given** 评估样本存在, **When** `create_snapshot()` 数据库写入失败, **Then** 临时文件被清理，不留下孤儿文件
2. **Given** 评估样本存在, **When** `restore_snapshot()` 插入新样本中途失败, **Then** 原有样本数据保留（回滚）
3. **Given** 快照存在, **When** `remove_snapshot()` 文件删除失败, **Then** 数据库记录仍存在，可重试
4. **Given** 快照存在, **When** `restore_snapshot()` 全部成功, **Then** 样本数据为新快照内容

---

### User Story 3 - 评测配置激活事务安全 (Priority: P2)

开发者激活评测配置时，不会出现所有配置都被停用但目标配置未激活的中间状态。

**Why this priority**: 功能正确性受影响，但发生概率较低（仅在异常时）。

**Independent Test**: 在两条 UPDATE 之间模拟异常，验证不存在无活跃配置的状态。

**Acceptance Scenarios**:

1. **Given** 配置 A 为活跃状态, **When** `activate_eval_config(B)` 执行中异常, **Then** 配置 A 仍为活跃（事务回滚）
2. **Given** 配置 A 为活跃状态, **When** `activate_eval_config(B)` 成功, **Then** 仅配置 B 为活跃

---

### User Story 4 - 数据库迁移事务安全 (Priority: P2)

数据库迁移执行时，如果中途失败，不会留下部分迁移的不一致 schema。

**Why this priority**: 迁移仅在启动时执行，且 SQLite DDL 部分可回滚，但复杂表重建操作风险较高。

**Independent Test**: 在迁移中途模拟异常，验证数据库 schema 回滚到迁移前状态。

**Acceptance Scenarios**:

1. **Given** 数据库需要迁移, **When** `_migrate_db()` 中途异常, **Then** 数据库 schema 保持迁移前状态
2. **Given** 数据库需要迁移, **When** `_migrate_db()` 成功, **Then** 所有新列/表正确创建

---

### Edge Cases

- `create_snapshot()` 时目标目录已存在（重名快照）?
- `restore_snapshot()` 时快照文件损坏或为空?
- `remove_snapshot()` 时快照被评测运行引用（已有保护，确认行为不变）?
- 并发执行 `activate_eval_config()` 时竞态条件?

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 将 database.py 按功能域拆分为独立模块（session, eval_samples, eval_snapshots, eval_configs, eval_runs, feedback, traces, human_reviews, compliance, documents, schema, common）
- **FR-002**: 系统 MUST 通过 `__init__.py` 重新导出所有函数，保持向后兼容
- **FR-003**: `create_snapshot()` MUST 使用临时文件 + DB 先提交 + 原子 rename 模式，异常时清理临时文件
- **FR-004**: `restore_snapshot()` MUST 使用显式事务（BEGIN IMMEDIATE），失败时回滚保留原数据
- **FR-005**: `remove_snapshot()` MUST 先删除 DB 记录再删除文件，文件删除失败不影响 DB 状态
- **FR-006**: `activate_eval_config()` MUST 使用显式事务保证两步 UPDATE 的原子性
- **FR-007**: `_migrate_db()` MUST 使用显式事务包裹迁移操作

### Key Entities

- **DatabaseModule**: 按功能域拆分的数据库访问模块，每个模块包含该域的所有 CRUD 函数
- **TransactionBoundary**: 需要事务保护的操作边界，定义了 BEGIN/COMMIT/ROLLBACK 的范围
- **SnapshotFile**: 快照文件系统对象，与 DB 记录需保持一致性

## Success Criteria

- **SC-001**: database.py 拆分后所有现有测试通过（零功能变更）
- **SC-002**: 每个功能模块文件不超过 200 行
- **SC-003**: 5 个事务问题函数均有对应的事务回滚测试用例
- **SC-004**: `from api.database import xxx` 仍可正常工作

## Assumptions

- SQLite WAL 模式下 BEGIN IMMEDIATE 可保证写事务互斥
- 文件系统 `os.rename()` 在同一文件系统上是原子操作
- 快照功能使用频率低，不涉及并发恢复场景
- 拆分不改变任何函数签名和返回值
