# 保险产品条款审核评测数据集生成 - 技术调研报告

生成时间: 2026-04-16 14:30:00
源规格: .claude/specs/013-audit-dataset-generation/spec.md

## 执行摘要

本调研分析了现有评测数据集系统的实现，评估了支持审核样本所需的技术选型和改动范围。

**关键发现**：
1. 现有 `eval_samples` 表和数据模型可通过迁移扩展支持 `sample_type` 字段
2. Word/PDF 解析需新增依赖（`python-docx`, `pdfplumber`），但复用现有 OCR 和分块逻辑
3. 违规项数据结构需强类型定义，可参考现有 `QualityIssue` 模式
4. 统一评测框架可通过新增 `AuditEvaluator` 类实现，复用现有检索评估基础设施
5. 前端需新增审核工作台 Tab，现有 `EvalPage.tsx` 已有审核相关 UI 组件可复用

**风险提示**：
- 违规项标注依赖 LLM 质量，需设计有效的提示词模板
- 法规引用准确性需验证（引用的法规在知识库中存在）

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 (Word/PDF解析) | `lib/common/document_fetcher.py` | 需新增，现仅支持飞书文档 |
| FR-002 (条款结构化) | `lib/rag_engine/chunker.py` | 可复用，`ChecklistChunker` 按标题切分 |
| FR-003 (LLM生成样本) | `lib/rag_engine/sample_synthesizer.py` | 可复用架构，需新增提示词模板 |
| FR-004 (违规项标注) | 无 | 需新增 |
| FR-005 (质量检查) | `lib/rag_engine/dataset_validator.py` | 可复用，扩展检查规则 |
| FR-006 (存入数据库) | `api/database.py` | 需扩展 `sample_type` 字段 |
| FR-007 (人工审核) | `web/src/pages/EvalPage.tsx` | 已有基础，需增强工作台 |
| FR-008 (仅APPROVED参与) | `lib/rag_engine/evaluator.py` | 需新增过滤逻辑 |
| FR-009 (sample_type字段) | `api/database.py` | 需迁移脚本 |
| FR-010 (统一评估) | `lib/rag_engine/evaluator.py` | 需新增 `AuditEvaluator` |
| FR-011 (审核指标) | 无 | 需新增 |

### 1.2 可复用组件

