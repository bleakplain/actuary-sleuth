# Eval 模块归档与清理 - 技术调研报告

生成时间: 2026-05-09
源规格: .claude/specs/030-eval-consolidate/spec.md

## 执行摘要

调研发现 eval 代码散布在 3 个层次共 14 个文件中。核心域逻辑集中在 `lib/rag_engine/` 的 10+1 个模块（含 eval_configs.py），API 层 3 个文件，CLI 1 个文件。模块间耦合度较低：eval 模块对 rag_engine 核心的依赖仅限于 `rag_engine.py`（检索/生成）和 `kb_manager.py`（知识库），无反向依赖，迁移可行。`eval_guide.py` 确认为 `eval_rating.py` 的子集副本且无外部引用，可直接删除。主要风险在于 `dataset_coverage.py` 对 `kb_manager` 的依赖和 `eval_configs.py` 的归属判断。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 迁移核心模块 | `lib/rag_engine/evaluator.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/eval_dataset.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/eval_rating.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/eval_guide.py` | 需删除（重复） |
| FR-001 迁移核心模块 | `lib/rag_engine/dataset_validator.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/dataset_coverage.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/quality_detector.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/badcase_classifier.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/weakness_analyzer.py` | 需迁移 |
| FR-001 迁移核心模块 | `lib/rag_engine/sample_synthesizer.py` | 需迁移 |
| FR-001（补充） | `lib/rag_engine/eval_configs.py` | **需讨论归属** |
| FR-002 清理重复 | `lib/rag_engine/eval_guide.py` | 需删除 |
| FR-003 兼容 re-export | `lib/rag_engine/__init__.py` | 需修改 |
| FR-006 API 层调整 | `api/routers/eval.py` | 需修改 import 路径 |
| FR-006 API 层调整 | `api/schemas/eval.py` | 无需改动（不 import eval 模块） |
| FR-008 CLI 入口 | `evaluate_rag.py` | 需修改 import 路径 |
| FR-009 测试迁移 | `tests/lib/rag_engine/test_evaluator.py` | 需迁移 |
| FR-009 测试迁移 | `tests/lib/rag_engine/test_eval_dataset.py` | 需迁移 |

### 1.2 eval_configs.py 归属分析

`eval_configs.py` 是一个 **评估配置管理模块**，职责：
- 管理评估配置的 CRUD（`activate_config`, `get_config`, `list_configs`, `delete_config`）
- 配置包含：检索参数（top_k, similarity_threshold）、生成参数（temperature, max_tokens）、评估阈值
- 数据存储在 `api/database.py` 的 `eval_configs` 表

**关键判断**：此模块是评估域逻辑还是 rag_engine 配置？

| 论点 | 评估配置归入 lib/eval | 保留在 lib/rag_engine |
|------|---------------------|---------------------|
| 职责归属 | 配置的消费者是 evaluator，属于 eval 域 | 配置包含检索/生成参数，属于 RAG 域 |
| 依赖方向 | eval_configs → database（同其他 eval 模块） | 无 rag_engine 内部依赖 |
| 数据归属 | `eval_configs` 表明确是 eval 语义 | 同左 |
| 调用者 | 仅 `api/routers/eval.py` 调用 | — |

**建议**：归入 `lib/eval/configs.py`。理由：配置的语义边界是"评估"，非"检索"；evaluator 消费配置时不需要经过 rag_engine 中转。

### 1.3 可复用组件

| 组件 | 位置 | 可复用于 |
|------|------|---------|
| `EvalSample` 数据类 | `eval_dataset.py` | 所有 eval 模块的核心数据模型 |
| `QuestionType` 枚举 | `eval_dataset.py` | 问题分类标准 |
| `ReviewStatus` 枚举 | `eval_dataset.py` | 评测状态机 |
| `EVAL_THRESHOLDS` 常量 | `eval_rating.py` | 评级阈值标准 |
| `interpret_metric()` | `eval_rating.py` | 指标解读逻辑 |
| `generate_eval_summary()` | `eval_rating.py` | 报告生成模板 |
| `detect_quality()` | `quality_detector.py` | 质量检测逻辑 |
| `_token_bigrams()` | `quality_detector.py` | 文本 n-gram 工具 |
| `compute_coverage()` | `dataset_coverage.py` | 覆盖度计算 |

