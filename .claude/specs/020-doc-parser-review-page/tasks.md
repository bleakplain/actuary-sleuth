# Tasks: 产品文档解析结果审核页面

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3, US4)

---

## Phase 1: 数据存储与 API (P1) ✅

- [x] T001 [FR-001] 定义 ParsedDocument 数据模型 in `scripts/lib/common/models.py`
- [x] T002 [FR-001] 添加 parsed_documents 表和操作函数 in `scripts/api/database.py`
- [x] T003 [FR-001] 创建产品文档 API 路由 in `scripts/api/routers/product_doc.py`
- [x] T004 [FR-004] 注册路由 in `scripts/api/main.py`
- [x] T005 [FR-001] 编写单元测试 in `scripts/tests/api/test_product_doc.py`

**Checkpoint**: Phase 1 可独立测试（API 可调用） ✅

---

## Phase 2: 前端审核页面 (P1) ✅

- [x] T006 [P] [US1] 创建 API 封装 in `scripts/web/src/api/productDoc.ts`
- [x] T007 [US1] 创建审核页面组件 in `scripts/web/src/pages/ProductDocPage.tsx`
- [x] T008 [US1] 添加路由 in `scripts/web/src/App.tsx`
- [x] T009 [US1] 添加导航入口 in `scripts/web/src/components/AppLayout.tsx`

**Checkpoint**: Phase 2 可独立测试（前端页面可访问） ✅

---

## Phase 3: 审核状态管理 (P2) ✅

- [x] T010 [US3] 添加审核 Drawer in `scripts/web/src/pages/ProductDocPage.tsx`

**Checkpoint**: Phase 3 可独立测试（审核功能可用） ✅

---

## Phase 4: 原文对照定位增强 (P2) ✅

- [x] T011 [P] [US2] 扩展 Clause 数据模型添加位置字段 in `scripts/lib/doc_parser/models.py`
- [x] T012 [US2] 扩展 PremiumTable 数据模型添加位置字段 in `scripts/lib/doc_parser/models.py`
- [x] T013 [US2] 修改 PDF 解析器提取位置信息 in `scripts/lib/doc_parser/pd/pdf_parser.py`

**Checkpoint**: Phase 4 可独立测试（位置信息可用） ✅

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: 无依赖
- Phase 2: 依赖 Phase 1（需要后端 API）
- Phase 3: 依赖 Phase 2（需要前端页面）
- Phase 4: 无依赖，可与 Phase 1-3 并行

### Within Each Phase
- Phase 1: T001 → T002 → T003 → T004 → T005
- Phase 2: T006 可并行，T007 → T008 → T009
- Phase 3: T010 依赖 Phase 2 完成
- Phase 4: T011, T012 可并行 → T013
