# Tasks: PDF Parser Fix

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, US3)
- 包含精确文件路径

## Phase 1: Setup

- [x] T001 创建 keywords.json 配置文件 in scripts/lib/doc_parser/pd/data/keywords.json
- [x] T002 [P] [Setup] 增强 SectionDetector 条款头识别 in scripts/lib/doc_parser/pd/section_detector.py

## Phase 2: User Story 1 - 正确解析 PDF 条款结构 (P1)

- [x] T003 [US1] 重构 PdfParser.parse() 方法 in scripts/lib/doc_parser/pd/pdf_parser.py
- [x] T004 [US1] 新增条款提取方法 _extract_clauses_from_text() in scripts/lib/doc_parser/pd/pdf_parser.py (depends on T003)
- [x] T005 [US1] 新增条款构建方法 _build_clause() in scripts/lib/doc_parser/pd/pdf_parser.py (depends on T004)
- [x] T006 [US1] 重构费率表提取方法 _extract_premium_tables() in scripts/lib/doc_parser/pd/pdf_parser.py (depends on T003)
- [x] T007 [US1] 重构章节提取方法 _extract_sections_from_pages() in scripts/lib/doc_parser/pd/pdf_parser.py (depends on T003)

**Checkpoint**: User Story 1 可独立测试 ✅

## Phase 3: User Story 2 - 参照 DOCX 解析设计重构 (P1)

- [x] T008 [US2] 验证接口兼容性（无需代码修改）

## Phase 4: User Story 3 - 真实文档验证测试 (P2)

- [x] T009 [US3] 添加真实文档测试 in scripts/tests/lib/doc_parser/pd/test_pdf_parser.py

## Phase 5: Enhancement - 扫描版 PDF 支持 (P2)

- [x] T010 [P] [OCR] 创建 OCR 处理器 in scripts/lib/doc_parser/pd/ocr_handler.py
- [x] T011 [OCR] 集成 OCR 处理器到 PdfParser in scripts/lib/doc_parser/pd/pdf_parser.py (depends on T010)

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (Setup): No dependencies
- Phase 2 (US1): Depends on Phase 1
- Phase 3 (US2): Depends on Phase 2
- Phase 4 (US3): Depends on Phase 2
- Phase 5 (OCR): Depends on Phase 1, can parallel with US1 if independent

### Within Each Story
- T001, T002 can run in parallel
- T003 must complete before T004, T005, T006, T007
- T004, T005 are sequential (build_clause depends on extract_clauses)
- T006, T007 can run in parallel after T003