| 组件 | 位置 | 可复用于 |
|------|------|---------|
| `EvalSample` 数据类 | `lib/rag_engine/eval_dataset.py` | 扩展 `sample_type` 字段 |
| `ReviewStatus` 枚举 | `lib/rag_engine/eval_dataset.py` | 直接复用 |
| `RegulationRef` 数据类 | `lib/rag_engine/eval_dataset.py` | 直接复用 |
| `RetrievalEvaluator` | `lib/rag_engine/evaluator.py` | 法规引用检索评估 |
| `QualityIssue` 模式 | `lib/rag_engine/dataset_validator.py` | Violation 数据类参考 |
| `Product` / `ProductCategory` | `lib/common/models.py` | 产品信息结构 |
| `get_category()` | `lib/common/product.py` | 产品类型识别 |
| `ChecklistChunker` | `lib/rag_engine/chunker.py` | 条款分块逻辑 |
| `ZhipuClient.ocr_table()` | `lib/llm/zhipu.py` | PDF 扫描件 OCR |
| `SampleDrawer` 组件 | `web/src/pages/EvalPage.tsx` | 样本编辑 Drawer |
| `approveSample()` API | `web/src/api/eval.ts` | 审核通过操作 |

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/audit_eval/clause_parser.py` | 新增 | Word/PDF 条款解析器 |
| `lib/audit_eval/audit_sample_synth.py` | 新增 | 审核样本合成器 |
| `lib/audit_eval/audit_evaluator.py` | 新增 | 审核评估器 |
| `lib/audit_eval/models.py` | 新增 | Violation, IssueType 等数据模型 |
| `lib/rag_engine/eval_dataset.py` | 修改 | 扩展 EvalSample 支持 sample_type |
| `api/database.py` | 修改 | 添加 sample_type 迁移和 CRUD |
| `api/routers/eval.py` | 修改 | 新增审核样本相关端点 |
| `web/src/pages/EvalPage.tsx` | 修改 | 新增审核工作台 Tab |
| `web/src/types.ts` | 修改 | 扩展 EvalSample 类型定义 |

---

## 二、技术选型研究

### 2.1 Word/PDF 解析方案对比

| 方案 | 库 | 优点 | 缺点 | 选择 |
|------|-----|------|------|------|
| **python-docx** | `python-docx>=0.8.11` | 纯 Python，API 简洁，已在 requirements 预留 | 仅支持 .docx | ✅ Word 解析 |
| **pdfplumber** | `pdfplumber>=0.9.0` | 表格提取好，文本位置精确 | 依赖 pdfminer.six，安装略重 | ✅ PDF 解析 |
| **pypdf** | `pypdf>=3.0` | 轻量，纯 Python | 表格提取弱 | ❌ |
| **PyMuPDF** | `pymupdf>=1.22` | 性能最优，图片提取强 | 二进制依赖，安装复杂 | ❌ |

**选型结论**：
- Word 解析：`python-docx`（已在 requirements 注释中预留）
- PDF 解析：`pdfplumber`（表格提取能力强，适合费率表）

### 2.2 条款解析策略

**真实保险产品文档格式分析**（基于 `/mnt/d/work/actuary-assets/products/` 24 个文件）：

| 格式 | 数量 | 说明 |
|------|------|------|
| `.docx` | 11 | 可直接解析 |
| `.doc` | 9 | 需预处理（OLE2 格式，python-docx 不支持） |
| `.pdf` | 3 | 可直接解析 |

**关键发现**：

1. **条款编号格式**：阿拉伯数字层级编号（1, 1.1, 2.3.2），**不是**中文"第X条"
2. **内容位置**：DOCX 文件中，条款内容主要在**表格**中（8-15 个空段落，2-3 个内容表格）
3. **标题/正文混合**：约 41% 的条款标题和正文混在同一单元格中

```
┌─────────────────────────────────────────────────────────────┐
│  条款解析流程                                                │
├─────────────────────────────────────────────────────────────┤
│  Word/PDF 文件                                              │
│       ↓                                                      │
│  python-docx / pdfplumber 提取表格                          │
│       ↓                                                      │
│  过滤非条款表格（公司信息等）                                 │
│       ↓                                                      │
│  识别条款编号（正则：^\d+(?:\.\d+)*\s*$）                    │
│       ↓                                                      │
│  分离标题/正文（换行符 > 句号 > 全部作为标题）                │
│       ↓                                                      │
│  按编号排序 → List[Clause]                                   │
│       ↓                                                      │
│  提取费率表（表头关键词识别）→ Optional[PremiumTable]        │
└─────────────────────────────────────────────────────────────┘
```

**条款编号识别正则**：
```python
# 真实保险条款使用阿拉伯数字层级编号，而非中文"第X条"
CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s*$')

# 匹配示例：
# - "1" → 匹配
# - "1.1" → 匹配
# - "2.3.2" → 匹配
# - "第一条" → 不匹配
```

**标题/正文分离算法**：
```python
def _separate_title_and_text(content: str) -> Tuple[str, str]:
    """
    分离策略（按优先级）：
    1. 如果有换行符，第一行为标题
    2. 如果有句号且第一句<=30字，第一句为标题
    3. 否则全部作为标题
    """
    lines = content.split('\n')
    if len(lines) > 1:
        return lines[0].strip(), '\n'.join(lines[1:]).strip()
    
    if '。' in content:
        parts = content.split('。', 1)
        if len(parts[0]) <= 30:
            return parts[0].strip(), parts[1].strip()
    
    return content, ""
