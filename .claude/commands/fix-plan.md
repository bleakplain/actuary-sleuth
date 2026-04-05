---
description: 文档审查和批注处理工具，支持多文档审查（spec/plan/tasks）和 CLAUDE.md 规则提炼
arguments:
  - name: action
    description: 操作类型：update/update-claude/review/check-spec/check-plan/check-tasks/rules
    required: true
  - name: target
    description: 目标文件（review/check 操作需要：spec/plan/tasks/claude）
    required: false
---

# Fix Plan - 文档审查与更新工具

审查 SDD 产物（spec.md、plan.md、tasks.md）的完整性和一致性，基于批注更新文档，提炼编码规则到 CLAUDE.md。

## 核心要求

> **支持多文档审查（spec/plan/tasks）、批注处理、规则提炼。所有操作基于当前 git branch 的 feature-name 定位产物目录。**

## 命令格式

```bash
/fix-plan <action> [target]
```

---

## 可用操作

### 1. `/fix-plan review <target>` - 查看文档

**用法**:
```bash
/fix-plan review spec      # 查看 spec.md
/fix-plan review plan      # 查看 plan.md
/fix-plan review tasks     # 查看 tasks.md
/fix-plan review claude    # 查看 CLAUDE.md
```

读取并显示 `specs/<feature-name>/` 下对应的文档内容。

---

### 2. `/fix-plan check-spec` - 审查 spec.md 完整性

**用法**:
```bash
/fix-plan check-spec
```

**审查项目**:

1. **User Stories 完整性**
   - 每个 User Story 是否有 Priority 标注
   - 每个 User Story 是否有 Acceptance Scenarios（Given/When/Then）
   - 每个 User Story 是否标注了 Independent Test

2. **Functional Requirements**
   - FR 编号是否连续
   - 是否有未标注 `[NEEDS CLARIFICATION]` 的模糊需求
   - 每个 FR 是否可追溯到 User Story

3. **Success Criteria**
   - 是否有可测量的指标
   - 是否覆盖所有 P1 User Stories

4. **一致性检查**
   - User Stories 和 Functional Requirements 是否对齐
   - Assumptions 是否合理

**输出格式**:
```
📋 spec.md 审查报告
═══════════════════════════════════

✅ User Stories: 3 个 (P1: 1, P2: 2)
✅ Acceptance Scenarios: 全部覆盖
⚠️ NEEDS CLARIFICATION: 2 处
   - FR-003: 认证方式未指定
   - FR-005: 数据保留期未指定
❌ 缺失: Success Criteria 未覆盖 US2

📋 建议
━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 明确 FR-003 的认证方式
2. 为 US2 添加 Success Criteria
```

---

### 3. `/fix-plan check-plan` - 审查 plan.md 一致性

**用法**:
```bash
/fix-plan check-plan
```

**审查项目**:

1. **User Story 回溯**
   - 每个 Implementation Phase 是否标注了对应的 User Story
   - 是否有 User Story 在 plan.md 中被遗漏

2. **Constitution Check**
   - 治理原则检查是否全部通过
   - 未通过的是否有 Complexity Tracking 记录

3. **技术上下文**
   - Technical Context 是否完整填写
   - 依赖版本是否明确

4. **代码示例质量**
   - 代码是否完整可运行（无 `...` 省略）
   - 是否包含必要的 import
   - 是否遵循 CLAUDE.md 编码规范

**输出格式**:
```
📋 plan.md 审查报告
═══════════════════════════════════

✅ User Story 回溯: 3/3 覆盖
⚠️ Constitution Check: 1 项未通过
   - 简单优先: 使用了复杂抽象 → 已记录在 Complexity Tracking
❌ 代码示例: Phase 3 步骤 2 代码不完整（使用了 ... 省略）

📋 建议
━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 补全 Phase 3 步骤 2 的完整代码
```

---

### 4. `/fix-plan check-tasks` - 审查 tasks.md 完整性

**用法**:
```bash
/fix-plan check-tasks
```

**审查项目**:

1. **任务覆盖**
   - plan.md 中的所有实现步骤是否都在 tasks.md 中有对应任务
   - 是否有遗漏的任务

2. **依赖正确性**
   - depends on 引用的任务 ID 是否存在
   - 是否有循环依赖

3. **并行标记**
   - 标记 [P] 的任务是否真的无依赖
   - 是否有可以并行但未标记的任务

4. **Checkpoint**
   - 每个 User Story Phase 是否有 Checkpoint
   - Checkpoint 验证条件是否明确

**输出格式**:
```
📋 tasks.md 审查报告
═══════════════════════════════════

✅ 任务覆盖: plan.md 15 步 → tasks.md 18 任务
✅ 依赖正确: 无循环依赖
⚠️ 并行标记: T008 和 T009 可并行但未标记 [P]
❌ Checkpoint: Phase 3 (US2) 缺少 Checkpoint

📋 建议
━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 为 T008 和 T009 添加 [P] 标记
2. 为 Phase 3 添加 Checkpoint
```

---

### 5. `/fix-plan update` - 基于批注更新文档

**用法**:
```bash
/fix-plan update
```

**执行步骤**:
1. 读取当前 plan.md 和 CLAUDE.md
2. 解析 plan.md 中的批注内容（`--批注：`）
3. 提炼新规则，去重后追加到 CLAUDE.md
4. 基于 CLAUDE.md 规则重新生成 plan.md
5. 移除所有批注内容
6. 输出变更摘要

---

### 6. `/fix-plan update-claude` - 仅更新 CLAUDE.md

**用法**:
```bash
/fix-plan update-claude
```

仅从批注中提炼规则更新 CLAUDE.md，不修改 plan.md。

---

### 7. `/fix-plan rules` - 查看规则清单

**用法**:
```bash
/fix-plan rules
```

显示 CLAUDE.md 中当前的所有约束规则。

---

## 文件定位

所有操作基于当前 git branch 名提取 feature-name：

```
当前分支: 001-kb-search
产物目录: specs/001-kb-search/
  ├── spec.md
  ├── research.md
  ├── plan.md
  └── tasks.md
```

---

## 相关文件

- `specs/<feature-name>/spec.md` — 需求规格
- `specs/<feature-name>/plan.md` — 实现方案
- `specs/<feature-name>/tasks.md` — 任务列表
- `specs/<feature-name>/research.md` — 技术调研
- `CLAUDE.md` — 项目编码规范和治理原则
