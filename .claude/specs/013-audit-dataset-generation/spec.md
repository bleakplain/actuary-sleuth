# Feature Specification: 保险产品条款审核评测数据集生成

**Feature Branch**: `013-audit-dataset-generation`
**Created**: 2026-04-16
**Status**: Draft
**Input**: 基于真实保险产品条款自动生成审核评测数据集，区别于现有基于法规 Chunk 的问答评测数据集

## Background

### 现状问题

现有评测数据集生成方式：
```
知识库法规 Chunk → LLM 生成问答对 → 质量过滤 → 存入 eval_samples 表
```

**问题**：
1. 数据源是法规文档（如《健康保险管理办法》），而非真实保险产品条款
2. 评估目标是"问答质量"（Faithfulness、Answer Correctness），而非"审核质量"（违规检出率、误报率）
3. 无法评估审核系统对真实产品条款的审核能力

### 目标资源

| 格式 | 数量 | 产品类型 |
|------|------|---------|
| Word (.docx) | 11个 | 重疾险、医疗险、意外险、护理险、团体险等 |
| PDF | 3个 | 特定药品医疗险、意外险、手术意外险 |

### 核心差异

| 维度 | 现有问答评测 | 新审核评测 |
|------|------------|------------|
| 输入 | 自然语言问题 | 产品条款文本 |
| 输出 | 答案文本 | 结构化违规列表 |
| 核心任务 | 检索 + 生成 | 分类 + 提取 |
| 评估指标 | Faithfulness, Answer Correctness | Violation F1, Type Accuracy |

---

## User Scenarios & Testing

### User Story 1 - 条款解析与评测样本生成 (Priority: P1)

**角色**: RAG 开发者

**用户旅程**: 作为 RAG 开发者，我需要将 14 个真实产品条款文件解析为结构化数据，并基于此生成评测样本，以便评估审核系统对真实产品的审核能力。

**Why this priority**: 条款解析是数据基础，无此无法生成评测样本。

**Independent Test**:
- 输入 14 个产品文件（docx/pdf），输出结构化条款 JSON
- 验证解析完整性：条款编号连续、内容非空、元数据正确

**Acceptance Scenarios**:

1. **Given** 11 个 docx 文件, **When** 执行条款解析, **Then** 每个文件输出结构化条款列表（number, title, text）
2. **Given** 3 个 pdf 文件, **When** 执行条款解析, **Then** 每个文件输出结构化条款列表
3. **Given** 条款文档中包含费率表, **When** 执行解析, **Then** 提取费率表数据（raw_text）
4. **Given** 解析后的条款数据, **When** 执行样本生成, **Then** 每个产品生成 10-20 条评测样本
5. **Given** 生成的样本, **When** 执行质量检查, **Then** 所有样本通过完整性、有效性、无重复检查

---

### User Story 2 - 违规项 LLM 辅助标注 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 作为精算审核人员，我需要 LLM 辅助识别条款中的潜在违规项，生成候选标注，我再进行人工校验确认，以提高标注效率。

**Why this priority**: 违规标注是评测数据集的核心，纯人工标注成本过高。

**Independent Test**:
- 输入结构化条款 + 法规知识库，输出候选违规项列表
- 验证违规项质量：类型正确、法规引用存在、描述有效

**Acceptance Scenarios**:

1. **Given** 产品条款 + 法规知识库, **When** LLM 分析条款, **Then** 输出候选违规项列表（clause_number, issue_type, severity, description, regulation_ref）
2. **Given** 候选违规项, **When** 检查法规引用, **Then** 每个引用的法规在知识库中存在
3. **Given** 无违规的产品, **When** LLM 分析, **Then** 输出空违规列表（作为"通过"样本）

---

### User Story 3 - 人工审核工作台 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 作为精算审核人员，我需要在前端工作台审核 LLM 生成的评测样本，支持通过、修改后通过、拒绝三种操作，确保只有校验通过的样本参与评测。

**Why this priority**: 强制人工校验是质量保障的关键，无此无法保证评测数据集准确性。

**Independent Test**:
- 前端工作台可展示待审核样本列表
- 支持通过、修改后通过、拒绝操作
- 评测运行时仅使用 APPROVED 状态样本

**Acceptance Scenarios**:

