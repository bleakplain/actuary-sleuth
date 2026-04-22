# Implementation Plan: 记忆系统评估与改进方向

**Branch**: `016-memory-evaluation` | **Date**: 2026-04-21 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

本方案对 actuary-sleuth 项目的记忆系统进行全面评估，识别 5 个核心问题领域，提出 4 个改进方向。基于边界条件（不涉及具体代码实现），输出评估报告和改进建议。

**核心发现**:
- 触发机制单一（仅语义检索），缺失关键词/元认知触发
- 记忆去重缺失，相同事实可能重复写入
- 无分层架构，短/长期记忆统一存储
- 用户画像更新噪声风险，无置信度评估

**改进优先级**: P0（触发器+去重）→ P1（分层+压缩）→ P2（画像优化）

---

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: mem0, lancedb, langgraph（现有，无新增）
**Storage**: SQLite（memory_metadata 表）+ LanceDB（向量存储）
**Testing**: pytest（现有测试覆盖不足，需补充）
**Performance Goals**: 记忆检索延迟 < 100ms，写入延迟 < 200ms
**Constraints**: 不涉及 Mem0/LanceDB 底层优化，仅做评估和建议

---

## Constitution Check

- [x] **Library-First**: 复用现有 `MemoryBase`、`MemoryConfig`、`TOPIC_KEYWORDS`、`_extract_topic()`
- [x] **测试优先**: 规划了 6 个新增测试场景（见第六章）
- [x] **简单优先**: 所有改进方案选择最小改动路径（单表+category字段，而非分表）
- [x] **显式优于隐式**: 无魔法行为，触发条件显式配置
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: 每个 User Story 可独立验证（见验收标准）

---

## Project Structure

### Documentation

```text
.claude/specs/016-memory-evaluation/
├── spec.md          # 需求规格（已完成）
├── research.md      # 技术调研（已完成）
└── plan.md          # 本文件
```

### 评估涉及的核心模块

```text
scripts/lib/memory/
├── base.py          # MemoryBase 抽象类 + Mem0Memory 实现
├── service.py       # MemoryService（触发/去重/画像更新逻辑）
├── vector_store.py  # LanceDB 向量存储
├── config.py        # 配置（TTL、分层参数）
└── prompts.py       # 事实提取、画像提取 prompt

scripts/lib/rag_engine/
└── graph.py         # retrieve_memory/extract_memory 节点

scripts/lib/common/
└── middleware.py    # TOPIC_KEYWORDS、_extract_topic()
```

---

## Implementation Phases

### Phase 1: 评估框架搭建

**目标**: 建立评估指标体系，量化当前系统状态

#### 需求回溯

→ 对应 spec.md Success Criteria: SC-001~SC-004

#### 评估维度

| 维度 | 指标 | 当前状态 | 目标 |
|------|------|---------|------|
| **触发覆盖率** | 关键词触发占比 | 0% | >30% |
| **记忆重复率** | 重复记忆占比 | 未知（需测量） | <5% |
| **检索精度** | Top-3 相关率 | 未知（需测量） | >80% |
| **画像准确率** | 提取结果正确率 | 未知（需测量） | >70% |

#### 评估方法

1. **触发机制评估**
   - 分析 `graph.py:129-162` 的 `retrieve_memory` 节点
   - 统计过去 N 次对话的触发模式
   - 计算语义检索的召回率（需人工标注）

2. **记忆质量评估**
   - 抽样检查 `memory_metadata` 表
   - 识别重复记忆（相似度 > 0.9）
   - 评估提取准确性（对照原始对话）

3. **用户画像评估**
   - 抽样检查 `user_profiles` 表
   - 评估 `focus_areas`、`preference_tags` 准确性
   - 识别噪声画像（无意义标签）

---

### Phase 2: 触发机制评估 (P0)

**目标**: 评估当前触发机制的局限性，提出改进方案

#### 需求回溯

→ 对应 spec.md User Story 1: 记忆触发机制评估

#### 当前实现分析

**位置**: `lib/rag_engine/graph.py:129-162`

```python
def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    # 当前：无条件执行语义检索
    memories = memory_svc.search(state["question"], state["user_id"])
    # ...
```

**问题清单**:

