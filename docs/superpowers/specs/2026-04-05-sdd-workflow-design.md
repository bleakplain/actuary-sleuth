# SDD Workflow Skill 改造设计

**日期**: 2026-04-05
**状态**: Approved
**范围**: `.claude/commands/` 下 5 个 skill + CLAUDE.md 改造

---

## 背景与目标

将现有 4 个 skill（gen-research、gen-plan、fix-plan、exec-plan）从"问题驱动"模式改造为"需求驱动"的 SDD（Spec-Driven Development）模式，参考 [GitHub Spec-Kit](https://github.com/github/spec-kit) 的最佳实践。

**核心理念变化**:
- 从"代码 → 找问题 → 修复"转变为"需求 → 规格说明 → 技术方案 → 实现"
- spec.md 成为开发的中心产物，代码服务于规格说明
- 每个阶段有明确的输入/输出和质量门禁

**关键约束**:
- 保持原有 skill 命名不变（gen-research、gen-plan、fix-plan、exec-plan）
- 新增 gen-specify 作为可选入口
- gen-research 必须支持无 spec.md 时按原有模式工作（向后兼容）
- 不删除旧 skill，直接在原文件上改造
- CLAUDE.md 改造为同时承担"项目治理原则 + 编码规范"
- **所有 SDD 产物统一输出到 `specs/<feature-name>/` 下，不再输出到项目根目录**（解决 worktree 合并冲突）

---

## 新工作流

```
[可选] /gen-specify   "需求描述"
  → 基于 origin/master 创建 worktree (NNN-feature-name)
  → 在 worktree 中生成 specs/NNN-feature-name/spec.md
             ↓
/gen-research  [spec.md?]           →  research.md
             ↓
/gen-plan      [spec.md?]           →  plan.md
             ↓
/exec-plan     [plan.md]            →  tasks.md + 代码实现
             ↓
/fix-plan      [review]             →  文档审查 + 批注处理
```

### Worktree 策略

- **始终基于 origin/master 创建 worktree**，保证每个 feature 是干净的起点
- worktree 目录位于 `.claude/worktrees/<feature-name>/`
- 分支编号：扫描本地+远程分支取 max+1，避免并行冲突
- 分支名 = 目录名 = `specs/` 子目录名（如 `001-kb-search`）
- gen-specify 跳过时，gen-research 交互式询问 feature-name 后创建 worktree

### 模式切换

- `gen-specify` 可选，跳过时 gen-research 按原有模式工作
- 每个步骤通过检测当前 worktree 的 `specs/<feature-name>/spec.md` 是否存在来切换 SDD/兼容模式

---

## 产出物目录结构

```
specs/<feature-name>/
├── spec.md          # gen-specify 输出（可选）
├── research.md      # gen-research 输出
├── plan.md          # gen-plan 输出
└── tasks.md         # exec-plan 生成
```

feature-name 命名规则：`NNN-简短描述`，如 `001-kb-search`，沿用 spec-kit 的编号风格。

---

## 各 Skill 详细改造设计

### 1. gen-specify（新增）

**文件**: `.claude/commands/gen-specify.md`

**职责**: 需求描述 → spec.md

**输入**: 用户自然语言描述的需求

**输出**: `specs/<feature-name>/spec.md`

**spec.md 结构**（对齐 spec-kit spec-template）:

```markdown
# Feature Specification: [FEATURE NAME]

**Feature Branch**: `NNN-feature-name`
**Created**: DATE
**Status**: Draft
**Input**: 用户描述

## User Scenarios & Testing

### User Story 1 - [标题] (Priority: P1)
描述用户旅程
**Why this priority**: 价值说明
**Independent Test**: 独立测试方式
**Acceptance Scenarios**:
1. Given... When... Then...

### User Story 2 - [标题] (Priority: P2)
...

### Edge Cases
- 边界条件
- 错误场景

## Requirements

### Functional Requirements
- FR-001: 系统 MUST ...
- FR-002: 系统 MUST ...

### Key Entities
- Entity1: 含义和属性

## Success Criteria
- SC-001: 可测量指标

## Assumptions
- 假设和约束
```

**执行步骤**:
1. 接收用户需求描述
2. 扫描本地+远程分支，确定编号 NNN，生成 feature-name
3. 基于 origin/master 创建 worktree（分支名 `NNN-feature-name`）
4. 通过多轮对话澄清需求（ask one question at a time）
5. 在 worktree 中生成 `specs/<feature-name>/spec.md`
6. 运行自审（检查 NEEDS CLARIFICATION 标记、矛盾、遗漏）
7. 提示用户切换到 worktree 目录继续开发

**关键行为**:
- 聚焦 WHAT 和 WHY，不涉及技术选型
- 强制要求 User Stories 有独立可测试性
- 不明确的标注 `[NEEDS CLARIFICATION]`

---

### 2. gen-research（改造）

**文件**: `.claude/commands/gen-research.md`（原地改造）

**变化**: 从"主动扫描找问题"变为"服务于 spec.md 的定向研究"

**两种工作模式**:

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| SDD 模式 | 当前 worktree 的 `specs/<feature-name>/spec.md` 存在 | 基于 spec.md 定向研究：分析现有代码如何支持需求实现、技术选型调研、依赖分析 |
| 兼容模式 | 无 `spec.md` | 询问 feature-name → 基于 origin/master 创建 worktree → 保持原有行为：深度代码分析、问题识别（向后兼容） |

**research.md 结构改造**（SDD 模式下）:

```markdown
# [Feature Name] - 技术调研报告

生成时间: DATE
源规格: specs/<feature-name>/spec.md

## 执行摘要
简要概述调研发现、技术选型建议、风险提示

## 一、现有代码分析
### 1.1 相关模块梳理
分析 spec.md 中涉及的需求在现有代码库中的对应模块
### 1.2 可复用组件
可复用的现有类、函数、数据结构
### 1.3 需要新增/修改的模块

## 二、技术选型研究
### 2.1 技术方案对比
| 方案 | 优点 | 缺点 | 适用场景 |
### 2.2 依赖分析
新增依赖、版本兼容性

## 三、数据流分析
### 3.1 现有数据流
### 3.2 新增/变更的数据流

## 四、关键技术问题
### 4.1 需要验证的技术假设
### 4.2 潜在风险和缓解措施

## 五、参考实现
相关开源项目、文档链接
```

**兼容模式**: 当无 spec.md 时，保持当前 research.md 的完整结构（项目概览、核心架构、潜在问题等）不变。

---

### 3. gen-plan（改造）

**文件**: `.claude/commands/gen-plan.md`（原地改造）

**变化**: 输入从 research.md 变为 spec.md + research.md，输出对齐 SDD plan 结构

**两种工作模式**:

| 模式 | 触发条件 | 输入 |
|------|---------|------|
| SDD 模式 | 当前 worktree 的 `specs/<feature-name>/spec.md` 存在 | spec.md + research.md |
| 兼容模式 | 无 spec.md | research.md（保持原有行为） |

**plan.md 结构改造**（SDD 模式下，对齐 spec-kit plan-template）:

```markdown
# Implementation Plan: [FEATURE]

**Branch**: `NNN-feature-name` | **Date**: DATE | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary
从 spec.md 提取的主要需求 + 从 research.md 提取的技术方案

## Technical Context
**Language/Version**: Python 3.x
**Primary Dependencies**: ...
**Storage**: ...
**Testing**: pytest
**Performance Goals**: ...
**Constraints**: ...

## Constitution Check
*基于 CLAUDE.md 治理原则的合规检查*
- [ ] 原则 1: ...
- [ ] 原则 2: ...

## Project Structure
### Documentation
specs/<feature-name>/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md

### Source Code
涉及修改/新增的目录结构

## Implementation Phases

### Phase 1: Setup
基础设施准备

### Phase 2: Core - User Story 1 (P1)
#### 需求回溯
→ 对应 spec.md User Story 1
#### 实现步骤
1. 步骤描述
   - 文件: path/to/file.py
   - 代码示例

### Phase 3: Enhancement - User Story 2 (P2)
...

## Complexity Tracking
| 复杂度项 | 原因 | 更简单的替代方案及排除理由 |

## Appendix
### 执行顺序建议
### 验收标准总结
```

**关键变化**:
- 每个实现阶段明确回溯到 spec.md 的 User Story（可追溯性）
- 新增 Constitution Check 门禁
- 新增 Technical Context 标准化上下文
- 保留兼容模式：无 spec.md 时按原有 plan.md 格式生成修复方案

---

### 4. exec-plan（改造）

**文件**: `.claude/commands/exec-plan.md`（原地改造）

**变化**: 新增 tasks.md 生成阶段，按用户故事分阶段执行

**执行流程改造**:

```
读取 plan.md
    ↓
检测 SDD 模式（plan.md 包含 Implementation Phases / User Story 回溯）
    ↓
SDD 模式:
  1. 生成 tasks.md（按用户故事分阶段，含依赖和并行标记）
  2. 按 tasks.md 逐任务执行
     ↓
兼容模式:
  1. 直接按 plan.md 逐任务执行（原有行为）
```

**tasks.md 结构**（对齐 spec-kit tasks-template）:

```markdown
# Tasks: [FEATURE NAME]

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md (如有)

## Format: `[ID] [P?] [Story] Description`
- [P]: 可并行执行
- [Story]: 所属用户故事 (US1, US2, ...)

## Phase 1: Setup
- [ ] T001 创建项目结构
- [ ] T002 [P] 配置依赖

## Phase 2: User Story 1 - [标题] (P1)
- [ ] T003 [P] [US1] 创建数据模型 in src/models/
- [ ] T004 [US1] 实现核心逻辑 in src/services/ (depends on T003)
- [ ] T005 [US1] 添加 API 端点
- [ ] T006 [US1] 编写测试
**Checkpoint**: User Story 1 可独立测试

## Phase 3: User Story 2 - [标题] (P2)
...

## Dependencies & Execution Order
### Phase Dependencies
- Setup → US1 → US2 → ...
### Within Each Story
- 模型 → 服务 → 端点 → 测试
```

**关键变化**:
- 新增 tasks.md 生成步骤（SDD 模式下）
- 任务按 User Story 分组，每个 Story 有 Checkpoint
- 支持并行标记 `[P]` 和依赖标记
- 兼容模式保持原有行为不变
- 保留强制 `/simplify` 代码审查和 mypy 类型检查

---

### 5. fix-plan（改造）

**文件**: `.claude/commands/fix-plan.md`（原地改造）

**变化**: 从"处理 plan.md 批注"扩展为"多文档审查"

**新增操作**:

| 操作 | 说明 |
|------|------|
| `update` | 保持原有行为（基于批注更新 plan.md + CLAUDE.md） |
| `update-claude` | 保持原有行为 |
| `review plan` | 查看 plan.md |
| `review spec` | 查看 spec.md |
| `review tasks` | 查看 tasks.md |
| `review claude` | 查看 CLAUDE.md |
| `rules` | 保持原有行为 |
| `check-spec` | **新增**: 审查 spec.md 完整性（User Stories、验收标准、NEEDS CLARIFICATION 标记） |
| `check-plan` | **新增**: 审查 plan.md 与 spec.md 的一致性（每个 Phase 是否回溯到 User Story） |
| `check-tasks` | **新增**: 审查 tasks.md 完整性（依赖是否正确、是否有遗漏任务） |

---

## CLAUDE.md 改造

在现有编码规范基础上，新增 SDD 相关章节。

### 新增内容

```markdown
## Development Workflow (SDD)

### 工作流阶段
1. [可选] /gen-specify — 需求 → spec.md
2. /gen-research — 代码/需求分析 → research.md
3. /gen-plan — 技术方案 → plan.md
4. /exec-plan — 任务分解 + 实现 → tasks.md + 代码
5. /fix-plan — 审查 + 批注处理

### 产物规范
- spec.md 是开发中心产物，代码服务于规格说明
- 每个 User Story 必须独立可测试
- plan.md 每个实现阶段必须回溯到 spec.md 的 User Story
- tasks.md 按用户故事分阶段，标注依赖和并行关系

### 治理原则
- Library-First: 优先复用现有库和模块
- 测试优先: 核心功能必须有测试覆盖
- 简单优先: 选择最简单的可行方案，除非有明确理由
- 显式优于隐式: 代码自文档化，避免魔法
- Constitution Check: gen-plan 必须通过治理原则合规检查
```

---

## 向后兼容策略

所有改造后的 skill 都保持向后兼容：

| Skill | 无 spec.md 时的行为 |
|-------|-------------------|
| gen-research | 按原有模式工作（扫描代码、找问题、生成 research.md） |
| gen-plan | 按原有模式工作（基于 research.md 问题列表生成修复方案） |
| exec-plan | 按原有模式工作（直接按 plan.md 执行，不生成 tasks.md） |
| fix-plan | 完全兼容，新增操作不影响原有功能 |

检测逻辑：从当前 git branch 名提取 feature-name（如 `001-kb-search`），检查 `specs/<feature-name>/spec.md` 是否存在。存在则进入 SDD 模式，否则进入兼容模式。

---

## 实施计划

1. **CLAUDE.md 改造** — 新增 SDD 工作流章节和治理原则
2. **gen-specify** — 新建 `.claude/commands/gen-specify.md`
3. **gen-research** — 改造为双模式（SDD + 兼容）
4. **gen-plan** — 改造为双模式（SDD + 兼容）
5. **exec-plan** — 改造为 SDD 模式下先生成 tasks.md
6. **fix-plan** — 扩展多文档审查能力

---

## 参考资料

- [GitHub Spec-Kit](https://github.com/github/spec-kit)
- [Spec-Driven Development Methodology](https://github.com/github/spec-kit/blob/main/spec-driven.md)
- [spec-template.md](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)
- [plan-template.md](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)
- [tasks-template.md](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md)
