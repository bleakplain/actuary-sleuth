# Feature Specification: 记忆系统评估与改进方向

**Feature Branch**: `016-memory-evaluation`
**Created**: 2026-04-21
**Status**: Draft
**Input**: 系统梳理和了解当前项目的记忆设计和实现，结合参考文章，评估潜在问题和可改进的地方

## Executive Summary

本规格说明对 actuary-sleuth 项目的记忆系统进行全面评估，结合《蚂蚁面试官：你的 Agent 怎么触发记忆提取？》参考文章，识别当前实现的潜在问题并提出改进方向。

**目标读者**: 开发团队 + 产品/业务方

**评估范围**:
- 记忆触发机制
- 记忆质量（提取与检索）
- 记忆生命周期管理
- 用户画像自动提取

**边界条件**:
- 不涉及 Mem0/LanceDB 底层优化
- 不涉及具体代码实现（仅评估，不修改）

---

## Current Architecture Overview

### Module Structure

```
scripts/lib/memory/
├── base.py          # MemoryBase 抽象类 + Mem0Memory 实现
├── service.py       # MemoryService（降级、活跃度管理、用户画像）
├── vector_store.py  # LanceDB 向量存储
├── config.py        # 配置（TTL、字符限制）
└── prompts.py       # 事实提取、画像提取 prompt
```

### LangGraph Workflow

```
load_session_context
       ↓
clarify_user_query
       ↓
[parallel]
  ├── retrieve_memory    → 检索相关记忆 + 用户画像
  └── rag_search
       ↓
    generate
       ↓
  extract_memory         → 写入记忆
       ↓
  update_user_profile    → 更新画像
       ↓
  save_session_context
```

### Current Trigger Mechanisms

| 时机 | 触发点 | 实现方式 |
|------|--------|----------|
| **记忆检索** | 每次提问 | `retrieve_memory` 节点，语义相似度匹配 |
| **记忆写入** | 每次回答后 | `extract_memory` 节点，Mem0 自动提取事实 |
| **画像更新** | 每次回答后 | `update_user_profile` 节点，LLM 提取结构化信息 |

---

## Evaluation Findings

### User Story 1 - 记忆触发机制评估 (Priority: P1)

**As a** 开发者
**I want to** 理解当前记忆触发机制的局限性
**So that** 我能设计更智能的触发策略

**Why this priority**: 触发机制是记忆系统的核心入口，直接影响记忆质量和系统效率

**Current Implementation Analysis**:

1. **检索触发**
   - ✅ 实现：每次提问时调用 `memory_svc.search(query, user_id)`
   - ✅ 基于：语义相似度（embedding 距离）
   - ❌ 缺失：关键词触发、实体触发、时间衰减权重

2. **写入触发**
   - ✅ 实现：每次对话后调用 `memory_svc.add()`
   - ✅ Mem0 内部：使用 `AUDIT_FACT_EXTRACTION_PROMPT` 过滤无关内容
   - ❌ 缺失：重要性判断、去重机制、写入时机优化

3. **参考文章对比**

| 触发方式 | 参考文章建议 | 当前实现 | Gap |
|----------|-------------|----------|-----|
| 语义相似度 | ✅ 推荐 | ✅ 已实现 | 无 |
| 关键词触发 | ✅ 推荐 | ❌ 未实现 | **高** |
| 时间衰减 | ✅ 推荐 | ⚠️ 部分实现 | 中 |
| 元认知触发 | ✅ 推荐 | ❌ 未实现 | **高** |
| 上下文窗口管理 | ✅ 推荐 | ⚠️ 部分实现 | 中 |

**Independent Test**: 检查 `graph.py` 中 `retrieve_memory` 和 `extract_memory` 节点的实现

**Acceptance Scenarios**:

1. **Given** 用户连续问相似问题, **When** 第二次提问时, **Then** 系统应能识别并利用之前的记忆
2. **Given** 用户提到特定产品名称（如"平安福"）, **When** 提问时, **Then** 系统应能触发相关历史记忆

---

### User Story 2 - 记忆质量评估 (Priority: P1)

**As a** 产品/业务方
**I want to** 了解记忆提取和检索的质量
**So that** 我能评估系统对用户体验的影响

**Why this priority**: 记忆质量直接决定了个性化效果和用户满意度

**Current Implementation Analysis**:

1. **提取质量**
   - ✅ 有领域特定 prompt：`AUDIT_FACT_EXTRACTION_PROMPT` 聚焦保险审核
   - ⚠️ 提取粒度：依赖 Mem0 内部逻辑，缺乏可控性
   - ❌ 去重问题：相同事实可能被重复提取

2. **检索质量**
   - ✅ 有 `limit=3` 默认限制
   - ✅ 有 `memory_context_max_chars=2000` 截断
   - ⚠️ 相关性排序：仅依赖向量距离，缺乏重排序
   - ❌ 噪声问题：可能检索到不相关的记忆

3. **质量问题示例**

```python
# 当前实现：每次都写入，无重要性判断
def extract_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc.add(conversation, user_id, metadata)
    # 问题：无去重、无重要性评分、无条件写入
```

**Independent Test**: 分析 `test_service.py` 中的测试用例覆盖率

**Acceptance Scenarios**:

1. **Given** 用户重复询问同一问题, **When** 记忆提取时, **Then** 不应创建重复的记忆条目
2. **Given** 记忆库中有大量条目, **When** 检索时, **Then** 应返回最相关的 top-K 结果

---

### User Story 3 - 记忆生命周期管理评估 (Priority: P2)

**As a** 开发者
**I want to** 评估记忆的存储和清理策略
**So that** 我能优化存储成本和检索效率

**Why this priority**: 生命周期管理影响长期运行的存储成本和查询性能

**Current Implementation Analysis**:

1. **TTL 配置**
   ```python
   @dataclass(frozen=True)
   class MemoryConfig:
       ttl_fact: int = 30              # 事实记忆 30 天
       ttl_preference: int = 90        # 偏好记忆 90 天
       ttl_audit_conclusion: int = -1  # 审核结论永不过期
       inactive_threshold_days: int = 60
   ```

2. **清理机制**
   - ✅ 有 `cleanup_expired()` 定期清理
   - ✅ 有 `access_count` 和 `last_accessed_at` 统计
   - ⚠️ 清理触发：需要外部调度，无自动触发

3. **参考文章对比**

| 生命周期机制 | 参考文章建议 | 当前实现 | Gap |
|-------------|-------------|----------|-----|
| 短期记忆 | ✅ 区分存储 | ❌ 统一存储 | **高** |
| 长期记忆 | ✅ 持久化 | ✅ LanceDB | 无 |
| 工作记忆 | ✅ 会话级 | ⚠️ session_context | 中 |
| 时间衰减权重 | ✅ 推荐实现 | ❌ 未实现 | **高** |

**Independent Test**: 检查 `memory_metadata` 表结构和 `cleanup_expired` 实现

**Acceptance Scenarios**:

1. **Given** 记忆超过 TTL, **When** 执行清理时, **Then** 应被正确删除
2. **Given** 记忆被频繁访问, **When** 评估是否清理时, **Then** 应保留高频访问的记忆

---

### User Story 4 - 用户画像自动提取评估 (Priority: P2)

**As a** 产品/业务方
**I want to** 了解用户画像的自动提取效果
**So that** 我能评估个性化推荐的准确性

**Why this priority**: 用户画像是实现个性化服务的关键数据

**Current Implementation Analysis**:

1. **提取机制**
   - ✅ 使用 LLM 提取结构化信息
   - ✅ 有领域特定 prompt：`PROFILE_EXTRACTION_PROMPT`
   - ⚠️ 每次对话都更新，可能引入噪声

2. **画像结构**
   ```python
   class UserProfile:
       focus_areas: list[str]      # 关注的保险类型
       preference_tags: list[str]  # 用户偏好标签
       audit_stats: dict           # 审核统计
       summary: str                # 画像摘要
   ```

3. **潜在问题**
   - ❌ 缺乏置信度评分：提取结果无质量评估
   - ❌ 缺乏冲突检测：新旧画像可能矛盾
   - ⚠️ 更新过于频繁：每次对话都触发

**Independent Test**: 检查 `update_user_profile` 方法和 `PROFILE_EXTRACTION_PROMPT`

**Acceptance Scenarios**:

1. **Given** 用户多次表达相同偏好, **When** 画像更新时, **Then** 应合并而非重复添加
2. **Given** 用户偏好发生变化, **When** 画像更新时, **Then** 应能识别并更新过期标签

---

### User Story 5 - 上下文膨胀风险评估 (Priority: P1)