| 问题 | 严重程度 | 代码位置 |
|------|---------|---------|
| 无条件触发，无判断逻辑 | 高 | `graph.py:136` |
| 仅语义相似度，无关键词匹配 | 高 | - |
| 无时间衰减权重 | 中 | - |
| 无实体触发（产品名/公司名） | 高 | - |

#### 改进方案

**方案 A: 语义 + 关键词混合触发** ✅ 推荐

```python
# 新增文件: lib/memory/triggers.py

from lib.common.middleware import TOPIC_KEYWORDS, COMPANY_KEYWORDS, _extract_topic

@dataclass(frozen=True)
class TriggerResult:
    should_retrieve: bool
    trigger_type: str  # "keyword" | "entity" | "semantic" | "skip"
    confidence: float

def should_retrieve_memory(question: str, ctx: dict, last_retrieve_time: float) -> TriggerResult:
    # 1. 关键词触发（复用 TOPIC_KEYWORDS）
    topic = _extract_topic(question)
    if topic:
        return TriggerResult(True, "keyword", 0.9)

    # 2. 实体触发（产品名/公司名）
    entities = _extract_entities(question)
    if entities:
        return TriggerResult(True, "entity", 0.8)

    # 3. 时间间隔触发（至少 30 秒）
    if time.time() - last_retrieve_time > 30:
        return TriggerResult(True, "time", 0.5)

    return TriggerResult(False, "skip", 0.0)
```

**复用点**:
- `lib/common/middleware.py:78-84`: `TOPIC_KEYWORDS`、`COMPANY_KEYWORDS`
- `lib/common/middleware.py:87-92`: `_extract_topic()`

**改动范围**:
- 新增 `lib/memory/triggers.py`
- 修改 `lib/rag_engine/graph.py:129-162`（条件调用）

---

### Phase 3: 记忆去重评估 (P0)

**目标**: 评估记忆重复写入问题，提出去重方案

#### 需求回溯

→ 对应 spec.md User Story 2: 记忆质量评估

#### 当前实现分析

**位置**: `lib/memory/service.py:52-63`

```python
def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
    # 当前：无条件写入，无去重检查
    ids = self._backend.add(messages, user_id=user_id, metadata=metadata)
    # ...
```

**问题清单**:

| 问题 | 严重程度 | 影响 |
|------|---------|------|
| 无去重检查 | 高 | 相同事实重复存储 |
| 无重要性判断 | 中 | 低价值信息也存储 |
| 同步阻塞写入 | 低 | 增加响应延迟 |

#### 改进方案

**方案 A: 写入前语义相似度检查** ✅ 推荐

```python
# 修改: lib/memory/service.py

def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
    # 新增：去重检查
    query = messages[-1]["content"] if messages else ""
    similar = self.search(query, user_id, limit=1)
    if similar:
        # 假设 search 返回带 score 的结果
        score = similar[0].get("score", 1.0)
        if score > 0.9:  # 可配置阈值
            logger.debug(f"跳过重复记忆: {query[:50]}")
            return []

    # 继续写入
    ids = self._backend.add(messages, user_id=user_id, metadata=metadata)
    # ...
```

**配置项**:

```python
# 修改: lib/memory/config.py

@dataclass(frozen=True)
class MemoryConfig:
    # 现有配置
    ttl_fact: int = 30
    # ...

    # 新增配置
    dedup_similarity_threshold: float = 0.9  # 去重相似度阈值
    enable_importance_filter: bool = False   # 是否启用重要性过滤
```

---

### Phase 4: 记忆分层评估 (P1)

**目标**: 评估记忆分层需求，提出架构改进方案

#### 需求回溯

→ 对应 spec.md User Story 3: 记忆生命周期管理评估

#### 当前实现分析

**位置**: `lib/memory/config.py`

```python
@dataclass(frozen=True)
class MemoryConfig:
    ttl_fact: int = 30              # 事实记忆 30 天
    ttl_preference: int = 90        # 偏好记忆 90 天
    ttl_audit_conclusion: int = -1  # 审核结论永不过期
```

**问题**: 仅 TTL 差异化，无存储/查询分层

#### 改进方案

**方案 A: 扩展 category 字段** ✅ 推荐

