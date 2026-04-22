# Feature Specification: 记忆系统 P0 改进（触发器+去重）

**Feature Branch**: `017-memory-trigger-dedup`
**Created**: 2026-04-22
**Status**: Draft
**Input**: 基于 016-memory-evaluation 评估结果的 P0 改进实施

## Executive Summary

实施记忆系统 P0 优先级改进：关键词触发器和记忆去重机制。这两个改进相互独立，可并行实施。

**改进来源**: `.claude/specs/016-memory-evaluation/plan.md` Phase 2 + Phase 3

---

## User Scenarios & Testing

### User Story 1 - 关键词触发记忆检索 (Priority: P0)

**As a** 用户
**I want to** 当我提到特定保险术语时，系统能自动检索相关历史记忆
**So that** 我能获得更精准的个性化回答

**Why this priority**: 触发机制是记忆系统的核心入口，直接影响检索效率

**Independent Test**: 在 `test_graph.py` 中添加关键词触发测试

**Acceptance Scenarios**:

1. **Given** 用户提问包含"等待期", **When** 执行检索时, **Then** 应触发记忆检索
2. **Given** 用户提问包含产品名"平安福", **When** 执行检索时, **Then** 应触发记忆检索
3. **Given** 用户提问是普通问候"你好", **When** 执行检索时, **Then** 可跳过记忆检索

---

### User Story 2 - 记忆去重 (Priority: P0)

**As a** 系统
**I want to** 避免重复存储相同的记忆
**So that** 存储空间和检索效率得到优化

**Why this priority**: 去重直接影响存储成本和检索质量

**Independent Test**: 在 `test_service.py` 中添加去重测试

**Acceptance Scenarios**:

1. **Given** 用户重复询问同一问题, **When** 记忆提取时, **Then** 不应创建重复的记忆条目
2. **Given** 用户提问与已有记忆相似度 > 0.9, **When** 记忆写入时, **Then** 应跳过写入

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持关键词触发记忆检索
- **FR-002**: 系统 MUST 复用 `TOPIC_KEYWORDS` 和 `COMPANY_KEYWORDS` 作为触发词
- **FR-003**: 系统 MUST 在记忆写入前检查相似度，跳过重复记忆
- **FR-004**: 系统 MUST 提供去重相似度阈值配置（默认 0.9）

### Key Entities

- **TriggerResult**: 触发判断结果，包含 `should_retrieve`、`trigger_type`、`confidence`
- **MemoryConfig**: 扩展配置，新增 `dedup_similarity_threshold`

---

## Success Criteria

- **SC-001**: 关键词触发测试通过
- **SC-002**: 记忆去重测试通过
- **SC-003**: 类型检查通过 (`mypy scripts/lib/`)
- **SC-004**: 现有测试不被破坏
