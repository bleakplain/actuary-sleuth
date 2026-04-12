---
description: 基于plan.md拆分todolist，逐任务实现，持续类型检查，完成前不停
arguments:
  - name: source
    description: 方案文件路径（默认自动检测 specs/<feature-name>/plan.md）
    required: false
---

# Exec Plan - 方案执行器

基于 `plan.md` 拆分任务列表，逐任务实现代码变更，持续类型检查，确保不引入新问题。在所有任务和阶段全部完成之前不要停下。

## 核心要求

> **基于 plan.md 拆分 todolist，全部实现。每完成一个任务或阶段，在方案文档中标记为已完成。在所有任务和阶段全部完成之前不要停下。不要添加不必要的注释或 Doc，不要使用 any 或 unknown 类型。持续运行类型检查，确保不引入新问题。**

## 命令格式

```bash
/exec-plan [source]
```

## 用法

```bash
/exec-plan              # 自动检测 plan.md
/exec-plan fix.md       # 指定方案文件
```

---

## 模式检测

读取 plan.md 内容，检测是否包含 "Implementation Phases" 或 "User Story" 回溯标记。

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| **SDD 模式** | plan.md 包含 Implementation Phases / User Story 回溯 | 先生成 tasks.md，再逐任务执行 |
| **兼容模式** | 无上述标记 | 直接按 plan.md 逐任务执行（原有行为） |

---

## 第零步：Worktree 检查与创建

**执行任何代码变更前，必须确保在 worktree 中工作。**

#### 前置检查（worktree 就绪后、执行任务前）

1. **检查并拷贝 .env**: 确认 `scripts/.env` 存在，若不存在则从主仓库拷贝：
   ```bash
   cp <主仓库>/scripts/.env scripts/.env
   ```
2. **检查数据路径可达**: 读取 .env 中 `DATA_PATHS_SQLITE_DB` 等路径，验证关键目录（db、kb）的父目录存在，如果路径不存在则提示用户检查配置，不继续执行任务

### 检测是否已在 worktree 中

1. 运行 `git worktree list` 检查当前工作目录
2. 如果当前目录已指向一个 worktree 分支（非 master）→ 跳过创建，直接执行
3. 如果当前在 master 上 → 必须创建 worktree

### 创建 Worktree

1. **提取 feature-name** — 从 `specs/` 目录或 `plan.md` 路径中提取（如 `004-eval-dataset-curation`）
2. **扫描编号** — 检查本地+远程分支中已有的 `NNN-*` 分支，取 max+1
3. **检查分支是否已存在** — 如果 `<feature-name>` 分支已存在，直接切换到对应 worktree
4. **创建 worktree** — 基于 `origin/master` 创建：
   ```bash
   git worktree add .claude/worktrees/<feature-name> -b <feature-name> origin/master
   ```
5. **拷贝配置文件** — 从当前工作目录拷贝到新 worktree：
   ```bash
   cp scripts/config/settings.json .claude/worktrees/<feature-name>/scripts/config/settings.json
   cp scripts/.env .claude/worktrees/<feature-name>/scripts/.env
   ```
6. **将 plan.md 和相关产物复制到 worktree**：
   ```bash
   cp -r specs/<feature-name>/ .claude/worktrees/<feature-name>/specs/<feature-name>/
   ```
7. **切换工作目录到 worktree**：
   ```
   后续所有操作在 .claude/worktrees/<feature-name>/ 下执行
   ```

### 如果 plan.md 在 master 上且无 specs 目录

说明是兼容模式且方案文件在项目根目录或其他位置，此时：
1. 仍需创建 worktree 隔离开发环境
2. 将方案文件复制到 worktree 对应位置

---

## SDD 模式执行步骤

### 第一步：读取并解析 plan.md

1. 读取 `specs/<feature-name>/plan.md`
2. 提取所有 Implementation Phases
3. 识别每个 Phase 对应的 User Story
4. 提取任务间的依赖关系

### 第二步：生成 tasks.md

输出到 `specs/<feature-name>/tasks.md`：

```markdown
# Tasks: [FEATURE NAME]

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md (如有)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)
- 包含精确文件路径

## Phase 1: Setup

- [ ] T001 创建项目结构
- [ ] T002 [P] 配置依赖

## Phase 2: User Story 1 - [标题] (P1)

- [ ] T003 [P] [US1] 创建数据模型 in path/to/models.py
- [ ] T004 [US1] 实现核心逻辑 in path/to/service.py (depends on T003)
- [ ] T005 [US1] 添加 API 端点 in path/to/api.py
- [ ] T006 [US1] 编写测试 in tests/test_feature.py

**Checkpoint**: User Story 1 可独立测试

## Phase 3: User Story 2 - [标题] (P2)

...

## Dependencies & Execution Order

### Phase Dependencies
- Setup (Phase 1): No dependencies
- US1 (Phase 2): Depends on Setup
- US2 (Phase 3): Depends on Setup, can parallel with US1 if independent

### Within Each Story
- Models before services
- Services before endpoints
- Core implementation before tests
```