```python
# 修改: lib/memory/config.py

class MemoryCategory:
    SESSION = "session"        # 工作记忆（会话级，随会话结束删除）
    SHORT_TERM = "short_term"  # 短期记忆（高频访问，7天 TTL）
    LONG_TERM = "long_term"    # 长期记忆（低频访问，永不过期）
    FACT = "fact"              # 原有分类，保留
    PREFERENCE = "preference"  # 原有分类，保留
    AUDIT_CONCLUSION = "audit_conclusion"  # 原有分类，保留

@dataclass(frozen=True)
class MemoryConfig:
    # 现有配置
    ttl_fact: int = 30
    ttl_preference: int = 90
    ttl_audit_conclusion: int = -1

    # 新增分层配置
    ttl_session: int = -1      # 随会话结束清理
    ttl_short_term: int = 7    # 短期记忆 7 天
    ttl_long_term: int = -1    # 长期记忆永不过期
```

**查询分层**:

```python
# 修改: lib/memory/service.py

def search(self, query: str, user_id: str, limit: Optional[int] = None) -> List[Dict]:
    # 优先级: session > short_term > long_term
    # 1. 会话级记忆（最新）
    session_memories = self._search_by_category(query, user_id, "session", limit=1)
    # 2. 短期记忆（高频访问）
    short_term = self._search_by_category(query, user_id, "short_term", limit=2)
    # 3. 长期记忆
    long_term = self._search_by_category(query, user_id, "long_term", limit=limit - 3)

    return session_memories + short_term + long_term
```

---

### Phase 5: 用户画像评估 (P2)

**目标**: 评估用户画像提取准确性，提出噪声过滤方案

#### 需求回溯

→ 对应 spec.md User Story 4: 用户画像自动提取评估

#### 当前实现分析

**位置**: `lib/memory/service.py:160-201`

```python
def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
    # 当前：每次对话都触发 LLM 调用
    llm = LLMClientFactory.create_qa_llm()
    prompt = PROFILE_EXTRACTION_PROMPT.format(question=question, answer=answer)
    raw = str(llm.chat([{"role": "user", "content": prompt}]))
    # 无置信度评估，无冲突检测
```

**问题清单**:

| 问题 | 严重程度 | 影响 |
|------|---------|------|
| 每次对话都更新 | 高 | LLM 成本高，噪声风险 |
| 无置信度评估 | 高 | 低质量结果也写入 |
| 无冲突检测 | 中 | 新旧画像可能矛盾 |

#### 改进方案

**方案 A: 置信度评估 + 冲突检测** ✅ 推荐

```python
# 修改: lib/memory/prompts.py

PROFILE_EXTRACTION_PROMPT_V2 = """\
根据用户提问和系统回答，提取用户画像信息。

重要：输出 JSON 必须包含 confidence 字段（0.0-1.0），表示提取结果的可信程度。
不确定时 confidence 设为 0.0-0.3，较确定时设为 0.7-1.0。

Output JSON 格式:
{{"focus_areas": [...], "preference_tags": [...], "summary": "...", "confidence": 0.8}}

用户提问: {question}
系统回答: {answer}
"""
```

```python
# 修改: lib/memory/service.py

def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
    extracted = self._extract_with_confidence(question, answer)

    # 新增：置信度过滤
    if extracted.get("confidence", 0) < 0.7:
        logger.debug(f"跳过低置信度画像更新: {extracted.get('confidence')}")
        return

    # 新增：冲突检测
    existing = self.get_user_profile(user_id)
    if existing:
        conflicts = self._detect_conflicts(existing, extracted)
        if conflicts:
            logger.info(f"检测到画像冲突，保留现有值: {conflicts}")
            return

    # 继续写入
    self._save_profile(user_id, extracted)
```

---

### Phase 6: 上下文压缩评估 (P1)

**目标**: 评估上下文膨胀风险，提出智能压缩方案

#### 需求回溯

→ 对应 spec.md User Story 5: 上下文膨胀风险评估

#### 当前实现分析

**位置**: `lib/rag_engine/graph.py:153-155`

```python
context = "\n\n".join(parts)
if len(context) > max_chars:
    context = context[:max_chars] + "..."  # 硬截断
```

**问题**: 硬截断可能丢失重要信息

#### 改进方案

**方案 A: 按相关性智能选择** ✅ 推荐

