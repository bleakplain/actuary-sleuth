# Tasks: Chunk 语义增强

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)
- 包含精确文件路径

---

## Phase 1: 数据模型增强

- [x] T001 [US1] PremiumTable 增加 header 字段 in scripts/lib/doc_parser/models.py
- [x] T002 [US1] 新增 MarkdownTable 数据结构 in scripts/lib/doc_parser/models.py

**Checkpoint**: 数据模型支持表头存储 ✅

---

## Phase 2: User Story 1 - Markdown 表格完整性保护 (P1)

- [x] T003 [US1] 创建表格解析工具模块 in scripts/lib/doc_parser/kb/table_utils.py
- [x] T004 [US1] 修改 MdParser 增加表格识别 in scripts/lib/doc_parser/kb/md_parser.py
- [x] T005 [US1] 修改 _recursive_chunk 支持表格保护 in scripts/lib/doc_parser/kb/md_parser.py
- [x] T006 [P] [US1] 编写表格解析测试 in scripts/tests/lib/doc_parser/kb/test_table_utils.py

**Checkpoint**: User Story 1 可独立测试 ✅

---

## Phase 3: User Story 2 - PDF 跨页表格合并 (P1)

- [x] T007 [US2] 创建跨页表格合并器 in scripts/lib/doc_parser/pd/table_merger.py
- [x] T008 [US2] 修改 PdfParser 使用合并器 in scripts/lib/doc_parser/pd/pdf_parser.py
- [x] T009 [P] [US2] 编写跨页合并测试 in scripts/tests/lib/doc_parser/pd/test_table_merger.py

**Checkpoint**: User Story 2 可独立测试 ✅

---

## Phase 4: User Story 3 - 超大表格表头补充 (P2)

- [x] T010 [US3] MdParser 增加超大表格分块逻辑 in scripts/lib/doc_parser/kb/md_parser.py
- [x] T011 [US3] 修改 _recursive_chunk 使用表格分块 in scripts/lib/doc_parser/kb/md_parser.py

**Checkpoint**: User Story 3 可独立测试 ✅

---

## Phase 5: User Story 4 & 5 - 验证与增强 (P2/P3)

- [x] T012 [US4] 增强 _should_merge 检测更多列表模式 in scripts/lib/doc_parser/kb/md_parser.py

**Checkpoint**: 语义感知和层级保留已验证 ✅

---

## Phase 6: 集成测试与验收

- [x] T013 [ALL] 编写集成测试 in scripts/tests/lib/doc_parser/test_chunk_semantic.py
- [x] T014 [ALL] 运行完整测试套件和类型检查

**Checkpoint**: 所有验收标准通过 ✅

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: No dependencies
- Phase 2: Depends on Phase 1
- Phase 3: Depends on Phase 1 (can parallel with Phase 2)
- Phase 4: Depends on Phase 2
- Phase 5: No new dependencies
- Phase 6: Depends on all previous phases

### Within Each Story
- Models before services
- Core implementation before tests
- Phase 2 and Phase 3 can run in parallel after Phase 1
