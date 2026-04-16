# Feature Specification: 评测数据集系统性改进

**Feature Branch**: `008-eval-dataset-improvement`
**Created**: 2026-04-10
**Status**: Draft
**Input**: 评测数据集问题评估报告（16个问题，P0×3 / P1×6 / P2×5 / P3×2）

## Background & Motivation

当前评测数据集（150条样本硬编码在 `eval_dataset.py`）存在三类根本性问题：

1. **指标体系缺陷** — Recall 值域超过 1.0、相关性判断不利用同义词、Faithfulness 用 bigram 代替语义判断，导致评估结果不可信
2. **数据集构建方法论缺失** — 无自动合成 pipeline、无覆盖度评估、无弱点驱动的迭代策略，数据集质量无法系统化提升
3. **样本质量与代表性不足** — 缺少"无答案"否定样本、口语化不够真实、知识点重复、topic 分布不均

这些问题使得评测数据集无法作为"可靠的评估基准"驱动系统迭代。

## User Scenarios & Testing

### User Story 1 - 修复 Recall 指标定义错误 (Priority: P0)

评测工程师运行检索评估时，Recall 指标值域为 [0, 1]，公式为 `recall = |matched_evidence_docs| / |evidence_docs|`，其中 `matched_evidence_docs` 是检索结果中命中的**去重** evidence_doc 集合（按 result 的 source_file 或 law_name 与 evidence_docs 匹配确定），而非简单统计相关结果数。

**实现要点**: 当前 `_is_relevant()` 只返回 bool，需要在 `evaluate()` 中从相关结果的 source_file/law_name 反查对应的 evidence_doc，构建去重匹配集合来计算 Recall。

**Why this priority**: Recall > 1.0 是指标定义的根本性错误，测试中直接断言 `recall == 2.0` 将错误固化。所有依赖 Recall 的报告和对比都不可信。

**Independent Test**: 运行 `pytest scripts/tests/lib/rag_engine/test_evaluator.py`，验证所有 recall 断言值域在 [0, 1]。现有测试中 `assert result['recall'] == 2.0` 的断言必须更新为正确值域。

**Acceptance Scenarios**:

1. **Given** 一个 evidence_docs 含 2 个文档的样本, **When** 检索返回 5 个结果中有 2 个相关（分别对应 2 个不同的 evidence_doc）, **Then** recall = 1.0（不是 2.0）
2. **Given** 一个 evidence_docs 含 3 个文档的样本, **When** 检索返回 5 个结果中有 1 个相关（对应 1 个 evidence_doc）, **Then** recall ≈ 0.33
3. **Given** 一个 evidence_docs 含 2 个文档的样本, **When** 检索返回 5 个结果中有 3 个相关但都对应同 1 个 evidence_doc（同一文档的多个 chunk）, **Then** recall = 0.5（而非 1.5）
4. **Given** 现有测试套件中 `recall == 2.0` 的断言, **When** Recall 修复后, **Then** 所有测试通过且断言值域在 [0, 1]
5. **Given** UNANSWERABLE 样本（evidence_docs 为空）, **When** 计算 Recall, **Then** recall 标记为 N/A，不参与 Recall 均值计算

---

### User Story 2 - 评估侧利用同义词表增强相关性判断 (Priority: P0)

`_is_relevant()` 在字面关键词匹配之外，利用 `synonyms.json` 中的 20 组保险同义词进行**双向**匹配扩展：既将 evidence_keywords 中的术语扩展为同义词去匹配检索内容，也用同义词反查 evidence_keywords。同义词扩展作为字面匹配失败后的补充手段（fallback），不替代原有的字面匹配和 embedding 语义判断的优先级。

**Why this priority**: 检索侧 `QueryPreprocessor` 已做同义词扩展，但评估侧没有，导致检索能力被系统性低估。例如标注关键词为"退保"时，检索到含"解除保险合同"的内容被判为不相关。

**与 US4 的关系**: US2 扩展匹配能力（减少漏判），US4 收紧匹配条件（减少误判）。实现时按以下优先级判断相关性：字面关键词匹配 > 来源文档匹配 > 同义词扩展匹配 > embedding 语义匹配。