```

**.doc 文件处理**：
- python-docx 不支持 OLE2 格式的 .doc 文件
- 解决方案：使用 LibreOffice 批量转换
  ```bash
  libreoffice --headless --convert-to docx *.doc
  ```

### 2.3 违规项标注 LLM 提示词模板

参考现有 `sample_synthesizer.py` 的 `_SYNTH_PROMPT`，设计审核场景提示词：

```python
_AUDIT_SYNTH_PROMPT = """你是一个保险产品审核专家。根据以下产品条款和法规知识库，识别潜在违规项。

产品信息：
- 名称：{product_name}
- 类型：{product_type}

条款内容：
{clauses_text}

法规知识库摘要（供参考）：
{kb_summary}

请识别条款中的潜在违规项，输出 JSON 数组格式：
[
  {
    "clause_number": "条款编号，如第七条",
    "clause_title": "条款标题",
    "issue_type": "违规类型（见下方枚举）",
    "severity": "high/medium/low",
    "description": "违规描述（>=15字，包含具体问题）",
    "regulation_ref": {
      "doc_name": "法规名称",
      "article": "条款编号",
      "excerpt": "原文摘要"
    }
  }
]

违规类型枚举：
- invalid_waiting_period: 等待期设置违规
- invalid_exclusion_clause: 免责条款违规
- missing_mandatory_clause: 缺少必含条款
- incomplete_coverage: 保障责任不完整
- invalid_age_range: 投保年龄范围违规
...（共 15 种）

如条款完全合规，输出空数组 []。
仅输出 JSON，不要输出其他内容。"""
```

### 2.4 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| `python-docx` | >=0.8.11 | Word 解析 | 纯 Python，无兼容问题 |
| `pdfplumber` | >=0.9.0 | PDF 解析 | 依赖 pdfminer.six，兼容 |
| `zhipu` | (API) | GLM LLM + OCR | 已集成，复用 |

---

## 三、数据流分析

### 3.1 现有数据流

```
问答评测数据流：
┌───────────┐     ┌──────────────┐     ┌──────────────┐
│ KB Chunk  │ ──→ │ SynthQA      │ ──→ │ EvalSample   │
│ (LanceDB) │     │ (LLM生成)    │     │ (数据库)     │
└───────────┘     └──────────────┘     └──────────────┘
                         ↓
                  ┌──────────────┐
                  │ RetrievalEval │
                  │ GenerationEval│
                  └──────────────┘
```

### 3.2 新增数据流

```
审核评测数据流：
┌───────────┐     ┌──────────────┐     ┌──────────────┐
│ 产品文档   │ ──→ │ ClauseParser │ ──→ │ AuditInput   │
│ (docx/pdf)│     │ (解析条款)   │     │ (结构化)     │
└───────────┘     └──────────────┘     └──────────────┘
                                              ↓
                  ┌──────────────────────────────────────┐
                  │          AuditSampleSynth           │
                  │  (LLM 违规识别 + 法规引用生成)       │
                  └──────────────────────────────────────┘
                                              ↓
                  ┌──────────────┐     ┌──────────────┐
                  │ AuditSample  │ ──→ │ PENDING      │
                  │ (违规项列表) │     │ (人工审核)   │
                  └──────────────┘     └──────────────┘
                                              ↓
                  ┌──────────────────────────────────────┐
                  │           AuditEvaluator             │
                  │  (检索评估 + 违规匹配评估)           │
                  └──────────────────────────────────────┘
```

### 3.3 关键数据结构

#### 新增数据模型

```python
# lib/audit_eval/models.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

class IssueType(str, Enum):
    """违规类型枚举"""
    # 条款合规
    INVALID_WAITING_PERIOD = "invalid_waiting_period"
    INVALID_EXCLUSION_CLAUSE = "invalid_exclusion_clause"
    MISSING_MANDATORY_CLAUSE = "missing_mandatory_clause"
    AMBIGUOUS_DEFINITION = "ambiguous_definition"
    # 定价合理
    UNREASONABLE_PREMIUM = "unreasonable_premium"
    INVALID_PRICING_METHOD = "invalid_pricing_method"
    # 责任范围
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    INVALID_COVERAGE_LIMIT = "invalid_coverage_limit"
    SCOPE_BOUNDARY_UNCLEAR = "scope_boundary_unclear"
    # 产品结构
    INVALID_AGE_RANGE = "invalid_age_range"
    INVALID_PERIOD = "invalid_period"
    # 格式规范
    CLAUSE_NUMBERING_ERROR = "clause_numbering_error"
    MISSING_CLAUSE_ELEMENT = "missing_clause_element"


