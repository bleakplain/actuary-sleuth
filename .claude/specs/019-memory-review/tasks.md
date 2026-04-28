# Tasks: 记忆系统问题修复

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3, US4)
- 包含精确文件路径

---

## Phase 1: Critical 问题修复 (US1)

- [x] T001 [US1] 新增 `_escape_value` 函数 in `lib/memory/vector_store.py`
- [x] T002 [US1] 修改 `_build_where` 方法 in `lib/memory/vector_store.py`
- [x] T003 [US1] 修改 `_to_row` 方法避免突变 in `lib/memory/vector_store.py`
- [x] T004 [US1] 新增 `_restore_metadata` 方法 in `lib/memory/service.py`
- [x] T005 [US1] 修改 `delete` 方法 in `lib/memory/service.py`
- [x] T006 [US1] 修改 `add` 方法 in `lib/memory/service.py`
- [x] T007 [US1] 添加 `_dedup_threshold` 属性 in `lib/memory/service.py`
- [x] T008 [US1] 新建测试文件 `tests/lib/memory/test_vector_store.py`
- [x] T009 [US1] 新增测试用例 in `tests/lib/memory/test_service.py`

**Checkpoint**: ✅ Phase 1 完成，pytest 44 passed

---

## Phase 2: Major 问题修复 (US2, US3)

- [x] T010 [US2] 新建常量文件 `lib/memory/constants.py`
- [x] T011 [US2] 修改 `middleware.py` 引用新常量
- [x] T012 [US2] 修改 `triggers.py` 引用新常量
- [x] T013 [US2] 更新测试 in `tests/lib/memory/test_triggers.py`
- [x] T014 [US3] 配置化阈值 in `lib/memory/service.py`
- [x] T015 [US3] 添加画像更新统计指标 in `lib/memory/service.py`

**Checkpoint**: ✅ Phase 2 完成，pytest 52 passed

---

## Phase 3: Minor 问题修复 (US4)

- [x] T016 [US4] 修改清理任务启动逻辑 in `scripts/api/app.py`
- [x] T017 [US4] 添加数据库迁移脚本 in `scripts/api/database.py`
- [x] T018 [US4] 更新 `get_user_profile` 方法 in `lib/memory/service.py`

**Checkpoint**: ✅ Phase 3 完成，pytest 52 passed

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: 无依赖
- Phase 2: 依赖 Phase 1
- Phase 3: 依赖 Phase 2

### Within Each Phase
- T001-T003: 可并行（同一文件但不同函数）
- T004-T007: 顺序执行（service.py 累积修改）
- T008-T009: 依赖 T001-T007 完成
- T010-T013: 可并行
- T014-T015: 可并行
- T016-T018: 顺序执行