**Independent Test**: 构造一个检索结果包含"解除保险合同"但不包含"退保"的场景，验证 `_is_relevant()` 能通过同义词识别为相关。

**Acceptance Scenarios**:

1. **Given** evidence_keywords = ["退保", "现金价值"], **When** 检索结果包含"解除保险合同...退还保单现金价值"但不含"退保", **Then** 判定为相关
2. **Given** evidence_keywords = ["免赔额"], **When** 检索结果包含"自付额"但不含"免赔额", **Then** 判定为相关
3. **Given** evidence_keywords = ["犹豫期"], **When** 检索结果包含"冷静期"但不含"犹豫期", **Then** 判定为相关
4. **Given** evidence_keywords = ["万能险"], **When** 检索结果包含"万能型保险"但不含"万能险", **Then** 判定为相关

---

### User Story 3 - 实现从文档 Chunk 自动合成问答对的 Pipeline (Priority: P0)

评测工程师能通过 CLI 命令或 API 从知识库文档的 **Chunk 粒度** 自动生成候选问答对：逐个将 Chunk 喂给 LLM，每个 Chunk 生成 2-3 个问题及对应答案和来源标注，经过质量过滤后加入评测数据集。

**Why this priority**: 文章指出"冷启动的核心任务是尽快建立可靠的评估基准"，具体方法是"把每个 Chunk 喂给 LLM，让它生成 2-3 个真实用户可能会基于这段内容提出的问题"。Chunk 级合成比文档级合成粒度更细、覆盖更均匀、答案更精准。

**Independent Test**: 使用知识库中的单个 Chunk 运行合成命令，验证输出的问答对格式正确、答案来自该 Chunk 内容。

**Acceptance Scenarios**:

1. **Given** 知识库中 `05_健康保险产品开发.md` 被切分为 N 个 Chunk, **When** 运行合成命令指定该文档, **Then** 对每个 Chunk 分别调用 LLM，共生成约 2N-3N 个候选问答对
2. **Given** 单个 Chunk 的内容, **When** LLM 合成, **Then** 每个问答对的 evidence_docs 包含该 Chunk 所属的源文档，evidence_keywords 从 Chunk 内容中提取
3. **Given** 生成的候选问答对, **When** 运行质量过滤, **Then** 过滤掉：答案长度 < 20 字的过于简单问题、与已有样本 question 相似度 > 0.8 的重复问题、答案中不包含任何 evidence_keyword 的一致性问题
4. **Given** LLM 返回格式异常（非 JSON、空内容）, **When** 合成 pipeline 处理, **Then** 记录警告并跳过该 Chunk，不中断整个流程
5. **Given** 过滤后的候选问答对, **When** 导入评测数据集, **Then** created_by 标记为 "llm"，review_status 为 "pending"
6. **Given** 合成问答对, **When** 保存到 eval_dataset.json, **Then** 文件格式与现有 load_eval_dataset 兼容

---

### User Story 4 - 增强相关性判断的准确性 (Priority: P1)

`_is_relevant()` 的相关性判断从"匹配 2 个关键词即为相关"改为更严格的综合判断：区分"泛关键词"和"领域关键词"，泛关键词（如"保险"、"条款"、"规定"等高频通用词）不单独触发相关性，必须有来源文档佐证。领域关键词（如"等待期"、"既往症"、"免赔额"）仍可按原逻辑匹配。

**泛关键词判定标准**: 长度 ≤ 3 的中文字词，或出现在 `stopwords.txt` 中的词。`synonyms.json` 中的标准术语（如"退保"、"理赔"、"免赔额"）视为领域关键词，不受泛关键词限制。

**与 US2 的关系**: 先应用同义词扩展（US2），再应用严格度收紧（US4）。优先级：字面匹配 > 来源文档匹配 > 同义词扩展 > embedding 语义匹配。

**Why this priority**: 当前"匹配2个关键词即为相关"在保险监管领域容易误判。例如查询"保险合同的犹豫期"可能匹配到包含"保险"和"犹豫期"但实际讨论其他主题的文档片段。

**Independent Test**: 构造一个包含泛关键词（如"保险"、"条款"）但不相关的检索结果，验证不再被判为相关。

**Acceptance Scenarios**:

