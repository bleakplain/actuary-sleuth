# Tasks: RAG 记忆增强与 Agent 框架

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1-US6)
- 包含精确文件路径

## Phase 1: 基础设施 ✅

- [x] T001 [P] [FR-006] 创建 `scripts/lib/memory/__init__.py`
- [x] T002 [P] [FR-006] 创建 `scripts/lib/memory/config.py` — MemoryConfig
- [x] T003 [P] [FR-010] 创建 `scripts/lib/memory/embeddings.py` — EmbeddingBridge
- [x] T004 [P] [FR-002] 创建 `scripts/lib/memory/prompts.py` — 提取 prompt
- [x] T005 [FR-005] 修改 `scripts/api/database.py` — 新增表 + conversations 加 user_id + create_conversation 签名
- [x] T006 [P] [FR-010] 创建 `scripts/tests/lib/memory/test_embeddings.py`

**Checkpoint**: 基础设施就绪，数据库迁移安全 ✅

## Phase 2: LangGraph + 记忆检索注入 ✅

- [x] T007 [US-1/US-6] [FR-004] 创建 `scripts/lib/rag_engine/graph.py` — StateGraph + 节点函数
- [x] T008 [P] [FR-005] 修改 `scripts/api/schemas/ask.py` — ChatRequest 新增 user_id
- [x] T009 [US-1] [FR-001] 修改 `scripts/api/routers/ask.py` — chat 端点接入 LangGraph
- [x] T010 [FR-008] 修改 `scripts/api/dependencies.py` — 新增记忆服务 + ask_graph 管理
- [x] T011 [FR-008] [US-5] 修改 `scripts/api/app.py` — 初始化记忆服务 + 注册路由 + 清理任务
- [x] T012 [P] [US-6] 创建 `scripts/tests/lib/memory/test_graph.py`

**Checkpoint**: LangGraph 工作流可运行，记忆检索注入到问答流程 ✅

## Phase 3: MemoryService + 管理 API ✅

- [x] T013 [US-2/US-3/US-5] [FR-002/003/006] 创建 `scripts/lib/memory/service.py` — MemoryService
- [x] T014 [P] [US-4] [FR-007] 创建 `scripts/api/schemas/memory.py` — Pydantic schemas
- [x] T015 [US-4] [FR-007] 创建 `scripts/api/routers/memory.py` — 记忆管理 API
- [x] T016 [P] [US-2/US-3/US-5] 创建 `scripts/tests/lib/memory/test_service.py`

**Checkpoint**: 记忆 CRUD + TTL + 画像 + 管理 API 全部就绪 ✅

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (基础设施): No dependencies
- Phase 2 (LangGraph): Depends on Phase 1 (database tables, config)
- Phase 3 (MemoryService): Depends on Phase 1 (config, prompts, database tables); graph.py 通过 Any 类型间接引用，可与 Phase 2 并行

### Within Each Phase
- Phase 1: T001-T004 可并行，T005 独立，T006 可并行
- Phase 2: T007 无文件依赖，T008 可并行，T009 依赖 T007+T008+T010，T010 依赖 T007，T011 依赖 T010，T012 依赖 T007
- Phase 3: T13 独立，T14 可并行，T15 依赖 T14，T16 依赖 T13