### 1.4 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/eval/__init__.py` | 新增 | 包入口，暴露公共 API |
| `lib/eval/dataset.py` | 新增 | 从 eval_dataset.py 迁移 |
| `lib/eval/evaluator.py` | 新增 | 从 evaluator.py 迁移 |
| `lib/eval/rating.py` | 新增 | 从 eval_rating.py 迁移 |
| `lib/eval/validator.py` | 新增 | 从 dataset_validator.py 迁移 |
| `lib/eval/coverage.py` | 新增 | 从 dataset_coverage.py 迁移 |
| `lib/eval/quality.py` | 新增 | 从 quality_detector.py 迁移 |
| `lib/eval/badcase.py` | 新增 | 从 badcase_classifier.py 迁移 |
| `lib/eval/weakness.py` | 新增 | 从 weakness_analyzer.py 迁移 |
| `lib/eval/synthesizer.py` | 新增 | 从 sample_synthesizer.py 迁移 |
| `lib/eval/configs.py` | 新增 | 从 eval_configs.py 迁移 |
| `lib/rag_engine/eval_*.py` 等 11 个 | 修改 | 改为 re-export 兼容层 |
| `lib/rag_engine/__init__.py` | 修改 | 更新 re-export 路径 |
| `api/routers/eval.py` | 修改 | import 路径 lib.rag_engine → lib.eval |
| `evaluate_rag.py` | 修改 | import 路径更新 |
| `tests/lib/rag_engine/test_evaluator.py` | 迁移 | 移至 tests/lib/eval/ |
| `tests/lib/rag_engine/test_eval_dataset.py` | 迁移 | 移至 tests/lib/eval/ |

---

## 二、技术选型研究

### 2.1 迁移方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 文件移动 + re-export** | 最简单，git 保留历史追踪；旧代码零改动即可工作 | 旧路径仍存在，需后续清理 | ✅ |
| **B: 文件移动 + 无兼容层** | 最干净，无遗留代码 | 所有调用方必须同步更新，遗漏即 break | ❌ |
| **C: 原地重命名（不迁移）** | 无迁移风险 | 未解决目录归属问题 | ❌ |

**选择方案 A**：文件移动到 `lib/eval/` + 在 `lib/rag_engine/` 原地保留 re-export 兼容层。理由：
1. git `mv` 保留文件历史
2. re-export 保证渐进式迁移，不遗漏调用方
3. re-export 可标记 `# Deprecated: use lib.eval.xxx`，后续可清理

### 2.2 兼容 re-export 实现方式

```python
# lib/rag_engine/eval_dataset.py（兼容层）
# Deprecated: use lib.eval.dataset instead
from lib.eval.dataset import *  # noqa: F401,F403
```

**替代方案**：在 `lib/rag_engine/__init__.py` 中统一 re-export，删除原文件。但这会让 `from lib.rag_engine.eval_dataset import X` 失效（只有 `from lib.rag_engine import X` 能用），破坏性更大。

**推荐**：保留原文件作为 re-export 占位，最小化破坏。

### 2.3 依赖分析

| 依赖项 | 版本 | 用途 | 兼容性 |
|--------|------|------|--------|
| 无新依赖 | — | 纯代码迁移 | — |

此次归档不引入任何新依赖，纯代码组织变更。

---

## 三、数据流分析

### 3.1 现有数据流（eval 模块间）

```
┌─────────────────────────────────────────────────────┐
│                   lib/rag_engine/                     │
│                                                       │
│  eval_dataset.py ◄── evaluator.py                    │
│       │                   │                           │
│       │                   ├── eval_rating.py          │
│       │                   │                            │
│       ▼                   ▼                           │
│  dataset_validator.py  quality_detector.py            │
│  dataset_coverage.py        │                         │
│       ▲                     │ _token_bigrams          │
│       │                     ▼                         │
│  weakness_analyzer.py   badcase_classifier.py         │
│                                                       │
│  sample_synthesizer.py (独立)                         │
│  eval_configs.py (独立)                               │
└─────────────────────────────────────────────────────┘
```

### 3.2 eval 对 rag_engine 核心的依赖

```
lib/eval/                     lib/rag_engine/
─────────────                 ───────────────
evaluator.py ──────────────► rag_engine.py (检索/生成)
dataset_coverage.py ───────► kb_manager.py (知识库列表)
sample_synthesizer.py ─────► rag_engine.py (生成)
eval_configs.py ───────────► (无，直接访问 database)
```

**依赖方向**：eval → rag_engine ✅ 单向，无反向依赖。

### 3.3 迁移后数据流

```
┌──────────────────────────────┐
│         lib/eval/             │
│                               │
│  dataset.py ◄── evaluator.py │
│      │                │      │
│      │                ├── rating.py
│      │                │      │
│      ▼                ▼      │
│  validator.py    quality.py  │
│  coverage.py         │      │
│      ▲               │      │
│      │               ▼      │
│  weakness.py    badcase.py  │
│                               │
│  synthesizer.py (独立)       │
│  configs.py (独立)           │
└──────────┬───────────────────┘
           │
           │ import (单向)
           ▼
┌──────────────────────────────┐
│      lib/rag_engine/         │
│  rag_engine.py               │
│  kb_manager.py               │
└──────────────────────────────┘
```

