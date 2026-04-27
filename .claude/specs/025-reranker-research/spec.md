# Feature Specification: Reranker Research

**Feature Branch**: `025-reranker-research`
**Created**: 2026-04-26
**Status**: Draft
**Input**: 深入梳理和了解 actuary-sleuth 的 rag_engine 的精排代码实现，调研 bge-reranker-large 的可行性

## User Scenarios & Testing

### User Story 1 - 代码架构分析 (Priority: P1)

开发者需要理解现有精排模块的代码结构、接口设计和调用流程，以便为新增精排器做准备。

**Why this priority**: 这是后续可行性评估和实现的基础，必须先理解现状才能设计扩展。

**Independent Test**: 通过阅读 research.md 能够回答：现有精排器的接口是什么？在哪里注册？如何切换？

**Acceptance Scenarios**:

1. **Given** rag_engine 精排模块存在, **When** 阅读 research.md, **Then** 能清晰了解精排器的类结构、方法签名、配置方式
2. **Given** 现有 LLM 精排实现, **When** 阅读 research.md, **Then** 能了解其调用流程和依赖项
3. **Given** 精排器注册/切换机制, **When** 阅读 research.md, **Then** 能了解如何新增一种精排方式

---

### User Story 2 - bge-reranker-large 可行性评估 (Priority: P1)

开发者需要评估 bge-reranker-large 是否能作为独立精排器集成到现有架构中，并了解本地部署的要求。

**Why this priority**: 这是决策的关键，直接影响是否采用该方案。

**Independent Test**: 通过阅读 research.md 能够回答：bge-reranker-large 能否与现有接口兼容？本地部署需要什么条件？

**Acceptance Scenarios**:

1. **Given** bge-reranker-large 模型特性, **When** 阅读 research.md, **Then** 能了解其输入输出格式是否与现有接口兼容
2. **Given** 本地部署需求, **When** 阅读 research.md, **Then** 能了解硬件要求（CPU/GPU、内存）、依赖库、推理延迟
3. **Given** 现有精排器切换机制, **When** 阅读 research.md, **Then** 能了解集成到现有架构的技术可行性

---

### User Story 3 - 工程优化方案评估 (Priority: P1)

开发者需要了解可行的工程优化方案，包括批量推理、INT8 量化和阈值过滤，以实现高性能、低成本的精排服务。

**Why this priority**: 工程优化直接影响生产环境的可行性，是技术选型的关键考量。

**Independent Test**: 通过阅读 research.md 能够回答：推荐采用哪些优化？预期收益和风险是什么？

**Acceptance Scenarios**:

1. **Given** 批量推理优化方案, **When** 阅读 research.md, **Then** 能了解其实现方式、预期延迟改善（串行→批量）
2. **Given** INT8 量化方案, **When** 阅读 research.md, **Then** 能了解模型体积压缩比例、推理加速效果、精度损失评估
3. **Given** 精排阈值过滤策略, **When** 阅读 research.md, **Then** 能了解推荐的阈值设置、对 LLM 生成质量的影响
4. **Given** 三种优化组合, **When** 阅读 research.md, **Then** 能了解叠加后的预期效果（延迟、内存、精度）

---

### User Story 4 - 迁移建议 (Priority: P2)

开发者需要获得具体的技术建议，包括如何实现、需要注意什么、预估工作量。

**Why this priority**: 为后续实现提供明确指导，降低实现风险。

**Independent Test**: 通过阅读 research.md 能够回答：推荐的实现路径是什么？有哪些风险点？

**Acceptance Scenarios**:

1. **Given** 代码分析和可行性评估完成, **When** 阅读 research.md, **Then** 能获得具体的实现建议（文件结构、接口设计）
2. **Given** 潜在风险点, **When** 阅读 research.md, **Then** 能了解需要关注的问题（性能、兼容性、依赖冲突）

---

### Edge Cases

- bge-reranker-large 的输入 token 长度限制是否会影响现有查询场景？

## Requirements

### Functional Requirements

- **FR-001**: research.md MUST 包含现有精排模块的代码架构分析（类结构、接口定义、调用流程）
- **FR-002**: research.md MUST 包含 bge-reranker-large 的技术特性（模型规格、输入输出格式、推理性能）
- **FR-003**: research.md MUST 包含接口兼容性分析（输入输出格式、配置方式、异常处理）
- **FR-004**: research.md MUST 包含本地部署可行性评估（硬件要求、依赖库、推理延迟）
- **FR-005**: research.md MUST 包含工程优化方案分析（批量推理、INT8 量化、阈值过滤）
- **FR-006**: research.md MUST 包含实现建议和风险提示
- **FR-007**: 系统 MUST 保持现有精排接口不变，新增精排器作为可选项

### Key Entities

- **Reranker**: 精排器接口，接收 query 和候选文档列表，返回重排序后的结果
- **LLMReranker**: 现有的基于 LLM 的精排器实现
- **BgeReranker**: 新增的基于 bge-reranker-large 的精排器实现（待评估）
- **RerankerFactory**: 精排器工厂/注册器，负责根据配置创建精排器实例

### Engineering Optimizations

- **Batch Inference**: 批量推理优化，将多个候选文档一次性送入模型，利用 GPU 并行计算
  - 预期效果：50 候选的精排延迟从 ~1500ms（串行）降到 ~300ms（批量）
  - 实现要点：batch_size 参数控制，默认 32

- **INT8 Quantization**: 模型量化优化，将 FP32 权重转换为 INT8
  - 预期效果：模型体积 1.1GB → 280MB（-75%），推理速度提升 ~1.8x
  - 精度损失：MRR 0.923 → 0.921（-0.2%，可接受）
  - 依赖库：optimum[onnxruntime]

- **Score Threshold Filtering**: 精排阈值过滤，丢弃低相关性候选
  - 推荐阈值：min_score=0.3
  - 策略：宁可少给 LLM 内容，也不送入低相关性内容干扰生成

## Success Criteria

- **SC-001**: research.md 能让开发者清晰理解现有精排模块的设计和实现
- **SC-002**: research.md 能明确回答 bge-reranker-large 是否可以作为独立精排器集成
- **SC-003**: research.md 能提供工程优化方案的具体分析和预期效果
- **SC-004**: research.md 能提供足够的技术细节支持后续实现决策

## Assumptions

- 现有 rag_engine 精排模块有明确的接口抽象，支持扩展
- bge-reranker-large 可以通过 sentence-transformers 或 FlagEmbedding 库加载
- 本地部署环境可以满足模型推理的硬件要求
- 用户通过配置文件选择使用哪种精排器
- 精排器失败时采用 fail-fast 策略，不实现回退机制
- 性能/质量对比在后续评测模块实现，本次不涉及
