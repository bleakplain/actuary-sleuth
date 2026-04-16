# Tasks: 评测数据集人工审核与维护

**Input**: plan.md
**Prerequisites**: plan.md ✅

## Format: `[ID] [P?] Description`

- **[P]**: 可并行执行（不同文件，无依赖）

## Phase 1: 数据模型与存储层

- [x] T001 扩展 EvalSample 数据模型 in scripts/lib/rag_engine/eval_dataset.py
- [x] T002 SQLite DDL 迁移 in scripts/api/database.py (depends on T001)
- [x] T003 更新 JSON 字段映射和 CRUD 函数 in scripts/api/database.py (depends on T002)
- [x] T004 数据模型测试 in scripts/tests/lib/rag_engine/test_eval_dataset.py (depends on T001)

**Checkpoint**: Phase 1 ✅ — 数据模型向后兼容，DDL 迁移成功，7/7 测试通过

## Phase 2: 后端 API

- [x] T005 扩展 Pydantic Schema in scripts/api/schemas/eval.py (depends on T001)
- [x] T006 [P] 审核状态流转 API in scripts/api/routers/eval.py (depends on T003, T005)
- [x] T007 [P] 审核统计 API in scripts/api/routers/eval.py (depends on T003)
- [x] T008 [P] KB 搜索 API in scripts/api/routers/eval.py (depends on T005)
- [x] T009 [P] list_eval_samples 支持 review_status 过滤 in scripts/api/routers/eval.py + scripts/api/database.py (depends on T003)

**Checkpoint**: Phase 2 ✅ — 后端 API 就绪

## Phase 3: 前端审核工作台

- [x] T010 TypeScript 类型扩展 in scripts/web/src/types/index.ts (depends on T005)
- [x] T011 [P] 前端 API 函数 in scripts/web/src/api/eval.ts (depends on T010)
- [x] T012 EvalPage 新增"审核"Tab in scripts/web/src/pages/EvalPage.tsx (depends on T010, T011)

**Checkpoint**: Phase 3 ✅ — TypeScript 编译通过，审核 Tab 已实现

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (数据层): No dependencies
- Phase 2 (API): Depends on Phase 1
- Phase 3 (前端): Depends on Phase 2

### Within Each Phase
- T001 (数据模型) first — all others depend on it
- T002 → T003 (DDL → CRUD) sequential
- T004 (测试) parallel with T002/T003
- T005 (Schema) parallel with T002/T003
- T006, T007, T008, T009 parallel within Phase 2
- T010, T011 parallel within Phase 3
- T012 depends on T010 + T011
