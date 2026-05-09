# Implementation Plan: Eval 模块归档与清理

**Branch**: `030-eval-consolidate` | **Date**: 2026-05-09 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

将散布在 `lib/rag_engine/` 下的 10 个 eval 模块统一迁移至 `lib/eval/` 包，删除重复的 `eval_guide.py`，在 `lib/rag_engine/` 保留兼容 re-export，更新所有外部调用方的 import 路径，迁移测试文件至 `tests/lib/eval/`。

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: 无新增依赖，纯代码迁移
**Storage**: SQLite（eval 表留在 api/database.py，不迁移）
**Testing**: pytest
**Constraints**: 兼容 re-export 必须保留，旧 import 路径不能 break

## Constitution Check

- [x] **Library-First**: 无新增库，纯代码重组
- [x] **测试优先**: 每步迁移后运行 pytest 验证
- [x] **简单优先**: 选择方案 A（文件移动 + re-export），最简单且可逆
- [x] **显式优于隐式**: re-export 标记 `# Deprecated`，无隐式重定向
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: 每个 Phase 完成后 pytest 全绿，可独立验证

## Project Structure

### Documentation

```text
.claude/specs/030-eval-consolidate/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

迁移后的目标结构：

```text
scripts/lib/eval/
├── __init__.py       # 公共 API 入口
├── dataset.py        # ← eval_dataset.py
├── evaluator.py      # ← evaluator.py
├── rating.py         # ← eval_rating.py（eval_guide.py 不迁移，直接删除）
├── validator.py      # ← dataset_validator.py
├── coverage.py       # ← dataset_coverage.py
├── quality.py        # ← quality_detector.py
├── badcase.py        # ← badcase_classifier.py
├── weakness.py       # ← weakness_analyzer.py
└── synthesizer.py    # ← sample_synthesizer.py