1. **Given** evidence_keywords = ["等待期", "既往症"], **When** 检索结果包含"保险"和"既往症"但不包含"等待期"且来源文档不匹配, **Then** 判定为不相关（"既往症"是领域关键词但仅匹配 1 个领域关键词不够，"保险"是泛关键词不能单独计数）
2. **Given** evidence_keywords = ["保险", "条款"], **When** 检索结果包含"保险"和"条款"但来源文档不在 evidence_docs 中, **Then** 判定为不相关（两个都是泛关键词，必须来源文档佐证）

---

### User Story 5 - 增加"知识库无答案"否定样本 (Priority: P1)

评测数据集中包含一类新样本：问题是合理的保险领域查询，但知识库中没有对应监管规定。用于评估系统是否能正确识别"不知道"的场景而非编造幻觉。

**Why this priority**: 文章指出合成数据的固有偏差是"缺少知识库里根本没有答案的问题"。这是评估幻觉防范能力的关键场景。

**UNANSWERABLE 样本规范**:
- `question`: 合理的保险领域查询
- `ground_truth`: 固定为"知识库中无对应规定"
- `evidence_docs`: 空列表 `[]`
- `evidence_keywords`: 填写问题中的领域关键词（用于检索评估）

**Independent Test**: 使用"无答案"样本运行评估，验证系统能识别并拒绝回答（而非编造内容）。

**Acceptance Scenarios**:

1. **Given** 一个"无答案"样本（如"保险公司可以在抖音上直播卖保险吗"）, **When** 运行评估, **Then** 系统有指标衡量"是否正确拒绝回答"
2. **Given** 新增的 UNANSWERABLE 样本类型, **When** 加载评测数据集, **Then** QuestionType 枚举包含 UNANSWERABLE
3. **Given** UNANSWERABLE 样本, **When** 导入数据集, **Then** ground_truth 为"知识库中无对应规定"，evidence_docs 为空列表
4. **Given** 一个部分知识可回答的问题（如 KB 提到概念但无具体规定）, **When** 分类, **Then** 归类为 FACTUAL（答案不完整）而非 UNANSWERABLE

---

### User Story 6 - 实现知识库文档覆盖度评估 (Priority: P1)

评测工程师能查看评测数据集对知识库文档的覆盖度报告，识别哪些文档/章节被充分覆盖、哪些是覆盖盲点。

**Why this priority**: 无法回答"150条样本是否充分覆盖14份知识库文档"这个关键问题。覆盖度是评估数据集质量的基础指标。

**Independent Test**: 对当前 150 条样本运行覆盖度检查，输出每份文档的样本数量分布。

**Acceptance Scenarios**:

1. **Given** 当前 150 条评测样本, **When** 运行覆盖度检查, **Then** 输出每份 KB 文档（01-14）被引用的样本数量
2. **Given** 覆盖度报告, **When** 某文档引用数为 0, **Then** 标记为覆盖盲点并警告
3. **Given** 覆盖度报告, **When** 某文档引用数 < 5, **Then** 标记为覆盖不足
4. **Given** 空的评测数据集, **When** 运行覆盖度检查, **Then** 报告显示所有 KB 文档为覆盖盲点

---

### User Story 7 - 实现弱点驱动的样本补充建议 (Priority: P1)

评测运行后，系统能基于失败样本和低分样本，生成"优先补充哪些类型样本"的建议报告，帮助评测工程师有针对性地扩充数据集。

**Why this priority**: 文章建议"优先标注系统最不确定、或当前回答最差的样本"。当前缺少从评估结果到数据集改进的闭环。

**Independent Test**: 运行一次完整评估后，查看弱点报告是否包含具体的补充建议。

**Acceptance Scenarios**:

1. **Given** 一次评估运行结果, **When** 生成弱点报告, **Then** 列出 recall < 0.5 的失败样本
2. **Given** 弱点报告, **When** 按题型和 topic 聚合, **Then** 识别出"哪些 topic 的哪些题型最薄弱"
3. **Given** 薄弱领域识别, **When** 与覆盖度报告交叉分析, **Then** 给出"优先在 X topic 补充 Y 类型样本"的建议

---

