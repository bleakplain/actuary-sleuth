# Feature Specification: 统一文档解析器

**Feature Branch**: `015-document-parser`
**Created**: 2026-04-17
**Status**: Draft
**Input**: 创建独立的文档解析 package，将知识库文档解析和保险产品文档解析统一抽象，与评测系统解耦

## Background

### 现状问题

当前文档解析逻辑分散在多个模块中：

| 模块 | 职责 | 问题 |
|------|------|------|
| `rag_engine/chunker.py` | Markdown 分块 | 知识库专用，输出 TextNode |
| `common/document_fetcher.py` | 飞书文档获取 | 仅支持飞书 URL，将被删除 |
| `eval/clause_parser.py`（计划中）| Word/PDF 条款解析 | 审核专用，输出 Clause |

**问题**：
1. 没有统一的文档解析抽象层，无法复用
2. 知识库文档和保险产品文档解析逻辑分散，维护成本高
3. 不同格式（Markdown、Word、PDF）缺乏统一接口
4. 飞书文档同步代码不再需要，应删除

**注意**：`rag_engine/preprocessor.py` 负责 Excel→Markdown 转换，属于知识库预处理，不在本模块范围内。

### 目标

创建独立的 `lib/doc_parser` package，统一处理：
- **知识库文档**：Markdown 文件解析为 TextNode（供 RAG 检索）
- **保险产品文档**：Word/PDF 解析为结构化审核数据（供审核评测）

---

## User Scenarios & Testing

### User Story 1 - 知识库文档解析 (Priority: P1)

**角色**: RAG 开发者

**用户旅程**: 作为 RAG 开发者，我需要将法规 Markdown 文档解析为结构化 TextNode，以便构建知识库索引。

**Why this priority**: 知识库是 RAG 系统的核心，解析是最基础功能。

**Independent Test**:
- 输入 Markdown 文件，输出 TextNode 列表
- 验证 frontmatter 元数据提取、分块边界识别

**Acceptance Scenarios**:

1. **Given** 带有 YAML frontmatter 的 Markdown 文件, **When** 执行解析, **Then** 提取 frontmatter 为元数据
2. **Given** 包含 `## 第N项` 标题的 Markdown, **When** 执行分块, **Then** 按 `## 第N项` 边界切分为独立 chunk
3. **Given** 包含 blockquote 元数据的 Markdown, **When** 执行解析, **Then** 提取 blockquote 中的 `key=value` 元数据
4. **Given** 超过 3000 字的 chunk, **When** 执行分块, **Then** 按句子边界拆分为多个 chunk
5. **Given** 已有的知识库构建流程, **When** 迁移到新 package, **Then** 输出结果与原实现一致

---

### User Story 2 - 保险产品条款解析 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 作为精算审核人员，我需要解析 Word/PDF 格式的保险产品条款文档，提取结构化条款列表，以便进行审核评测。

**Why this priority**: 条款是审核的核心内容，必须首先支持。

**Independent Test**:
- 输入 Word/PDF 文件，输出 Clause 列表
- 验证条款编号识别、标题/正文分离

**Acceptance Scenarios**:

1. **Given** 包含阿拉伯数字编号条款的 Word 文档, **When** 执行解析, **Then** 按编号提取条款（如 1, 1.1, 2.3.2）
2. **Given** 条款标题和正文混合的单元格, **When** 执行解析, **Then** 正确分离标题和正文
3. **Given** 包含费率表的 Word 文档, **When** 执行解析, **Then** 识别并提取费率表
4. **Given** 包含公司信息等非条款表格, **When** 执行解析, **Then** 过滤掉非条款表格
5. **Given** PDF 格式的条款文档, **When** 执行解析, **Then** 输出与 Word 格式一致的结构
6. **Given** `.doc` 格式文件, **When** 执行解析, **Then** 抛出明确错误提示需转换为 `.docx`

---

### User Story 3 - 多内容类型解析 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 作为精算审核人员，我需要从保险产品文档中提取多种内容类型（条款、费率表、投保须知、健康告知、责任免除、附加险说明），以便全面审核产品。

**Why this priority**: 审核不只有条款，需要支持多种内容类型的解析。

**Independent Test**:
- 输入保险产品文档，输出 `AuditDocument` 结构
- 验证各内容类型正确识别和提取

