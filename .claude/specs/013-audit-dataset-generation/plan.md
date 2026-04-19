# Implementation Plan: 保险产品条款审核评测数据集生成

**Branch**: `013-audit-dataset-generation` | **Date**: 2026-04-16 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

本方案实现基于真实保险产品条款的审核评测数据集生成系统，区别于现有基于法规 Chunk 的问答评测数据集。

**核心需求**（来自 spec.md）：
- FR-001/002: Word/PDF 条款解析为结构化数据
- FR-003/004: LLM 辅助生成评测样本和违规项标注
- FR-007/008: 人工审核工作台，强制 APPROVED 样本参与评测
- FR-009-011: 统一评测框架，支持审核专属指标

**技术方案**（来自 research.md）：
- 使用 `python-docx` + `pdfplumber` 解析条款
- 扩展 `eval_samples` 表支持 `sample_type` 字段
- 新增 `AuditEvaluator` 计算审核指标
- 前端新增审核工作台 Tab

---

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**:
- 现有: `lancedb`, `llama-index`, `jieba`, `rank-bm25`, `zhipu`
- 新增: `python-docx>=0.8.11`, `pdfplumber>=0.9.0`

**Storage**: SQLite (eval_samples 表扩展)
**Testing**: pytest
**Performance Goals**: 14 个产品 × 10-20 样本/产品 = 140-280 条样本
**Constraints**:
- 必须有人工校验环节（LLM 生成不可直接入库）
- 复用现有 eval_samples 表结构和评估基础设施
- 条款解析准确率 >= 90%

---

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| **Library-First** | ✅ | 复用 `python-docx`, `pdfplumber`, 现有 `RetrievalEvaluator`, `EvalSample` |
| **测试优先** | ✅ | 每个模块规划测试：`test_clause_parser.py`, `test_audit_evaluator.py` |
| **简单优先** | ✅ | 选择最简方案：扩展现有表而非新建表，复用现有评估器 |
| **显式优于隐式** | ✅ | 违规类型使用枚举 `IssueType`，样本类型使用 `sample_type` 字段 |
| **可追溯性** | ✅ | 每个 Phase 回溯到 spec.md User Story |
| **独立可测试** | ✅ | 每个 User Story 可独立测试和交付 |

---

## Project Structure

### Documentation

```text
.claude/specs/013-audit-dataset-generation/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── lib/
│   ├── eval/                           # 统一评估包（合并 rag_engine/eval_* + 审核评估）
│   │   ├── __init__.py
│   │   ├── sample.py                   # 迁移自 rag_engine/eval_dataset.py，扩展 sample_type
│   │   ├── retrieval_evaluator.py      # 迁移自 rag_engine/evaluator.py RetrievalEvaluator
│   │   ├── generation_evaluator.py     # 迁移自 rag_engine/evaluator.py GenerationEvaluator
│   │   ├── thresholds.py               # 迁移自 rag_engine/eval_rating.py（合并 eval_guide.py）
│   │   ├── qa_sample_synthesizer.py    # 迁移自 rag_engine/sample_synthesizer.py（问答样本合成）
│   │   ├── sample_validator.py         # 迁移自 rag_engine/dataset_validator.py（样本质量校验）
│   │   ├── sample_coverage.py          # 迁移自 rag_engine/dataset_coverage.py（知识库覆盖度）
│   │   ├── quality_detector.py         # 迁移自 rag_engine/quality_detector.py（质量检测）
│   │   ├── audit_models.py             # 新增：Violation, IssueType, Clause, PremiumTable
│   │   ├── clause_parser.py            # 新增：Word/PDF 条款解析器
│   │   ├── audit_sample_synthesizer.py # 新增：审核样本合成器
│   │   ├── audit_evaluator.py          # 新增：审核评估器
│   │   └── violation_matcher.py        # 新增：违规项匹配 + 法规引用验证
│   └── rag_engine/
│       └── (保留其他模块，删除 eval_*.py, sample_synthesizer.py, dataset_*.py, quality_detector.py, eval_guide.py)
├── api/
│   ├── database.py                    # 修改：迁移 + CRUD
│   └── routers/
│       └── eval.py                    # 修改：更新 import 路径
├── evaluate_rag.py                    # 修改：更新 import 路径
└── web/src/
    ├── pages/EvalPage.tsx             # 修改：新增审核工作台 Tab
    ├── components/ReviewWorkbench.tsx # 新增
    └── types.ts                       # 修改：扩展类型
```

**迁移说明**：

| 原文件 | 新位置 | 变更说明 |
|-------|--------|---------|
| `rag_engine/eval_dataset.py` | `eval/sample.py` | 重命名，业务语义更清晰 |
| `rag_engine/evaluator.py` | `eval/retrieval_evaluator.py` + `eval/generation_evaluator.py` | 拆分为两个文件，导出私有函数 |
| `rag_engine/eval_rating.py` + `eval_guide.py` | `eval/thresholds.py` | 合并两文件（eval_rating.py 更完整） |
| `rag_engine/sample_synthesizer.py` | `eval/qa_sample_synthesizer.py` | 保持不变，问答样本合成 |
| `rag_engine/dataset_validator.py` | `eval/sample_validator.py` | 重命名 |
| `rag_engine/dataset_coverage.py` | `eval/sample_coverage.py` | 重命名，依赖 `_normalize_doc_name` |
| `rag_engine/quality_detector.py` | `eval/quality_detector.py` | 保持命名，依赖 `_token_bigrams` |

**模块职责说明**：

| 模块 | 职责 |
|------|------|
| `sample.py` | 评测样本数据模型（EvalSample）、加载/保存函数 |
| `thresholds.py` | 定义评估指标阈值（优秀/良好），解读指标等级，生成评估总结 |
| `qa_sample_synthesizer.py` | 从知识库 Chunk 生成问答评测样本（现有功能） |
| `audit_sample_synthesizer.py` | 从产品条款生成审核评测样本（新增功能） |
| `sample_validator.py` | 样本质量校验：空字段、重复检测、关键词检查、审核样本专用校验 |
| `sample_coverage.py` | 知识库覆盖度评估：检查评测样本对 KB 文档的引用覆盖 |
| `quality_detector.py` | 自动质量检测：忠实度 + 检索相关性 + 信息完整性 |
| `violation_matcher.py` | 违规项匹配（加权打分）+ 法规引用验证（检查知识库中是否存在） |

**私有函数导出说明**：

以下私有函数需要导出为公共接口（供 `sample_coverage.py` 和 `quality_detector.py` 使用）：

| 私有函数 | 新公共名称 | 使用方 |
|---------|-----------|--------|
| `_normalize_doc_name` | `normalize_doc_name` | sample_coverage.py |
| `_token_bigrams` | `token_bigrams` | quality_detector.py |

**测试文件迁移**：

| 原测试文件 | 新位置 |
|-----------|--------|
| `tests/lib/rag_engine/test_eval_dataset.py` | `tests/lib/eval/test_sample.py` |
| `tests/lib/rag_engine/test_evaluator.py` | `tests/lib/eval/test_retrieval_evaluator.py` + `tests/lib/eval/test_generation_evaluator.py` |
| `tests/lib/rag_engine/test_eval_guide.py` | `tests/lib/eval/test_thresholds.py` |
| `tests/lib/rag_engine/test_synth_qa.py` | `tests/lib/eval/test_qa_sample_synthesizer.py` |
| `tests/lib/rag_engine/test_dataset_validator.py` | `tests/lib/eval/test_sample_validator.py` |
| `tests/lib/rag_engine/test_coverage.py` | `tests/lib/eval/test_sample_coverage.py` |

---

## Implementation Phases

### Phase 1: 基础设施 - 数据模型与数据库迁移

#### 需求回溯

→ 对应 spec.md FR-009: 扩展 eval_samples 表支持 sample_type 字段

#### 实现步骤

**Step 1.1: 迁移现有评估代码 + 新增数据模型**

- 文件: `scripts/lib/eval/__init__.py`
- 文件: `scripts/lib/eval/sample.py` (迁移自 rag_engine/eval_dataset.py)
- 文件: `scripts/lib/eval/audit_models.py` (新增)

```python
# scripts/lib/eval/__init__.py
from .sample import EvalSample, QuestionType, ReviewStatus, RegulationRef, load_eval_samples, save_eval_samples
from .retrieval_evaluator import RetrievalEvaluator, RetrievalEvalReport, normalize_doc_name
from .generation_evaluator import GenerationEvaluator, GenerationEvalReport
from .thresholds import EVAL_THRESHOLDS, MetricThreshold, interpret_metric, generate_eval_summary
from .qa_sample_synthesizer import SynthQA, SynthConfig, SynthResult as QASynthResult
from .sample_validator import validate_samples, validate_audit_samples, QualityReport, QualityIssue
from .sample_coverage import compute_coverage, get_kb_doc_names, CoverageReport
from .quality_detector import detect_quality, compute_retrieval_relevance, compute_info_completeness, token_bigrams
from .audit_models import IssueType, Violation, Clause, PremiumTable, AuditInput, AuditGroundTruth
from .clause_parser import parse_document, ClauseParseError
from .audit_sample_synthesizer import AuditSampleSynthesizer
from .violation_matcher import match_violations, validate_regulation_refs
from .audit_evaluator import AuditEvaluator, AuditEvalResult, AuditEvalReport

__all__ = [
    # 样本模型
    'EvalSample', 'QuestionType', 'ReviewStatus', 'RegulationRef', 'load_eval_samples', 'save_eval_samples',
    # 问答评估（迁移自 rag_engine）
    'RetrievalEvaluator', 'RetrievalEvalReport', 'normalize_doc_name',
    'GenerationEvaluator', 'GenerationEvalReport',
    'EVAL_THRESHOLDS', 'MetricThreshold', 'interpret_metric', 'generate_eval_summary',
    'SynthQA', 'SynthConfig', 'QASynthResult',
    'validate_samples', 'validate_audit_samples', 'QualityReport', 'QualityIssue',
    'compute_coverage', 'get_kb_doc_names', 'CoverageReport',
    'detect_quality', 'compute_retrieval_relevance', 'compute_info_completeness', 'token_bigrams',
    # 审核评估（新增）
    'IssueType', 'Violation', 'Clause', 'PremiumTable',
    'AuditInput', 'AuditGroundTruth',
    'parse_document', 'ClauseParseError',
    'AuditSampleSynthesizer', 'AuditEvaluator', 'AuditEvalResult', 'AuditEvalReport',
    'match_violations', 'validate_regulation_refs',
]
```