### 3.4 关键数据结构

迁移不改变任何数据结构，以下列出核心模型供参考：

```python
# eval_dataset.py → lib/eval/dataset.py
@dataclass(frozen=True)
class EvalSample:
    question: str
    question_type: QuestionType
    expected_chunks: List[str]
    expected_answer: str
    # ...

class QuestionType(str, Enum):
    FACTUAL = "factual"
    COMPARISON = "comparison"
    # ...

class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    # ...
```

```python
# eval_rating.py → lib/eval/rating.py
EVAL_THRESHOLDS = {
    "retrieval_relevance": 0.7,
    "info_completeness": 0.6,
    # ...
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [x] **eval_guide.py 无外部引用** — 已验证：grep 搜索整个项目无 `from lib.rag_engine.eval_guide import` 或 `from .eval_guide import`，确认可安全删除
- [x] **eval 模块对 rag_engine 无反向依赖** — 已验证：所有 eval 模块 import rag_engine 的 `rag_engine.py` 和 `kb_manager.py`，但 rag_engine 核心不 import eval 模块
- [ ] **dataset_coverage.py 对 kb_manager 的依赖** — 已确认依赖存在（`from .kb_manager import KBManager`），迁移后改为 `from lib.rag_engine.kb_manager import KBManager`。需验证跨包 import 无问题
- [ ] **evaluator.py 内部 import 路径** — `evaluator.py` import `from .eval_dataset import EvalSample` 等，迁移后需改为 `from .dataset import EvalSample`（包内相对导入，不影响外部）
- [ ] **weakness_analyzer.py → dataset_coverage.py 内部引用** — 迁移后同为包内引用 `from .coverage import compute_coverage`，无跨包问题

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 遗漏某处旧 import 路径 | 中 | 运行时 ImportError | 全局 grep `from lib.rag_engine.eval_` / `from lib.rag_engine.evaluator` 确保无遗漏 |
| rag_engine/\_\_init\_\_.py re-export 路径更新不完整 | 中 | 包级别 import 失败 | 更新后运行 `pytest` 验证 |
| dataset_coverage.py 跨包 import kb_manager 失败 | 低 | coverage 功能不可用 | 测试中验证 `from lib.eval.coverage import compute_coverage` 正常工作 |
| eval_configs.py 归属判断有误 | 低 | 配置管理职责混乱 | 与用户确认后再迁移 |
| 测试文件迁移后 fixture 路径失效 | 低 | 测试失败 | 检查 conftest.py 中的路径引用 |

### 4.3 eval_guide.py 与 eval_rating.py 重复确认

| 对比维度 | eval_guide.py | eval_rating.py |
|---------|---------------|----------------|
| 文件行数 | ~150 行 | ~300 行 |
| 核心函数 | `interpret_metric()`, `generate_eval_summary()` | 同上 + `compute_retrieval_relevance()`, `compute_info_completeness()`, `assess_compliance_risk()`, `EVAL_THRESHOLDS` |
| 关系 | eval_guide.py 的内容是 eval_rating.py 的子集 | 完整版 |
| 外部引用 | 无 | evaluator.py, api/routers/eval.py |

**结论**：eval_guide.py 是 eval_rating.py 的早期草稿，可安全删除。

---

## 五、迁移清单

### 5.1 文件映射表

| 源文件 | 目标文件 | 操作 |
|--------|---------|------|
| `lib/rag_engine/eval_dataset.py` | `lib/eval/dataset.py` | 移动 + 改内部 import |
| `lib/rag_engine/evaluator.py` | `lib/eval/evaluator.py` | 移动 + 改内部 import |
| `lib/rag_engine/eval_rating.py` | `lib/eval/rating.py` | 移动 + 改内部 import |
| `lib/rag_engine/eval_guide.py` | — | **删除** |
| `lib/rag_engine/dataset_validator.py` | `lib/eval/validator.py` | 移动 + 改内部 import |
| `lib/rag_engine/dataset_coverage.py` | `lib/eval/coverage.py` | 移动 + 改外部 import（kb_manager） |
| `lib/rag_engine/quality_detector.py` | `lib/eval/quality.py` | 移动 + 改内部 import |
| `lib/rag_engine/badcase_classifier.py` | `lib/eval/badcase.py` | 移动（无内部依赖变化） |
| `lib/rag_engine/weakness_analyzer.py` | `lib/eval/weakness.py` | 移动 + 改内部 import（coverage） |
| `lib/rag_engine/sample_synthesizer.py` | `lib/eval/synthesizer.py` | 移动 + 改外部 import（rag_engine） |
| `lib/rag_engine/eval_configs.py` | `lib/eval/configs.py` | 移动（无内部依赖变化） |
| — | `lib/eval/__init__.py` | **新建**，暴露公共 API |

### 5.2 import 路径变更清单

**包内 import（eval 模块间，迁移后自动更新为相对导入）**：

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| evaluator.py | `from .eval_dataset import EvalSample` | `from .dataset import EvalSample` |
| evaluator.py | `from .eval_rating import interpret_metric, generate_eval_summary` | `from .rating import interpret_metric, generate_eval_summary` |
| weakness_analyzer.py | `from .dataset_coverage import compute_coverage` | `from .coverage import compute_coverage` |

**跨包 import（eval → rag_engine，迁移后改为绝对导入）**：

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| dataset_coverage.py | `from .kb_manager import KBManager` | `from lib.rag_engine.kb_manager import KBManager` |
| evaluator.py | `from .rag_engine import RAGEngine` | `from lib.rag_engine.rag_engine import RAGEngine` |
| sample_synthesizer.py | `from .rag_engine import RAGEngine` | `from lib.rag_engine.rag_engine import RAGEngine` |

**外部调用方 import 路径更新**：

| 文件 | 旧 import | 新 import |
|------|-----------|-----------|
| `api/routers/eval.py` | `from lib.rag_engine.evaluator import RetrievalEvaluator, GenerationEvaluator` | `from lib.eval.evaluator import RetrievalEvaluator, GenerationEvaluator` |
| `api/routers/eval.py` | `from lib.rag_engine.eval_dataset import ...` | `from lib.eval.dataset import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.eval_configs import ...` | `from lib.eval.configs import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.eval_rating import ...` | `from lib.eval.rating import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.badcase_classifier import ...` | `from lib.eval.badcase import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.quality_detector import ...` | `from lib.eval.quality import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.weakness_analyzer import ...` | `from lib.eval.weakness import ...` |
| `api/routers/eval.py` | `from lib.rag_engine.sample_synthesizer import ...` | `from lib.eval.synthesizer import ...` |
| `evaluate_rag.py` | `from lib.rag_engine.evaluator import ...` | `from lib.eval.evaluator import ...` |
| `evaluate_rag.py` | `from lib.rag_engine.eval_dataset import ...` | `from lib.eval.dataset import ...` |

### 5.3 兼容 re-export 文件清单

以下文件保留在 `lib/rag_engine/`，内容改为 re-export：

```
eval_dataset.py  →  from lib.eval.dataset import *  # Deprecated
evaluator.py     →  from lib.eval.evaluator import *  # Deprecated
eval_rating.py   →  from lib.eval.rating import *  # Deprecated
dataset_validator.py  →  from lib.eval.validator import *  # Deprecated
dataset_coverage.py   →  from lib.eval.coverage import *  # Deprecated
quality_detector.py   →  from lib.eval.quality import *  # Deprecated
badcase_classifier.py →  from lib.eval.badcase import *  # Deprecated
weakness_analyzer.py  →  from lib.eval.weakness import *  # Deprecated
sample_synthesizer.py →  from lib.eval.synthesizer import *  # Deprecated
eval_configs.py       →  from lib.eval.configs import *  # Deprecated
```

`eval_guide.py` 不保留 re-export（无外部引用，直接删除）。

### 5.4 lib/eval/__init__.py 公共 API

```python
# 核心数据模型
from .dataset import EvalSample, QuestionType, ReviewStatus, load_eval_dataset, save_eval_dataset

# 评测器
from .evaluator import RetrievalEvaluator, GenerationEvaluator

# 评级与报告
from .rating import EVAL_THRESHOLDS, interpret_metric, generate_eval_summary

# 质量评估
from .validator import validate_dataset
from .coverage import compute_coverage
from .quality import detect_quality, QualityAuditReport

# 问题分析
from .badcase import classify_badcase, assess_compliance_risk
from .weakness import generate_weakness_report

# 样本合成
from .synthesizer import synthesize_samples

# 配置管理
from .configs import activate_config, get_config, list_configs, delete_config
```

---

## 六、参考实现

此归档为纯代码组织重构，无外部参考实现。可参考项目中已有的包组织模式：
- `lib/audit/` — 独立业务包，import `lib/common/` 和 `lib/llm/`，无反向依赖
- `lib/reporting/` — 独立业务包，依赖 `lib/common/models.py`