**Acceptance Scenarios**:

1. **Given** 包含条款表的文档, **When** 执行解析, **Then** 输出到 `clauses` 列表
2. **Given** 包含费率表的文档, **When** 执行解析, **Then** 输出到 `premium_tables` 列表
3. **Given** 包含投保须知章节的文档, **When** 执行解析, **Then** 输出到 `notices` 列表
4. **Given** 包含健康告知章节的文档, **When** 执行解析, **Then** 输出到 `health_disclosures` 列表
5. **Given** 包含责任免除章节的文档, **When** 执行解析, **Then** 输出到 `exclusions` 列表
6. **Given** 包含附加险说明的文档, **When** 执行解析, **Then** 输出到 `rider_clauses` 列表

---

### User Story 4 - 飞书文档同步代码删除 (Priority: P2)

**角色**: RAG 开发者

**用户旅程**: 作为 RAG 开发者，我需要删除不再使用的飞书文档同步代码，减少代码维护负担。

**Why this priority**: 清理无用代码，但不影响核心功能。

**Independent Test**:
- 检查 `common/document_fetcher.py` 已删除
- 检查相关测试已删除
- 检查引用已清理

**Acceptance Scenarios**:

1. **Given** `lib/common/document_fetcher.py` 文件, **When** 执行清理, **Then** 删除该文件
2. **Given** 相关测试文件, **When** 执行清理, **Then** 删除测试文件
3. **Given** 其他模块对 document_fetcher 的引用, **When** 执行清理, **Then** 移除所有引用

---

### User Story 5 - 解析错误处理 (Priority: P2)

**角色**: RAG 开发者

**用户旅程**: 作为 RAG 开发者，我需要文档解析器在遇到错误时抛出明确异常，以便快速定位问题。

**Why this priority**: 错误处理是基础设施，但不影响核心解析逻辑。

**Independent Test**:
- 输入损坏/不支持的文件，验证异常类型和消息

**Acceptance Scenarios**:

1. **Given** 不存在的文件路径, **When** 执行解析, **Then** 抛出 `DocumentParseError` 并提示"文件不存在"
2. **Given** 不支持的文件格式, **When** 执行解析, **Then** 抛出 `DocumentParseError` 并提示"不支持的文件格式"
3. **Given** 损坏的 Word 文件, **When** 执行解析, **Then** 抛出 `DocumentParseError` 并提示具体错误
4. **Given** 空文件, **When** 执行解析, **Then** 抛出 `DocumentParseError` 并提示"文件内容为空"

---

### Edge Cases

- 条款编号格式不规范（如 "条款1" 而非 "1"）如何处理？
- 表格跨页导致内容断裂如何处理？
- PDF 中包含图片等非文本内容如何处理？
- 同一文档中条款编号重复如何处理？
- 内容类型识别冲突（如标题包含"责任免除"但实际是条款）如何处理？

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持解析 Markdown 文件，提取 YAML frontmatter 和按 `## 第N项` 分块
- **FR-002**: 系统 MUST 支持解析 Word (.docx) 文件，从表格中提取条款
- **FR-003**: 系统 MUST 支持解析 PDF 文件，从表格中提取条款
- **FR-004**: 系统 MUST 识别阿拉伯数字层级编号（1, 1.1, 2.3.2）作为条款编号
- **FR-005**: 系统 MUST 自动识别并分离条款标题和正文
- **FR-006**: 系统 MUST 自动识别表格类型（条款表、费率表、非条款表）
- **FR-007**: 系统 MUST 提取多种内容类型：条款、费率表、投保须知、健康告知、责任免除、附加险说明
- **FR-008**: 系统 MUST 在解析失败时抛出明确的 `DocumentParseError` 异常
- **FR-009**: 系统 MUST 输出统一的数据结构：知识库用 `TextNode`，审核用 `AuditDocument`
- **FR-010**: 系统 MUST 删除 `lib/common/document_fetcher.py` 及相关代码

### Non-Functional Requirements

- **NFR-001**: 条款解析准确率 >= 90%（基于真实保险产品测试）
- **NFR-002**: 知识库文档解析输出与原实现完全一致（向后兼容）
- **NFR-003**: 单文档解析时间 < 5 秒（普通大小文档）

---