```python
# scripts/lib/eval/audit_models.py
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import json
import uuid


class IssueType(str, Enum):
    """违规类型枚举（15 种）"""
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
    # 其他
    OTHER = "other"


@dataclass(frozen=True)
class Violation:
    """违规项"""
    id: str
    clause_number: str
    clause_title: str
    issue_type: IssueType
    severity: str  # high/medium/low
    description: str
    regulation_ref: Optional[Dict[str, str]] = None  # {doc_name, article, excerpt}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'clause_number': self.clause_number,
            'clause_title': self.clause_title,
            'issue_type': self.issue_type.value,
            'severity': self.severity,
            'description': self.description,
            'regulation_ref': self.regulation_ref,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Violation':
        return cls(
            id=data['id'],
            clause_number=data['clause_number'],
            clause_title=data['clause_title'],
            issue_type=IssueType(data['issue_type']),
            severity=data['severity'],
            description=data['description'],
            regulation_ref=data.get('regulation_ref'),
        )


@dataclass(frozen=True)
class Clause:
    """条款"""
    number: str
    title: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {'number': self.number, 'title': self.title, 'text': self.text}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Clause':
        return cls(number=data['number'], title=data['title'], text=data['text'])


@dataclass(frozen=True)
class PremiumTable:
    """费率表"""
    raw_text: str
    data: List[List[str]] = field(default_factory=list)
    remark: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {'raw_text': self.raw_text, 'data': self.data, 'remark': self.remark}


@dataclass(frozen=True)
class AuditInput:
    """审核输入"""
    product: Dict[str, Any]
    clauses: List[Clause]
    premium_table: Optional[PremiumTable] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'product': self.product,
            'clauses': [c.to_dict() for c in self.clauses],
            'premium_table': self.premium_table.to_dict() if self.premium_table else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> 'AuditInput':
        data = json.loads(json_str)
        return cls(
            product=data['product'],
            clauses=[Clause.from_dict(c) for c in data['clauses']],
            premium_table=PremiumTable(**data['premium_table']) if data.get('premium_table') else None,
        )


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

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> 'AuditGroundTruth':
        data = json.loads(json_str)
        return cls(
            violations=[Violation.from_dict(v) for v in data['violations']],
            overall_result=data['overall_result'],
            risk_level=data['risk_level'],
        )
```

**Step 1.2: 数据库迁移**

- 文件: `scripts/api/database.py`

在 `_migrate_db()` 函数中新增：

```python
# 在 _migrate_db() 末尾添加
sample_cols = {row[1] for row in conn.execute("PRAGMA table_info(eval_samples)").fetchall()}

# 新增 sample_type 字段
if 'sample_type' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN sample_type TEXT NOT NULL DEFAULT 'qa'")

# 新增 audit_input_json 字段
if 'audit_input_json' not in sample_cols:
    conn.execute("ALTER TABLE eval_samples ADD COLUMN audit_input_json TEXT NOT NULL DEFAULT ''")
```

修改 `get_eval_samples()` 函数：

```python
def get_eval_samples(
    question_type: Optional[str] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    review_status: Optional[str] = None,
    sample_type: Optional[str] = None,  # 新增
) -> List[Dict]:
    clauses: list[str] = []
    params: list = []
    if question_type:
        clauses.append("question_type = ?")
        params.append(question_type)
    if difficulty:
        clauses.append("difficulty = ?")
        params.append(difficulty)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if sample_type:
        clauses.append("sample_type = ?")
        params.append(sample_type)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM eval_samples{where} ORDER BY id", params
        ).fetchall()
        return [_deserialize_json_fields(dict(r), _SAMPLE_JSON_FIELDS) for r in rows]
```

修改 `_sample_insert_values()` 和 `upsert_eval_sample()` 包含新字段。

**Step 1.3: 扩展 sample.py 支持 sample_type**

- 文件: `scripts/lib/eval/sample.py`

在迁移 `rag_engine/eval_dataset.py` 时，扩展 `EvalSample`：

```python
# 在 EvalSample dataclass 中添加
sample_type: str = "qa"  # "qa" | "audit"
audit_input_json: str = ""  # 审核样本专用：产品条款 JSON

# 添加 REJECTED 状态
class ReviewStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"  # 新增
```

**Step 1.4: 扩展 sample_validator.py 支持审核样本校验**

- 文件: `scripts/lib/eval/sample_validator.py`

在迁移 `rag_engine/dataset_validator.py` 时，新增审核样本专用校验函数：

```python
# 新增审核样本校验函数

def validate_audit_samples(samples: List[EvalSample]) -> QualityReport:
    """
    审核样本专用校验
    
    校验项：
    1. audit_input_json 字段有效性（JSON 可解析、clauses 非空）
    2. ground_truth 格式正确（violations 数组、overall_result、risk_level）
    3. 违规项字段完整性（clause_number, issue_type, severity, description）
    4. 违规描述长度 >= 15 字
    5. IssueType 枚举值有效
    6. severity 值有效（high/medium/low）
    """
    from .audit_models import IssueType, AuditInput, AuditGroundTruth
    
    issues: List[QualityIssue] = []
    
    for sample in samples:
        if sample.sample_type != 'audit':
            continue
        
        # 1. 校验 audit_input_json
        if not sample.audit_input_json:
            issues.append(QualityIssue(sample.id, 'missing_field', 'error', 'audit_input_json 为空'))
        else:
            try:
                audit_input = AuditInput.from_json(sample.audit_input_json)
                if not audit_input.clauses:
                    issues.append(QualityIssue(sample.id, 'empty_field', 'error', 'clauses 为空'))
                if not audit_input.product.get('name'):
                    issues.append(QualityIssue(sample.id, 'missing_field', 'warning', 'product.name 为空'))
            except json.JSONDecodeError as e:
                issues.append(QualityIssue(sample.id, 'invalid_json', 'error', f'audit_input_json 解析失败: {e}'))
            except KeyError as e:
                issues.append(QualityIssue(sample.id, 'invalid_format', 'error', f'audit_input_json 格式错误: 缺少 {e}'))
        
        # 2. 校验 ground_truth 格式
        if not sample.ground_truth:
            issues.append(QualityIssue(sample.id, 'empty_field', 'error', 'ground_truth 为空'))
        else:
            try:
                gt = AuditGroundTruth.from_json(sample.ground_truth)
                
                # 3. 校验违规项字段
                for v in gt.violations:
                    if not v.clause_number:
                        issues.append(QualityIssue(sample.id, 'missing_field', 'warning', f'违规项 {v.id} 缺少 clause_number'))
                    
                    if not v.description or len(v.description) < 15:
                        issues.append(QualityIssue(sample.id, 'short_description', 'warning', 
                            f'违规项 {v.id} 描述过短（<15字）: {v.description[:20]}...'))
                    
                    # 5. 校验 IssueType 枚举
                    try:
                        IssueType(v.issue_type.value)
                    except ValueError:
                        issues.append(QualityIssue(sample.id, 'invalid_enum', 'error', 
                            f'违规项 {v.id} issue_type 无效: {v.issue_type}'))
                    
                    # 6. 校验 severity
                    if v.severity not in ('high', 'medium', 'low'):
                        issues.append(QualityIssue(sample.id, 'invalid_severity', 'error', 
                            f'违规项 {v.id} severity 无效: {v.severity}'))
                
                # 校验 overall_result
                if gt.overall_result not in ('pass', 'conditional_pass', 'fail'):
                    issues.append(QualityIssue(sample.id, 'invalid_value', 'warning', 
                        f'overall_result 无效: {gt.overall_result}'))
                
                # 校验 risk_level
                if gt.risk_level not in ('low', 'medium', 'high'):
                    issues.append(QualityIssue(sample.id, 'invalid_value', 'warning', 
                        f'risk_level 无效: {gt.risk_level}'))
                        
            except json.JSONDecodeError as e:
                issues.append(QualityIssue(sample.id, 'invalid_json', 'error', f'ground_truth 解析失败: {e}'))
            except Exception as e:
                issues.append(QualityIssue(sample.id, 'invalid_format', 'error', f'ground_truth 格式错误: {e}'))
    
    # 复用现有的分布统计逻辑
    type_dist: Dict[str, int] = {}
    diff_dist: Dict[str, int] = {}
    topic_dist: Dict[str, int] = {}
    for s in samples:
        if s.sample_type == 'audit':
            type_dist['audit'] = type_dist.get('audit', 0) + 1
        else:
            type_dist[s.question_type.value] = type_dist.get(s.question_type.value, 0) + 1
        diff_dist[s.difficulty] = diff_dist.get(s.difficulty, 0) + 1
        if s.topic:
            topic_dist[s.topic] = topic_dist.get(s.topic, 0) + 1

    error_count = sum(1 for i in issues if i.severity == 'error')
    return QualityReport(
        total_samples=len(samples),
        valid_samples=len(samples) - error_count,
        issues=issues,
        distribution={
            'by_type': type_dist,
            'by_difficulty': diff_dist,
            'by_topic': topic_dist,
        },
    )


# 统一入口函数，自动根据 sample_type 选择校验逻辑
def validate_samples(samples: List[EvalSample]) -> QualityReport:
    """统一样本校验入口，自动识别问答/审核样本"""
    audit_samples = [s for s in samples if getattr(s, 'sample_type', 'qa') == 'audit']
    qa_samples = [s for s in samples if getattr(s, 'sample_type', 'qa') == 'qa']
    
    # 分别校验
    qa_report = _validate_qa_samples(qa_samples) if qa_samples else None
    audit_report = validate_audit_samples(audit_samples) if audit_samples else None
    
    # 合并报告
    if qa_report and audit_report:
        return QualityReport(
            total_samples=qa_report.total_samples + audit_report.total_samples,
            valid_samples=qa_report.valid_samples + audit_report.valid_samples,
            issues=qa_report.issues + audit_report.issues,
            distribution={
                'qa': qa_report.distribution,
                'audit': audit_report.distribution,
            },
        )
    return qa_report or audit_report or QualityReport(total_samples=0, valid_samples=0, issues=[])
```

