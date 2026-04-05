---
description: 基于spec.md和research.md生成技术实现方案plan.md，或基于research.md生成问题修复方案
arguments:
  - name: source
    description: 源文件路径（默认自动检测）
    required: false
  - name: output
    description: 输出文件路径（默认 specs/<feature-name>/plan.md）
    required: false
---

# Gen Plan - 技术实现方案生成器

根据 spec.md + research.md 生成技术实现方案，或基于 research.md 的问题列表生成修复方案。

## 核心要求

> **SDD 模式：spec.md + research.md → plan.md（含 Constitution Check、User Story 回溯）。**
> **兼容模式：research.md → plan.md（问题修复方案，保持原有行为）。**
>
> **所有输出写入 `specs/<feature-name>/plan.md`，不写项目根目录。**

## 命令格式

```bash
/gen-plan [source] [output]
```

## 用法

```bash
/gen-plan                    # 自动检测模式
/gen-plan research.md        # 指定源文件
/gen-plan research.md fix.md # 指定源文件和输出文件
```

---

## 模式检测

从当前 git branch 名提取 feature-name，检查 `specs/<feature-name>/spec.md` 是否存在。

| 模式 | 触发条件 | 输入 |
|------|---------|------|
| **SDD 模式** | `specs/<feature-name>/spec.md` 存在 | spec.md + research.md |
| **兼容模式** | 无 spec.md | research.md |

---

## SDD 模式执行步骤

### 第一步：读取输入

1. 读取 `specs/<feature-name>/spec.md` — User Stories, Requirements, Success Criteria
2. 读取 `specs/<feature-name>/research.md` — 技术调研结果
3. 从 git branch 名提取 feature-name

### 第二步：Constitution Check

基于 CLAUDE.md 治理原则逐条检查：

- [ ] Library-First — 是否复用了现有库和模块？
- [ ] 测试优先 — 核心功能是否规划了测试？
- [ ] 简单优先 — 是否选择了最简方案？
- [ ] 显式优于隐式 — 是否有魔法行为？
- [ ] 可追溯性 — 每个阶段是否回溯到 User Story？
- [ ] 独立可测试 — User Story 是否可独立交付？

如有违反，在 Complexity Tracking 中记录原因和更简单的替代方案。

### 第三步：生成技术方案

为每个 User Story 生成实现方案：

1. **需求回溯** — 标注对应 spec.md 的哪个 User Story
2. **实现步骤** — 每步包含文件路径和代码示例
3. **依赖分析** — 步骤间的执行顺序

### 第四步：输出文档

输出到 `specs/<feature-name>/plan.md`：

```markdown
# Implementation Plan: [FEATURE NAME]

**Branch**: `NNN-feature-name` | **Date**: YYYY-MM-DD | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

[从 spec.md 提取的主要需求 + 从 research.md 提取的技术方案]

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: [现有+新增依赖]
**Storage**: [数据库/文件]
**Testing**: pytest
**Performance Goals**: [性能目标]
**Constraints**: [约束条件]

## Constitution Check

- [x] Library-First: [说明]
- [x] 测试优先: [说明]
- [ ] 简单优先: [违反说明] → 见 Complexity Tracking
- [x] 显式优于隐式: [说明]
- [x] 可追溯性: [说明]
- [x] 独立可测试: [说明]

## Project Structure

### Documentation

```text
specs/<feature-name>/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

[涉及修改/新增的目录结构]

## Implementation Phases

### Phase 1: Setup

基础设施准备（如需）。

#### 实现步骤

1. [步骤描述]
   - 文件: path/to/file.py
   - 代码示例

---

### Phase 2: Core - User Story 1 (P1)

#### 需求回溯

→ 对应 spec.md User Story 1: [标题]

#### 实现步骤

1. [步骤描述]
   - 文件: path/to/file.py
   - 代码示例
2. [步骤描述]
   - 文件: path/to/file.py
   - 代码示例

---

### Phase 3: Enhancement - User Story 2 (P2)

#### 需求回溯

→ 对应 spec.md User Story 2: [标题]

#### 实现步骤

...

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|

## Appendix

### 执行顺序建议
[Phase 间的依赖关系和推荐顺序]

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
```

---

## 兼容模式执行步骤

### 第一步：读取 research.md

1. 读取 research.md
2. 提取所有问题条目（第五章：潜在问题分析）
3. 解析每个问题的文件路径、行号、当前代码、建议方案

### 第二步：分析代码库

对于每个问题：
1. 读取问题所在文件
2. 分析相关代码上下文
3. 理解根本原因
4. 评估修复影响范围

### 第三步：生成修复方案

为每个问题生成：

1. **问题概述** — 文件路径、行号、严重程度、影响范围
2. **当前代码** — 完整的问题代码片段
3. **修复方案** — 问题分析、解决思路、实施步骤
4. **代码变更** — 完整可运行的修复代码（无省略）
5. **涉及文件** — 修改/新增/删除文件列表
6. **权衡考虑** — 3种方案对比（表格形式）
7. **风险分析** — 风险列表、概率影响、缓解措施
8. **测试建议** — 测试策略、完整测试代码
9. **验收标准** — SMART 原则的可测量条件

### 第四步：输出文档

输出到 `specs/<feature-name>/plan.md`：

```markdown
# 项目名称 - 综合改进方案

生成时间: YYYY-MM-DD
源文档: research.md

---

## 一、问题修复方案

### 🔴 安全问题 (P0/P1)

#### 问题 1.1: [标题]
[详细修复方案]

### ⚠️ 质量问题 (P1/P2)
...

### 🏗️ 设计缺陷 (P2)
...

### ⚡ 性能问题 (P2)
...

## 二、测试覆盖改进方案

## 三、技术债务清理方案

## 四、架构和代码质量改进

## 附录
### 执行顺序建议
### 变更摘要
### 验收标准总结
```

---

## 质量要求

### 代码示例
- ✅ 完整可运行，不使用 `...` 省略
- ✅ 包含必要的 import 语句
- ✅ 遵循项目编码规范

### 权衡考虑
- ✅ 至少 3 种可行方案
- ✅ 表格形式展示
- ✅ 明确选择理由（✅/❌/⏳）

### 文件路径
- ✅ 使用项目相对路径
- ✅ 包含行号信息
- ✅ 明确修改/新增/删除

---

## 注意事项

1. **分析代码库**: 必须实际读取相关文件，分析代码上下文
2. **完整代码**: 代码变更必须是完整的、可直接运行的
3. **权衡分析**: 每个问题至少提供 3 种可行方案
4. **遵循规范**: 遵循 CLAUDE.md 编码规范
5. **产物位置**: 输出到 `specs/<feature-name>/plan.md`

---

## 相关文件

- `specs/<feature-name>/spec.md` — 需求规格（SDD 模式输入）
- `specs/<feature-name>/research.md` — 技术调研（输入）
- `specs/<feature-name>/plan.md` — 实现方案（输出）
- `CLAUDE.md` — 项目编码规范和治理原则（参考）
