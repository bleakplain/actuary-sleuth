# Tasks: 记忆系统 P0 改进

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: 关键词触发器 (US1) ✅

- [x] T001 [US1] 创建 TriggerResult 数据类和 should_retrieve_memory() 函数 in scripts/lib/memory/triggers.py
- [x] T002 [US1] 修改 retrieve_memory 节点增加条件触发 in scripts/lib/rag_engine/graph.py
- [x] T003 [US1] 编写关键词触发测试 in scripts/tests/lib/memory/test_triggers.py

**Checkpoint**: ✅ 关键词触发可独立测试（6 tests passed）

---

## Phase 2: 记忆去重 (US2) ✅

- [x] T004 [P] [US2] 扩展 MemoryConfig 添加 dedup_similarity_threshold in scripts/lib/memory/config.py
- [x] T005 [US2] 修改 MemoryService.add() 增加去重检查 in scripts/lib/memory/service.py
- [x] T006 [US2] 编写去重测试 in scripts/tests/lib/memory/test_service.py

**Checkpoint**: ✅ 记忆去重可独立测试（24 tests passed）

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (触发器): 无依赖 ✅
- Phase 2 (去重): 无依赖，可与 Phase 1 并行 ✅

### Within Each Story
- 核心实现 before 测试 ✅