**Step 1.5: 单元测试**

- 文件: `scripts/tests/lib/eval/test_audit_models.py`

```python
import pytest
from lib.eval.audit_models import IssueType, Violation, Clause, AuditInput, AuditGroundTruth


def test_issue_type_enum():
    assert IssueType.INVALID_WAITING_PERIOD.value == "invalid_waiting_period"
    assert IssueType.INCOMPLETE_COVERAGE.value == "incomplete_coverage"


def test_violation_to_dict():
    v = Violation(
        id="V001",
        clause_number="第七条",
        clause_title="保险责任",
        issue_type=IssueType.INCOMPLETE_COVERAGE,
        severity="medium",
        description="重大疾病定义未包含28种必保重疾",
        regulation_ref={"doc_name": "《重大疾病保险的疾病定义使用规范》", "article": "第四条"},
    )
    d = v.to_dict()
    assert d['issue_type'] == "incomplete_coverage"
    assert d['clause_number'] == "第七条"

    # 反序列化
    v2 = Violation.from_dict(d)
    assert v2.issue_type == IssueType.INCOMPLETE_COVERAGE


def test_audit_input_json():
    clauses = [Clause(number="第一条", title="保险合同构成", text="本保险合同由...")]
    audit_input = AuditInput(
        product={"name": "测试产品", "category": "critical_illness"},
        clauses=clauses,
    )
    json_str = audit_input.to_json()
    recovered = AuditInput.from_json(json_str)
    assert recovered.clauses[0].number == "第一条"
```

---

### Phase 2: Core - 条款解析器 (User Story 1)

#### 需求回溯

→ 对应 spec.md User Story 1: 条款解析与评测样本生成 (P1)
→ FR-001: 支持 Word (.docx) 和 PDF 格式解析
→ FR-002: 条款解析为结构化数据

#### 真实保险产品文档分析

基于 `/mnt/d/work/actuary-assets/products/` 目录下 24 个真实保险产品文件的分析：

| 格式 | 数量 | 说明 |
|------|------|------|
| `.docx` | 11 | 可直接解析 |
| `.doc` | 9 | 需预处理转换（OLE2 格式，python-docx 不支持） |
| `.pdf` | 3 | 可直接解析 |

**产品类型分布**：医疗险 (8)、重疾险 (4)、护理险 (4)、意外险 (3)、残疾险 (2)、年金险 (1)、附加险 (1)

**关键发现**：

1. **条款编号格式**：真实保险条款使用阿拉伯数字层级编号（1, 1.1, 2.3.2），**不是**中文"第X条"
2. **内容位置**：DOCX 文件中，条款内容主要在**表格**中（8-15 个空段落，2-3 个内容表格）
3. **标题/正文混合**：约 41% 的条款标题和正文混在同一单元格中，需要算法分离
4. **费率表检测**：可通过表头关键词（年龄、费率、保费、周岁、性别）识别

#### 实现步骤

**Step 2.1: 文档解析器（适配真实格式）**

- 文件: `scripts/lib/eval/clause_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险产品条款解析器

适配真实保险产品文档格式：
- 条款编号：阿拉伯数字层级编号（1, 1.1, 2.3.2）
- 内容位置：主要在表格中，非段落
- 标题/正文：约 41% 混合，需要算法分离

不支持 .doc 格式（OLE2），需预处理转换为 .docx 或 .pdf。
"""
import re
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from .audit_models import Clause, PremiumTable

logger = logging.getLogger(__name__)

# 条款编号正则（阿拉伯数字层级编号）
# 真实保险条款格式：1, 1.1, 2.3.2 等
CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s*$')

# 费率表关键词
PREMIUM_TABLE_KEYWORDS = {'年龄', '费率', '保费', '周岁', '性别', '缴费', '保额'}

# 非条款表格关键词（用于过滤）
NON_CLAUSE_TABLE_KEYWORDS = {'公司', '地址', '电话', '邮编', '客服', '网址', '资质'}


class ClauseParseError(Exception):
    """条款解析错误"""
    pass


@dataclass
class ParseResult:
    """解析结果"""
    clauses: List[Clause]
    premium_table: Optional[PremiumTable]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'clauses': [c.to_dict() for c in self.clauses],
            'premium_table': self.premium_table.to_dict() if self.premium_table else None,
            'metadata': self.metadata,
        }


def parse_document(file_path: str) -> ParseResult:
    """
    统一文档解析入口

    支持 .docx 和 .pdf 格式。.doc 格式需预处理。

    Args:
        file_path: 文档文件路径

    Returns:
        ParseResult

    Raises:
        ClauseParseError: 解析失败
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if not path.exists():
        raise ClauseParseError(f"文件不存在: {file_path}")

    if suffix == '.docx':
        clauses, premium_table = _parse_docx(file_path)
    elif suffix == '.pdf':
        clauses, premium_table = _parse_pdf(file_path)
    elif suffix == '.doc':
        raise ClauseParseError(
            f".doc 格式不支持，请转换为 .docx 或 .pdf: {file_path}\n"
            "转换方法: libreoffice --headless --convert-to docx input.doc"
        )
    else:
        raise ClauseParseError(f"不支持的文件格式: {suffix}")

    # 按编号排序
    clauses = _sort_clauses_by_number(clauses)

    metadata = {
        'file_name': path.name,
        'file_type': suffix,
        'clause_count': len(clauses),
        'has_premium_table': premium_table is not None,
    }

    logger.info(f"解析完成: {path.name} -> {len(clauses)} 条款, 费率表: {premium_table is not None}")
    return ParseResult(clauses=clauses, premium_table=premium_table, metadata=metadata)


def _parse_docx(file_path: str) -> Tuple[List[Clause], Optional[PremiumTable]]:
    """Word 文档解析（条款内容在表格中）"""
    try:
        from docx import Document
    except ImportError:
        raise ClauseParseError("python-docx 未安装，请执行: pip install python-docx")

    try:
        doc = Document(file_path)
    except Exception as e:
        raise ClauseParseError(f"Word 文件打开失败: {e}")

    # 从表格提取条款（主要内容在表格中）
    clauses = _extract_clauses_from_docx_tables(doc.tables)
    premium_table = _extract_premium_from_docx_tables(doc.tables)

    return clauses, premium_table


def _extract_clauses_from_docx_tables(tables) -> List[Clause]:
    """
    从 Word 表格提取条款

    适配真实保险条款格式：
    - 编号在第一列（阿拉伯数字）
    - 内容在第二列（标题和正文可能混合）
    """
    clauses = []
    seen_numbers = set()

    for table in tables:
        # 先检查是否为非条款表格
        if _is_non_clause_table(table):
            continue

        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) < 2:
                continue

            number_cell = cells[0].strip()
            content_cell = cells[1].strip() if len(cells) > 1 else ""

            # 检查是否为条款编号（阿拉伯数字）
            if not CLAUSE_NUMBER_PATTERN.match(number_cell):
                continue

            if number_cell in seen_numbers:
                continue
            seen_numbers.add(number_cell)

            # 分离标题和正文
            title, text = _separate_title_and_text(content_cell)

            clauses.append(Clause(
                number=number_cell,
                title=title,
                text=text,
            ))

    return clauses


def _separate_title_and_text(content: str) -> Tuple[str, str]:
    """
    分离标题和正文

    策略（按优先级）：
    1. 如果有换行符，第一行为标题
    2. 如果有句号，第一句为标题
    3. 否则全部作为标题（短内容）
    """
    if not content:
        return "", ""

    # 策略 1: 换行符分隔
    lines = content.split('\n')
    if len(lines) > 1:
        title = lines[0].strip()
        text = '\n'.join(lines[1:]).strip()
        return title, text

    # 策略 2: 句号分隔（标题通常是短句）
    if '。' in content:
        parts = content.split('。', 1)
        title = parts[0].strip()
        # 标题太长（>30字）可能是正文，不分隔
        if len(title) > 30:
            return content, ""
        text = parts[1].strip() if len(parts) > 1 else ""
        return title, text

    # 策略 3: 全部作为标题
    return content, ""


def _is_non_clause_table(table) -> bool:
    """检查是否为非条款表格（如公司信息表）"""
    # 合并所有单元格文本
    all_text = ""
    for row in table.rows:
        for cell in row.cells:
            all_text += cell.text + " "

    # 检查非条款关键词
    for kw in NON_CLAUSE_TABLE_KEYWORDS:
        if kw in all_text:
            return True

    return False


def _extract_premium_from_docx_tables(tables) -> Optional[PremiumTable]:
    """从 Word 表格提取费率表"""
    for table in tables:
        rows_data = []
        for row in table.rows:
            row_text = [cell.text.strip() for cell in row.cells]
            rows_data.append(row_text)

        # 检测是否为费率表
        if rows_data and len(rows_data) > 1:
            header = ' '.join(rows_data[0])
            if any(kw in header for kw in PREMIUM_TABLE_KEYWORDS):
                raw_text = '\n'.join([' | '.join(row) for row in rows_data])
                return PremiumTable(raw_text=raw_text, data=rows_data)

    return None


def _parse_pdf(file_path: str) -> Tuple[List[Clause], Optional[PremiumTable]]:
    """PDF 文档解析"""
    try:
        import pdfplumber
    except ImportError:
        raise ClauseParseError("pdfplumber 未安装，请执行: pip install pdfplumber")

    try:
        with pdfplumber.open(file_path) as pdf:
            clauses = []
            premium_table = None
            seen_numbers = set()

            for page_num, page in enumerate(pdf.pages):
                # 从表格提取条款
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if not row or len(row) < 2:
                            continue

                        number_cell = str(row[0]).strip() if row[0] else ""
                        content_cell = str(row[1]).strip() if len(row) > 1 and row[1] else ""

                        if CLAUSE_NUMBER_PATTERN.match(number_cell):
                            if number_cell in seen_numbers:
                                continue
                            seen_numbers.add(number_cell)

                            title, text = _separate_title_and_text(content_cell)

                            clauses.append(Clause(
                                number=number_cell,
                                title=title,
                                text=text,
                            ))

                if premium_table is None:
                    premium_table = _extract_premium_from_pdf_page(page)

            return clauses, premium_table
    except Exception as e:
        raise ClauseParseError(f"PDF 解析失败: {e}")


def _extract_premium_from_pdf_page(page) -> Optional[PremiumTable]:
    """从 PDF 页面提取费率表"""
    tables = page.extract_tables()
    if not tables:
        return None

    for table in tables:
        if not table or len(table) < 2:
            continue

        cleaned = [[str(cell).strip() if cell else '' for cell in row] for row in table]
        header = ' '.join(cleaned[0])

        if any(kw in header for kw in PREMIUM_TABLE_KEYWORDS):
            raw_text = '\n'.join([' | '.join(row) for row in cleaned])
            return PremiumTable(raw_text=raw_text, data=cleaned)

    return None


def _sort_clauses_by_number(clauses: List[Clause]) -> List[Clause]:
    """按条款编号排序"""
    def sort_key(c: Clause) -> Tuple[int, ...]:
        parts = c.number.split('.')
        return tuple(int(p) for p in parts)

    return sorted(clauses, key=sort_key)
```