**As a** 开发者
**I want to** 评估记忆注入对上下文窗口的影响
**So that** 我能避免 token 超限和成本增加

**Why this priority**: 上下文膨胀会直接导致成本增加和响应变慢

**Current Implementation Analysis**:

1. **当前防护**
   - ✅ `memory_context_max_chars = 2000` 硬截断
   - ✅ `memory_search_limit = 3` 限制检索数量

2. **潜在风险**
   - ⚠️ 截断方式粗暴：直接截断可能丢失重要信息
   - ❌ 无智能压缩：长记忆没有摘要机制
   - ❌ 无相关性评分：可能注入低相关记忆

3. **参考文章建议**
   > "需要平衡检索精度与召回率，避免过度提取导致上下文膨胀"

**Independent Test**: 模拟大量记忆场景，测试 `retrieve_memory` 输出长度

**Acceptance Scenarios**:

1. **Given** 用户有 100+ 条记忆, **When** 检索时, **Then** 输出应限制在 2000 字符内
2. **Given** 检索结果包含低相关记忆, **When** 注入 prompt 时, **Then** 应过滤或降权

---

## Edge Cases

- **多用户场景**：当前 `user_id` 默认为 "default"，多用户隔离是否充分？
- **会话恢复**：`session_context` 与长期记忆的边界是否清晰？
- **降级场景**：Mem0 初始化失败时的降级逻辑是否完善？
- **并发写入**：用户画像更新使用 `INSERT OR REPLACE`，是否存在竞态？

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持多种记忆触发机制（语义、关键词、时间衰减）
- **FR-002**: 系统 MUST 实现记忆去重和重要性评分
- **FR-003**: 系统 MUST 区分短期记忆和长期记忆的存储策略
- **FR-004**: 系统 MUST 对用户画像提取结果进行置信度评估
- **FR-005**: 系统 MUST 实现智能的上下文压缩机制
- **FR-006**: [NEEDS CLARIFICATION] 是否需要支持用户手动管理记忆？

### Key Entities

- **Memory**: 用户对话中提取的事实性信息，包含 ID、内容、分类、TTL、访问统计
- **UserProfile**: 用户画像，包含关注领域、偏好标签、审核统计、摘要
- **MemoryMetadata**: 记忆元数据，用于 TTL 管理和活跃度统计
- **GraphContext**: LangGraph 依赖注入上下文，包含 RAG 引擎、LLM 客户端、记忆服务

---

## Gap Analysis Summary

| 问题领域 | 严重程度 | 改进优先级 |
|----------|---------|-----------|
| 触发机制单一 | **高** | P0 |
| 记忆去重缺失 | **高** | P0 |
| 无记忆分层 | **高** | P1 |
| 上下文膨胀风险 | **中** | P1 |
| 画像提取噪声 | **中** | P2 |
| 时间衰减权重缺失 | **中** | P2 |
| 置信度评估缺失 | **低** | P3 |

---

## Improvement Directions

### Direction 1: 智能触发机制

**目标**: 从"无条件触发"升级为"条件触发"

**改进点**:
- 增加关键词/实体触发器
- 实现"元认知"判断：LLM 自我评估是否需要检索记忆
- 基于会话上下文决定是否需要检索

### Direction 2: 记忆分层架构

**目标**: 区分短期/长期/工作记忆

**改进点**:
- 会话级工作记忆（session_context 已部分实现）
- 短期记忆（高频访问、低 TTL）
- 长期记忆（低频访问、高 TTL 或永不过期）

### Direction 3: 记忆质量控制

**目标**: 提升记忆提取和检索的准确性

**改进点**:
- 写入前去重检查
- 提取结果重要性评分
- 检索结果重排序（结合语义+时间衰减）

### Direction 4: 用户画像优化

**目标**: 提升画像准确性和稳定性

**改进点**:
- 提取结果置信度评分
- 新旧画像冲突检测
- 降低更新频率（仅在高置信度时更新）

---

## Success Criteria

- **SC-001**: 识别出至少 5 个主要改进方向
- **SC-002**: 每个改进方向有明确的 Gap 分析
- **SC-003**: 改进方向与参考文章的建议对标
- **SC-004**: 输出可被开发和产品双方理解

---

## Assumptions

- 参考 PDF 文章的观点具有普适性，适用于保险审核场景
- 当前 Mem0 作为记忆后端不会短期内被替换
- 记忆系统的改进优先级低于核心审核功能
