# Feature Specification: RAG 评估体系评估与改进

**Feature Branch**: `002-rag-eval-assessment`
**Created**: 2026-04-05
**Status**: Draft
**Input**: 参考三篇行业文章，评估当前 RAG 评估体系和评测数据集的实现，并规划改进方案

## 背景与现状

### 参考标准

基于三篇行业文章提取的 RAG 评估标准：

1. **五维评估框架**（文章1）：准确性（BLEU/ROUGE/MRR/Top-k）、可信度（文档覆盖率）、响应速度、可扩展性、用户体验
2. **三层评估体系**（文章2）：检索评估（Recall@K/Precision@K/MRR/nDCG）→ 生成一致性（Faithfulness/Groundedness/Factual Consistency）→ 系统整体（延迟/吞吐/可复现性）
3. **工程化评估**（文章3）：测试集构建六步流程、检索四指标（Precision@K/Recall@K/MRR/nDCG/冗余率）、生成三维度（答案正确性/忠实度/答案相关性）、工具选型（RAGAS/TruLens/DeepEval）、A/B 对比

### 当前实现

| 维度 | 现状 | 差距等级 |
|------|------|---------|
| 检索指标 | Precision@K, Recall@K, MRR, NDCG, Redundancy, Context Relevance | 基本完备 |
| 生成指标 | Faithfulness, Answer Relevancy, Answer Correctness（轻量 token 指标） | 较大差距 |
| 评测数据集 | 60 条，4 种题型，保险监管领域 | 较大差距 |
| 评估流程 | CLI + Web UI，异步执行、对比、快照 | 部分完备 |
| LLM-as-a-Judge | 未实现 | 缺失 |
| 评估指南 | 无指标阈值和结果解读文档 | 缺失 |
| 在线监控 | 无 | 缺失 |

---

## User Scenarios & Testing

### User Story 1 - 评估报告生成 (Priority: P1)

作为精算审核系统的开发者，我希望生成一份全面的 RAG 评估现状报告，对照行业标准逐维度分析当前实现的差距，明确哪些方面已达标、哪些需要改进。

**Why this priority**: 评估报告是所有后续改进工作的基础，必须先明确现状和差距才能有针对性地优化。

**Independent Test**: 报告可通过独立脚本生成，输出结构化的评估文档，包含每个维度的达标状态和差距分析。

**Acceptance Scenarios**:

1. **Given** 当前 RAG 评估系统代码，**When** 运行评估分析，**Then** 输出覆盖检索指标、生成指标、数据集、流程、工具链等全部维度的评估报告
2. **Given** 三篇参考文章的行业标准，**When** 对比当前实现，**Then** 每个维度标注"达标/部分达标/缺失"状态，并附带差距说明
3. **Given** 评估报告，**When** 按差距严重程度排序，**Then** 输出改进优先级列表

---

### User Story 2 - 评测数据集扩充 (Priority: P1)

作为精算审核系统的开发者，我希望将评测数据集从 60 条扩充到 150+ 条，重点覆盖不同保险产品条款的审核场景，并建立持续迭代机制。

**Why this priority**: 数据集是评估的基石，规模不足和覆盖不全会直接影响评估结论的可信度。精算审核场景（条款、定价、免责、等待期等）是系统核心，必须有充分覆盖。

**Independent Test**: 扩充后的数据集可通过现有评估流程独立运行，验证指标计算和数据加载正确性。

**Acceptance Scenarios**:

1. **Given** 当前 60 条数据集，**When** 扩充数据集，**Then** 总量达到 150+ 条，新增样本覆盖多产品类型（重疾险、医疗险、意外险、寿险等）
2. **Given** 扩充后的数据集，**When** 按问题类型统计分布，**Then** 事实题、多跳推理题、否定性查询、口语化查询四种类型均有充足样本
3. **Given** 扩充后的数据集，**When** 按难度统计分布，**Then** 简单、中等、困难三级梯度合理分布
4. **Given** 扩充后的数据集，**When** 按审核点统计，**Then** 覆盖等待期、免责条款、保额计算、赔付比例、健康告知、犹豫期等核心审核点
5. **Given** 新增的 badcase 样本，**When** 验证每条样本，**Then** 每条包含 question、ground_truth、evidence_docs、evidence_keywords 完整标注