@dataclass(frozen=True)
class Violation:
    """违规项"""
    id: str
    clause_number: str
    clause_title: str
    issue_type: IssueType
    severity: str  # high/medium/low
    description: str
    regulation_ref: Optional[RegulationRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'clause_number': self.clause_number,
            'clause_title': self.clause_title,
            'issue_type': self.issue_type.value,
            'severity': self.severity,
            'description': self.description,
            'regulation_ref': self.regulation_ref.to_dict() if self.regulation_ref else None,
        }


@dataclass(frozen=True)
class Clause:
    """条款"""
    number: str
    title: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'number': self.number,
            'title': self.title,
            'text': self.text,
        }


@dataclass(frozen=True)
class PremiumTable:
    """费率表"""
    raw_text: str
    age_rates: Optional[Dict[str, str]] = None
    remark: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'raw_text': self.raw_text,
            'age_rates': self.age_rates,
            'remark': self.remark,
        }


@dataclass(frozen=True)
class AuditInput:
    """审核输入"""
    product: Dict[str, Any]  # Product.to_dict()
    clauses: List[Clause]
    premium_table: Optional[PremiumTable] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'product': self.product,
            'clauses': [c.to_dict() for c in self.clauses],
            'premium_table': self.premium_table.to_dict() if self.premium_table else None,
        }


@dataclass(frozen=True)
class AuditGroundTruth:
    """审核标准答案"""
    violations: List[Violation]
    overall_result: str  # pass/conditional_pass/fail
    risk_level: str  # low/medium/high

    def to_dict(self) -> Dict[str, Any]:
        return {
            'violations': [v.to_dict() for v in self.violations],
            'overall_result': self.overall_result,
            'risk_level': self.risk_level,
        }
```

#### 扩展 EvalSample

```python
# 修改 lib/rag_engine/eval_dataset.py

@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str  # 审核样本时存储产品名称或标识
    ground_truth: str  # 审核样本时存储 JSON 序列化的 AuditGroundTruth
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: QuestionType  # 审核样本时使用 FACTUAL
    difficulty: str
    topic: str
    regulation_refs: List[RegulationRef] = field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING
    reviewer: str = ""
    reviewed_at: str = ""
    review_comment: str = ""
    created_by: str = "human"
    kb_version: str = ""
    # 新增字段
    sample_type: str = "qa"  # "qa" | "audit"
    audit_input_json: str = ""  # 审核样本专属：AuditInput JSON
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

| 假设 | 验证方式 | 风险 |
|------|---------|------|
| python-docx 可正确解析保险条款 Word 文件 | 用实际文件测试 | 低 - 标准库 |
| pdfplumber 可提取费率表 | 用实际 PDF 测试 | 中 - 表格复杂度 |
| LLM 可识别常见违规类型 | 构造测试样本验证 | 中 - LLM 能力 |
| 法规引用在知识库中可检索 | 对现有法规测试 Recall | 低 - 知识库覆盖 |

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 条款解析失败（格式损坏） | 中 | 高 | 错误处理 + 人工兜底 |
| LLM 违规标注质量低 | 中 | 高 | 设计强提示词 + 人工校验强制 |
| 法规引用不存在知识库 | 中 | 中 | 记录警告 + 人工补充法规 |
| 费率表提取不完整 | 中 | 低 | OCR 兜底 + 人工补录 |
| 审核样本评估指标不可自动计算 | 低 | 中 | 采用实体匹配 F1 计算 |

---

## 五、评估框架设计

### 5.1 统一评测框架架构

