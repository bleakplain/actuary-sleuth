# Tasks: 保险产品合规检查

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US2, US5)
- 包含精确文件路径

---

## Phase 1: 条款级检查结果改造 (US2) ✅

- [x] T001 [US2] 更新 Schema 添加 clause_number 字段 in `scripts/api/schemas/compliance.py`
- [x] T002 [US2] 修改 Prompt 要求按条款编号输出 in `scripts/api/routers/compliance.py`
- [x] T003 [US2] 更新 check_document 使用新 Prompt in `scripts/api/routers/compliance.py`
- [x] T004 [US2] 编写条款级输出测试 in `scripts/tests/compliance/test_clause_level.py`

**Checkpoint**: ✅ US2 Phase 1 - 检查结果包含条款编号

---

## Phase 2: 遗漏检测 (US2) ✅

- [x] T005 [US2] 更新请求 Schema 添加 parse_id in `scripts/api/schemas/compliance.py`
- [x] T006 [US2] 实现 _detect_missing_clauses 函数 in `scripts/api/routers/compliance.py`
- [x] T007 [US2] 在 check_document 中集成遗漏检测 in `scripts/api/routers/compliance.py`
- [x] T008 [US2] 前端传入 parse_id 参数 in `scripts/web/src/pages/CompliancePage.tsx`
- [x] T009 [US2] 编写遗漏检测测试 in `scripts/tests/compliance/test_clause_level.py`

**Checkpoint**: ✅ US2 Phase 2 - 遗漏检测功能可用

---

## Phase 3: 前端条款级树状展示 (US2) ✅

- [x] T010 [US2] 添加条款级分组和排序逻辑 in `scripts/web/src/pages/CompliancePage.tsx`
- [x] T011 [US2] 使用 Collapse 树状展示检查结果 in `scripts/web/src/pages/CompliancePage.tsx`
- [x] T012 [US2] 显示遗漏项警告 in `scripts/web/src/pages/CompliancePage.tsx`
- [x] T013 [US2] 更新前端类型定义 in `scripts/web/src/types/index.ts`
- [x] T014 [US2] 更新 API 调用支持 parse_id in `scripts/web/src/api/compliance.ts`

**Checkpoint**: ✅ US2 Phase 3 - 前端条款级展示可用

---

## Phase 4: 法规无结果处理 (US2) ✅

- [x] T015 [US2] 修改 _run_compliance_check 添加无结果处理 in `scripts/api/routers/compliance.py`
- [x] T016 [US2] 前端显示无结果警告 in `scripts/web/src/pages/CompliancePage.tsx`

**Checkpoint**: ✅ US2 Phase 4 - 无结果处理可用

---

## Phase 5: 测试验证流程 (US5) ✅

- [x] T017 [US5] 创建测试验证脚本 in `scripts/tests/compliance/validate_flow.py`
- [x] T018 [US5] 创建测试数据模板 in `scripts/tests/fixtures/compliance/sample_1.json`
- [x] T019 [US5] 编写条款级对比测试 in `scripts/tests/compliance/test_validation.py`

**Checkpoint**: ✅ US5 - 测试验证流程可用

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: 无依赖
- Phase 2: 依赖 Phase 1 (需要 clause_number 字段)
- Phase 3: 依赖 Phase 2 (需要遗漏检测)
- Phase 4: 可与 Phase 2-3 并行
- Phase 5: 依赖所有前面 Phase

### Within Each Phase
- Schema 先于业务逻辑
- 业务逻辑先于测试
- 前端类型定义先于组件修改

---

## Summary

✅ All phases completed successfully.
- 19 tasks completed
- 8 tests passing
- Code reviewed and optimized