**Step 2.2: 单元测试**

- 文件: `scripts/tests/lib/eval/test_clause_parser.py`

```python
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from lib.eval.clause_parser import (
    parse_document,
    ClauseParseError,
    _separate_title_and_text,
    _is_non_clause_table,
    CLAUSE_NUMBER_PATTERN,
)


class TestClauseNumberPattern:
    """条款编号正则测试"""

    def test_matches_simple_number(self):
        assert CLAUSE_NUMBER_PATTERN.match("1")
        assert CLAUSE_NUMBER_PATTERN.match("10")
        assert CLAUSE_NUMBER_PATTERN.match("99")

    def test_matches_hierarchical_number(self):
        assert CLAUSE_NUMBER_PATTERN.match("1.1")
        assert CLAUSE_NUMBER_PATTERN.match("2.3.2")
        assert CLAUSE_NUMBER_PATTERN.match("10.2.5.3")

    def test_matches_with_trailing_space(self):
        assert CLAUSE_NUMBER_PATTERN.match("1 ")
        assert CLAUSE_NUMBER_PATTERN.match("2.3 ")

    def test_rejects_chinese_format(self):
        # 真实保险条款使用阿拉伯数字，不使用中文"第X条"
        assert not CLAUSE_NUMBER_PATTERN.match("第一条")
        assert not CLAUSE_NUMBER_PATTERN.match("第七条")

    def test_rejects_text_prefix(self):
        assert not CLAUSE_NUMBER_PATTERN.match("条款1")
        assert not CLAUSE_NUMBER_PATTERN.match("第1条")


class TestSeparateTitleAndText:
    """标题/正文分离测试"""

    def test_newline_separation(self):
        title, text = _separate_title_and_text("保险责任\n本合同承担以下保险责任...")
        assert title == "保险责任"
        assert text == "本合同承担以下保险责任..."

    def test_period_separation(self):
        title, text = _separate_title_and_text("保险责任。本合同承担以下保险责任...")
        assert title == "保险责任"
        assert text == "本合同承担以下保险责任..."

    def test_long_title_no_separation(self):
        # 标题超过30字不分隔
        long_title = "这是一个非常长的标题内容超过了三十个字符的限制不应该被分隔"
        title, text = _separate_title_and_text(long_title)
        assert title == long_title
        assert text == ""

    def test_short_content(self):
        title, text = _separate_title_and_text("保险责任")
        assert title == "保险责任"
        assert text == ""

    def test_empty_content(self):
        title, text = _separate_title_and_text("")
        assert title == ""
        assert text == ""


class TestNonClauseTableDetection:
    """非条款表格检测测试"""

    def test_company_info_table(self):
        mock_table = Mock()
        mock_table.rows = []
        # 模拟公司信息表格
        mock_cell = Mock()
        mock_cell.text = "公司地址：北京市朝阳区"
        mock_row = Mock()
        mock_row.cells = [mock_cell]
        mock_table.rows = [mock_row]
        
        assert _is_non_clause_table(mock_table) is True

    def test_clause_table(self):
        mock_table = Mock()
        mock_cell1 = Mock()
        mock_cell1.text = "1"
        mock_cell2 = Mock()
        mock_cell2.text = "保险责任"
        mock_row = Mock()
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table.rows = [mock_row]
        
        assert _is_non_clause_table(mock_table) is False


class TestParseDocument:
    """文档解析测试"""

    def test_unsupported_format(self):
        with pytest.raises(ClauseParseError, match="不支持的文件格式"):
            parse_document("test.txt")

    def test_not_exist(self):
        with pytest.raises(ClauseParseError, match="文件不存在"):
            parse_document("/nonexistent/path.docx")

    def test_doc_format_rejected(self):
        """ .doc 格式应该被拒绝，并提示转换方法"""
        with pytest.raises(ClauseParseError, match=".doc 格式不支持"):
            parse_document("test.doc")


# 集成测试需要实际文件，标记为 slow
@pytest.mark.slow
class TestRealDocumentParsing:
    """真实文档解析测试"""

    def test_parse_real_docx(self):
        """测试实际 Word 文件解析"""
        # 使用第一个可用的 docx 文件
        products_dir = Path("/mnt/d/work/actuary-assets/products/")
        docx_files = list(products_dir.glob("*.docx"))
        
        if not docx_files:
            pytest.skip("无测试文件")
        
        file_path = str(docx_files[0])
        result = parse_document(file_path)
        
        assert result.clauses, f"未解析到条款: {file_path}"
        assert result.metadata['clause_count'] > 0
        assert result.metadata['file_type'] == '.docx'
        
        # 验证条款编号格式
        first_clause = result.clauses[0]
        assert first_clause.number.split('.')[0].isdigit(), \
            f"条款编号格式错误: {first_clause.number}"
        
        # 验证条款内容
        for clause in result.clauses[:5]:  # 检查前5条
            assert clause.number, "条款编号为空"
            assert clause.title or clause.text, f"条款 {clause.number} 内容为空"

    def test_parse_real_pdf(self):
        """测试实际 PDF 文件解析"""
        products_dir = Path("/mnt/d/work/actuary-assets/products/")
        pdf_files = list(products_dir.glob("*.pdf"))
        
        if not pdf_files:
            pytest.skip("无 PDF 测试文件")
        
        file_path = str(pdf_files[0])
        result = parse_document(file_path)
        
        assert result.clauses or result.premium_table, \
            f"未解析到任何内容: {file_path}"
```

**Step 2.3: .doc 文件预处理脚本**

由于 `python-docx` 不支持 OLE2 格式的 .doc 文件，需要预处理：