```python
# lib/rag_engine/evaluator.py 扩展

class UnifiedEvaluator:
    """统一评测引擎"""

    def evaluate(
        self,
        sample: EvalSample,
        system_output: Dict[str, Any],
    ) -> EvalResult:
        # 通用：法规检索评估
        context_metrics = self._evaluate_context(
            sample.regulation_refs,
            system_output.get("retrieved_docs", [])
        )

        # 分类型评估
        if sample.sample_type == "qa":
            return self._evaluate_qa_sample(sample, system_output, context_metrics)
        elif sample.sample_type == "audit":
            return self._evaluate_audit_sample(sample, system_output, context_metrics)


class AuditEvaluator:
    """审核样本评估器"""

    def evaluate(
        self,
        sample: EvalSample,
        system_output: Dict[str, Any],
    ) -> AuditEvalResult:
        """
        Args:
            sample: 评测样本，ground_truth 为 AuditGroundTruth JSON
            system_output: 审核系统输出，包含 violations 字段

        Returns:
            AuditEvalResult: 违规检出率、类型准确率等指标
        """
        gt = AuditGroundTruth.from_json(sample.ground_truth)
        pred_violations = [
            Violation.from_dict(v) for v in system_output.get("violations", [])
        ]

        # 计算违规匹配
        matched = self._match_violations(pred_violations, gt.violations)

        # 计算指标
        precision = len(matched) / len(pred_violations) if pred_violations else 0
        recall = len(matched) / len(gt.violations) if gt.violations else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        # 类型准确率
        type_correct = sum(1 for p, g in matched if p.issue_type == g.issue_type)
        type_accuracy = type_correct / len(matched) if matched else 0

        # 严重程度准确率
        severity_correct = sum(1 for p, g in matched if p.severity == g.severity)
        severity_accuracy = severity_correct / len(matched) if matched else 0

        return AuditEvalResult(
            sample_id=sample.id,
            violation_precision=precision,
            violation_recall=recall,
            violation_f1=f1,
            type_accuracy=type_accuracy,
            severity_accuracy=severity_accuracy,
        )

    def _match_violations(
        self,
        predictions: List[Violation],
        ground_truths: List[Violation],
    ) -> List[Tuple[Violation, Violation]]:
        """匹配预测违规项与标注违规项"""
        matched = []
        used_gt = set()

        for pred in predictions:
            for i, gt in enumerate(ground_truths):
                if i in used_gt:
                    continue
                # 匹配规则：条款编号相同 + 类型相同
                if pred.clause_number == gt.clause_number and pred.issue_type == gt.issue_type:
                    matched.append((pred, gt))
                    used_gt.add(i)
                    break
                # 部分匹配：条款编号相同
                elif pred.clause_number == gt.clause_number:
                    matched.append((pred, gt))
                    used_gt.add(i)
                    break

        return matched
```

### 5.2 评测运行时强制过滤

```python
# 修改 lib/rag_engine/evaluator.py

def evaluate_batch(self, samples: List[EvalSample], ...) -> Report:
    # 强制过滤：仅使用 APPROVED 状态样本
    approved_samples = [s for s in samples if s.review_status == ReviewStatus.APPROVED]

    skipped_count = len(samples) - len(approved_samples)
    if skipped_count > 0:
        logger.warning(
            f"跳过 {skipped_count} 条待审核/拒绝样本，"
            f"仅使用 {len(approved_samples)} 条已审核样本"
        )

    if not approved_samples:
        raise ValueError("无已审核样本，请先完成人工校验")

    return self._do_evaluate(approved_samples, ...)
```

---

## 六、数据库扩展方案

### 6.1 迁移脚本

```python
# api/database.py - _migrate_db() 新增

sample_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_samples)").fetchall()}

# 现有迁移...
if 'kb_version' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN kb_version TEXT NOT NULL DEFAULT ''")

# 新增：sample_type 字段
if 'sample_type' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN sample_type TEXT NOT NULL DEFAULT 'qa'")

# 新增：audit_input_json 字段（存储审核样本输入）
if 'audit_input_json' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN audit_input_json TEXT NOT NULL DEFAULT ''")
```

### 6.2 CRUD 函数扩展

```python
# api/database.py

def get_eval_samples(
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    review_status: Optional[str] = None,
    sample_type: Optional[str] = None,  # 新增
) -> List[Dict]:
    clauses: list[str] = []
    params: list = []
    # ...
    if sample_type:
        clauses.append("sample_type = ?")
        params.append(sample_type)
    # ...


def _sample_insert_values(s: Dict, use_now: bool = True) -> tuple:
    # ...
    return (
        # 现有字段...
        s.get("sample_type", "qa"),  # 新增
        s.get("audit_input_json", ""),  # 新增
    )
```

