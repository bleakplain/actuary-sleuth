# Tasks: 合规审核模块系统化 Review

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)
- 包含精确文件路径

## Phase 1: 数据正确性修复 (P0)

### Step 1.1: 移除文档和法规的不必要截断

- [ ] T001 [US1,US2] 移除 `scripts/api/routers/compliance.py:42-44` 中的文档和法规截断
- [ ] T002 [US1,US2] 添加超大文档保护函数 `_prepare_document_content` in `scripts/api/routers/compliance.py`

### Step 1.2: 负面清单批量检查

- [ ] T003 [US3] 重写 `check_negative_list` 返回 `Tuple[List, bool]` in `scripts/lib/compliance/checker.py`
- [ ] T004 [US3] 添加 `_parse_violation_response` 批量解析函数 in `scripts/lib/compliance/checker.py`
- [ ] T005 [US3] 删除废弃的 `_check_violation` 函数 in `scripts/lib/compliance/checker.py`

### Step 1.3: 对齐 ProductCategory 枚举值

- [ ] T006 [US4] 修改 `ProductCategory` 枚举值为简称 in `scripts/lib/common/product_types.py:12-23`

### Step 1.4: 更新路由层消费新签名

- [ ] T007 [US1] 更新 `check_negative_list` 调用适配 `(items, checked)` 返回值 in `scripts/api/routers/compliance.py:53-65`

### Step 1.5: 更新测试适配新签名

- [ ] T008 [US6] 更新 `test_negative_list.py` 适配新签名 in `scripts/tests/compliance/test_negative_list.py`

### Step 1.6: 标注双定义

- [ ] T009 [US4] 添加注释标注 `ProductCategory` 双定义关系 in `scripts/lib/common/models.py:76`

**Checkpoint**: Phase 1 完成后运行 `pytest scripts/tests/compliance/`

## Phase 2: 测试覆盖补齐 (P1)

### Step 2.1: 重写 test_clause_level.py

- [ ] T010 [US6] 重写 `test_clause_level.py` 测试 `run_compliance_check` JSON 解析 in `scripts/tests/compliance/test_clause_level.py`

### Step 2.2: 新增 test_checker.py

- [ ] T011 [US6] 新增 `test_checker.py` 覆盖 `identify_category`, `build_enhanced_context` in `scripts/tests/compliance/test_checker.py`

**Checkpoint**: Phase 2 完成后运行 `pytest scripts/tests/compliance/`

## Phase 3: 代码质量改进 (P2)

### Step 3.1: identify_category 返回 NamedTuple

- [ ] T012 [US4] 定义 `CategoryResult` NamedTuple 并修改 `identify_category` 返回类型 in `scripts/lib/compliance/checker.py:158`

### Step 3.2: 简化 JSON fallback

- [ ] T013 [US3] 移除层级 5 regex 提取，改为返回带 error 标记的空结果 in `scripts/lib/compliance/checker.py:297-305`

**Checkpoint**: Phase 3 完成后运行 `mypy scripts/lib/` 和 `pytest scripts/tests/`

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (Setup): No dependencies - 核心修复
- Phase 2 (测试): Depends on Phase 1
- Phase 3 (质量): Depends on Phase 2

### Within Phase 1
- T001, T002: 可并行（同文件不同函数）
- T003, T004, T005: 顺序执行（T003 依赖 T004，T005 最后删除）
- T006: 独立
- T007: 依赖 T003
- T008: 依赖 T003, T007
- T009: 独立

### Critical Path
```
T001+T002 → T007 → T008
T003 → T004 → T005 → T007 → T008
T006 (独立)
T009 (独立)
```
