# Tasks: Reranker Research

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)
- 包含精确文件路径

---

## Phase 1: 调研报告产出 ✅ 已完成

- [x] T001 [US1] 代码架构分析 → research.md
- [x] T002 [US2] bge-reranker-large 可行性评估 → research.md
- [x] T003 [US3] 工程优化方案分析 → research.md
- [x] T004 [US4] 迁移建议 → research.md
- [x] T005 生成 plan.md

**Checkpoint**: 所有 User Stories 验收通过 ✅

---

## Phase 2-4: BgeReranker 实现 (可选/未执行)

以下任务为后续实现参考，不在本次调研范围内：

### Phase 2: 基础集成

- [ ] T006 [P] 扩展 RerankConfig in scripts/lib/rag_engine/config.py
- [ ] T007 创建 BgeReranker 类 in scripts/lib/rag_engine/bge_reranker.py
- [ ] T008 修改工厂方法 in scripts/lib/rag_engine/rag_engine.py
- [ ] T009 [P] 更新导出 in scripts/lib/rag_engine/__init__.py
- [ ] T010 编写测试 in scripts/tests/lib/rag_engine/test_bge_reranker.py

### Phase 3: INT8 量化支持

- [ ] T011 添加依赖 in scripts/requirements.txt
- [ ] T012 创建 QuantizedBgeReranker 类 in scripts/lib/rag_engine/bge_reranker.py
- [ ] T013 更新工厂方法 in scripts/lib/rag_engine/rag_engine.py

### Phase 4: 配置调优

- [ ] T014 [P] 调整默认阈值 in scripts/lib/rag_engine/config.py
- [ ] T015 [P] 添加环境变量支持 in scripts/lib/config.py

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (调研) ✅ 完成
    ↓
Phase 2 (基础集成) — 可选，独立任务
    ↓
Phase 3 (量化) — 依赖 Phase 2
    ↓
Phase 4 (配置) — 可与 Phase 2 并行
```

### Within Phase 2

```
T006 (config) → T008 (factory)
T007 (class) → T008 (factory)
T008 (factory) → T010 (test)
T009 (export) — 可并行
```

---

## 验收标准总结

| User Story | 验收标准 | 状态 |
|-----------|---------|------|
| US-1 代码架构分析 | research.md 包含类结构、接口定义、调用流程 | ✅ |
| US-2 可行性评估 | research.md 包含模型特性、接口兼容性、部署要求 | ✅ |
| US-3 工程优化分析 | research.md 包含批量推理、INT8 量化、阈值过滤方案 | ✅ |
| US-4 迁移建议 | research.md 包含实现路径和风险提示 | ✅ |

---

## 变更摘要

| 类型 | 文件 | 说明 |
|------|------|------|
| 删除 | `scripts/lib/rag_engine/cross_encoder_reranker.py` | 无效代码清理 |
| 修改 | `scripts/lib/rag_engine/config.py` | 移除 "hf" 类型 |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` | 移除 "hf" 分支 |
| 修改 | `scripts/lib/rag_engine/__init__.py` | 移除导出 |
| 新增 | `.claude/specs/025-reranker-research/spec.md` | 需求规格 |
| 新增 | `.claude/specs/025-reranker-research/research.md` | 技术调研报告 |
| 新增 | `.claude/specs/025-reranker-research/plan.md` | 实现方案 |
| 新增 | `.claude/specs/025-reranker-research/tasks.md` | 本文件 |
