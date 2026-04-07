# Tasks: RAG 检索质量改进 — GGUF Reranker 默认化 + 阈值过滤

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

## Phase 1: 配置修改 — 默认 Reranker + 新增字段

- [x] T001 [US1] 修改 reranker_type 默认值 "llm" → "gguf" in scripts/lib/rag_engine/config.py
- [x] T002 [US1] 新增 rerank_min_score 字段 in scripts/lib/rag_engine/config.py
- [x] T003 [US1] 新增 rerank_min_score __post_init__ 验证 in scripts/lib/rag_engine/config.py

**Checkpoint**: ✅ User Story 1 配置变更完成

## Phase 2: 阈值过滤逻辑 — Rerank 后过滤

- [x] T004 [US2][US3] 在 _hybrid_search() Rerank 后新增阈值过滤 in scripts/lib/rag_engine/rag_engine.py

**Checkpoint**: ✅ User Story 2+3 过滤逻辑完成

## Phase 3: 测试

- [x] T005 [US1][US2][US3] 新增配置验证和阈值过滤测试 in scripts/tests/lib/rag_engine/test_hybrid_search_config.py

**Checkpoint**: ✅ 13/13 测试全部通过

## Phase 4: 评估方案设计

- [x] T006 [US4] 评估方案已在 research.md 完成

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (配置): ✅ No dependencies
- Phase 2 (过滤逻辑): ✅ Depends on Phase 1
- Phase 3 (测试): ✅ Depends on Phase 1 + Phase 2
- Phase 4 (评估方案): ✅ Independent