- 文件: `scripts/tools/convert_doc_to_docx.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
.doc 文件转换为 .docx

python-docx 不支持 OLE2 格式的 .doc 文件，需要转换为 .docx。

方法 1: LibreOffice (推荐，跨平台)
    libreoffice --headless --convert-to docx input.doc

方法 2: Windows COM (仅 Windows + Word)
    python convert_doc_to_docx.py input.doc
"""
import subprocess
import sys
from pathlib import Path


def convert_with_libreoffice(doc_path: str, output_dir: str = None) -> str:
    """使用 LibreOffice 转换"""
    output = output_dir or str(Path(doc_path).parent)
    cmd = [
        'libreoffice',
        '--headless',
        '--convert-to', 'docx',
        '--outdir', output,
        doc_path,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")
    
    docx_path = Path(output) / (Path(doc_path).stem + '.docx')
    return str(docx_path)


def convert_with_word_com(doc_path: str) -> str:
    """使用 Windows Word COM 转换（仅 Windows）"""
    import win32com.client
    
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    
    doc = word.Documents.Open(str(Path(doc_path).absolute()))
    docx_path = str(Path(doc_path).with_suffix('.docx'))
    
    # 16 = wdFormatXMLDocument (.docx)
    doc.SaveAs2(docx_path, FileFormat=16)
    doc.Close()
    word.Quit()
    
    return docx_path


def main():
    if len(sys.argv) < 2:
        print("用法: python convert_doc_to_docx.py <input.doc> [output_dir]")
        sys.exit(1)
    
    doc_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        # 优先使用 LibreOffice
        docx_path = convert_with_libreoffice(doc_path, output_dir)
        print(f"转换成功: {docx_path}")
    except Exception as e:
        print(f"LibreOffice 转换失败: {e}")
        print("尝试 Windows Word COM...")
        try:
            docx_path = convert_with_word_com(doc_path)
            print(f"转换成功: {docx_path}")
        except Exception as e2:
            print(f"转换失败: {e2}")
            sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2.4: 批量转换命令**

```bash
# 转换单个文件
python scripts/tools/convert_doc_to_docx.py /mnt/d/work/actuary-assets/products/某产品.doc

# 批量转换（使用 LibreOffice）
cd /mnt/d/work/actuary-assets/products/
libreoffice --headless --convert-to docx *.doc
```

---

### Phase 3: Core - 审核样本合成器 (User Story 2)

#### 需求回溯

→ 对应 spec.md User Story 2: 违规项 LLM 辅助标注 (P1)
→ FR-003: LLM 为每个产品生成 10-20 条评测样本
→ FR-004: 生成候选违规项列表

#### 实现步骤

**Step 3.1: 审核样本合成器**

- 文件: `scripts/lib/eval/audit_sample_synthesizer.py`

```python
import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .audit_models import Clause, PremiumTable, AuditInput, AuditGroundTruth, Violation, IssueType
from .clause_parser import parse_document, ClauseParseError

logger = logging.getLogger(__name__)


_AUDIT_SYNTH_PROMPT = """你是一个保险产品审核专家。根据以下产品条款，识别潜在违规项。

产品信息：
- 名称：{product_name}
- 类型：{product_type}

条款内容（共 {clause_count} 条）：
{clauses_text}

请识别条款中的潜在违规项，输出 JSON 数组格式：
[
  {{
    "clause_number": "条款编号，如第七条",
    "clause_title": "条款标题",
    "issue_type": "违规类型（见下方枚举）",
    "severity": "high/medium/low",
    "description": "违规描述（>=15字，包含具体问题）",
    "regulation_doc_name": "相关法规名称",
    "regulation_article": "法规条款编号",
    "regulation_excerpt": "法规原文摘要（可选）"
  }}
]

违规类型枚举（选择最匹配的一个）：
- invalid_waiting_period: 等待期设置违规（如超过监管规定的90天）
- invalid_exclusion_clause: 免责条款违规（如免责范围过宽）
- missing_mandatory_clause: 缺少必含条款（如缺少犹豫期条款）
- ambiguous_definition: 定义模糊不清（如术语未明确定义）
- unreasonable_premium: 费率不合理（如偏离风险保费）
- invalid_pricing_method: 定价方法不规范
- incomplete_coverage: 保障责任不完整（如重疾种类不足）
- invalid_coverage_limit: 保障限额设置不当
- scope_boundary_unclear: 责任边界不清晰
- invalid_age_range: 投保年龄范围违规
- invalid_period: 保险期间设置不当
- clause_numbering_error: 条款编号不规范
- missing_clause_element: 条款要素缺失

判断要点：
1. 重大疾病保险应包含28种必保重疾
2. 医疗保险等待期一般不超过90天
3. 意外伤害保险应有明确的意外定义
4. 免责条款不得排除法定责任
5. 投保年龄范围应符合产品类型要求

如条款完全合规，输出空数组 []。
仅输出 JSON 数组，不要输出其他内容。"""


@dataclass
class SynthResult:
    """合成结果"""
    product_name: str
    total_samples: int = 0
    valid_samples: int = 0
    samples: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AuditSampleSynth:
    """审核样本合成器"""

    def __init__(self, kb_summary: str = ""):
        """
        Args:
            kb_summary: 法规知识库摘要（可选，用于增强 LLM 判断）
        """
        self.kb_summary = kb_summary

    def synthesize_from_file(
        self,
        file_path: str,
        product_name: str,
        product_type: str,
        samples_per_product: int = 15,
    ) -> SynthResult:
        """
        从产品条款文件生成评测样本

        Args:
            file_path: 条款文件路径（.docx 或 .pdf）
            product_name: 产品名称
            product_type: 产品类型（critical_illness, medical_insurance 等）
            samples_per_product: 每个产品生成的样本数

        Returns:
            SynthResult
        """
        result = SynthResult(product_name=product_name)

        # 解析条款
        try:
            clauses, premium_table = parse_document(file_path)
        except ClauseParseError as e:
            result.errors.append(f"条款解析失败: {e}")
            return result

        if not clauses:
            result.errors.append("未解析到任何条款")
            return result

        # 构建 AuditInput
        audit_input = AuditInput(
            product={'name': product_name, 'type': product_type},
            clauses=clauses,
            premium_table=premium_table,
        )

        # LLM 生成违规项
        violations = self._generate_violations(
            product_name=product_name,
            product_type=product_type,
            clauses=clauses,
            premium_table=premium_table,
        )

        # 构建评测样本
        sample = self._build_sample(
            audit_input=audit_input,
            violations=violations,
            product_name=product_name,
            product_type=product_type,
        )

        if sample:
            result.samples.append(sample)
            result.valid_samples = 1
        result.total_samples = 1

        return result

    def _generate_violations(
        self,
        product_name: str,
        product_type: str,
        clauses: List[Clause],
        premium_table: Optional[PremiumTable],
    ) -> List[Violation]:
        """LLM 生成违规项"""
        from lib.llm.factory import LLMClientFactory

        # 构建条款文本
        clauses_text = '\n\n'.join([
            f"【{c.number}】{c.title}\n{c.text[:500]}"
            for c in clauses[:20]  # 限制长度
        ])

        prompt = _AUDIT_SYNTH_PROMPT.format(
            product_name=product_name,
            product_type=product_type,
            clause_count=len(clauses),
            clauses_text=clauses_text,
        )

        try:
            llm = LLMClientFactory.create_audit_llm()
            response = llm.generate(prompt)
            return self._parse_violations(response)
        except Exception as e:
            logger.warning(f"LLM 违规项生成失败: {e}")
            return []

    def _parse_violations(self, response: str) -> List[Violation]:
        """解析 LLM 返回的违规项"""
        from lib.rag_engine.preprocessor import _extract_json_array

        json_str = _extract_json_array(response)
        if not json_str:
            return []

        try:
            items = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        violations = []
        for item in items:
            try:
                regulation_ref = None
                if item.get('regulation_doc_name'):
                    regulation_ref = {
                        'doc_name': item['regulation_doc_name'],
                        'article': item.get('regulation_article', ''),
                        'excerpt': item.get('regulation_excerpt', ''),
                    }

                v = Violation(
                    id=f"V_{uuid.uuid4().hex[:8]}",
                    clause_number=item['clause_number'],
                    clause_title=item.get('clause_title', ''),
                    issue_type=IssueType(item['issue_type']),
                    severity=item.get('severity', 'medium'),
                    description=item['description'],
                    regulation_ref=regulation_ref,
                )
                violations.append(v)
            except (KeyError, ValueError) as e:
                logger.debug(f"违规项解析跳过: {e}")
                continue

        return violations

    def _build_sample(
        self,
        audit_input: AuditInput,
        violations: List[Violation],
        product_name: str,
        product_type: str,
    ) -> Optional[Dict[str, Any]]:
        """构建评测样本"""
        # 计算审核结论
        if not violations:
            overall_result = "pass"
            risk_level = "low"
        else:
            high_count = sum(1 for v in violations if v.severity == 'high')
            if high_count > 0:
                overall_result = "fail"
                risk_level = "high"
            else:
                overall_result = "conditional_pass"
                risk_level = "medium"

        ground_truth = AuditGroundTruth(
            violations=violations,
            overall_result=overall_result,
            risk_level=risk_level,
        )

        # 提取法规引用
        regulation_refs = []
        for v in violations:
            if v.regulation_ref:
                regulation_refs.append(v.regulation_ref)

        # 确定难度
        difficulty = "medium"
        if len(violations) == 0:
            difficulty = "easy"
        elif any(v.severity == 'high' for v in violations):
            difficulty = "hard"

        return {
            'id': f"audit_{uuid.uuid4().hex[:8]}",
            'question': product_name,  # 审核样本用 question 存储产品名称
            'ground_truth': ground_truth.to_json(),
            'evidence_docs': [],
            'evidence_keywords': [product_type],
            'question_type': 'factual',
            'difficulty': difficulty,
            'topic': product_type,
            'regulation_refs': regulation_refs,
            'review_status': 'pending',
            'created_by': 'llm',
            'sample_type': 'audit',
            'audit_input_json': audit_input.to_json(),
        }
