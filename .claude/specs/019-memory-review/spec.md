# Feature Specification: 记忆系统深度 Review

**Feature Branch**: `019-memory-review`
**Created**: 2026-04-22
**Status**: Draft
**Input**: 参考「面试官追问：你的 Agent 说有长期记忆，用户上周问的问题这周还记得，这个记忆存在哪？怎么检索？什么时候更新，什么时候删除？」深度 review 当前记忆的设计与实现，评估潜在问题和改进点

## User Scenarios & Testing

### User Story 1 - 存储架构审查 (Priority: P1)

作为系统架构师，我需要深入审查记忆存储的可靠性和一致性，确保记忆不会丢失或损坏。

**Why this priority**: 存储是记忆系统的基石，任何存储问题都会导致数据丢失。

**Independent Test**: 检查 LanceDB + SQLite 双写的一致性机制，验证向量和元数据的同步逻辑。

**Acceptance Scenarios**:

1. **Given** 记忆写入时 LanceDB 成功但 SQLite 失败, **When** 系统重启后查询, **Then** 识别孤儿向量问题并记录
2. **Given** 记忆删除时只软删除 SQLite, **When** LanceDB 空间未释放, **Then** 识别存储膨胀问题
3. **Given** user_id 过滤依赖自定义 LanceDB 实现, **When** 多租户场景下检索, **Then** 验证隔离性是否可靠

---

### User Story 2 - 检索策略审查 (Priority: P1)

作为产品负责人，我需要确认记忆检索的准确性和召回率，确保相关记忆能被正确召回。

**Why this priority**: 检索质量直接影响 Agent 回答的相关性。

**Independent Test**: 审查触发机制（关键词/实体/时间间隔）的覆盖率和误触发率。

**Acceptance Scenarios**:

1. **Given** 触发器依赖 TOPIC_KEYWORDS 和 COMPANY_KEYWORDS, **When** 用户新词不在词表中, **Then** 识别检索漏召回问题
2. **Given** Mem0 语义检索基于 embedding 相似度, **When** 用户用不同表述问同一问题, **Then** 评估语义等价性
3. **Given** score > 0.9 判定为重复记忆, **When** 相似但不同的业务场景, **Then** 识别误去重风险

---

### User Story 3 - 更新机制审查 (Priority: P1)

作为开发者，我需要审查记忆更新的触发条件和内容提取逻辑，确保记忆质量。

**Why this priority**: 记忆更新决定了 Agent 是否能「记住」用户偏好。

**Independent Test**: 检查 update_user_profile() 的 LLM 提取逻辑和置信度阈值。

**Acceptance Scenarios**:

1. **Given** 用户画像通过 LLM 从对话中提取, **When** LLM 提取错误或幻觉, **Then** 识别画像污染风险
2. **Given** 置信度阈值 0.6, **When** 边界情况 confidence=0.59, **Then** 评估阈值合理性
3. **Given** 用户画像和记忆是两个独立系统, **When** 用户偏好变化时, **Then** 识别更新同步问题

---

### User Story 4 - 删除策略审查 (Priority: P2)

作为运维人员，我需要确认过期记忆的清理机制有效，避免存储无限增长。

**Why this priority**: 删除策略影响存储成本和数据新鲜度。

**Independent Test**: 检查 cleanup_expired() 的清理逻辑和调度频率。

**Acceptance Scenarios**:

1. **Given** TTL = 30 天, **When** 记忆刚过 31 天, **Then** 验证是否被清理
2. **Given** 60 天未访问且 access_count=0, **When** 记忆符合条件, **Then** 验证是否被清理
3. **Given** cleanup 每日运行一次, **When** 服务重启, **Then** 识别清理中断风险

---

### Edge Cases

- 并发写入时 user_id 竞态？
- 记忆条数上限？是否会导致检索性能下降？
- 用户画像的 audit_stats 字段未被使用？

## Requirements

### Functional Requirements

- **FR-001**: 研究 MUST 覆盖存储、检索、更新、删除四个维度
- **FR-002**: 研究 MUST 识别潜在问题并标注严重程度（Critical/Major/Minor）
- **FR-003**: 研究 MUST 提供具体改进建议，而非泛泛而谈
- **FR-004**: 研究 MUST 区分「当前实现问题」和「架构设计缺陷」

### Key Entities

- **MemoryService**: 记忆服务门面，封装 Mem0 后端和元数据管理
- **Mem0Memory**: 向量记忆后端，基于 Mem0 框架
- **LanceDBMemoryStore**: 向量存储实现，自定义 user_id 过滤
- **memory_metadata**: SQLite 元数据表，记录 TTL、访问统计
- **user_profiles**: 用户画像表，记录偏好和关注领域

## Success Criteria

- **SC-001**: 产物输出为 research.md，包含问题清单、严重程度、改进建议
- **SC-002**: 每个问题都有代码行号引用或具体场景描述
- **SC-003**: 改进建议可执行，可供后续 /gen-plan 使用

## Assumptions

- 当前实现代码是 review 对象，不会在 review 阶段修改
- PDF 文档中的面试问题作为 review 视角参考
- 最终产物是分析报告，不是代码实现