---

### User Story 3 - LLM-as-a-Judge 实现 (Priority: P1)

作为精算审核系统的开发者，我希望实现 LLM-as-a-Judge 评估机制，用 LLM 替代 token 匹配来评判生成质量，并配合人工抽检校准。

**Why this priority**: 当前生成指标依赖 token 级 bigram/Jaccard 匹配，对语义等价但表述不同的回答评估不准确。LLM-as-a-Judge 是行业标准做法，能更准确评估忠实度、正确性和相关性。

**Independent Test**: LLM Judge 可独立运行，输出评分结果，与人工评分对比计算偏差。

**Acceptance Scenarios**:

1. **Given** 评测数据集和 RAG 生成的回答，**When** 运行 LLM Judge 评估，**Then** 输出每条样本的忠实度、正确性、相关性评分（0-1 分）
2. **Given** LLM Judge 评分结果，**When** 抽样 20% 进行人工评分对比，**Then** 两者偏差在 10% 以内
3. **Given** RAGAS 不可用的情况，**When** LLM Judge 作为独立评估器运行，**Then** 不依赖 RAGAS 库即可完成评估
4. **Given** LLM Judge 评分，**When** 与现有轻量 token 指标对比，**Then** 两种评估结果均可查看，LLM Judge 作为主要指标

---

### User Story 4 - 评估指南与阈值 (Priority: P2)

作为精算审核系统的开发者，我希望有一份评估指南文档，明确各指标的合格阈值、解读方法和优化建议，让评估结果可操作。

**Why this priority**: 有了指标但没有解读标准，评估结果就只是数字。评估指南能将指标转化为可操作的优化方向。

**Independent Test**: 指南文档独立于代码，可通过人工评审验证其准确性和实用性。

**Acceptance Scenarios**:

1. **Given** 评估指标结果，**When** 参照评估指南，**Then** 能判断每项指标是否达标
2. **Given** 未达标的指标，**When** 查看评估指南，**Then** 能找到对应的优化建议和常见原因
3. **Given** 评估指南中的阈值，**When** 在当前数据集上验证，**Then** 阈值设定合理，符合实际分布

---

### User Story 5 - 评估流程优化 (Priority: P2)

作为精算审核系统的开发者，我希望优化评估流程，支持增量评估、统计显著性检验和更详细的错误分析。

**Why this priority**: 当前评估只支持全量批量执行，缺少统计严谨性和细粒度的错误定位能力。

**Independent Test**: 优化后的评估流程可通过现有 API 和 CLI 独立运行。

**Acceptance Scenarios**:

1. **Given** 修改了检索策略，**When** 运行增量评估（仅跑修改相关的样本子集），**Then** 输出该子集的指标变化
2. **Given** 两次评估结果，**When** 对比分析，**Then** 标注指标变化是否具有统计显著性
3. **Given** 评估失败样本（recall < 0.5），**When** 查看错误分析，**Then** 输出失败原因分类（关键词未命中、语义相似度不足、文档缺失等）

---

### User Story 6 - 数据集质量审查流程 (Priority: P2)

作为精算审核系统的开发者，我希望建立数据集质量审查流程，包括交叉验证和自动校验，确保评测数据的质量可信。

**Why this priority**: 参考文章建议抽样 20% 做交叉验证，初次标注错误率约 8%。当前系统无质量审查机制，数据集质量无法保证。

**Independent Test**: 质量审查工具可独立运行，输出审查报告。

**Acceptance Scenarios**:

1. **Given** 评测数据集，**When** 运行自动校验，**Then** 检查每条样本的字段完整性、ground_truth 与 evidence_docs 的一致性、关键词的有效性
2. **Given** 校验结果，**When** 发现问题样本，**Then** 标注问题类型并生成修复建议
3. **Given** 审查流程，**When** 执行交叉验证，**Then** 支持随机抽样 20% 样本供人工复核

---

### User Story 7 - Badcase 沉淀与持续迭代 (Priority: P3)