### 第三步：创建 todolist

使用 TaskCreate 工具将 tasks.md 拆分为任务列表：

1. **按 Phase 分组** — 每个 Phase 对应一组任务
2. **按优先级排序** — P1 → P2 → P3
3. **设置依赖关系** — 被阻塞的任务设置 blockedBy
4. **任务粒度** — 每个任务应是一个可独立验证的原子变更

### 第四步：逐任务执行

对于每个任务：

1. **标记为 in_progress**
2. **读取相关文件** — 理解当前代码上下文
3. **实施代码变更** — 严格按照方案执行
4. **运行类型检查** — `mypy scripts/lib/`
5. **运行相关测试** — `pytest scripts/tests/`
6. **标记为 completed**

### 第五步：更新 tasks.md

每完成一个任务：
- 在 tasks.md 对应任务前添加 ✅ 标记
- Phase 完成后添加阶段完成标记

### 第六步：Checkpoint 验证

每个 User Story 的 Phase 完成后：

1. **独立测试** — 验证该 User Story 可独立运行
2. **验收标准检查** — 对照 spec.md 的 Acceptance Scenarios
3. **类型检查** — `mypy scripts/lib/`

### 第七步：代码审查（强制）

所有任务完成后，**必须**执行 `/simplify` 命令：

1. `/simplify` 审查代码质量（复用性、可读性、效率、潜在 bug）
2. **根据反馈修复所有问题**，不跳过任何建议
3. 修复后重新运行类型检查和测试

### 第八步：完成验证

1. **运行完整类型检查** — `mypy scripts/lib/`
2. **运行完整测试套件** — `pytest scripts/tests/`
3. **汇总变更** — 列出所有修改/新增/删除的文件
4. **输出执行报告**

---

## 兼容模式执行步骤

### 第一步：读取并解析方案文件

1. 读取方案文件（默认 `specs/<feature-name>/plan.md`）
2. 解析所有章节和任务条目
3. 识别任务间的依赖关系和执行顺序

### 第二步：创建 todolist

使用 TaskCreate 工具拆分任务：

1. **按章节分组**
2. **按优先级排序** — P0 → P1 → P2 → P3
3. **设置依赖关系**
4. **任务粒度** — 可独立验证的原子变更

### 第三步：逐任务执行

对于每个任务：

1. **标记为 in_progress**
2. **读取相关文件**
3. **实施代码变更**
4. **运行类型检查** — `mypy scripts/lib/`
5. **运行相关测试** — `pytest scripts/tests/`
6. **标记为 completed**

### 第四步：更新方案文档

每完成一个任务或阶段：
- 在方案文档对应任务标题后添加 ✅ 标记
- 在阶段标题后添加完成标记

### 第五步：代码审查（强制）

所有任务完成后，**必须**执行 `/simplify` 命令。

### 第六步：完成验证

1. **运行完整类型检查** — `mypy scripts/lib/`
2. **运行完整测试套件** — `pytest scripts/tests/`
3. **汇总变更**
4. **输出执行报告**

---

## 约束规则

### 代码规范
- ❌ 不添加不必要的注释或 Doc
- ❌ 不使用 `any` 或 `unknown` 类型
- ✅ 严格类型注解
- ✅ 遵循 CLAUDE.md 编码规范

### 质量保障
- 每个任务完成后运行 `mypy scripts/lib/`
- 发现类型错误立即修复，不延后
- 测试失败时修复问题，不跳过

### 执行纪律
- 在所有任务和阶段全部完成之前不要停下
- 每个任务严格按方案执行，不自行扩展范围
- 遇到阻塞立即报告，不猜测或跳过

---

## 输出格式

### 执行报告

```
📋 执行报告
═══════════════════════════════════
方案文件: specs/<feature-name>/plan.md
完成时间: YYYY-MM-DD HH:MM

✅ 任务完成统计
━━━━━━━━━━━━━━━━━━━━━━━━━━
总任务数: N
已完成: N
类型检查: ✅ 通过
测试套件: ✅ N/N 通过

📊 变更摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━
修改文件: file1.py, file2.py
新增文件: file3.py
删除文件: file4.py
```

---

## 相关文件

- `specs/<feature-name>/plan.md` — 实现方案（源）
- `specs/<feature-name>/tasks.md` — 任务列表（SDD 模式生成）
- `specs/<feature-name>/spec.md` — 需求规格（SDD 模式参考）
- `CLAUDE.md` — 项目编码规范（参考）
