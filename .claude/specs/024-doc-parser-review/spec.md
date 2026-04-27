# Feature Specification: Doc Parser 模块审查与改进

**Feature Branch**: `024-doc-parser-review`
**Created**: 2026-04-24
**Status**: Draft
**Input**: 系统并深入梳理 actuary-sleuth 的 doc_parser 模块的设计与代码实现，重点关注 docx 和 pdf 等文档的文档解析，review 潜在问题和改进点

## User Scenarios & Testing

### User Story 1 - PDF 多栏排版正确解析 (Priority: P1)

保险公司的理赔指南通常采用双栏排版，左侧是正文，右侧是补充说明。当前解析器按行顺序提取文本，导致左右栏内容混在一起，语义完全混乱。需要实现版面分析，识别多栏结构并按逻辑顺序重组。

**Why this priority**: 多栏混排直接破坏语义完整性，是最严重的数据质量问题，影响所有后续检索和问答。

**Independent Test**: 准备一个双栏排版的 PDF 测试文件，解析后验证左侧正文和右侧说明是否被正确分离，而非混在一起。

**Acceptance Scenarios**:

1. **Given** 一个双栏排版的 PDF 文件（左侧正文，右侧补充说明）, **When** 调用 PDF 解析器, **Then** 输出文本中左侧正文和右侧说明分别形成独立段落，而非按行交错
2. **Given** 一个单栏排版的 PDF 文件, **When** 调用 PDF 解析器, **Then** 输出文本保持原有段落顺序不变

---

### User Story 2 - 页眉页脚过滤 (Priority: P1)

PDF 文件通常包含页眉（如"XXX保险公司 内部资料"）和页脚（如"第 X 页/共 Y 页"），这些无意义文本会混入每个 Chunk，干扰向量检索。需要识别并过滤页眉页脚区域。

**Why this priority**: 页眉页脚污染影响每个 Chunk 的质量，导致检索结果中充斥无意义文本。

**Independent Test**: 准备一个带页眉页脚的 PDF，解析后验证页眉页脚文本是否被过滤。

**Acceptance Scenarios**:

1. **Given** 一个带页眉"内部资料"和页脚"第 1 页/共 10 页"的 PDF, **When** 调用 PDF 解析器, **Then** 输出文本中不包含"内部资料"和"第 X 页/共 Y 页"等页眉页脚文本
2. **Given** 一个无页眉页脚的 PDF, **When** 调用 PDF 解析器, **Then** 输出文本完整保留正文内容

---

### User Story 3 - 扫描件 OCR 质量优化 (Priority: P2)

历史合同大量是扫描件，存在低分辨率、水印印章叠加、表格结构失真等问题。需要：
1. 低分辨率扫描：图像清晰度检测 + 预处理（对比度增强、降噪、矫正偏斜）
2. 水印印章：像素级分割去除水印后再 OCR
3. 表格 OCR：特殊处理策略

**Why this priority**: 扫描件 OCR 质量直接影响历史合同的可用性，但已有基础 OCR 能力，属于优化改进。

**Independent Test**: 准备低分辨率扫描件、带水印扫描件，验证 OCR 准确率提升。

**Acceptance Scenarios**:

1. **Given** 一个低分辨率（150 DPI）扫描件, **When** 调用 OCR 解析器, **Then** 先进行图像预处理再 OCR，识别准确率高于直接 OCR
2. **Given** 一个带红色公章水印的扫描件, **When** 调用 OCR 解析器, **Then** 水印区域被识别并去除后再 OCR，减少乱码

---

### User Story 4 - 无边框表格智能解析 (Priority: P1)

保险合同中的无边框对齐式表格（靠空格对齐）是最难解析的内容。通用工具识别出来的是一堆没有行列关系的文本。需要：
1. 前置分类器识别无边框表格
2. 对无边框表格调用专用解析器（如 MinerU）
3. 对普通表格调用轻量工具（如 camelot）

**Why this priority**: 表格中的保费、责任范围等数字是用户最常查询的内容，解析失败直接影响问答质量。

**Independent Test**: 准备无边框表格 PDF，验证解析后保持行列结构。

**Acceptance Scenarios**:

1. **Given** 一个无边框对齐式表格 PDF, **When** 调用表格解析器, **Then** 前置分类器识别为无边框表格，调用 MinerU 解析，输出保持行列结构
2. **Given** 一个有边框结构化表格 PDF, **When** 调用表格解析器, **Then** 分类器识别为有边框表格，调用轻量工具解析
3. **Given** 一个混合页（既有有边框也有无边框表格）, **When** 调用表格解析器, **Then** 各表格被正确分类并调用对应解析器

---

### User Story 5 - 表格存储格式标准化 (Priority: P2)

解析出的表格需要以 Markdown 格式存储进向量库，LLM 对 Markdown 表格理解一致性最好，且方便人工审查。

**Why this priority**: 存储格式影响 LLM 理解质量，但已有基础存储能力，属于格式优化。

