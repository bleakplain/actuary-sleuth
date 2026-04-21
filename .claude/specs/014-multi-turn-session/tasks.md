# Tasks: 多轮会话架构增强

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3, US5)

---

## Phase 1: 基础设施 (1天)

- [ ] T001 数据库迁移：sessions.context_json
- [ ] T002 扩展 AskState：新增 7 个字段 + merge_session_context Reducer
- [ ] T003 扩展 ChatRequest：新增 skip_clarify 参数
- [ ] T004 [P] 新增数据库访问函数 get_session_context / save_session_context
- [ ] T005 [P] 测试：Reducer 合并逻辑

**Checkpoint**: AskState 可正确初始化，Reducer 合并通过测试

---

## Phase 2: 中间件基础设施 (1.5天)

- [ ] T006 创建中间件目录 lib/common/middleware/__init__.py
- [ ] T007 [P] 实现 Middleware Protocol in base.py
- [ ] T008 [P] 实现共享常量 in constants.py
- [ ] T009 实现 SessionContextMiddleware
- [ ] T010 实现 ClarificationMiddleware
- [ ] T011 [P] 实现 LoopDetectionMiddleware
- [ ] T012 [P] 实现 IterationLimitMiddleware
- [ ] T013 测试：各中间件单元测试

**Checkpoint**: 所有中间件可独立测试通过

---

## Phase 3: LangGraph 工作流重构 (2天)

- [ ] T014 重构 create_ask_graph()：新增节点（load_context, clarify_check, parallel_retrieval_entry, save_context）
- [ ] T015 实现 rag_search 查询增强：用 session_context.product_type 前缀
- [ ] T016 实现条件路由 route_by_action
- [ ] T017 扩展 SSE 事件：clarify 事件支持
- [ ] T018 新增 API 端点：GET/PUT /api/sessions/{id}/context
- [ ] T019 测试：工作流集成测试

**Checkpoint**: 澄清流程、上下文继承可端到端测试

---

## Phase 4: 增强功能 (0.5天)

- [ ] T020 集成 LoopDetectionMiddleware 到 generate 节点
- [ ] T021 测试：循环检测集成测试

**Checkpoint**: 循环检测正常触发

---

## Dependencies & Execution Order

### Phase Dependencies
```
Phase 1 (基础设施)
    │
    ▼
Phase 2 (中间件) ──► Phase 3 (工作流)
                           │
                           ▼
                      Phase 4 (增强)
```

### Within Each Phase
- T001 → T002 → T003（串行，同文件）
- T004, T005 可并行（不同文件）
- T006 → T007, T008（目录创建后可并行）
- T009, T010, T011, T012 可并行（不同文件）
- T014 → T015 → T016 → T017 → T018（串行，有依赖）

---

## 总工作量: 5天