scripts/tests/lib/eval/
├── test_evaluator.py       # ← tests/lib/rag_engine/test_evaluator.py
├── test_eval_dataset.py    # ← tests/lib/rag_engine/test_eval_dataset.py
├── test_eval_guide.py      # ← tests/lib/rag_engine/test_eval_guide.py（改为 import rating）
├── test_coverage.py        # ← tests/lib/rag_engine/test_coverage.py
├── test_dataset_validator.py  # ← tests/lib/rag_engine/test_dataset_validator.py
├── test_quality_detector.py   # ← tests/lib/rag_engine/test_quality_detector.py
├── test_badcase_classifier.py # ← tests/lib/rag_engine/test_badcase_classifier.py
├── test_weakness.py           # ← tests/lib/rag_engine/test_weakness.py
└── test_synth_qa.py           # ← tests/lib/rag_engine/test_synth_qa.py
```

## Implementation Phases

### Phase 1: 创建 lib/eval 包骨架 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档

#### 实现步骤

1. **创建 `lib/eval/` 目录和 `__init__.py`**
   - 文件: `scripts/lib/eval/__init__.py`
   - 初始内容为空 `__init__.py`，后续 Phase 填充公共 API

---

### Phase 2: 迁移核心数据模型 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-001: 迁移 eval_dataset.py

#### 实现步骤

1. **移动 `eval_dataset.py` → `lib/eval/dataset.py`**
   - 源: `scripts/lib/rag_engine/eval_dataset.py`
   - 目标: `scripts/lib/eval/dataset.py`
   - 使用 `git mv` 保留历史

2. **更新 `dataset.py` 内部 import**
   - 无包内 import 需更新（eval_dataset.py 仅 import 标准库）
   - 注意: `load_eval_dataset()` 中 `from api.database import get_eval_samples` 保持不变（跨层依赖，非本次迁移范围）

3. **创建 `lib/rag_engine/eval_dataset.py` 兼容 re-export**
   - 文件: `scripts/lib/rag_engine/eval_dataset.py`
   ```python
   # Deprecated: use lib.eval.dataset instead
   from lib.eval.dataset import *  # noqa: F401,F403
   ```

4. **验证**: `python -c "from lib.eval.dataset import EvalSample, QuestionType, ReviewStatus"`

---

### Phase 3: 迁移评级与解读模块 + 清理重复 — US1+US2 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ spec.md User Story 2: 重复代码清理
→ FR-001: 迁移 eval_rating.py
→ FR-002: 删除 eval_guide.py

#### 实现步骤

1. **移动 `eval_rating.py` → `lib/eval/rating.py`**
   - 源: `scripts/lib/rag_engine/eval_rating.py`
   - 目标: `scripts/lib/eval/rating.py`
   - 无包内 import 需更新

2. **创建 `lib/rag_engine/eval_rating.py` 兼容 re-export**
   ```python
   # Deprecated: use lib.eval.rating instead
   from lib.eval.rating import *  # noqa: F401,F403
   ```

3. **删除 `eval_guide.py`**
   - 删除: `scripts/lib/rag_engine/eval_guide.py`
   - 无需创建 re-export（已验证无外部引用）
   - 注意: `api/routers/eval.py` 第 37 行 `from lib.rag_engine.eval_guide import generate_eval_summary` 需更新为 `from lib.eval.rating import generate_eval_summary`

4. **更新 `api/routers/eval.py` 的 eval_guide import**
   - 文件: `scripts/api/routers/eval.py:37`
   - 旧: `from lib.rag_engine.eval_guide import generate_eval_summary`
   - 新: `from lib.eval.rating import generate_eval_summary`

5. **验证**: `python -c "from lib.eval.rating import EVAL_THRESHOLDS, interpret_metric, generate_eval_summary"`

---

### Phase 4: 迁移评估器核心 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-001: 迁移 evaluator.py

#### 实现步骤

1. **移动 `evaluator.py` → `lib/eval/evaluator.py`**
   - 源: `scripts/lib/rag_engine/evaluator.py`
   - 目标: `scripts/lib/eval/evaluator.py`

2. **更新 `evaluator.py` 内部 import**
   - 文件: `scripts/lib/eval/evaluator.py`
   - 旧: `from .eval_dataset import EvalSample, QuestionType`
   - 新: `from .dataset import EvalSample, QuestionType`
   - 旧: `from .tokenizer import tokenize_chinese`（rag_engine 内部工具）
   - 新: `from lib.rag_engine.tokenizer import tokenize_chinese`
   - 旧: `from .llamaindex_adapter import _create_embedding_model`（lazy import in `_get_embed_model`）
   - 新: `from lib.rag_engine.llamaindex_adapter import _create_embedding_model`

3. **创建 `lib/rag_engine/evaluator.py` 兼容 re-export**
   ```python
   # Deprecated: use lib.eval.evaluator instead
   from lib.eval.evaluator import *  # noqa: F401,F403
   ```

4. **更新 `lib/rag_engine/__init__.py` re-export 路径**
   - 文件: `scripts/lib/rag_engine/__init__.py:43`
   - 旧: `from .evaluator import RetrievalEvaluator, GenerationEvaluator, RAGEvalReport`
   - 新: `from lib.eval.evaluator import RetrievalEvaluator, GenerationEvaluator, RAGEvalReport`

5. **验证**: `python -c "from lib.eval.evaluator import RetrievalEvaluator, GenerationEvaluator, evaluate_retrieval, compute_faithfulness"`

---

### Phase 5: 迁移质量评估工具模块 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-001: 迁移 dataset_validator.py, dataset_coverage.py, quality_detector.py

#### 实现步骤

1. **移动 `dataset_validator.py` → `lib/eval/validator.py`**
   - 更新内部 import:
     - `from .eval_dataset import EvalSample, QuestionType` → `from .dataset import EvalSample, QuestionType`
     - `from .tokenizer import tokenize_to_set, jaccard_similarity` → `from lib.rag_engine.tokenizer import tokenize_to_set, jaccard_similarity`
     - `from .evaluator import GENERIC_KEYWORDS` → `from .evaluator import GENERIC_KEYWORDS`（包内相对导入，无需改动）
   - 创建 re-export

2. **移动 `dataset_coverage.py` → `lib/eval/coverage.py`**
   - 更新内部 import:
     - `from .eval_dataset import EvalSample` → `from .dataset import EvalSample`
   - 无 kb_manager import（实际代码不 import kb_manager，research.md 有误）
   - 创建 re-export

3. **移动 `quality_detector.py` → `lib/eval/quality.py`**
   - 更新内部 import:
     - `from .evaluator import _token_bigrams` → `from .evaluator import _token_bigrams`（包内相对导入，无需改动）
   - 创建 re-export

4. **更新 `lib/rag_engine/__init__.py` re-export 路径**
   - `from .dataset_validator import ...` → `from lib.eval.validator import ...`
   - `from .quality_detector import ...` → `from lib.eval.quality import ...`

5. **验证**: `python -c "from lib.eval.validator import validate_dataset; from lib.eval.coverage import compute_coverage; from lib.eval.quality import detect_quality"`

---

### Phase 6: 迁移问题分析模块 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-001: 迁移 badcase_classifier.py, weakness_analyzer.py

#### 实现步骤

1. **移动 `badcase_classifier.py` → `lib/eval/badcase.py`**
   - 无包内 import 需更新（仅 import 标准库）
   - 创建 re-export

2. **移动 `weakness_analyzer.py` → `lib/eval/weakness.py`**
   - 更新内部 import:
     - `from .dataset_coverage import CoverageReport` → `from .coverage import CoverageReport`
   - 创建 re-export

3. **更新 `lib/rag_engine/__init__.py` re-export 路径**
   - `from .badcase_classifier import ...` → `from lib.eval.badcase import ...`

4. **验证**: `python -c "from lib.eval.badcase import classify_badcase; from lib.eval.weakness import generate_weakness_report"`

---

### Phase 7: 迁移样本合成模块 — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-001: 迁移 sample_synthesizer.py

#### 实现步骤

1. **移动 `sample_synthesizer.py` → `lib/eval/synthesizer.py`**
   - 更新内部 import:
     - `from .eval_dataset import EvalSample, QuestionType, ReviewStatus, save_eval_dataset, RegulationRef` → `from .dataset import EvalSample, QuestionType, ReviewStatus, save_eval_dataset, RegulationRef`
     - `from .kb_manager import KBManager` → `from lib.rag_engine.kb_manager import KBManager`（lazy import in `load_chunks`）
     - `from lib.llm.factory import LLMClientFactory` → 不变（已是绝对导入）
     - `from lib.doc_parser.kb.converter.excel_to_md import extract_json_array` → 不变（已是绝对导入）
   - 创建 re-export

2. **验证**: `python -c "from lib.eval.synthesizer import SynthQA, SynthConfig"`

---

### Phase 8: 填充 lib/eval/__init__.py 公共 API — US1 (P1)

#### 需求回溯

→ spec.md User Story 1: 核心评估模块归档
→ FR-004: 在 lib/eval/__init__.py 中暴露公共 API

#### 实现步骤

1. **写入 `lib/eval/__init__.py`**
   - 文件: `scripts/lib/eval/__init__.py`
   ```python
   """RAG 评测域 — 数据集、评估器、评级、质量检测、问题分析、样本合成。"""
   __all__ = [
       "EvalSample", "QuestionType", "ReviewStatus", "load_eval_dataset", "save_eval_dataset",
       "RetrievalEvaluator", "GenerationEvaluator",
       "EVAL_THRESHOLDS", "interpret_metric", "generate_eval_summary",
       "validate_dataset", "QualityAuditReport", "compute_coverage",
       "detect_quality", "compute_retrieval_relevance", "compute_info_completeness",
       "classify_badcase", "assess_compliance_risk",
       "generate_weakness_report",
       "SynthQA", "SynthConfig",
   ]
   # 核心数据模型
   from .dataset import EvalSample, QuestionType, ReviewStatus, load_eval_dataset, save_eval_dataset
   # 评测器
   from .evaluator import RetrievalEvaluator, GenerationEvaluator
   # 评级与报告
   from .rating import EVAL_THRESHOLDS, interpret_metric, generate_eval_summary
   # 质量评估
   from .validator import validate_dataset, QualityAuditReport
   from .coverage import compute_coverage
   from .quality import detect_quality, compute_retrieval_relevance, compute_info_completeness
   # 问题分析
   from .badcase import classify_badcase, assess_compliance_risk
   from .weakness import generate_weakness_report
   # 样本合成
   from .synthesizer import SynthQA, SynthConfig
   ```

2. **更新 `lib/rag_engine/__init__.py` re-export 路径**
   - 将所有 eval 模块的 re-export 从 `from .xxx import` 改为 `from lib.eval.xxx import`
   - 具体变更（`scripts/lib/rag_engine/__init__.py`）:
     - L43: `from .evaluator import ...` → `from lib.eval.evaluator import RetrievalEvaluator, GenerationEvaluator, RAGEvalReport`
     - L44: `from .eval_dataset import ...` → `from lib.eval.dataset import EvalSample, QuestionType, load_eval_dataset, save_eval_dataset`
     - L45: `from .dataset_validator import ...` → `from lib.eval.validator import validate_dataset, QualityAuditReport`
     - L46: `from .eval_rating import ...` → `from lib.eval.rating import interpret_metric, generate_eval_summary`
     - L47: `from .quality_detector import ...` → `from lib.eval.quality import detect_quality, compute_retrieval_relevance, compute_info_completeness`
     - L48: `from .badcase_classifier import ...` → `from lib.eval.badcase import classify_badcase, assess_compliance_risk`

3. **验证**: `python -c "from lib.eval import EvalSample, RetrievalEvaluator, GenerationEvaluator, EVAL_THRESHOLDS"`

---

### Phase 9: 更新外部调用方 import 路径 — US4 (P2)

#### 需求回溯

→ spec.md User Story 4: CLI 入口与测试路径更新
→ FR-006: API 层 import 路径调整
→ FR-008: CLI 入口 import 路径更新

#### 实现步骤

1. **更新 `api/routers/eval.py`**
   - 文件: `scripts/api/routers/eval.py`
   - L33: `from lib.rag_engine.eval_dataset import EvalSample, ReviewStatus` → `from lib.eval.dataset import EvalSample, ReviewStatus`
   - L36: `from lib.rag_engine import RetrievalEvaluator, GenerationEvaluator, load_eval_dataset` → `from lib.eval import RetrievalEvaluator, GenerationEvaluator, load_eval_dataset`
   - L37: `from lib.rag_engine.eval_guide import generate_eval_summary` → `from lib.eval.rating import generate_eval_summary`（已在 Phase 3 更新，此处确认）
   - L38: `from lib.rag_engine.dataset_validator import validate_dataset` → `from lib.eval.validator import validate_dataset`

2. **更新 `api/routers/feedback.py`**
   - 文件: `scripts/api/routers/feedback.py`
   - L90: `from lib.rag_engine.badcase_classifier import classify_badcase, assess_compliance_risk` → `from lib.eval.badcase import classify_badcase, assess_compliance_risk`
   - L91: `from lib.rag_engine.quality_detector import detect_quality` → `from lib.eval.quality import detect_quality`
   - L169: `from lib.rag_engine.evaluator import compute_faithfulness` → `from lib.eval.evaluator import compute_faithfulness`

3. **更新 `api/routers/ask.py`**
   - 文件: `scripts/api/routers/ask.py`
   - L34: `from lib.rag_engine.quality_detector import detect_quality` → `from lib.eval.quality import detect_quality`

4. **更新 `evaluate_rag.py`**
   - 文件: `scripts/evaluate_rag.py`
   - L27-33: `from lib.rag_engine.evaluator import ...` → `from lib.eval.evaluator import ...`
   - L34-38: `from lib.rag_engine.eval_dataset import ...` → `from lib.eval.dataset import ...`

5. **验证**: `pytest scripts/tests/ -x` 全部通过

---

### Phase 10: 迁移测试文件 — US4 (P2)

#### 需求回溯

→ spec.md User Story 4: CLI 入口与测试路径更新
→ FR-009: eval 测试迁移至 tests/lib/eval/

#### 实现步骤

1. **创建 `tests/lib/eval/` 目录**
   - 包含 `__init__.py`

2. **迁移测试文件并更新 import**
   - 9 个文件迁移：

   | 源文件 | 目标文件 | import 变更 |
   |--------|---------|------------|
   | `tests/lib/rag_engine/test_evaluator.py` | `tests/lib/eval/test_evaluator.py` | `from lib.rag_engine.evaluator` → `from lib.eval.evaluator`; `from lib.rag_engine.eval_dataset` → `from lib.eval.dataset` |
   | `tests/lib/rag_engine/test_eval_dataset.py` | `tests/lib/eval/test_eval_dataset.py` | `from lib.rag_engine.eval_dataset` → `from lib.eval.dataset` |
   | `tests/lib/rag_engine/test_eval_guide.py` | `tests/lib/eval/test_eval_guide.py` | `from lib.rag_engine.eval_rating` → `from lib.eval.rating` |
   | `tests/lib/rag_engine/test_coverage.py` | `tests/lib/eval/test_coverage.py` | `from lib.rag_engine.eval_dataset` → `from lib.eval.dataset`; `from lib.rag_engine.dataset_coverage` → `from lib.eval.coverage` |
   | `tests/lib/rag_engine/test_dataset_validator.py` | `tests/lib/eval/test_dataset_validator.py` | `from lib.rag_engine.dataset_validator` → `from lib.eval.validator`; `from lib.rag_engine.eval_dataset` → `from lib.eval.dataset` |
   | `tests/lib/rag_engine/test_quality_detector.py` | `tests/lib/eval/test_quality_detector.py` | `from lib.rag_engine.quality_detector` → `from lib.eval.quality` |
   | `tests/lib/rag_engine/test_badcase_classifier.py` | `tests/lib/eval/test_badcase_classifier.py` | `from lib.rag_engine.badcase_classifier` → `from lib.eval.badcase` |
   | `tests/lib/rag_engine/test_weakness.py` | `tests/lib/eval/test_weakness.py` | `from lib.rag_engine.weakness_analyzer` → `from lib.eval.weakness`; `from lib.rag_engine.dataset_coverage` → `from lib.eval.coverage` |
   | `tests/lib/rag_engine/test_synth_qa.py` | `tests/lib/eval/test_synth_qa.py` | `from lib.rag_engine.sample_synthesizer` → `from lib.eval.synthesizer`; `from lib.rag_engine.eval_dataset` → `from lib.eval.dataset` |

3. **更新 `tests/test_evaluator.py`（顶层集成测试）**
   - 文件: `scripts/tests/test_evaluator.py`
   - `from lib.rag_engine.evaluator import ...` → `from lib.eval.evaluator import ...`
   - 不迁移位置（顶层集成测试保留原位）

4. **更新 `tests/lib/rag_engine/test_qa_prompt.py` 中的 eval import**
   - 文件: `scripts/tests/lib/rag_engine/test_qa_prompt.py`
   - L175,182,189,195,208,220: `from lib.rag_engine.evaluator import compute_faithfulness` → `from lib.eval.evaluator import compute_faithfulness`

5. **验证**: `pytest scripts/tests/ -x` 全部通过

---

### Phase 11: 最终验证与清理 — 全部 US

#### 需求回溯

→ spec.md SC-001~SC-007: 所有验收标准

#### 实现步骤

1. **运行完整测试套件**
   - `pytest scripts/tests/ -v`

2. **验证公共 API 可用性**
   ```bash
   python -c "from lib.eval import EvalSample, RetrievalEvaluator, GenerationEvaluator, EVAL_THRESHOLDS, interpret_metric, generate_eval_summary, validate_dataset, compute_coverage, detect_quality, classify_badcase, generate_weakness_report"
   ```

3. **验证兼容路径仍可工作**
   ```bash
   python -c "from lib.rag_engine.eval_dataset import EvalSample"
   python -c "from lib.rag_engine.evaluator import RetrievalEvaluator"
   python -c "from lib.rag_engine import RetrievalEvaluator, EvalSample"
   ```

4. **验证文件结构**
   - `lib/eval/` 包含 9 个模块 + `__init__.py`
   - `lib/eval/` 中无文件名包含 `eval_` 前缀
   - `lib/eval/` 中不存在 `eval_guide.py`
   - `lib/rag_engine/eval_guide.py` 已删除

5. **运行 mypy 类型检查**（如配置了 mypy）
   - `mypy scripts/lib/eval/`

## Complexity Tracking

无违反项。所有选择遵循简单优先原则。

## Appendix

### 执行顺序建议

Phase 2→3→4→5→6→7 串行执行（每步依赖前一步的 re-export 机制就绪），Phase 8 依赖 2-7 全部完成，Phase 9 依赖 8，Phase 10 依赖 9，Phase 11 依赖 10。

```
Phase 1 (骨架)
  → Phase 2 (dataset)
  → Phase 3 (rating + 删除 guide)
  → Phase 4 (evaluator)
  → Phase 5 (validator + coverage + quality)
  → Phase 6 (badcase + weakness)
  → Phase 7 (synthesizer)
→ Phase 8 (__init__.py + rag_engine __init__)
→ Phase 9 (外部调用方 import)
→ Phase 10 (测试迁移)
→ Phase 11 (验证)
```

### 兼容 re-export 完整模板

每个迁移模块在 `lib/rag_engine/` 中保留的 re-export 文件格式：

```python
# Deprecated: use lib.eval.<new_name> instead
from lib.eval.<new_name> import *  # noqa: F401,F403
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 核心归档 | `from lib.eval import EvalSample, RetrievalEvaluator` 可用 | Phase 11 步骤 2 |
| US1 核心归档 | `from lib.rag_engine.eval_dataset import EvalSample` 兼容可用 | Phase 11 步骤 3 |
| US2 清理重复 | `lib/eval/` 无 eval_guide.py | Phase 11 步骤 4 |
| US3 模块重命名 | `lib/eval/` 无 eval_ 前缀文件名 | Phase 11 步骤 4 |
| US4 路径更新 | `pytest` 全部通过 | Phase 11 步骤 1 |
| US4 路径更新 | `evaluate_rag.py` 从 lib.eval 导入 | Phase 9 步骤 4 |