作为精算审核系统的开发者，我希望将线上发现的 badcase 自动或半自动地加入评测数据集，形成持续迭代的闭环。

**Why this priority**: 参考文章强调测试集需要持续迭代，badcase 是最有价值的评测样本。但当前系统缺乏从线上到评测集的闭环。

**Independent Test**: Badcase 导入流程可通过 API 独立运行。

**Acceptance Scenarios**:

1. **Given** 一条线上 badcase（用户问题 + 系统回答 + 期望回答），**When** 提交到评测数据集，**Then** 自动填充 evidence_docs 和 evidence_keywords
2. **Given** 新增的 badcase 样本，**When** 自动标注 evidence 信息，**Then** 标注结果准确率 ≥ 80%（需人工抽检确认）
3. **Given** 数据集迭代历史，**When** 查看版本变化，**Then** 可追溯每次新增/修改/删除的样本

---

## Edge Cases

- LLM Judge 评分不稳定（同一输入多次评分结果差异大）→ 需要多次采样取均值
- 数据集扩充后评估耗时过长 → 需要支持并行评估或子集评估
- RAGAS 和 LLM Judge 同时可用时选择哪个 → LLM Judge 优先，RAGAS 作为备选
- 自动标注 evidence_docs 失败 → 降级为人工标注模式
- 中文保险术语的 token 匹配精度 → 需要领域词典增强

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 输出一份结构化的 RAG 评估现状报告，覆盖检索指标、生成指标、数据集、流程、工具链全部维度
- **FR-002**: 系统 MUST 将评测数据集从 60 条扩充到 150+ 条，覆盖多产品类型和核心审核点
- **FR-003**: 系统 MUST 实现 LLM-as-a-Judge 评估机制，评估忠实度、正确性、相关性三个维度
- **FR-004**: 系统 MUST 支持 LLM Judge 评分与人工抽检的对比校准流程
- **FR-005**: 系统 SHOULD 提供评估指南文档，包含指标阈值和解读建议
- **FR-006**: 系统 SHOULD 支持增量评估和统计显著性检验
- **FR-007**: 系统 SHOULD 支持数据集自动校验和交叉验证
- **FR-008**: 系统 SHOULD 支持从线上 badcase 到评测数据集的沉淀流程
- **FR-009**: LLM Judge MUST 支持配置不同模型，默认使用项目已配置的智谱 GLM 系列

### Key Entities

- **EvalReport**: 评估现状报告，包含各维度的达标状态、差距分析、改进优先级
- **EvalSample**: 评测样本，包含 question、ground_truth、evidence_docs、evidence_keywords、question_type、difficulty、topic
- **LLMJudgeResult**: LLM Judge 评分结果，包含 faithfulness_score、correctness_score、relevancy_score、explanation
- **QualityAuditReport**: 数据集质量审查报告，包含完整性检查、一致性检查、修复建议

## Success Criteria

- **SC-001**: 评估报告覆盖参考文章提出的全部评估维度，无遗漏
- **SC-002**: 评测数据集达到 150+ 条，4 种题型和 3 级难度均有 ≥ 20 条样本
- **SC-003**: LLM Judge 评分与人工评分偏差 ≤ 10%（抽样 20% 校准）
- **SC-004**: 数据集扩充后，现有评估流程（CLI + Web UI）正常运行，无回归
- **SC-005**: 数据集自动校验能检出 ≥ 80% 的常见标注问题（字段缺失、证据不匹配等）

## Assumptions

- 精算审核场景（条款、定价、免责、等待期等）是评估数据集的核心覆盖范围，不涉及公司运营类问题（资本变更、精算师招聘等）
- LLM Judge 使用项目已配置的智谱 GLM 系列模型（glm-4-flash 或更高），不引入新的模型供应商
- 人工抽检由团队成员执行，系统只需提供抽检工具和对比界面
- 当前 Web UI 的评估页面保持不变，改进在其基础上扩展
- 在线监控（Drift Detection、实时质量看板）不在本次范围内，作为后续迭代方向
- 评估指南以文档形式提供，不强制实现为系统内的交互式引导