### User Story 8 - 修正 Faithfulness 评估 (Priority: P1)

`compute_faithfulness()` 从纯 bigram 重叠度改为语义感知的评估方式，在 embedding 可用时利用语义相似度判断答案对上下文的忠实度。新公式：`faithfulness = α × sentence_semantic_coverage + β × bigram_overlap`，其中语义覆盖使用句子级 embedding 相似度（阈值 ≥ 0.7），α=0.7, β=0.3。

**Why this priority**: 当前 bigram 重叠度 + 0.4 阈值容易放过幻觉（同义改写但语义不同的内容会被判为忠实）。该函数被 `feedback.py`（feedback API）和 `test_qa_prompt.py`（测试）直接调用，修改必须向后兼容。

**Independent Test**: 构造一个与上下文语义不同但 bigram 重叠度高的答案，验证被正确判为低忠实度。

**Acceptance Scenarios**:

1. **Given** 上下文"等待期不超过180天", **When** 答案为"等待期不超过360天"（bigram 高重叠但语义错误）, **Then** faithfulness < 0.5
2. **Given** 上下文描述A规则, **When** 答案用同义表达准确复述A规则, **Then** faithfulness ≥ 0.8
3. **Given** embedding 模型不可用, **When** 计算 faithfulness, **Then** 回退到 bigram 方式但不报错
4. **Given** 上下文包含多个句子, **When** 答案中有一个句子与上下文语义矛盾, **Then** 该句子的语义覆盖率 < 0.7，拉低整体 faithfulness

---

### User Story 9 - 数据集持久化与去硬编码 (Priority: P2)

评测数据集持久化到 `eval_dataset.json` 文件，`create_default_eval_dataset()` 仅作为首次初始化的 fallback。后续修改通过 API 或 CLI 操作，不再需要改代码。

**前置依赖**: US13（created_by 标记准确性）应在本 Story 之前完成，确保迁移到 JSON 时标记已审查。

**Why this priority**: 当前 eval_dataset.json 不存在，150条样本全部硬编码在 Python 源码中，任何修改都需要改代码走代码审查。

**Independent Test**: 删除 eval_dataset.json，调用 load_eval_dataset() 自动生成并保存；再次调用从文件加载而非代码。

**Acceptance Scenarios**:

1. **Given** eval_dataset.json 不存在, **When** 调用 load_eval_dataset(), **Then** 自动从代码生成默认数据集并保存到 JSON 文件
2. **Given** eval_dataset.json 已存在, **When** 调用 load_eval_dataset(), **Then** 从 JSON 文件加载（不执行代码中的硬编码函数）
3. **Given** 通过 API 修改了样本, **When** 重新加载, **Then** 修改后的内容被持久化

---

### User Story 10 - 增强数据集验证器 (Priority: P2)

`dataset_validator.py` 增加三项验证能力：ground_truth 与 evidence_docs 的一致性检查、样本间重复/相似度检测、evidence_keywords 区分度检查。

**Why this priority**: 当前验证器只检查字段非空和关键词长度，无法发现质量问题（如同一知识点的重复样本、过于泛化的关键词）。

**Independent Test**: 对当前 150 条样本运行增强验证，验证能检测出"犹豫期"相关的高重复样本和"保险"等泛关键词。

**Acceptance Scenarios**:

1. **Given** 两条样本的 question 相似度 > 0.8, **When** 运行验证, **Then** 报告"重复样本"警告
2. **Given** evidence_keywords 中包含"保险"（3字通用词）, **When** 运行验证, **Then** 报告"关键词过于泛化"警告
3. **Given** 一条样本的 ground_truth 与 evidence_docs 引用的文档内容完全无关, **When** 运行验证, **Then** 报告"答案与证据文档不一致"错误

---

### User Story 11 - 补充高质量样本解决分布问题 (Priority: P2)

通过手工和自动合成结合的方式，补充以下类型样本：去重后的高信息密度样本、带场景的口语化样本、3+文档的复杂推理样本、均衡 topic 分布的样本。

**Why this priority**: 当前数据集存在知识点重复（犹豫期 6+ 条）、口语感弱、MULTI_HOP 缺少复杂推理、topic 分布不均等问题。

