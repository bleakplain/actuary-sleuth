# Tasks: 评测数据集系统性改进

**Input**: plan.md
**Prerequisites**: plan.md, spec.md

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)

## Phase 1: 修复 Recall 指标 + UNANSWERABLE 类型 + 来源标记 ✅

- [x] T001 [US1] 新增 `_match_source_to_evidence` 辅助函数 in `scripts/lib/rag_engine/evaluator.py`
- [x] T002 [US1] 修改 `evaluate()` 中 recall 计算，使用 matched_docs 去重集合 in `scripts/lib/rag_engine/evaluator.py`
- [x] T003 [US1] 修改 `evaluate_batch()` recall_at_k 均值跳过 evidence_docs 为空样本 in `scripts/lib/rag_engine/evaluator.py`
- [x] T004 [P] [US5] 在 QuestionType 枚举中新增 UNANSWERABLE in `scripts/lib/rag_engine/eval_dataset.py`
- [x] T005 [P] [US5] 修改 EvalSampleCreate question_type pattern 增加 unanswerable in `scripts/api/schemas/eval.py`
- [x] T006 [P] [US5] 修改 dataset_validator UNANSWERABLE 样本跳过 evidence 空值检查 in `scripts/lib/rag_engine/dataset_validator.py`
- [x] T007 [FR-014] 更新 test_evaluator recall 断言值 + 新增 multi_doc/unanswerable 测试 in `scripts/tests/lib/rag_engine/test_evaluator.py`
- [x] T008 [P] [US5] 新增 UNANSWERABLE 序列化测试 in `scripts/tests/lib/rag_engine/test_eval_dataset.py`

**Checkpoint**: Phase 1 — recall 值域 [0,1]，UNANSWERABLE 类型可用 ✅

## Phase 2: 同义词扩展 + 泛关键词收紧 ✅

- [x] T009 [US2] 新增 `_expand_keywords_with_synonyms` 辅助函数 in `scripts/lib/rag_engine/evaluator.py`
- [x] T010 [US2] 在 `_is_relevant()` 中插入同义词扩展层（第3层） in `scripts/lib/rag_engine/evaluator.py`
- [x] T011 [US4] 新增 `_build_generic_keywords` + `_GENERIC_KEYWORDS` 集合 in `scripts/lib/rag_engine/evaluator.py`
- [x] T012 [US4] 修改 `_is_relevant()` 第1层关键词匹配区分领域/泛关键词 in `scripts/lib/rag_engine/evaluator.py`
- [x] T013 [US2,US4] 新增同义词扩展 + 泛关键词收紧测试 in `scripts/tests/lib/rag_engine/test_evaluator.py`

**Checkpoint**: Phase 2 — 同义词匹配生效，泛关键词不单独触发 ✅

## Phase 3: Chunk 级合成 Pipeline ✅

- [x] T014 [US3] 新建 synth_qa.py — SynthConfig/SynthResult/SynthQA 类 in `scripts/lib/rag_engine/synth_qa.py`
- [x] T015 [US3] 新增合成 API 端点 `/dataset/synthesize` in `scripts/api/routers/eval.py`
- [x] T016 [US3] 新建 test_synth_qa.py 测试文件 in `scripts/tests/lib/rag_engine/test_synth_qa.py`

**Checkpoint**: Phase 3 — 合成 pipeline 可独立运行 ✅

## Phase 4: 覆盖度评估 + 弱点报告 ✅

- [x] T017 [P] [US6] 新建 coverage.py — CoverageReport + compute_coverage + get_kb_doc_names in `scripts/lib/rag_engine/coverage.py`
- [x] T018 [P] [US7] 新建 weakness.py — WeaknessReport + generate_weakness_report in `scripts/lib/rag_engine/weakness.py`
- [x] T019 [US6,US7] 新增覆盖度 + 弱点报告 API 端点 in `scripts/api/routers/eval.py`
- [x] T020 [P] [US6] 新建 test_coverage.py in `scripts/tests/lib/rag_engine/test_coverage.py`
- [x] T021 [P] [US7] 新建 test_weakness.py in `scripts/tests/lib/rag_engine/test_weakness.py`

**Checkpoint**: Phase 4 — 覆盖度/弱点报告可独立生成 ✅

## Phase 5: Faithfulness 语义改进 ✅

- [x] T022 [US8] 修改 `compute_faithfulness` 增加 embedding 语义判断 in `scripts/lib/rag_engine/evaluator.py`
- [x] T023 [US8] 新增语义 faithfulness 测试 in `scripts/tests/lib/rag_engine/test_qa_prompt.py`

**Checkpoint**: Phase 5 — faithfulness 语义感知生效 ✅

## Phase 6: 拒绝回答指标 ✅

- [x] T024 [US12] 在 RetrievalEvalReport 新增 rejection_rate + evaluate_batch 排除 UNANSWERABLE in `scripts/lib/rag_engine/evaluator.py`
- [x] T025 [US12] 在 eval_guide.py 新增 rejection_rate 阈值 in `scripts/lib/rag_engine/eval_guide.py`
- [x] T026 [US12] 新增拒绝指标测试 in `scripts/tests/lib/rag_engine/test_evaluator.py`

**Checkpoint**: Phase 6 — rejection_rate 可计算 ✅

## Phase 7: 数据集持久化 + 增强验证 + 样本补充 ✅

- [x] T027 [US9] 修改 `load_eval_dataset` 首次生成后自动保存 JSON in `scripts/lib/rag_engine/eval_dataset.py`
- [x] T028 [US10] 增强验证器 — 重复检测 + 泛关键词检测 in `scripts/lib/rag_engine/dataset_validator.py`
- [x] T029 [US11] 补充 UNANSWERABLE 样本到默认数据集 in `scripts/lib/rag_engine/eval_dataset.py`
- [x] T030 [US9,US10,US11] 新增持久化 + 增强验证 + 补样本测试 in `scripts/tests/lib/rag_engine/test_eval_dataset.py`

**Checkpoint**: Phase 7 — 全部完成 ✅

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1: No dependencies (foundation)
- Phase 2: Depends on Phase 1 (evaluator.py changes sequential)
- Phase 3: Independent (new file), but after Phase 1 for UNANSWERABLE
- Phase 4: Independent (new files)
- Phase 5: Independent (evaluator.py but different function)
- Phase 6: Depends on Phase 1 (UNANSWERABLE type)
- Phase 7: Depends on Phase 1 (UNANSWERABLE), Phase 2 (_GENERIC_KEYWORDS)

### Within Each Phase
- evaluator.py changes are sequential (T001→T002→T003)
- Independent file changes can be parallel (T004, T005, T006)
- Tests follow implementation
