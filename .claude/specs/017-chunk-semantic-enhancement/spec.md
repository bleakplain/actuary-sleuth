# Feature Specification: Chunk 语义增强

**Feature Branch**: `017-chunk-semantic-enhancement`
**Created**: 2026-04-22
**Status**: Draft
**Input**: 基于 RAG chunk 切分最佳实践，改进 doc_parser 模块的切分策略

## User Scenarios & Testing

### User Story 1 - 表格完整性保护 (Priority: P1)

作为知识库构建人员，我希望 Markdown 文档中的表格被识别为完整的语义单元，不被切分，以便检索时能返回完整的表格信息。

**Why this priority**: 表格切碎是当前召回率低的主要原因，直接影响检索质量。

**Independent Test**: 准备包含表格的 Markdown 文件，验证解析后每个表格作为一个独立 chunk。

**Acceptance Scenarios**:

1. **Given** 一个包含 Markdown 表格的文档，**When** 执行分块解析，**Then** 表格整体作为一个 chunk，不被截断。
2. **Given** 表格内容超过 max_chunk_chars，**When** 执行分块解析，**Then** 表格仍保持完整，可适度超出限制。
3. **Given** 文档中包含多个连续表格，**When** 执行分块解析，**Then** 每个表格独立成块，不合并。

---

### User Story 2 - 跨页表格合并 (Priority: P1)

作为保险产品审核人员，我希望 PDF 文档中跨页的费率表被正确识别和合并，以便审核时看到完整的费率数据。

**Why this priority**: 保险产品文档中费率表常见跨页，数据不完整直接影响审核准确性。

**Independent Test**: 准备包含跨页表格的 PDF 文件，验证解析后表格行数据完整连续。

**Acceptance Scenarios**:

1. **Given** PDF 文档中一个表格跨越 2 页，**When** 执行 PDF 解析，**Then** 两页的表格被识别为同一表格并合并。
2. **Given** 跨页表格第二页缺少表头，**When** 执行表格合并，**Then** 自动补充第一页的表头信息。
3. **Given** PDF 中有多个独立表格（非跨页），**When** 执行解析，**Then** 各表格独立提取，不错误合并。

---

### User Story 3 - 超大表格 Header 补充 (Priority: P2)

作为 RAG 检索用户，我希望检索到的表格片段包含表头信息，以便理解数据含义。

**Why this priority**: 超大表格分块后，缺少表头会导致数据难以理解。

**Independent Test**: 准备超过 chunk 限制的超大表格，验证分块后每块都包含表头。

**Acceptance Scenarios**:

1. **Given** 表格行数超过分块阈值，**When** 执行分块，**Then** 每个分块都包含原始表头。
2. **Given** 表格分块后，**When** 检索返回某个分块，**Then** 用户能看到列名信息，理解数据含义。

---

### User Story 4 - 语义感知段落切分 (Priority: P2)

作为知识库构建人员，我希望段落按语义边界切分，不在句子中间截断，以便检索结果语义完整。

**Why this priority**: 当前已有基础实现，需验证和增强边界检测能力。

**Independent Test**: 准备长段落文档，验证切分点都在句子边界。

**Acceptance Scenarios**:

1. **Given** 段落内容超过 max_chunk_chars，**When** 执行分块，**Then** 切分点在句子结束符（。！？等）之后。
2. **Given** 段落包含列表（如 1. 2. 3.），**When** 执行分块，**Then** 列表项不被截断，作为一个整体。

---

### User Story 5 - 层级结构保留 (Priority: P3)

作为 RAG 检索用户，我希望检索结果包含文档层级信息（章节、条款编号），以便理解上下文。

**Why this priority**: 层级信息提升检索结果的可读性和可信度。

**Independent Test**: 验证解析后的 chunk metadata 包含完整的层级路径。

**Acceptance Scenarios**:

1. **Given** 文档有章节结构（# ## ###），**When** 执行分块，**Then** chunk 的 section_path 包含完整层级路径。
2. **Given** 文档有条款编号（第一条、第二条），**When** 执行分块，**Then** chunk 的 article_number 字段正确记录条款号。

---

### Edge Cases

- 表格嵌套在其他内容中如何处理？
- 表格内包含合并单元格如何处理？
- PDF 扫描件中的表格（非文本层）如何处理？
- 多个表格紧邻且有语义关联是否合并？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 识别 Markdown 表格语法（`|...|` 格式），将表格作为完整语义单元。
- **FR-002**: 系统 MUST 识别 PDF 中的表格结构，支持跨页表格检测与合并。
- **FR-003**: 系统 MUST 为跨页/分块表格补充表头信息。
- **FR-004**: 系统 MUST 在段落切分时保持句子完整性，优先在句子边界切分。
- **FR-005**: 系统 MUST 保留文档层级结构信息到 chunk metadata。
- **FR-006**: 系统 MUST 兼容现有 MdParser 的公开接口（`parse_document`, `chunk`）。
- **FR-007**: [NEEDS CLARIFICATION: 表格分块的阈值策略是什么？]

### Key Entities

- **TableChunk**: 表格类型的 chunk，包含原始文本、结构化数据、表头信息。
- **SemanticChunk**: 普通文本 chunk，包含内容、层级路径、前后 chunk 关联。
- **TableHeader**: 表头信息，用于跨页表格和分块表格的表头补充。
- **ChunkMetadata**: chunk 元数据，包含 law_name、section_path、content_type 等。

## Success Criteria

- **SC-001**: Markdown 表格解析正确率达到 100%（表格不被切碎）。
- **SC-002**: 跨页表格合并准确率达到 90% 以上。
- **SC-003**: 超大表格分块后表头覆盖率达到 100%。
- **SC-004**: 现有测试用例 100% 通过，不引入回归问题。
- **SC-005**: 单文档解析性能不下降超过 20%。

## Assumptions

- Markdown 表格使用标准 `|...|` 语法，非复杂嵌套表格。
- PDF 文档使用 pdfplumber 提取表格，依赖其文本层提取能力。
- 不引入重量级依赖（如深度学习表格识别模型）。
- 表格分块阈值可配置，默认值为当前 max_chunk_chars。
