---
description: 需求描述生成 spec.md，自动创建 worktree 隔离开发环境
arguments:
  - name: description
    description: 需求描述（自然语言）
    required: true
---

# Gen Specify - 需求规格说明生成器

将自然语言需求描述转化为结构化的 spec.md，并自动创建基于 origin/master 的 worktree 隔离开发环境。

## 核心要求

> **接收需求描述，通过多轮对话澄清后，生成结构化的 spec.md。聚焦 WHAT 和 WHY，不涉及技术选型。**

## 命令格式

```bash
/gen-specify <需求描述>
```

## 用法

```bash
/gen-specify 实现知识库搜索功能，支持按条款类型和产品分类检索
/gen-specify 添加评估报告导出为 PDF 的功能
```

---

## 执行步骤

### 第一步：创建 Worktree

1. **扫描编号** — 检查本地+远程分支中已有的 `NNN-*` 分支，取 max+1
2. **生成 feature-name** — 从需求描述中提取 3-4 个关键词，格式 `NNN-keyword-keyword`
3. **创建 worktree** — 基于 `origin/master` 创建：
   ```bash
   git worktree add .claude/worktrees/<feature-name> -b <feature-name> origin/master
   ```
4. **拷贝配置文件** — 从当前工作目录拷贝到新 worktree：
   ```bash
   cp scripts/config/settings.json .claude/worktrees/<feature-name>/scripts/config/settings.json
   cp scripts/.env .claude/worktrees/<feature-name>/scripts/.env
   ```
5. **创建产物目录**：
   ```bash
   mkdir -p .claude/worktrees/<feature-name>/specs/<feature-name>
   ```

### 第二步：需求澄清

通过多轮对话（一次一个问题）澄清需求：

1. **目标用户** — 谁在使用这个功能？
2. **核心场景** — 最关键的 1-2 个使用场景是什么？
3. **验收标准** — 怎么算做完了？
4. **边界条件** — 什么情况不需要处理？
5. **依赖和约束** — 有没有必须遵守的技术/业务约束？

每个问题等待用户回答后再问下一个。如果用户已经描述得很清楚，可以跳过。

### 第三步：生成 spec.md

在 worktree 中生成 `specs/<feature-name>/spec.md`：

```markdown
# Feature Specification: [FEATURE NAME]

**Feature Branch**: `NNN-feature-name`
**Created**: YYYY-MM-DD
**Status**: Draft
**Input**: 用户原始需求描述

## User Scenarios & Testing

### User Story 1 - [标题] (Priority: P1)

[描述用户旅程]

**Why this priority**: [价值说明]

**Independent Test**: [如何独立测试]

**Acceptance Scenarios**:

1. **Given** [初始状态], **When** [操作], **Then** [预期结果]
2. **Given** [初始状态], **When** [操作], **Then** [预期结果]

---

### User Story 2 - [标题] (Priority: P2)

[描述用户旅程]

**Why this priority**: [价值说明]

**Independent Test**: [如何独立测试]

**Acceptance Scenarios**:

1. **Given** [初始状态], **When** [操作], **Then** [预期结果]

---

### Edge Cases

- [边界条件 1]?
- [错误场景 1]?

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST [具体能力]
- **FR-002**: 系统 MUST [具体能力]
- **FR-003**: [NEEDS CLARIFICATION: 不明确的标注此项]

### Key Entities

- **[Entity1]**: [含义和关键属性]
- **[Entity2]**: [含义和关系]

## Success Criteria

- **SC-001**: [可测量指标]
- **SC-002**: [可测量指标]

## Assumptions

- [假设 1]
- [约束 1]
- [依赖 1]
```

### 第四步：自审

生成后自动检查：

1. **NEEDS CLARIFICATION 标记** — 列出所有未明确的需求
2. **矛盾检查** — User Stories 之间是否有冲突
3. **遗漏检查** — 是否有明显缺失的场景
4. **可测试性** — 每个 User Story 是否有明确的验收场景

输出自审报告，如有问题提示用户修正。

### 第五步：输出提示

```
✅ spec.md 已生成

📁 产物位置: specs/<feature-name>/spec.md
🌳 工作目录: .claude/worktrees/<feature-name>/
🌿 分支: <feature-name> (基于 origin/master)

⚠️ NEEDS CLARIFICATION: N 处未明确需求（见上方列表）

→ 请切换到 worktree 目录继续开发：
  cd .claude/worktrees/<feature-name>
→ 然后执行 /gen-research 开始技术调研
```

---

## 关键行为

- **聚焦 WHAT 和 WHY** — 不涉及技术选型、框架选择、实现细节
- **独立可测试** — 每个 User Story 必须能独立开发和测试
- **不明确标注** — 用 `[NEEDS CLARIFICATION]` 标注需要澄清的需求，不猜测
- **用户确认** — 生成后让用户确认或修正，不强制接受

---

## 相关文件

- `specs/<feature-name>/spec.md` — 产物（输出）
- `CLAUDE.md` — 治理原则和产物规范（参考）