**Independent Test**: 运行 `validate_dataset()` 检查分布指标，验证重复率下降、topic 分布更均匀。

**Acceptance Scenarios**:

1. **Given** 当前数据集, **When** 去重后, **Then** 同一知识点（如犹豫期）的样本不超过 3 条
2. **Given** 补充后的 COLLOQUIAL 样本, **When** 人工审核, **Then** 至少 50% 包含具体场景描述（如"我妈55岁有高血压"而非"健康险投保条件"）
3. **Given** 补充后的 MULTI_HOP 样本, **When** 统计, **Then** 至少 5 条需要综合 3 个以上文档进行推理
4. **Given** 补充后的数据集, **When** 按 topic 统计, **Then** 任何单一 topic 的样本数不超过总数的 20%

---

### User Story 12 - 增加"拒绝回答"评估指标 (Priority: P2)

评估体系新增指标衡量系统面对超出知识库范围问题时的表现：是否正确拒绝回答而非编造幻觉。

**Why this priority**: 当前系统无法评估"不知道"场景。实际用户会问超出知识库的问题，系统应能正确拒绝而非编造。

**Independent Test**: 使用 UNANSWERABLE 样本运行评估，验证拒绝回答率指标。

**Acceptance Scenarios**:

1. **Given** UNANSWERABLE 类型样本, **When** 运行评估, **Then** 输出 "rejection_rate" 指标（正确拒绝回答的比例）
2. **Given** 系统对无答案问题编造了答案, **When** 评估, **Then** 该样本标记为 "hallucination_on_unanswerable" 失败类型
3. **Given** 评估报告, **When** 包含 UNANSWERABLE 样本, **Then** 报告中单独展示该类型的指标

---

### User Story 13 - ground_truth 来源标记准确性 (Priority: P1)

自动合成的样本 `created_by` 正确标记为 "llm"，手工创建的样本标记为 "human"。数据集加载时对现有样本的标记进行一致性检查。

**Why this priority**: 当前所有硬编码样本的 `created_by` 默认值为 "human"，但多数 ground_truth 看起来像 LLM 生成。标记不准确会影响后续的质量分析和迭代策略。

**Independent Test**: 加载数据集后验证 created_by 标记与实际来源一致。

**Acceptance Scenarios**:

1. **Given** 通过合成 pipeline 生成的样本, **When** 保存到数据集, **Then** created_by = "llm"
2. **Given** 通过 API 手工创建的样本, **When** 保存到数据集, **Then** created_by = "human"
3. **Given** 现有硬编码的 150 条样本, **When** 迁移到 JSON, **Then** created_by 标记经过审查并准确

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 将 Recall 指标的值域修正为 [0, 1]，分母使用"实际相关文档数"而非"标注文档数"
- **FR-002**: 系统 MUST 在 `_is_relevant()` 中利用 `synonyms.json` 同义词表进行匹配扩展
- **FR-003**: 系统 MUST 提供从知识库文档 Chunk 自动合成问答对的 pipeline（CLI + API）
- **FR-004**: 系统 MUST 增加相关性判断的严格度，避免仅靠泛关键词匹配误判为相关
- **FR-005**: 系统 MUST 支持 UNANSWERABLE 问题类型，包含"知识库无答案"的否定样本
- **FR-006**: 系统 MUST 提供知识库文档覆盖度评估功能
- **FR-007**: 系统 MUST 提供弱点驱动的样本补充建议报告
- **FR-008**: 系统 MUST 改进 `compute_faithfulness()` 在 embedding 可用时使用语义相似度
- **FR-009**: 系统 MUST 将默认评测数据集持久化到 `eval_dataset.json`
- **FR-010**: 系统 MUST 增强 `dataset_validator` 的验证能力（重复检测、一致性检查、关键词区分度）
- **FR-011**: 系统 MUST 补充样本解决分布问题（去重、口语化、复杂推理、topic 均衡）
- **FR-012**: 系统 MUST 增加"拒绝回答"评估指标（rejection_rate）
- **FR-013**: 系统 MUST 确保 `created_by` 标记准确反映样本来源（human / llm）
- **FR-014**: 系统 MUST 更新现有测试套件中不正确的断言（如 `recall == 2.0`），确保所有测试在修改后通过