1. **Given** 45 条 PENDING 状态样本, **When** 打开审核工作台, **Then** 展示待审核列表和统计信息
2. **Given** 一条待审核样本, **When** 点击"通过", **Then** 样本状态变为 APPROVED，记录审核人和时间
3. **Given** 一条待审核样本, **When** 点击"修改后通过"并提交修改, **Then** 应用修改后状态变为 APPROVED
4. **Given** 一条待审核样本, **When** 点击"拒绝", **Then** 样本状态变为 REJECTED，不参与评测
5. **Given** 评测运行请求, **When** 存在 PENDING 样本, **Then** 仅使用 APPROVED 样本运行评测，并警告跳过的样本数

---

### User Story 4 - 统一评测框架 (Priority: P1)

**角色**: RAG 开发者

**用户旅程**: 作为 RAG 开发者，我需要一个统一评测框架，支持问答和审核两种样本类型，共享法规检索评估基础设施，分类型计算专属指标。

**Why this priority**: 统一框架减少重复建设，便于维护和扩展。

**Independent Test**:
- 扩展 eval_samples 表支持 sample_type 字段
- 统一评估引擎根据 sample_type 计算不同指标
- 问答样本计算 Faithfulness/Answer Correctness，审核样本计算 Violation F1/Type Accuracy

**Acceptance Scenarios**:

1. **Given** eval_samples 表结构, **When** 添加 sample_type 字段, **Then** 支持 "question" 和 "audit" 两种类型
2. **Given** 问答类型样本, **When** 执行评测, **Then** 计算 context_recall, faithfulness, answer_correctness
3. **Given** 审核类型样本, **When** 执行评测, **Then** 计算 context_recall, violation_f1, type_accuracy, severity_accuracy
4. **Given** 混合类型样本集, **When** 执行评测, **Then** 分别输出问答和审核的评估报告

---

### User Story 5 - 评估报告与维度分析 (Priority: P2)

**角色**: 产品经理

**用户旅程**: 作为产品经理，我需要查看评测报告，了解审核系统在不同产品类型、违规类型上的表现，以便评估业务价值和改进方向。

**Why this priority**: 报告分析是业务价值体现，但不影响核心评测功能。

**Independent Test**:
- 评测报告包含汇总指标和分组指标
- 支持按产品类型、违规类型、难度分组统计

**Acceptance Scenarios**:

1. **Given** 评测运行完成, **When** 查看报告, **Then** 展示汇总指标（violation_f1, type_accuracy 等）
2. **Given** 评测报告, **When** 按产品类型分组, **Then** 展示各产品类型（重疾、医疗、意外）的指标
3. **Given** 评测报告, **When** 按违规类型分组, **Then** 展示各违规类型（incomplete_coverage, invalid_waiting_period 等）的 precision/recall

---

### Edge Cases

- 条款解析失败（格式损坏、编码问题）如何处理？
- 法规引用在知识库中不存在如何处理？
- 全部样本都被拒绝后评测如何处理？
- 条款中包含表格（如费率表）如何解析？
- 条款中包含图片等非文本内容如何处理？

---

## Requirements

### Dependencies

**依赖 015-document-parser**：

本功能依赖 `015-document-parser` 提供的文档解析能力：

```python
from lib.doc_parser import (
    AuditDocument,    # 审核文档结构
    Clause,           # 条款
    PremiumTable,     # 费率表
    DocumentSection,  # 文档章节
    parse_product_document,  # 解析接口
)
```

**职责划分**：

| 职责 | 所属模块 |
|------|---------|
| Word/PDF 文档解析 | 015-document-parser |
| 条款编号识别、标题/正文分离 | 015-document-parser |
| 费率表提取 | 015-document-parser |
| 多内容类型提取（投保须知、健康告知等） | 015-document-parser |
| 违规项识别与标注 | **013-audit-dataset-generation** |
| 审核评测样本生成 | **013-audit-dataset-generation** |
| 审核评估指标计算 | **013-audit-dataset-generation** |
| 人工审核工作台 | **013-audit-dataset-generation** |

### Functional Requirements

- **FR-001**: 系统 MUST 调用 `lib.doc_parser.parse_product_document()` 解析保险产品文档
- **FR-002**: 系统 MUST 使用 `AuditDocument` 结构作为审核输入，支持条款、费率表等多种内容类型
- **FR-003**: 系统 MUST 基于 LLM 为每个产品生成 10-20 条评测样本
- **FR-004**: 系统 MUST 为每个评测样本生成候选违规项列表（clause_number, issue_type, severity, description, regulation_ref）
- **FR-005**: 系统 MUST 对生成的样本执行质量检查（完整性、有效性、无重复）
- **FR-006**: 系统 MUST 将样本存入 eval_samples 表，状态为 PENDING
- **FR-007**: 系统 MUST 提供人工审核工作台，支持通过、修改后通过、拒绝操作
- **FR-008**: 系统 MUST 在评测运行时仅使用 APPROVED 状态样本
- **FR-009**: 系统 MUST 扩展 eval_samples 表支持 sample_type 字段（"question" | "audit"）
- **FR-010**: 系统 MUST 提供统一评估引擎，根据 sample_type 计算不同指标
- **FR-011**: 系统 MUST 计算审核专属指标：violation_precision, violation_recall, violation_f1, type_accuracy, severity_accuracy
- **FR-012**: 系统 MUST 生成评估报告，支持按产品类型、违规类型分组统计