**Independent Test**: 解析表格后验证输出为 Markdown 格式，且 LLM 能正确理解。

**Acceptance Scenarios**:

1. **Given** 解析出的表格数据, **When** 序列化存储, **Then** 输出 Markdown 格式表格字符串
2. **Given** 超大表格（超过 Chunk 大小限制）, **When** 分割存储, **Then** 每个子 Chunk 都携带表头

---

### User Story 6 - Chunk 元数据挂载 (Priority: P1)

每个 Chunk 需要挂载完整元数据，包括：文档 ID、章节路径、是否关键条款、前后 Chunk 引用等。元数据用于检索过滤、来源展示、归因分析。

**Why this priority**: 元数据是检索质量和可解释性的基础，缺失元数据会导致检索结果无上下文。

**Independent Test**: 解析文档后验证每个 Chunk 携带完整元数据。

**Acceptance Scenarios**:

1. **Given** 解析出的文档 Chunk, **When** 提取元数据, **Then** 包含 doc_id、doc_name、section_path、section_level、chunk_index、is_key_clause、has_table、prev_chunk_id、next_chunk_id、parse_confidence、update_time
2. **Given** 来自"责任免除"章节的 Chunk, **When** 提取元数据, **Then** section_path 为"第3条保险责任 > 3.2责任免除"，is_key_clause 为 True

---

### User Story 7 - 术语标准化处理 (Priority: P2)

同一概念在保险文档中有多种写法（如"被保险人"/"被保人"/"投保对象"），需要构建同义词词典，在文档入库和查询时进行标准化处理，提升检索匹配率。

**Why this priority**: 术语不一致影响 BM25 召回率和向量相似度，实测可提升 Recall@5 约 6%。

**Independent Test**: 输入含同义词的文本，验证标准化后替换为标准术语。

**Acceptance Scenarios**:

1. **Given** 文档 Chunk 含"被保人", **When** 术语标准化处理, **Then** 替换为"被保险人"
2. **Given** 用户查询"被保人能不能买", **When** 查询预处理, **Then** 标准化为"被保险人能不能买"
3. **Given** 含"90天"和"三个月"的文档, **When** 数字格式统一处理, **Then** 统一为相同格式

---

### Edge Cases

- 空白页或纯图片页如何处理？
- 表格跨页分割如何合并？
- 嵌套表格（表格内含表格）如何解析？
- 页码格式不统一（"第1页"vs"Page 1"）如何识别？
- 扫描件旋转/倾斜如何检测和矫正？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 实现 PDF 版面分析，识别多栏结构并按逻辑顺序重组文本
- **FR-002**: 系统 MUST 识别并过滤页眉页脚区域
- **FR-003**: 系统 MUST 对扫描件进行图像质量检测，低分辨率时进行预处理
- **FR-004**: 系统 MUST 支持水印印章区域的识别和去除（可选，需模型）
- **FR-005**: 系统 MUST 实现表格类型分类器，区分有边框和无边框表格
- **FR-006**: 系统 MUST 对无边框表格调用专用解析器
- **FR-007**: 系统 MUST 以 Markdown 格式存储表格数据
- **FR-008**: 系统 MUST 为每个 Chunk 挂载完整元数据
- **FR-009**: 系统 MUST 构建保险领域同义词词典
- **FR-010**: 系统 MUST 在文档入库和查询时进行术语标准化处理
- **FR-011**: 系统 MUST 统一数字和日期格式

### Key Entities

- **LayoutRegion**: 版面区域，包含类型（标题/正文/左栏/右栏/页眉/页脚）、坐标、内容
- **Table**: 表格实体，包含类型（有边框/无边框）、行列数据、Markdown 表示
- **ChunkMetadata**: Chunk 元数据，包含文档信息、章节路径、前后引用、置信度等
- **SynonymDict**: 同义词词典，映射标准术语到同义词列表

## Success Criteria

- **SC-001**: 双栏 PDF 解析后，左右栏内容正确分离（人工抽检 50 个样本，准确率 > 90%）
- **SC-002**: 页眉页脚过滤后，Chunk 中无无意义文本（人工抽检验证）
- **SC-003**: 无边框表格解析保持行列结构（人工抽检 30 个表格，准确率 > 85%）
- **SC-004**: 每个 Chunk 携带完整元数据（元数据字段完整率 = 100%）
- **SC-005**: 术语标准化后，BM25 Recall@5 提升 > 5%

## Assumptions

- 当前已有基础 PDF/DOCX 解析能力，本任务是对现有能力的审查和改进
- 水印去除需要训练 U-Net 模型，属于可选能力，优先级较低
- 版面分析可先用 pdfplumber 坐标信息实现，复杂场景再考虑 layoutparser
- 表格分类器可先用规则判断（如检测边框线），再考虑 CNN 分类器
- 无边框表格解析工具 MinerU 需要单独部署，需评估引入成本
