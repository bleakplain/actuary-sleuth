# Implementation Plan: 记忆系统 P0 改进

**Branch**: `017-memory-trigger-dedup` | **Date**: 2026-04-22 | **Spec**: spec.md

## Summary

实施 P0 改进：关键词触发器 + 记忆去重。两个改进相互独立，可并行实施。

---

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: mem0, lancedb, langgraph（现有，无新增）
**Storage**: SQLite + LanceDB
**Testing**: pytest

---

## Constitution Check

- [x] **Library-First**: 复用 `TOPIC_KEYWORDS`、`COMPANY_KEYWORDS`、`_extract_topic()`
- [x] **测试优先**: 规划了 4 个新增测试用例
- [x] **简单优先**: 最小改动，无过度设计
- [x] **显式优于隐式**: 触发条件显式配置
- [x] **可追溯性**: 每个 Phase 回溯到 User Story
- [x] **独立可测试**: US1 和 US2 可独立测试

---

## Implementation Phases

### Phase 1: 关键词触发器 (US1)

#### 需求回溯

→ 对应 spec.md User Story 1: 关键词触发记忆检索

#### 实现步骤

1. **创建触发器模块**
   - 文件: `scripts/lib/memory/triggers.py`（新增）
   - 内容: `TriggerResult` 数据类、`should_retrieve_memory()` 函数

2. **修改 graph.py 节点**
   - 文件: `scripts/lib/rag_engine/graph.py`
   - 改动: `retrieve_memory` 节点增加条件触发逻辑

3. **编写测试**
   - 文件: `scripts/tests/lib/memory/test_graph.py`
   - 内容: 关键词触发测试、跳过触发测试

---

### Phase 2: 记忆去重 (US2)

#### 需求回溯

→ 对应 spec.md User Story 2: 记忆去重

#### 实现步骤

1. **扩展配置类**
   - 文件: `scripts/lib/memory/config.py`
   - 改动: 新增 `dedup_similarity_threshold` 配置项

2. **修改 service.py 写入逻辑**
   - 文件: `scripts/lib/memory/service.py`
   - 改动: `add()` 方法增加去重检查

3. **编写测试**
   - 文件: `scripts/tests/lib/memory/test_service.py`
   - 内容: 去重测试、正常写入测试

---

## Phase Dependencies

```
Phase 1 (触发器) ─┬─→ 可并行
Phase 2 (去重)  ─┘
```

无依赖，可并行实施。

---

## 变更摘要

| 操作 | 文件 | 改动量 |
|------|------|-------|
| 新增 | `lib/memory/triggers.py` | ~40 行 |
| 修改 | `lib/rag_engine/graph.py` | ~15 行 |
| 修改 | `lib/memory/config.py` | ~5 行 |
| 修改 | `lib/memory/service.py` | ~20 行 |
| 新增测试 | `tests/lib/memory/test_graph.py` | ~30 行 |
| 新增测试 | `tests/lib/memory/test_service.py` | ~25 行 |

**总改动量**: ~135 行
