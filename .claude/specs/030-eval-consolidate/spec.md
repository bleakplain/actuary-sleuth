# Feature Specification: Eval 模块归档与清理

**Feature Branch**: `030-eval-consolidate`
**Created**: 2026-05-09
**Status**: Draft
**Input**: 深入梳理和了解 actuary-sleuth 评测集的设计与实现，将 eval 相关代码统一归档到 lib/eval package

## User Scenarios & Testing

### User Story 1 - 核心评估模块归档 (Priority: P1)

作为开发者，我需要将分散在 `lib/rag_engine/` 下的 10 个 eval 相关模块统一迁移到 `lib/eval/` 包，使 eval 代码有独立的归属目录，与 rag_engine 的检索/索引逻辑分离。

**Why this priority**: 归档是本次需求的主体，其他工作都依赖归档完成后的目录结构。

**Independent Test**: 迁移后 `python -c "from lib.eval import ..."` 能正常导入所有公共 API；原有 `from lib.rag_engine.eval_dataset import ...` 等旧路径仍可兼容导入；`pytest scripts/tests/` 全部通过。

**Acceptance Scenarios**:

1. **Given** `lib/rag_engine/` 下有 10 个 eval 相关模块, **When** 执行归档迁移, **Then** `lib/eval/` 包含这些模块的重组版本，`lib/rag_engine/` 中移除原文件（保留兼容 re-export）
2. **Given** `lib/eval/` 已创建, **When** 查看 `lib/eval/__init__.py`, **Then** 公共 API 清晰暴露（EvalSample, RetrievalEvaluator, GenerationEvaluator 等核心符号）
3. **Given** 外部代码通过旧路径 `from lib.rag_engine.eval_dataset import EvalSample` 导入, **When** 归档后运行, **Then** 仍能正常工作（兼容 re-export）
4. **Given** `lib/eval/` 归档完成, **When** 运行 `pytest scripts/tests/`, **Then** 全部测试通过，无 import 错误

---

### User Story 2 - 重复代码清理 (Priority: P1)

作为开发者，我需要在归档的同时删除已知重复代码（eval_guide.py 是 eval_rating.py 的完全重复），避免迁移把重复也带过去。

**Why this priority**: 清理与归档紧密耦合，分开做会多一次全量 import 修正；且重复代码带入新包会污染新的模块结构。

**Independent Test**: 归档后 `lib/eval/` 中不存在 eval_guide.py；所有曾 import eval_guide 的代码改为 import eval_rating 或通过 `lib.eval` 包入口导入；测试通过。

**Acceptance Scenarios**:

1. **Given** `eval_guide.py` 是 `eval_rating.py` 的完全重复, **When** 执行清理, **Then** 仅保留 `eval_rating.py`（归入 `lib/eval/rating.py`），删除 `eval_guide.py`
2. **Given** 有代码 `from lib.rag_engine.eval_guide import interpret_metric`, **When** 清理后, **Then** 改为 `from lib.eval.rating import interpret_metric` 或兼容路径
3. **Given** `lib/rag_engine/eval_guide.py` 被删除, **When** 运行测试, **Then** 无 import 错误

---

### User Story 3 - 模块重命名与子包组织 (Priority: P2)

作为开发者，我需要在 `lib/eval/` 包内按职责划分子模块，使文件名更清晰地反映功能边界，而非沿用 rag_engine 下的大前缀命名。

**Why this priority**: 重命名是归档的自然延伸，但不影响外部功能；P2 因为即使不重命名，归档本身已实现目录分离的目标。

**Independent Test**: `lib/eval/` 目录下文件名语义清晰（如 `dataset.py` 而非 `eval_dataset.py`）；`lib/eval/__init__.py` 导出的公共 API 不变。

**Acceptance Scenarios**:

1. **Given** 归档后 `lib/eval/` 包含 `eval_dataset.py`, `evaluator.py` 等文件, **When** 重命名, **Then** 采用去除 eval_ 前缀的命名（`dataset.py`, `evaluator.py`, `rating.py`, `validator.py`, `coverage.py`, `quality.py`, `badcase.py`, `weakness.py`, `synthesizer.py`）
2. **Given** 重命名后的模块, **When** 查看 `lib/eval/__init__.py`, **Then** 公共 API 符号集与归档前一致（向后兼容）

---

### User Story 4 - CLI 入口与测试路径更新 (Priority: P2)

作为开发者，我需要更新 `evaluate_rag.py` CLI 入口和所有测试文件的 import 路径，使它们指向 `lib/eval` 包。

**Why this priority**: P2 因为这是归档的收尾工作，只要兼容 re-export 存在，旧路径仍可工作；但正式迁移应使用新路径。

**Independent Test**: `evaluate_rag.py` 从 `lib.eval` 导入；测试文件 import 路径指向 `lib.eval` 或其子模块；测试从 `tests/lib/eval/` 目录运行。

**Acceptance Scenarios**:

