# Tasks: RAG 性能优化 — 三级缓存 + 全链路异步

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3, US4, US6)

## Phase 1: CacheManager — 三级缓存核心 (P1) ✅

- [x] T001 [P] [US3] 添加 ENABLE_CACHE 配置项 in scripts/lib/config.py
- [x] T002 [US3] 创建 CacheManager 核心类 in scripts/lib/rag_engine/cache.py (depends on T001)
- [x] T003 [P] [US3] 编写 CacheManager 单元测试 in scripts/tests/lib/rag_engine/test_cache.py (depends on T002)
- [x] T004 [US1] 将 CacheManager 集成到 RAGEngine in scripts/lib/rag_engine/rag_engine.py (depends on T002)
- [x] T005 [P] [US1] Embedding 缓存集成 in scripts/lib/rag_engine/llamaindex_adapter.py (depends on T002)

**Checkpoint**: 缓存核心可独立测试，ENABLE_CACHE=false 时行为不变 ✅

## Phase 2: LLM 原生流式 (P1) ✅

- [x] T006 [P] [US2] BaseLLMClient 添加 stream_chat 接口 in scripts/lib/llm/base.py
- [x] T007 [P] [US2] ZhipuClient 实现 SSE 流式 in scripts/lib/llm/zhipu.py (depends on T006)
- [x] T008 [P] [US2] OllamaClient 实现 NDJSON 流式 in scripts/lib/llm/ollama.py (depends on T006)
- [x] T009 [US2] API 层缓存优先+去除伪流式 in scripts/api/routers/ask.py (depends on T004, T007)

**Checkpoint**: 首次查询正常返回，缓存命中快速返回 ✅

## Phase 3: LanceDB 索引优化 (P2) ✅

- [x] T010 [P] [US4] 添加 IVF_HNSW_SQ 索引创建 in scripts/lib/rag_engine/index_manager.py

**Checkpoint**: 索引创建成功，搜索延迟降低 ✅

## Phase 4: 缓存统计与监控 (P3) ✅

- [x] T011 [US6] 添加缓存统计端点 in scripts/api/routers/observability.py (depends on T002)

**Checkpoint**: /api/observability/cache/stats 返回统计数据 ✅

## Phase 5: 清理与集成 (P1) ✅

- [x] T012 [US3] KB 版本切换触发缓存失效 in scripts/lib/rag_engine/kb_manager.py (depends on T002)
- [x] T013 [US3] 删除废弃 llm/cache.py in scripts/lib/llm/cache.py (depends on T012)

**Checkpoint**: KB 版本切换后缓存自动失效 ✅

## Phase 6: 最终验证 ✅

- [x] T014 运行完整类型检查 mypy scripts/lib/
- [x] T015 运行完整测试套件 pytest scripts/tests/

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (缓存核心): No dependencies — 基础设施
- Phase 2 (流式): Depends on T004 (缓存集成)
- Phase 3 (索引): Independent — 可并行
- Phase 4 (监控): Depends on T002 (CacheManager)
- Phase 5 (清理): Depends on T002 (CacheManager)
- Phase 6 (验证): Depends on all above

### Parallel Opportunities
- T001 + T006 可并行（不同模块，无依赖）
- T003 + T005 + T007 + T008 + T010 + T011 可并行（不同文件）