### Key Entities

- **EvalSample**: 评测样本，核心字段包括 question, ground_truth, evidence_docs, evidence_keywords, question_type, difficulty, topic, created_by
- **QuestionType**: 问题类型枚举，新增 UNANSWERABLE（当前：FACTUAL, MULTI_HOP, NEGATIVE, COLLOQUIAL）
- **QualityAuditReport**: 数据集质量审计报告，新增重复检测、一致性检查、关键词区分度、覆盖度分析
- **WeaknessReport**: 弱点分析报告，包含失败样本聚合、薄弱领域识别、补充建议
- **CoverageReport**: 知识库覆盖度报告，包含每份 KB 文档的样本引用统计

## Success Criteria

- **SC-001**: Recall 指标值域 [0, 1]，所有现有测试通过且断言值域正确
- **SC-002**: `_is_relevant()` 利用同义词表后，对包含同义表达的相关文档的识别率提升
- **SC-003**: 合成 pipeline 能从单个 KB 文档生成 2-3 个格式正确的候选问答对
- **SC-004**: 14 份 KB 文档中每份至少有 5 条评测样本引用（覆盖盲点清零）
- **SC-005**: 同一知识点的样本不超过 3 条（重复率下降）
- **SC-006**: 数据集从 eval_dataset.json 加载（不再依赖硬编码 fallback）
- **SC-007**: `pytest scripts/tests/` 全部通过

## Assumptions

- 知识库文档（14 份 .md 文件）内容稳定，短期内不会大幅变更
- LLM API（用于合成问答对）的调用成本在可接受范围内（单文档合成约 2-3 次 LLM 调用，14 份文档约 30-40 次调用）
- 合成 pipeline 的 Chunk 数据来源从 KBManager 获取生效版本的知识库（LanceDB 索引），不直接读取原始 .md 文件
- 现有 150 条样本的 ground_truth 质量总体可接受，不需要全部重新标注
- `synonyms.json` 的 20 组同义词已覆盖主要术语变体
- embedding 模型在评估环境中可用（fallback 到 bigram 方式）
- 评测数据集改进不需要修改知识库本身的文档和索引结构
- 专家标注和真实用户数据属于运营流程，已有 review_status（PENDING→APPROVED）机制支撑，不在本次开发范围
- `source_file` 字段值格式需在实现阶段确认（预期为文件名如 `05_健康保险产品开发.md`，非完整路径）

## Out of Scope

- 知识库文档质量治理（OCR、结构化解析、去重、版本管理）— 属于知识库构建范畴
- RAG 系统本身的检索/生成优化 — 本次只改进评测数据集
- 自动化 CI 集成和定期评估调度 — 属于 DevOps 范畴
- 评估报告的 PDF 导出功能
- 前端 UI 改造

## Problem Traceability

| # | 原始问题 | 优先级 | 对应 User Story |
|---|---------|--------|----------------|
| 1 | Recall 值域超过 1.0 | P0 | US1 |
| 2 | 无自动合成 pipeline | P0 | US3 |
| 3 | `_is_relevant` 未利用同义词表 | P0 | US2 |
| 4 | 缺少"知识库无答案"否定样本 | P1 | US5 |
| 5 | ground_truth 质量可疑/created_by 不准确 | P1 | US13 |
| 6 | `_is_relevant` 纯关键词匹配过于宽松 | P1 | US4 |
| 7 | `compute_faithfulness` 用 bigram 代替语义 | P1 | US8 |
| 8 | 缺少知识库文档覆盖度评估 | P1 | US6 |
| 9 | 缺少基于弱点优先补充样本的策略 | P1 | US7 |
| 10 | 同一知识点重复样本过多 | P2 | US11 |
| 11 | COLLOQUIAL 样本口语感不够真实 | P2 | US11 |
| 12 | 数据集硬编码在源码中 | P2 | US9 |
| 13 | dataset_validator 验证太浅 | P2 | US10 |
| 14 | 缺少"拒绝回答"评估指标 | P2 | US12 |
| 15 | MULTI_HOP 多为对比类，缺少复杂推理 | P3 | US11 |
| 16 | topic 分布不均 | P3 | US11 |