1. **Given** `evaluate_rag.py` 当前从 `lib.rag_engine.evaluator` 导入, **When** 更新, **Then** 改为从 `lib.eval` 导入
2. **Given** 测试文件在 `tests/lib/rag_engine/` 下, **When** 迁移, **Then** eval 相关测试移至 `tests/lib/eval/` 目录
3. **Given** 所有 import 路径已更新, **When** 运行 `pytest scripts/tests/`, **Then** 全部通过

---

### Edge Cases

- `badcase_classifier.py` 与 `api/routers/feedback.py` 有耦合吗？归档后 feedback router 的 import 路径需要同步更新吗？
- `sample_synthesizer.py` 依赖 LLM 客户端，归档后 `lib/eval/` 对 `lib/llm/` 的依赖方向是否合理？
- `quality_detector.py` 和 `quality_checker.py`（rag_engine 中非 eval 命名）是否有关联？是否应一并归入 eval？
- `dataset_coverage.py` 依赖 KB 管理器，归档后 `lib/eval/` 对 `lib/rag_engine/kb_manager` 的依赖如何处理？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 将以下 9 个模块从 `lib/rag_engine/` 迁移至 `lib/eval/`：evaluator.py, eval_dataset.py, eval_rating.py, dataset_validator.py, dataset_coverage.py, quality_detector.py, badcase_classifier.py, weakness_analyzer.py, sample_synthesizer.py
- **FR-002**: 系统 MUST 删除 `eval_guide.py` 重复文件，仅保留 `eval_rating.py` 的内容（归入 `lib/eval/rating.py`）
- **FR-003**: 系统 MUST 在 `lib/rag_engine/` 中保留兼容 re-export，使旧 import 路径 `from lib.rag_engine.eval_dataset import ...` 等仍可工作
- **FR-004**: 系统 MUST 在 `lib/eval/__init__.py` 中暴露公共 API，包含核心符号：EvalSample, QuestionType, ReviewStatus, RetrievalEvaluator, GenerationEvaluator, EVAL_THRESHOLDS, interpret_metric, generate_eval_summary, validate_dataset, compute_coverage, detect_quality, classify_badcase, generate_weakness_report
- **FR-005**: 系统 MUST 保持 `lib/eval` → `lib/rag_engine` 的依赖方向（eval 可依赖 rag_engine 的检索/生成能力），不允许反向依赖
- **FR-006**: 系统 MUST 保持 API 层（routers/eval.py, schemas/eval.py, database.py）不动，仅调整 import 路径指向 `lib.eval`
- **FR-007**: 系统 MUST 保持 database.py 中的 6 张 eval 表和 30+ 数据访问函数在原位，不迁移
- **FR-008**: 系统 MUST 更新 `evaluate_rag.py` CLI 入口的 import 路径
- **FR-009**: 系统 MUST 将 eval 相关测试迁移至 `tests/lib/eval/` 目录
- **FR-010**: 系统 MUST 在 `lib/eval/` 内采用去除 `eval_` 前缀的文件命名：dataset.py, evaluator.py, rating.py, validator.py, coverage.py, quality.py, badcase.py, weakness.py, synthesizer.py

### Key Entities

- **lib/eval/**: 新的 eval 包，包含评测域逻辑的所有模块
- **lib/eval/__init__.py**: 包入口，暴露公共 API
- **lib/rag_engine/ (兼容 re-export)**: 保留旧路径的兼容导入，标记 deprecation
- **EvalSample / QuestionType / ReviewStatus**: 核心数据模型
- **RetrievalEvaluator / GenerationEvaluator**: 核心评测器
- **EVAL_THRESHOLDS / interpret_metric / generate_eval_summary**: 评级与解读
- **validate_dataset / compute_coverage / detect_quality**: 质量评估工具
- **classify_badcase / generate_weakness_report**: 问题分析工具
- **sample_synthesizer**: 样本合成工具

## Success Criteria

- **SC-001**: `lib/eval/` 目录包含 9 个模块文件 + `__init__.py`
- **SC-002**: `from lib.eval import EvalSample, RetrievalEvaluator, GenerationEvaluator` 正常工作
- **SC-003**: `from lib.rag_engine.eval_dataset import EvalSample` 兼容路径仍可工作
- **SC-004**: `pytest scripts/tests/` 全部通过
- **SC-005**: `evaluate_rag.py` 可正常运行
- **SC-006**: `lib/eval/` 中不存在 `eval_guide.py` 或其他重复代码
- **SC-007**: `lib/eval/` 中无文件名包含 `eval_` 前缀

## Assumptions

- 归档后 `lib/eval/` 依赖 `lib/rag_engine/` 的检索/生成能力，反向依赖不被允许
- API 层 import 路径调整是安全的，不影响 HTTP 接口契约
- 兼容 re-export 在 `lib/rag_engine/` 中是过渡措施，未来版本可移除
- `quality_checker.py`（非 eval 命名）属于 rag_engine 检索质量检查，不属于 eval 评测域，不纳入归档
- database.py 中 eval 相关代码留在 API 层，遵循 CLAUDE.md "Do not put persistence in domain modules" 原则