```

**Step 3.2: 单元测试**

- 文件: `scripts/tests/lib/eval/test_audit_sample_synth.py`

```python
import pytest
from unittest.mock import Mock, patch
from lib.eval.audit_sample_synth import AuditSampleSynth, _AUDIT_SYNTH_PROMPT


def test_synth_prompt_contains_product_info():
    prompt = _AUDIT_SYNTH_PROMPT.format(
        product_name="测试产品",
        product_type="critical_illness",
        clause_count=10,
        clauses_text="测试条款内容",
    )
    assert "测试产品" in prompt
    assert "critical_illness" in prompt
    assert "10 条" in prompt


def test_parse_violations_empty():
    synth = AuditSampleSynth()
    violations = synth._parse_violations("[]")
    assert violations == []


def test_parse_violations_valid():
    synth = AuditSampleSynth()
    response = '''
    [
        {
            "clause_number": "第七条",
            "clause_title": "保险责任",
            "issue_type": "incomplete_coverage",
            "severity": "medium",
            "description": "重大疾病定义未包含28种必保重疾",
            "regulation_doc_name": "《重大疾病保险的疾病定义使用规范》",
            "regulation_article": "第四条"
        }
    ]
    '''
    violations = synth._parse_violations(response)
    assert len(violations) == 1
    assert violations[0].clause_number == "第七条"
    assert violations[0].issue_type.value == "incomplete_coverage"
```

---

### Phase 4: Core - 审核评估器 (User Story 4)

#### 需求回溯

→ 对应 spec.md User Story 4: 统一评测框架 (P1)
→ FR-010: 统一评估引擎，根据 sample_type 计算不同指标
→ FR-011: 审核专属指标

#### 实现步骤

**Step 4.1: 违规项匹配器与验证器**

- 文件: `scripts/lib/eval/violation_matcher.py`

```python
from typing import List, Tuple, Dict, Any, Optional
from .audit_models import Violation


def match_violations(
    predictions: List[Violation],
    ground_truths: List[Violation],
) -> List[Tuple[Violation, Violation, float]]:
    """
    匹配预测违规项与标注违规项

    Returns:
        List of (predicted, ground_truth, match_score) tuples
    """
    matched = []
    used_gt = set()

    for pred in predictions:
        best_match = None
        best_score = 0.0
        best_idx = -1

        for i, gt in enumerate(ground_truths):
            if i in used_gt:
                continue

            score = _compute_match_score(pred, gt)
            if score > best_score:
                best_score = score
                best_match = gt
                best_idx = i

        if best_match and best_score >= 0.5:
            matched.append((pred, best_match, best_score))
            used_gt.add(best_idx)

    return matched


def _compute_match_score(pred: Violation, gt: Violation) -> float:
    """计算匹配分数（0-1）"""
    score = 0.0

    # 条款编号匹配（权重 0.4）
    if pred.clause_number == gt.clause_number:
        score += 0.4

    # 类型匹配（权重 0.3）
    if pred.issue_type == gt.issue_type:
        score += 0.3

    # 描述相似度（权重 0.3）
    from lib.rag_engine.tokenizer import tokenize_chinese
    pred_tokens = set(tokenize_chinese(pred.description))
    gt_tokens = set(tokenize_chinese(gt.description))
    if pred_tokens and gt_tokens:
        overlap = len(pred_tokens & gt_tokens) / len(pred_tokens | gt_tokens)
        score += 0.3 * overlap

    return score


def validate_regulation_refs(
    violations: List[Violation],
    kb_manager=None,
) -> Dict[str, List[str]]:
    """
    验证违规项的法规引用是否在知识库中存在

    Args:
        violations: 违规项列表
        kb_manager: 知识库管理器（可选，用于验证引用）

    Returns:
        {
            'valid': [violation_id, ...],  # 引用存在的违规项
            'invalid': [violation_id, ...],  # 引用不存在的违规项
            'missing_ref': [violation_id, ...],  # 无引用的违规项
        }
    """
    result = {'valid': [], 'invalid': [], 'missing_ref': []}

    for v in violations:
        if not v.regulation_ref:
            result['missing_ref'].append(v.id)
            continue

        doc_name = v.regulation_ref.get('doc_name', '')
        article = v.regulation_ref.get('article', '')

        if not doc_name:
            result['missing_ref'].append(v.id)
            continue

        # 如果提供了 kb_manager，验证引用是否存在
        if kb_manager:
            if _check_regulation_exists(kb_manager, doc_name, article):
                result['valid'].append(v.id)
            else:
                result['invalid'].append(v.id)
        else:
            # 无 kb_manager 时，仅检查字段完整性
            if doc_name and article:
                result['valid'].append(v.id)
            else:
                result['invalid'].append(v.id)

    return result


def _check_regulation_exists(kb_manager, doc_name: str, article: str) -> bool:
    """检查法规引用是否在知识库中存在"""
    try:
        from .kb_manager import KBManager
        if isinstance(kb_manager, KBManager):
            # 使用知识库搜索验证
            query = f"{doc_name} {article}"
            results = kb_manager.search(query, top_k=1)
            return len(results) > 0
    except Exception:
        pass
    return True  # 验证失败时默认通过
```

**Step 4.2: 审核评估器**

- 文件: `scripts/lib/eval/audit_evaluator.py`

```python
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from .audit_models import Violation, AuditGroundTruth
from .violation_matcher import match_violations

logger = logging.getLogger(__name__)


@dataclass
class AuditEvalResult:
    """单条审核样本评估结果"""
    sample_id: str
    violation_precision: float
    violation_recall: float
    violation_f1: float
    type_accuracy: float
    severity_accuracy: float
    matched_count: int
    pred_count: int
    gt_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sample_id': self.sample_id,
            'violation_precision': self.violation_precision,
            'violation_recall': self.violation_recall,
            'violation_f1': self.violation_f1,
            'type_accuracy': self.type_accuracy,
            'severity_accuracy': self.severity_accuracy,
            'matched_count': self.matched_count,
            'pred_count': self.pred_count,
            'gt_count': self.gt_count,
        }


@dataclass
class AuditEvalReport:
    """批量审核评估报告"""
    total_samples: int
    avg_precision: float
    avg_recall: float
    avg_f1: float
    avg_type_accuracy: float
    avg_severity_accuracy: float
    by_product_type: Dict[str, Dict[str, float]] = field(default_factory=dict)
    by_issue_type: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_samples': self.total_samples,
            'avg_precision': self.avg_precision,
            'avg_recall': self.avg_recall,
            'avg_f1': self.avg_f1,
            'avg_type_accuracy': self.avg_type_accuracy,
            'avg_severity_accuracy': self.avg_severity_accuracy,
            'by_product_type': self.by_product_type,
            'by_issue_type': self.by_issue_type,
        }


class AuditEvaluator:
    """审核样本评估器"""

    def evaluate(
        self,
        sample_id: str,
        ground_truth_json: str,
        system_output: Dict[str, Any],
    ) -> AuditEvalResult:
        """
        评估单条审核样本

        Args:
            sample_id: 样本 ID
            ground_truth_json: AuditGroundTruth JSON 字符串
            system_output: 审核系统输出，包含 violations 字段

        Returns:
            AuditEvalResult
        """
        gt = AuditGroundTruth.from_json(ground_truth_json)
        pred_violations = [
            Violation.from_dict(v) for v in system_output.get('violations', [])
        ]

        # 匹配违规项
        matched = match_violations(pred_violations, gt.violations)

        # 计算指标
        pred_count = len(pred_violations)
        gt_count = len(gt.violations)
        matched_count = len(matched)

        precision = matched_count / pred_count if pred_count > 0 else 0.0
        recall = matched_count / gt_count if gt_count > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        # 类型准确率
        type_correct = sum(1 for p, g, _ in matched if p.issue_type == g.issue_type)
        type_accuracy = type_correct / matched_count if matched_count > 0 else 0.0

        # 严重程度准确率
        severity_correct = sum(1 for p, g, _ in matched if p.severity == g.severity)
        severity_accuracy = severity_correct / matched_count if matched_count > 0 else 0.0

        return AuditEvalResult(
            sample_id=sample_id,
            violation_precision=precision,
            violation_recall=recall,
            violation_f1=f1,
            type_accuracy=type_accuracy,
            severity_accuracy=severity_accuracy,
            matched_count=matched_count,
            pred_count=pred_count,
            gt_count=gt_count,
        )

    def evaluate_batch(
        self,
        samples: List[Dict[str, Any]],
        system_outputs: List[Dict[str, Any]],
    ) -> AuditEvalReport:
        """
        批量评估审核样本

        Args:
            samples: 评测样本列表，每个包含 id, ground_truth, topic
            system_outputs: 对应的系统输出列表

        Returns:
            AuditEvalReport
        """
        results = []
        by_product_type: Dict[str, List[AuditEvalResult]] = {}
        by_issue_type: Dict[str, List[AuditEvalResult]] = {}

        for sample, output in zip(samples, system_outputs):
            result = self.evaluate(
                sample_id=sample['id'],
                ground_truth_json=sample['ground_truth'],
                system_output=output,
            )
            results.append(result)

            # 按产品类型分组
            product_type = sample.get('topic', 'unknown')
            by_product_type.setdefault(product_type, []).append(result)

            # 按违规类型分组（从 ground_truth 提取）
            gt = AuditGroundTruth.from_json(sample['ground_truth'])
            for v in gt.violations:
                issue_type = v.issue_type.value
                by_issue_type.setdefault(issue_type, []).append(result)

        # 计算平均值
        n = len(results)
        avg_precision = sum(r.violation_precision for r in results) / n if n > 0 else 0
        avg_recall = sum(r.violation_recall for r in results) / n if n > 0 else 0
        avg_f1 = sum(r.violation_f1 for r in results) / n if n > 0 else 0
        avg_type_accuracy = sum(r.type_accuracy for r in results) / n if n > 0 else 0
        avg_severity_accuracy = sum(r.severity_accuracy for r in results) / n if n > 0 else 0

        # 分组统计
        product_type_stats = {
            pt: {
                'avg_f1': sum(r.violation_f1 for r in rs) / len(rs) if rs else 0,
                'avg_recall': sum(r.violation_recall for r in rs) / len(rs) if rs else 0,
            }
            for pt, rs in by_product_type.items()
        }

        return AuditEvalReport(
            total_samples=n,
            avg_precision=avg_precision,
            avg_recall=avg_recall,
            avg_f1=avg_f1,
            avg_type_accuracy=avg_type_accuracy,
            avg_severity_accuracy=avg_severity_accuracy,
            by_product_type=product_type_stats,
        )