## Key Entities

### AuditDocument（审核文档）

```python
@dataclass
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .docx, .pdf
    
    # 按类型分组的内容
    clauses: List[Clause]              # 条款
    premium_tables: List[PremiumTable] # 费率表
    notices: List[DocumentSection]     # 投保须知
    health_disclosures: List[DocumentSection]  # 健康告知
    exclusions: List[DocumentSection]  # 责任免除
    rider_clauses: List[Clause]        # 附加险条款
    
    # 元数据
    parse_time: datetime
    warnings: List[str]  # 解析警告（非致命问题）
```

### Clause（条款）

```python
@dataclass
class Clause:
    """条款"""
    number: str       # 条款编号，如 "1.2.3"
    title: str        # 条款标题
    text: str         # 条款正文
    section_type: str = "clause"  # 内容类型标识
```

### PremiumTable（费率表）

```python
@dataclass
class PremiumTable:
    """费率表"""
    raw_text: str              # 原始文本
    data: List[List[str]]      # 结构化数据（二维表格）
    remark: str = ""           # 备注
    section_type: str = "premium_table"
```

### DocumentSection（文档章节）

```python
@dataclass
class DocumentSection:
    """通用文档章节"""
    title: str        # 章节标题
    content: str      # 章节内容
    section_type: str # 内容类型：notice, health_disclosure, exclusion, rider
```

### DocumentParseError（解析错误）

```python
class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
```

---

## Success Criteria

- **SC-001**: 知识库文档解析输出与原 `ChecklistChunker` 完全一致
- **SC-002**: 条款解析准确率 >= 90%（基于 14 个真实保险产品测试）
- **SC-003**: 支持解析 6 种内容类型（条款、费率表、投保须知、健康告知、责任免除、附加险说明）
- **SC-004**: 所有现有测试通过（迁移后）
- **SC-005**: 飞书文档同步代码已删除，无残留引用

---

## Dependencies

### 依赖关系

```
┌─────────────────────────────────────────────────────────────┐
│  015-document-parser (底层基础设施)                          │
│  - 不依赖其他业务模块                                         │
│  - 仅依赖: python-docx, pdfplumber, llama-index, yaml       │
└─────────────────────────────────────────────────────────────┘
                              ↓ 被依赖
┌─────────────────────────────────────────────────────────────┐
│  013-audit-dataset-generation (审核评测)                    │
│  - 依赖 015 提供的 AuditDocument, Clause, PremiumTable      │
│  - 定义审核专属数据结构: Violation, IssueType, AuditSample  │
└─────────────────────────────────────────────────────────────┘
```

### 提供的公共接口

```python
# lib/doc_parser/__init__.py

# 数据模型（供外部模块使用）
from .models import (
    Clause,
    PremiumTable,
    DocumentSection,
    AuditDocument,
    DocumentParseError,
    SectionType,
)

# 基类 (供扩展新解析器使用)
from .parser import KnowledgeBaseParser, ProductDocumentParser

# 解析器类 (供高级用户直接使用)
from .md_parser import MdParser              # Markdown 解析器
from .docx_parser import DocxParser          # Word 解析器
from .pdf_parser import PdfParser            # PDF 解析器

# 便捷接口 (推荐使用，自动路由)
from .parser import (
    parse_knowledge_base,    # 知识库文档 → List[TextNode]
    parse_product_document,  # 产品文档 → AuditDocument
)

__all__ = [
    # 数据模型
    'Clause', 'PremiumTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType',
    # 基类
    'KnowledgeBaseParser', 'ProductDocumentParser',
    # 解析器类
    'MdParser', 'DocxParser', 'PdfParser',
    # 便捷接口
    'parse_knowledge_base', 'parse_product_document',
]
\n```\n
---

## Assumptions

- 假设保险产品文档格式规范，可被 python-docx/pdfplumber 正确处理
- 假设 `.doc` 文件已预先转换为 `.docx`（不支持 OLE2 格式）
- 假设知识库文档解析保持向后兼容，输出格式不变
- **约束**：本模块是底层基础设施，不依赖任何业务模块（eval、audit 等）
- **约束**：Markdown 解析复用现有 `ChecklistChunker` 逻辑
- **约束**：Word/PDF 解析基于 013 plan.md 中已设计的技术方案
