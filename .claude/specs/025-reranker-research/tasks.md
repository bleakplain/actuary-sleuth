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

## Phase 2: 基础集成 ✅ 已完成

- [x] T006 [P] 扩展 RerankConfig in scripts/lib/rag_engine/config.py
- [x] T007 创建 BgeReranker 类 in scripts/lib/rag_engine/bge_reranker.py
- [x] T008 修改工厂方法 in scripts/lib/rag_engine/rag_engine.py
- [x] T009 [P] 更新导出 in scripts/lib/rag_engine/__init__.py
- [x] T010 编写测试 in scripts/tests/lib/rag_engine/test_bge_reranker.py

**Checkpoint**: 11 tests passed with real model on MPS ✅

---

## Phase 3: INT8 量化支持 ✅ 已完成

- [x] T011 添加依赖 in scripts/requirements.txt
- [x] T012 创建 QuantizedBgeReranker 类 in scripts/lib/rag_engine/bge_reranker.py
- [x] T013 更新工厂方法 in scripts/lib/rag_engine/rag_engine.py

**Checkpoint**: QuantizedBgeReranker with ONNX provider selection ✅

---

## Phase 4: 配置调优 ✅ 已完成

- [x] T014 [P] 调整默认阈值 in scripts/lib/rag_engine/config.py
- [x] T015 [P] 提取 _apply_scores 到 BaseReranker in scripts/lib/rag_engine/reranker_base.py

**Checkpoint**: Code review (/simplify) fixes applied ✅

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (调研) ✅ 完成
    ↓
Phase 2 (基础集成) ✅ 完成
    ↓
Phase 3 (量化) ✅ 完成
    ↓
Phase 4 (配置) ✅ 完成
```

---

## 验收标准总结

| User Story | 验收标准 | 状态 |
|-----------|---------|------|
| US-1 代码架构分析 | research.md 包含类结构、接口定义、调用流程 | ✅ |
| US-2 可行性评估 | research.md 包含模型特性、接口兼容性、部署要求 | ✅ |
| US-3 工程优化分析 | research.md 包含批量推理、INT8 量化、阈值过滤方案 | ✅ |
| US-4 迁移建议 | research.md 包含实现路径和风险提示 | ✅ |
| Phase 2 基础集成 | BgeReranker 可正常精排，11 测试通过 | ✅ |
| Phase 3 量化支持 | QuantizedBgeReranker + ONNX provider 选择 | ✅ |
| Phase 4 配置调优 | _apply_scores 提取，model_name="" bug 修复 | ✅ |

---

## 变更摘要

| 类型 | 文件 | 说明 |
|------|------|------|
| 删除 | `scripts/lib/rag_engine/cross_encoder_reranker.py` | 无效代码清理 |
| 新增 | `scripts/lib/rag_engine/bge_reranker.py` | BgeReranker + QuantizedBgeReranker |
| 修改 | `scripts/lib/rag_engine/reranker_base.py` | 添加 _apply_scores 共享方法 |
| 修改 | `scripts/lib/rag_engine/config.py` | 添加 bge 配置项，移除 hf 类型 |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` | 添加 bge 工厂分支，移除 hf 分支 |
| 修改 | `scripts/lib/rag_engine/__init__.py` | 添加 BgeReranker/QuantizedBgeReranker 导出 |
| 新增 | `scripts/tests/lib/rag_engine/test_bge_reranker.py` | 11 项集成测试 |
| 新增 | `.claude/specs/025-reranker-research/spec.md` | 需求规格 |
| 新增 | `.claude/specs/025-reranker-research/research.md` | 技术调研报告 |
| 新增 | `.claude/specs/025-reranker-research/plan.md` | 实现方案 |