```

**Step 4.3: 评测运行时过滤**

修改 `scripts/lib/eval/retrieval_evaluator.py`：

```python
# 在 RetrievalEvaluator.evaluate_batch 开头添加

def evaluate_batch(self, samples: List[EvalSample], ...) -> Tuple[RetrievalEvalReport, List[Dict]]:
    # 强制过滤：仅使用 APPROVED 状态样本
    from .dataset import ReviewStatus
    approved_samples = [s for s in samples if s.review_status == ReviewStatus.APPROVED]

    skipped_count = len(samples) - len(approved_samples)
    if skipped_count > 0:
        logger.warning(
            f"跳过 {skipped_count} 条待审核/拒绝样本，"
            f"仅使用 {len(approved_samples)} 条已审核样本"
        )

    if not approved_samples:
        raise ValueError("无已审核样本，请先完成人工校验")

    # 继续原有逻辑...
    all_results: List[Dict[str, Any]] = []
    # ...
```

---

### Phase 5: Enhancement - 人工审核工作台 (User Story 3)

#### 需求回溯

→ 对应 spec.md User Story 3: 人工审核工作台 (P1)
→ FR-007: 审核工作台支持通过、修改后通过、拒绝
→ FR-008: 评测运行时仅使用 APPROVED 样本

#### 实现步骤

**Step 5.1: 前端类型定义扩展**

- 文件: `scripts/web/src/types.ts`

```typescript
// 扩展 EvalSample 类型
export interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: string;
  difficulty: string;
  topic: string;
  regulation_refs: RegulationRef[];
  review_status: 'pending' | 'approved' | 'rejected';
  reviewer: string;
  reviewed_at: string;
  review_comment: string;
  created_by: string;
  kb_version: string;
  sample_type?: 'qa' | 'audit';  // 新增
  audit_input_json?: string;      // 新增
}

// 新增 Violation 类型
export interface Violation {
  id: string;
  clause_number: string;
  clause_title: string;
  issue_type: string;
  severity: 'high' | 'medium' | 'low';
  description: string;
  regulation_ref?: RegulationRef;
}

