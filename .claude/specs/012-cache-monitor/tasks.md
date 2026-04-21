# Tasks: Cache Monitor Dashboard

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3, US4)
- 包含精确文件路径

---

## Phase 1: Backend - CacheManager 扩展 ✅

- [x] T001 [US2] 增加 evictions 计数器 in scripts/lib/common/cache.py
- [x] T002 [US2] 增加 L2 条目统计 in scripts/lib/common/cache.py
- [x] T003 [US2] 增加 get_entries() 条目查询 in scripts/lib/common/cache.py
- [x] T004 [US4] 增加 cleanup_expired() 清理过期 in scripts/lib/common/cache.py
- [x] T005 [US2] 扩展单元测试 in scripts/tests/lib/common/test_cache.py

**Checkpoint**: ✅ CacheManager 扩展完成，测试通过

---

## Phase 2: Backend - 历史指标存储 ✅

- [x] T006 [US3] 增加 cache_metrics_history 表 in scripts/api/database.py
- [x] T007 [US3] 实现 CacheMetricsCollector 采集器 in scripts/lib/common/cache_metrics.py (新增)
- [x] T008 [US3] 在 API 启动时初始化采集器 in scripts/api/app.py

**Checkpoint**: ✅ 历史指标存储完成

---

## Phase 3: Backend - API 端点 ✅

- [x] T009 [P] [US1,US3,US4] 增加 Schema 定义 in scripts/api/schemas/observability.py
- [x] T010 [US1,US3,US4] 增加缓存 API 端点 in scripts/api/routers/observability.py
- [x] T011 [US1,US3,US4] 新增 API 测试 in scripts/tests/api/test_cache_api.py (新增)

**Checkpoint**: ✅ API 端点完成，测试通过

---

## Phase 4: Frontend - 类型和 API ✅

- [x] T012 [P] [US1,US2] 增加类型定义 in scripts/web/src/types/index.ts
- [x] T013 [US1,US3,US4] 增加 API 函数 in scripts/web/src/api/observability.ts

**Checkpoint**: ✅ 前端类型和 API 完成

---

## Phase 5: Frontend - 状态管理 ✅

- [x] T014 [US1,US3,US4] 创建 cacheStore in scripts/web/src/stores/cacheStore.ts (新增)

**Checkpoint**: ✅ 状态管理完成

---

## Phase 6: Frontend - UI 组件 ✅

- [x] T015 [P] [US1,US2] 创建 CacheMetrics 组件 in scripts/web/src/components/observability/CacheMetrics.tsx (新增)
- [x] T016 [P] [US3] 创建 CacheTrendChart 组件 in scripts/web/src/components/observability/CacheTrendChart.tsx (新增)
- [x] T017 [P] [US4] 创建 CacheEntryList 组件 in scripts/web/src/components/observability/CacheEntryList.tsx (新增)
- [x] T018 [US1,US2,US3,US4] 创建 CacheView 主视图 in scripts/web/src/components/observability/CacheView.tsx (新增)
- [x] T019 [US1,US2,US3,US4] 修改 ObservabilityPage 为 Tab 结构 in scripts/web/src/pages/ObservabilityPage.tsx

**Checkpoint**: ✅ UI 组件完成，TypeScript 编译通过

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: No dependencies
- Phase 2: No dependencies (可并行 with Phase 1)
- Phase 3: Depends on Phase 1, Phase 2
- Phase 4: No dependencies (可并行 with Phase 1-3)
- Phase 5: Depends on Phase 4
- Phase 6: Depends on Phase 4, Phase 5

### Within Each Story
- Models before services
- Services before endpoints
- Core implementation before tests
