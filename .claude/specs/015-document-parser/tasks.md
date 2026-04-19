# Tasks: 统一文档解析器

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)
- 包含精确文件路径

---

## Phase 1: Infrastructure ✅

- [x] T001 [P] 创建数据模型 in scripts/lib/doc_parser/models.py
- [x] T002 [P] 创建顶层导出 in scripts/lib/doc_parser/__init__.py
- [x] T003 创建错误处理测试 in scripts/tests/lib/doc_parser/test_error_handling.py

**Checkpoint**: ✅ 数据模型和异常可独立导入使用

---

## Phase 2: User Story 1 - 知识库文档解析 (P1) ✅

- [x] T004 创建 kb 包导出 in scripts/lib/doc_parser/kb/__init__.py
- [x] T005 创建 kb 编排器 in scripts/lib/doc_parser/kb/parser.py
- [x] T006 实现 Markdown 解析器 in scripts/lib/doc_parser/kb/md_parser.py
- [x] T007 [P] 创建测试 fixtures in scripts/tests/lib/doc_parser/conftest.py
- [x] T008 创建 Markdown 解析测试 in scripts/tests/lib/doc_parser/kb/test_md_parser.py

**Checkpoint**: ✅ User Story 1 可独立测试，parse_knowledge_base() 可用

---

## Phase 3: User Story 2 & 3 - 产品文档解析 (P1) ✅

- [x] T009 创建 pd 包导出 in scripts/lib/doc_parser/pd/__init__.py
- [x] T010 创建 pd 编排器 in scripts/lib/doc_parser/pd/parser.py
- [x] T011 [P] 创建内容类型检测器 in scripts/lib/doc_parser/pd/section_detector.py
- [x] T012 [P] 创建关键词配置 in scripts/lib/doc_parser/pd/data/keywords.json
- [x] T013 实现 Word 解析器 in scripts/lib/doc_parser/pd/docx_parser.py
- [x] T014 实现 PDF 解析器 in scripts/lib/doc_parser/pd/pdf_parser.py
- [x] T015 创建 Word 解析测试 in scripts/tests/lib/doc_parser/pd/test_docx_parser.py
- [x] T016 创建 PDF 解析测试 in scripts/tests/lib/doc_parser/pd/test_pdf_parser.py
- [x] T017 创建检测器测试 in scripts/tests/lib/doc_parser/pd/test_section_detector.py

**Checkpoint**: ✅ User Story 2 & 3 可独立测试，parse_product_document() 可用

---

## Phase 4: User Story 4 - 飞书代码删除 (P2) ✅

- [x] T018 删除 document_fetcher.py 及相关测试
- [x] T019 清理所有 document_fetcher 引用

**Checkpoint**: ✅ 废弃代码已清理，无残留引用

---

## Phase 5: Integration ✅

- [x] T020 修改 KnowledgeBuilder 使用 MdParser in scripts/lib/rag_engine/builder.py
- [x] T021 删除旧 chunker.py 及更新导出
- [x] T022 运行完整测试验证向后兼容

**Checkpoint**: ✅ 知识库构建流程正常，输出与原实现一致

---

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (Infrastructure): No dependencies
- Phase 2 (US1): Depends on Phase 1
- Phase 3 (US2&3): Depends on Phase 1, can parallel with Phase 2
- Phase 4 (US4): No dependencies, can parallel with Phase 1-3
- Phase 5 (Integration): Depends on Phase 2

### Within Each Phase
- Models before parsers
- Parsers before tests
- Core implementation before integration