// 新增 AuditInput 类型
export interface AuditInput {
  product: { name: string; type: string; [key: string]: any };
  clauses: { number: string; title: string; text: string }[];
  premium_table?: { raw_text: string; data: string[][] };
}
```

**Step 5.2: 审核工作台组件**

- 文件: `scripts/web/src/components/ReviewWorkbench.tsx`

```tsx
import { useState, useEffect } from 'react';
import { Card, Table, Button, Space, Tag, Modal, Input, message, Descriptions, Collapse } from 'antd';
import { CheckOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons';
import * as evalApi from '../api/eval';
import type { EvalSample, Violation } from '../types';

const { Panel } = Collapse;

interface ReviewWorkbenchProps {
  onRefresh: () => void;
}

export function ReviewWorkbench({ onRefresh }: ReviewWorkbenchProps) {
  const [samples, setSamples] = useState<EvalSample[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSample, setSelectedSample] = useState<EvalSample | null>(null);
  const [reviewComment, setReviewComment] = useState('');
  const [editModalOpen, setEditModalOpen] = useState(false);

  useEffect(() => {
    loadSamples();
  }, []);

  const loadSamples = async () => {
    setLoading(true);
    try {
      const data = await evalApi.fetchEvalSamples({
        review_status: 'pending',
        sample_type: 'audit',
      });
      setSamples(data);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (sampleId: string) => {
    try {
      await evalApi.approveSample(sampleId, 'admin', reviewComment);
      message.success('审核通过');
      setReviewComment('');
      loadSamples();
      onRefresh();
    } catch (err) {
      message.error(`审核失败: ${err}`);
    }
  };

  const handleReject = async (sampleId: string) => {
    try {
      await evalApi.rejectSample(sampleId, 'admin', reviewComment);
      message.success('已拒绝');
      setReviewComment('');
      loadSamples();
      onRefresh();
    } catch (err) {
      message.error(`操作失败: ${err}`);
    }
  };

  const parseViolations = (groundTruth: string): Violation[] => {
    try {
      const data = JSON.parse(groundTruth);
      return data.violations || [];
    } catch {
      return [];
    }
  };

  const columns = [
    {
      title: '产品名称',
      dataIndex: 'question',
      key: 'question',
    },
    {
      title: '违规项数',
      key: 'violation_count',
      render: (_: any, record: EvalSample) => parseViolations(record.ground_truth).length,
    },
    {
      title: '风险等级',
      key: 'risk_level',
      render: (_: any, record: EvalSample) => {
        try {
          const data = JSON.parse(record.ground_truth);
          const color = { high: 'red', medium: 'orange', low: 'green' }[data.risk_level] || 'default';
          return <Tag color={color}>{data.risk_level || 'low'}</Tag>;
        } catch {
          return <Tag>unknown</Tag>;
        }
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (t: string) => t?.slice(0, 19).replace('T', ' '),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: EvalSample) => (
        <Space>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={() => handleApprove(record.id)}
          >
            通过
          </Button>
          <Button
            danger
            icon={<CloseOutlined />}
            onClick={() => handleReject(record.id)}
          >
            拒绝
          </Button>
          <Button
            icon={<EditOutlined />}
            onClick={() => {
              setSelectedSample(record);
              setEditModalOpen(true);
            }}
          >
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Card title={`待审核审核样本 (${samples.length})`}>
        <Table
          dataSource={samples}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
          expandable={{
            expandedRowRender: (record) => {
              const violations = parseViolations(record.ground_truth);
              return (
                <div style={{ padding: 12 }}>
                  <Descriptions title="违规项详情" column={1} size="small">
                    {violations.map((v, i) => (
                      <Descriptions.Item key={i} label={`${v.clause_number} - ${v.clause_title}`}>
                        <div>
                          <Tag color={v.severity === 'high' ? 'red' : v.severity === 'medium' ? 'orange' : 'green'}>
                            {v.severity}
                          </Tag>
                          <Tag>{v.issue_type}</Tag>
                          <span style={{ marginLeft: 8 }}>{v.description}</span>
                          {v.regulation_ref && (
                            <div style={{ marginTop: 4, color: '#666' }}>
                              参考: {v.regulation_ref.doc_name} {v.regulation_ref.article}
                            </div>
                          )}
                        </div>
                      </Descriptions.Item>
                    ))}
                  </Descriptions>
                  <div style={{ marginTop: 12 }}>
                    <Input.TextArea
                      placeholder="审核意见（可选）"
                      value={reviewComment}
                      onChange={(e) => setReviewComment(e.target.value)}
                      rows={2}
                    />
                  </div>
                </div>
              );
            },
          }}
        />
      </Card>
    </div>
  );
}
```

**Step 5.3: 集成到 EvalPage**

修改 `scripts/web/src/pages/EvalPage.tsx`，新增审核工作台 Tab：

```tsx
// 在 items 数组中添加
import { ReviewWorkbench } from '../components/ReviewWorkbench';

// 在 Tab 配置中添加
const pendingAuditCount = samples.filter(s => s.sample_type === 'audit' && s.review_status === 'pending').length;

const items = [
  { key: 'dataset', label: '数据集', children: <DatasetTab /> },
  { key: 'review', label: `审核工作台 (${pendingAuditCount})`, children: <ReviewWorkbench onRefresh={loadSamples} /> },
  { key: 'snapshots', label: '快照', children: <SnapshotsTab /> },
  { key: 'runs', label: '评测历史', children: <RunsTab /> },
  { key: 'configs', label: '配置', children: <ConfigsTab /> },
];
```

---

### Phase 6: Enhancement - 评估报告与维度分析 (User Story 5)

#### 需求回溯

→ 对应 spec.md User Story 5: 评估报告与维度分析 (P2)
→ FR-012: 支持按产品类型、违规类型分组统计

#### 实现步骤

**Step 6.1: 后端评估报告端点**

- 文件: `scripts/api/routers/eval.py`

新增端点：

```python
@router.get("/audit-report")
async def get_audit_report(
    product_type: Optional[str] = None,
    issue_type: Optional[str] = None,
):
    """获取审核评估报告（分组统计）"""
    from lib.eval.audit_evaluator import AuditEvaluator
    from api.database import get_eval_samples

    # 获取已审核通过的审核样本
    samples = get_eval_samples(
        review_status='approved',
        sample_type='audit',
    )

    # 计算统计
    by_product_type = {}
    by_issue_type = {}
    total_violations = 0

    for s in samples:
        pt = s.get('topic', 'unknown')
        by_product_type.setdefault(pt, {'count': 0, 'violations': 0})
        by_product_type[pt]['count'] += 1

        try:
            gt = json.loads(s['ground_truth'])
            v_count = len(gt.get('violations', []))
            by_product_type[pt]['violations'] += v_count
            total_violations += v_count

            for v in gt.get('violations', []):
                it = v.get('issue_type', 'unknown')
                by_issue_type.setdefault(it, {'count': 0})
                by_issue_type[it]['count'] += 1
        except:
            pass

    return {
        'total_samples': len(samples),
        'total_violations': total_violations,
        'by_product_type': by_product_type,
        'by_issue_type': by_issue_type,
    }
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (基础) → Phase 2 (解析) → Phase 3 (合成) → Phase 4 (评估) → Phase 5 (前端) → Phase 6 (报告)
```

依赖关系：
- Phase 2-6 依赖 Phase 1（数据模型）
- Phase 3 依赖 Phase 2（条款解析）
- Phase 4 依赖 Phase 3（样本合成）
- Phase 5 依赖 Phase 1, 4（数据模型 + 评估器）
- Phase 6 依赖 Phase 4（评估器）

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 条款解析 | 条款编号连续、内容非空 | `test_clause_parser.py` |
| US-2 违规标注 | 类型正确、法规引用存在 | `test_audit_sample_synth.py` |
| US-3 人工审核 | 仅 APPROVED 参与评测 | `test_evaluator_filter.py` |
| US-4 统一框架 | 审核指标正确计算 | `test_audit_evaluator.py` |
| US-5 报告分析 | 分组统计准确 | `test_audit_report.py` |

### 依赖安装

```bash
pip install python-docx>=0.8.11 pdfplumber>=0.9.0
```

### 测试执行

```bash
# 单元测试
pytest scripts/tests/lib/eval/ -v

# 集成测试（需要实际文件）
pytest scripts/tests/lib/eval/ -v -m slow
```

### 迁移检查清单

**Phase A: 代码迁移**

- [ ] 创建 `scripts/lib/eval/` 目录
- [ ] 迁移 `rag_engine/eval_dataset.py` → `eval/sample.py`
  - 扩展 `sample_type`, `audit_input_json` 字段
  - 重命名 `load_eval_dataset` → `load_eval_samples`, `save_eval_dataset` → `save_eval_samples`
- [ ] 拆分 `rag_engine/evaluator.py` → `eval/retrieval_evaluator.py` + `eval/generation_evaluator.py`
  - 导出 `_normalize_doc_name` → `normalize_doc_name`
  - 导出 `_token_bigrams` → `token_bigrams`
- [ ] 合并 `rag_engine/eval_rating.py` + `rag_engine/eval_guide.py` → `eval/thresholds.py`
  - 使用 `eval_rating.py` 内容（含 `rejection_rate`）
  - 删除 `eval_guide.py`
- [ ] 迁移 `rag_engine/sample_synthesizer.py` → `eval/qa_sample_synthesizer.py`
  - 更新 import：`.eval_dataset` → `.sample`
  - 更新 import：`.kb_manager` → `lib.rag_engine.kb_manager`
  - 更新 import：`.preprocessor._extract_json_array` → `lib.rag_engine.preprocessor._extract_json_array`
- [ ] 迁移 `rag_engine/dataset_validator.py` → `eval/sample_validator.py`
  - 重命名 `validate_dataset` → `validate_samples`
  - 重命名 `QualityAuditReport` → `QualityReport`
  - **修复现有 bug**：定义缺失的 `GENERIC_KEYWORDS` 常量
  - 更新 import：`.tokenizer` → `lib.rag_engine.tokenizer`
  - 更新 import：`.evaluator.GENERIC_KEYWORDS` → 本模块定义
- [ ] 迁移 `rag_engine/dataset_coverage.py` → `eval/sample_coverage.py`
  - 更新内部 import：`.evaluator._normalize_doc_name` → `.retrieval_evaluator.normalize_doc_name`
- [ ] 迁移 `rag_engine/quality_detector.py` → `eval/quality_detector.py`
  - 更新内部 import：`.evaluator._token_bigrams` → `.retrieval_evaluator.token_bigrams`
- [ ] 新增审核模块：`audit_models.py`, `clause_parser.py`, `audit_sample_synthesizer.py`, `audit_evaluator.py`, `violation_matcher.py`
  - **条款解析器适配真实格式**：阿拉伯数字编号（1, 1.1, 2.3.2），内容在表格中
  - **标题/正文分离算法**：换行符 > 句号 > 全部作为标题
  - **非条款表格过滤**：检测公司信息等非条款内容
  - **`.doc` 文件不支持**：python-docx 仅支持 `.docx`，返回明确错误提示

**Phase B: .doc 文件预处理**

- [ ] 创建 `scripts/tools/convert_doc_to_docx.py` 转换工具
- [ ] 执行批量转换：
  ```bash
  cd /mnt/d/work/actuary-assets/products/
  libreoffice --headless --convert-to docx *.doc
  ```
- [ ] 验证转换结果：检查 9 个 .doc 文件是否成功转换为 .docx

**Phase C: Import 路径更新**

- [ ] 更新 `scripts/lib/rag_engine/__init__.py`
  - 修改 import 路径：`from .eval_*` → `from lib.eval`
  - 保持向后兼容的 re-export
- [ ] 更新 `scripts/api/routers/eval.py`
  - `from lib.rag_engine.evaluator` → `from lib.eval`
  - `from lib.rag_engine.eval_dataset` → `from lib.eval`
- [ ] 更新 `scripts/evaluate_rag.py`
  - 所有 eval 相关 import 改为 `from lib.eval`
- [ ] 更新迁移后的 eval 模块内部 import
  - `retrieval_evaluator.py`: `from .tokenizer` → `from lib.rag_engine.tokenizer`
  - `generation_evaluator.py`: `from .tokenizer` → `from lib.rag_engine.tokenizer`
  - `violation_matcher.py`: `from .tokenizer` → `from lib.rag_engine.tokenizer`（已更新）
  - `sample_validator.py`: `from .tokenizer` → `from lib.rag_engine.tokenizer`（原有依赖）

**Phase D: 测试文件迁移**

- [ ] 迁移 `tests/lib/rag_engine/test_eval_dataset.py` → `tests/lib/eval/test_sample.py`
- [ ] 迁移 `tests/lib/rag_engine/test_evaluator.py` → `tests/lib/eval/test_retrieval_evaluator.py` + `test_generation_evaluator.py`
- [ ] 迁移 `tests/lib/rag_engine/test_eval_guide.py` → `tests/lib/eval/test_thresholds.py`
- [ ] 迁移 `tests/lib/rag_engine/test_synth_qa.py` → `tests/lib/eval/test_qa_sample_synthesizer.py`
- [ ] 迁移 `tests/lib/rag_engine/test_dataset_validator.py` → `tests/lib/eval/test_sample_validator.py`
- [ ] 迁移 `tests/lib/rag_engine/test_coverage.py` → `tests/lib/eval/test_sample_coverage.py`
- [ ] 新增 `tests/lib/eval/test_clause_parser.py`
  - 条款编号正则测试（阿拉伯数字格式）
  - 标题/正文分离测试
  - 非条款表格检测测试
  - 真实文档解析集成测试

**Phase E: 清理与验证**

- [ ] 删除原 `rag_engine/eval_*.py`, `sample_synthesizer.py`, `dataset_*.py`, `quality_detector.py`, `eval_guide.py`
- [ ] 运行全量测试验证迁移正确性：`pytest scripts/tests/`
- [ ] 运行真实文档解析测试：`pytest scripts/tests/lib/eval/test_clause_parser.py -v -m slow`

---

## Pre-existing Bugs Fixed During Migration

| Bug | 文件 | 修复方案 |
|-----|------|---------|
| `GENERIC_KEYWORDS` 未定义 | `dataset_validator.py` → `sample_validator.py` | 在 `sample_validator.py` 中定义常量：`GENERIC_KEYWORDS = {'保险', '条款', '规定', '产品', '合同'}` |
| `eval_guide.py` 与 `eval_rating.py` 冗余 | 两个文件内容几乎相同 | 合并为 `thresholds.py`，使用 `eval_rating.py` 内容（含完整 `rejection_rate` 指标） |
