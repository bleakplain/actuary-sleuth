# Tasks: RAG 评估体系评估与改进

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)

## Phase 1: LLM-as-a-Judge 核心实现 (US3)

- [x] T001 [US3] 创建 llm_judge.py 数据模型 + Prompt 常量 + LLMPJudge 类 in scripts/lib/rag_engine/llm_judge.py
- [x] T002 [P] [US3] 创建 LLM Judge 测试 in scripts/tests/lib/rag_engine/test_llm_judge.py
- [x] T003 [US3] 集成 LLM Judge 到 GenerationEvaluator in scripts/lib/rag_engine/evaluator.py
- [x] T004 [US3] 更新 __init__.py 导出 in scripts/lib/rag_engine/__init__.py

**Checkpoint**: ✅ `pytest scripts/tests/lib/rag_engine/test_llm_judge.py` 全部通过

## Phase 2: 评测数据集扩充 (US2)

- [x] T005 [P] [US2] 新增 90 条评测样本 in scripts/lib/rag_engine/eval_dataset.py
- [x] T006 [US2] 更新 create_default_eval_dataset() 引用新函数 in scripts/lib/rag_engine/eval_dataset.py
- [x] T007 [US2] 更新测试断言适配新数据集规模 in scripts/tests/lib/rag_engine/test_evaluator.py

**Checkpoint**: ✅ `pytest scripts/tests/lib/rag_engine/test_evaluator.py::TestEvalDataset` 全部通过

## Phase 3: Bug 修复与 API 集成 (US3)

- [x] T008 [US3] 修复 create_evaluation 重复调用 bug in scripts/api/routers/eval.py
- [x] T009 [P] [US3] 更新 EvaluationRequest schema in scripts/api/schemas/eval.py
- [x] T010 [P] [US3] 更新 eval_runs.mode CHECK 约束 in scripts/api/database.py
- [x] T011 [US3] 更新 CLI evaluate_rag.py 支持 LLM Judge 模式

**Checkpoint**: ✅ `mypy scripts/lib/` 通过（无新增错误）

## Phase 4: 数据集质量审查 (US6)

- [x] T012 [P] [US6] 创建 dataset_validator.py in scripts/lib/rag_engine/dataset_validator.py
- [x] T013 [P] [US6] 创建数据集校验测试 in scripts/tests/lib/rag_engine/test_dataset_validator.py
- [x] T014 [US6] 新增 /dataset/audit API 端点 in scripts/api/routers/eval.py

**Checkpoint**: ✅ `pytest scripts/tests/lib/rag_engine/test_dataset_validator.py` 全部通过

## Phase 5: 评估指南 (US4)

- [x] T015 [P] [US4] 创建 eval_guide.py in scripts/lib/rag_engine/eval_guide.py
- [x] T016 [US4] 集成解读摘要到评估报告导出 in scripts/api/routers/eval.py

**Checkpoint**: ✅ 导入测试通过

## Phase 6: 人工抽检记录 (US3)

- [x] T017 [P] [US3] 新增 human_reviews 表 + CRUD in scripts/api/database.py
- [x] T018 [P] [US3] 新增人工抽检 schema in scripts/api/schemas/eval.py
- [x] T019 [US3] 新增人工抽检 API 端点 in scripts/api/routers/eval.py

**Checkpoint**: ✅ `mypy scripts/lib/` 通过（无新增错误）

## Final

- [x] T020 运行完整类型检查 mypy scripts/lib/ — 无新增错误
- [x] T021 运行完整测试套件 pytest scripts/tests/ — 326 passed, 3 pre-existing failures (test_jina_adapter.py)