```python
# 修改: lib/rag_engine/graph.py

def compress_memory_context(memories: List[Dict], max_chars: int = 2000) -> str:
    # 1. 按相关性排序（score 来自检索）
    sorted_memories = sorted(memories, key=lambda m: m.get("score", 0), reverse=True)

    # 2. 智能选择（优先高相关）
    selected = []
    total_chars = 0
    for m in sorted_memories:
        text = f"- {m['memory']} (记录于 {m['created_at'][:10]})"
        if total_chars + len(text) <= max_chars:
            selected.append(text)
            total_chars += len(text)
        else:
            break

    return "\n".join(selected)
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

**说明**: 所有改进方案均选择最小改动路径，无过度设计。

---

## Testing Plan

### 新增测试用例

| 测试文件 | 测试用例 | 覆盖需求 |
|---------|---------|---------|
| `test_service.py` | `test_add_skips_duplicate_memory` | FR-002 去重 |
| `test_service.py` | `test_add_respects_importance_score` | FR-002 重要性 |
| `test_service.py` | `test_update_user_profile_skips_low_confidence` | FR-04 置信度 |
| `test_graph.py` | `test_retrieve_memory_triggered_by_keyword` | FR-01 关键词触发 |
| `test_graph.py` | `test_retrieve_memory_skips_when_no_trigger` | FR-01 条件触发 |
| `test_graph.py` | `test_memory_context_compression` | FR-05 智能压缩 |

### 测试代码示例

```python
# scripts/tests/lib/memory/test_service.py

def test_add_skips_duplicate_memory():
    """测试去重：相似度 > 0.9 时跳过写入"""
    mock_backend = MagicMock()
    mock_backend.search.return_value = [{"id": "m1", "memory": "等待期180天", "score": 0.95}]

    svc = MemoryService(backend=mock_backend)
    result = svc.add([{"role": "user", "content": "等待期是180天"}], "user1")

    # 相似度高，应跳过写入
    assert result == []
    mock_backend.add.assert_not_called()

def test_update_user_profile_skips_low_confidence():
    """测试画像更新跳过低置信度结果"""
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch.object(svc, '_extract_with_confidence') as mock_extract:
        mock_extract.return_value = {"focus_areas": [], "confidence": 0.3}

        svc.update_user_profile("问题", "回答", "user1")

        # 置信度低，不应写入
        # 验证没有调用 save
```

---

## Appendix

### 执行顺序建议

```
Phase 1（评估框架）
    ↓
Phase 2（触发机制 P0）→ Phase 3（去重 P0）
    ↓
Phase 4（分层 P1）→ Phase 6（压缩 P1）
    ↓
Phase 5（画像 P2）
```

**依赖关系**:
- Phase 2/3 可并行（无依赖）
- Phase 4/6 可并行（无依赖）
- Phase 5 依赖 Phase 3（去重逻辑）

### 改动范围汇总

| 文件 | 操作 | 改动量 |
|------|------|-------|
| `lib/memory/triggers.py` | 新增 | ~50 行 |
| `lib/memory/service.py` | 修改 | ~30 行 |
| `lib/memory/config.py` | 修改 | ~10 行 |
| `lib/rag_engine/graph.py` | 修改 | ~20 行 |
| `lib/memory/prompts.py` | 修改 | ~5 行 |
| `tests/lib/memory/test_service.py` | 新增 | ~40 行 |
| `tests/lib/memory/test_graph.py` | 新增 | ~30 行 |

**总改动量**: ~185 行

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 触发机制 | 关键词触发覆盖率 > 30% | `test_retrieve_memory_triggered_by_keyword` |
| US-2 记忆质量 | 重复记忆占比 < 5% | `test_add_skips_duplicate_memory` |
| US-3 生命周期 | 分层存储正常工作 | `test_search_by_category` |
| US-4 用户画像 | 低置信度结果不写入 | `test_update_user_profile_skips_low_confidence` |
| US-5 上下文压缩 | 输出 < 2000 字符 | `test_memory_context_compression` |

### 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 关键词触发噪声 | 中 | 中 | 增加置信度阈值 |
| 去重阈值过高 | 低 | 高 | 设置为可配置项 |
| 分层迁移数据 | 低 | 中 | 编写迁移脚本 |
| 测试覆盖不足 | 中 | 低 | 补充 6 个测试用例 |