### Non-Functional Requirements

- **NFR-001**: 条款解析准确率 >= 90%（人工抽样检查）
- **NFR-002**: 法规引用准确率 >= 85%（引用的法规在知识库中存在且相关）
- **NFR-003**: 人工审核工作量 <= 5 分钟/样本（良好的 LLM 辅助质量）

---

## Key Entities

### 从 015-document-parser 引用的数据结构

以下数据结构由 `lib.doc_parser` 提供：

- **Clause（条款）**: 条款编号、标题、正文 → `from lib.doc_parser import Clause`
- **PremiumTable（费率表）**: 费率表原始文本、结构化数据、备注 → `from lib.doc_parser import PremiumTable`
- **DocumentSection（文档章节）**: 投保须知、健康告知、责任免除等 → `from lib.doc_parser import DocumentSection`
- **AuditDocument（审核文档）**: 按类型分组的内容集合 → `from lib.doc_parser import AuditDocument`

### 本模块定义的审核专属数据结构

### AuditEvalSample（审核评测样本）

```python
@dataclass
class AuditEvalSample:
    id: str                           # 样本唯一标识
    sample_type: str                  # 固定为 "audit"

    # 输入（引用 015 的数据结构）
    audit_document: AuditDocument     # 审核文档（包含条款、费率表等）

    # 标准答案
    ground_truth: AuditGroundTruth    # 审核结果

    # 元数据
    difficulty: str                   # easy/medium/hard
    topic: str                        # 审核维度
    created_by: str                   # "llm" | "human"
    review_status: ReviewStatus       # PENDING/APPROVED/REJECTED
    reviewer: str                     # 审核人
    reviewed_at: str                  # 审核时间
    review_comment: str               # 审核意见
    kb_version: str                   # 知识库版本
```

### AuditGroundTruth（审核标准答案）

```python
@dataclass
class AuditGroundTruth:
    violations: List[Violation]       # 违规项列表
    overall_result: str               # pass/conditional_pass/fail
    risk_level: str                   # low/medium/high
```

### Violation（违规项）

```python
@dataclass
class Violation:
    id: str                           # 违规项唯一标识
    clause_number: str                # 条款编号
    clause_title: str                 # 条款标题
    issue_type: IssueType             # 违规类型（枚举）
    severity: str                     # high/medium/low
    description: str                  # 违规描述
    regulation_ref: RegulationRef     # 法规引用
```

### IssueType（违规类型枚举）

```python
class IssueType(str, Enum):
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
```

### RegulationRef（法规引用）

```python
@dataclass
class RegulationRef:
    doc_name: str       # 法规名称，如"《重大疾病保险的疾病定义使用规范》"
    article: str        # 条款编号，如"第四条"
    excerpt: str        # 条款原文摘要
```

---

## Success Criteria

- **SC-001**: 评测数据集包含 >= 140 条审核样本（14 产品 × 10 条/产品）
- **SC-002**: 核心产品类型（重疾、医疗、意外）覆盖 >= 11 个产品
- **SC-003**: 人工审核通过率 >= 80%（LLM 生成质量足够高）
- **SC-004**: 评测运行后输出审核专属指标（violation_f1, type_accuracy 等）
- **SC-005**: 法规引用召回率 >= 90%（引用的法规能被检索到）

---

## Assumptions

- 假设 `015-document-parser` 已完成，提供 `AuditDocument`, `Clause`, `PremiumTable` 等数据结构
- 假设产品条款文件格式规范，可被 `lib.doc_parser` 正确解析
- 假设现有法规知识库覆盖审核所需的主要法规
- 假设 LLM 具备足够的保险专业知识，能识别常见违规类型
- 假设人工审核人员具备保险产品审核专业能力
- **约束**：必须有人工校验环节，LLM 生成不可直接入库
- **约束**：复用现有 eval_samples 表结构和评估基础设施
- **约束**：文档解析逻辑在 `lib.doc_parser` 中实现，本模块仅调用接口