---

## 七、前端扩展方案

### 7.1 类型定义扩展

```typescript
// web/src/types.ts

interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: string;
  difficulty: string;
  topic: string;
  regulation_refs: RegulationRef[];
  review_status: 'pending' | 'approved' | 'rejected';  // 新增 rejected
  reviewer: string;
  reviewed_at: string;
  review_comment: string;
  created_by: string;
  kb_version: string;
  sample_type?: 'qa' | 'audit';  // 新增
  audit_input_json?: string;  // 新增
}

interface Violation {
  id: string;
  clause_number: string;
  clause_title: string;
  issue_type: string;
  severity: 'high' | 'medium' | 'low';
  description: string;
  regulation_ref?: RegulationRef;
}

interface AuditInput {
  product: Product;
  clauses: Clause[];
  premium_table?: PremiumTable;
}
```

### 7.2 审核工作台 Tab

```tsx
// EvalPage.tsx 新增 Tab

const items = [
  { key: 'dataset', label: '数据集', children: <DatasetTab /> },
  { key: 'review', label: `审核工作台 (${pendingCount})`, children: <ReviewWorkbench /> },  // 新增
  { key: 'snapshots', label: '快照', children: <SnapshotsTab /> },
  { key: 'runs', label: '评测历史', children: <RunsTab /> },
  { key: 'configs', label: '配置', children: <ConfigsTab /> },
];

function ReviewWorkbench() {
  const [samples, setSamples] = useState<EvalSample[]>([]);

  useEffect(() => {
    evalApi.fetchEvalSamples({ review_status: 'pending', sample_type: 'audit' })
      .then(setSamples);
  }, []);

  return (
    <div>
      <Card title="待审核样本">
        <Table
          dataSource={samples}
          columns={[
            { title: '产品', dataIndex: 'question' },
            { title: '违规项数', render: (_, s) => parseViolations(s.ground_truth).length },
            { title: '操作', render: (_, s) => (
              <Space>
                <Button onClick={() => handleApprove(s.id)}>通过</Button>
                <Button onClick={() => handleReject(s.id)}>拒绝</Button>
                <Button onClick={() => openEditDrawer(s)}>编辑</Button>
              </Space>
            )},
          ]}
        />
      </Card>
    </div>
  );
}
```

---

## 八、参考实现

- [RAGAS 评估框架](https://docs.ragas.io/) — Faithfulness/Answer Correctness 计算参考
- [seqeval NER 评估](https://huggingface.co/docs/evaluate/main/en/measurement/seqeval) — 实体级 F1 计算参考
- [python-docx 文档](https://python-docx.readthedocs.io/) — Word 解析 API 参考
- [pdfplumber 文档](https://github.com/jsvine/pdfplumber) — PDF 表格提取参考

---

## 九、总结

### 9.1 改动范围评估

| 层级 | 改动量 | 说明 |
|------|--------|------|
| 数据模型 | 小 | 扩展 2 个字段，新增 4 个数据类 |
| 数据库 | 小 | 1 个迁移脚本，CRUD 函数小改 |
| 后端逻辑 | 中 | 新增 3 个模块（解析、合成、评估） |
| 前端 | 中 | 新增审核工作台 Tab，扩展编辑组件 |
| 依赖 | 小 | 新增 2 个解析库 |

### 9.2 实施路径建议

1. **Phase 1**: 数据模型 + 数据库迁移（基础）
2. **Phase 2**: 条款解析器（Word/PDF → 结构化）
3. **Phase 3**: 审核样本合成器（LLM 违规标注）
4. **Phase 4**: 审核评估器（指标计算）
5. **Phase 5**: 前端审核工作台（人工校验 UI）
6. **Phase 6**: 集成测试 + 文档

### 9.3 下一步

→ 执行 `/gen-plan` 生成技术实现方案
