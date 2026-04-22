# 记忆系统评估 - 技术调研报告

生成时间: 2026-04-21
源规格: .claude/specs/016-memory-evaluation/spec.md

## 执行摘要

本报告深入分析 actuary-sleuth 项目的记忆系统实现，基于 spec.md 中的 5 个 User Stories 进行定向研究。发现核心问题包括：触发机制单一（仅语义检索）、记忆去重缺失、无分层架构设计、用户画像更新噪声风险。改进方向建议优先实现关键词触发器和去重机制（P0），其次实现记忆分层架构（P1）。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 多种触发机制 | `lib/rag_engine/graph.py:129-162` | 仅语义相似度检索，无关键词/元认知触发 |
| FR-002 去重和重要性评分 | `lib/memory/service.py:52-63` | 无去重，无条件写入 |
| FR-003 短期/长期记忆分层 | `lib/memory/config.py` | 统一存储，仅 TTL 差异化 |
| FR-004 画像置信度评估 | `lib/memory/service.py:160-201` | 无置信度评分，无冲突检测 |
| FR-005 智能上下文压缩 | `lib/rag_engine/graph.py:153-155` | 硬截断，无智能压缩 |

### 1.2 可复用组件

| 组件 | 位置 | 复用价值 |
|------|------|---------|
| `MemoryBase` 抽象类 | `lib/memory/base.py:19-45` | 可扩展新触发器实现 |
| `MemoryConfig` 配置类 | `lib/memory/config.py` | 可扩展分层配置 |
| `memory_metadata` 表 | `api/database.py:241-254` | 已有 `access_count`、`expires_at`，可用于重要性计算 |
| `GraphContext` 依赖注入 | `lib/rag_engine/graph.py:78-84` | 已支持 `memory_service` 注入 |
| `_extract_topic()` | `lib/common/middleware.py:87-92` | 可复用于关键词触发 |

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/memory/triggers.py` | **新增** | 关键词触发器、元认知判断逻辑 |
| `lib/memory/service.py` | **修改** | 添加去重检查、重要性评分 |
| `lib/memory/config.py` | **修改** | 添加分层配置（短期/长期/工作记忆） |
| `lib/rag_engine/graph.py` | **修改** | `retrieve_memory` 节点增加条件触发 |
| `lib/memory/prompts.py` | **修改** | 添加重要性评分 prompt |

---

## 二、技术选型研究

### 2.1 触发机制方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| **A: 语义相似度 + 关键词混合** | 实现简单，复用现有代码 | 需维护关键词词典 | 当前项目 | ✅ 推荐 |
| **B: 纯元认知触发** | 更智能，适应性强 | 增加 LLM 调用成本，延迟增加 | 高价值场景 | ❌ 作为补充 |
| **C: 基于规则引擎** | 可配置，灵活 | 维护成本高，需产品配合 | 企业级系统 | ❌ 过度设计 |

**选择理由**: 方案 A 平衡实现成本与效果，可复用 `middleware.py` 中的 `TOPIC_KEYWORDS` 和 `_extract_topic()`。

### 2.2 记忆去重方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| **A: 写入前语义相似度检查** | 准确率高 | 增加一次向量查询 | 当前项目 | ✅ 推荐 |
| **B: LLM 判断重复** | 语义理解更准确 | 成本高、延迟大 | 高精度需求 | ❌ |
| **C: 基于关键词去重** | 成本低 | 误判率高 | 低成本场景 | ❌ |

**选择理由**: 方案 A 可复用现有 `search()` 接口，在写入前先检索相似记忆，相似度阈值 > 0.9 则跳过。

### 2.3 记忆分层方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| **A: 单表 + category 字段** | 改动最小 | 查询需过滤 | 当前项目 | ✅ 推荐 |
| **B: 分表存储** | 查询性能最优 | 迁移复杂 | 大规模系统 | ❌ 过度设计 |
| **C: 分数据库** | 物理隔离 | 运维成本高 | 多租户系统 | ❌ 不适用 |

**选择理由**: 方案 A 利用现有 `category` 字段，扩展为 `session`（工作记忆）、`short_term`（短期）、`long_term`（长期）三类。

### 2.4 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| `mem0` | - | 记忆提取核心 | 已集成 |
| `lancedb` | - | 向量存储 | 已集成 |
| `langgraph` | - | 工作流编排 | 已集成 |

**无需新增依赖**，所有改进基于现有组件扩展。

---

## 三、数据流分析

### 3.1 现有数据流（记忆检索）

```
用户提问
    ↓
AskState(question, user_id, session_id)
    ↓
retrieve_memory 节点
    ↓
memory_svc.search(query, user_id) → Mem0Memory.search() → LanceDB 向量查询
    ↓
memory_context (string, max 2000 chars)
    ↓
generate 节点 → 注入 system prompt
```

### 3.2 现有数据流（记忆写入）

```
generate 节点输出 (answer)
    ↓
extract_memory 节点
    ↓
memory_svc.add([user_msg, assistant_msg], user_id, metadata)
    ↓
Mem0Memory.add() → LLM 提取事实 → AUDIT_FACT_EXTRACTION_PROMPT
    ↓
LanceDB 写入向量
    ↓
memory_metadata 表写入元数据
```

### 3.3 改进后的数据流（触发机制）

```
用户提问
    ↓
[新增] should_retrieve_memory() 判断
    ├── 关键词匹配？ → 检索
    ├── 实体匹配？ → 检索
    ├── 上次检索时间 > N 秒？ → 检索
    └── 否则 → 跳过检索
    ↓
retrieve_memory 节点（条件执行）
```

### 3.4 改进后的数据流（去重检查）

```
generate 节点输出
    ↓
extract_memory 节点
    ↓
[新增] 去重检查
    ├── 检索相似记忆（阈值 0.9）
    ├── 存在相似记忆？ → 跳过写入
    └── 否则 → 继续写入
    ↓
[新增] 重要性评分
    ├── LLM 评分 (1-5)
    └── 低重要性？ → 跳过写入
    ↓
memory_svc.add()
```

### 3.5 关键数据结构

```python
# 现有: memory_metadata 表
# 改进: 新增 category 细分
class MemoryCategory:
    SESSION = "session"        # 工作记忆（会话级）
    SHORT_TERM = "short_term"  # 短期记忆（高频访问，7天 TTL）
    LONG_TERM = "long_term"    # 长期记忆（低频访问，永不过期）
    FACT = "fact"              # 原有分类，保留

# 新增: 触发判断结果
@dataclass(frozen=True)
class TriggerResult:
    should_retrieve: bool
    trigger_type: str  # "keyword" | "entity" | "semantic" | "time" | "skip"
    matched_keywords: List[str]
    confidence: float

# 新增: 重要性评分结果
@dataclass(frozen=True)
class ImportanceScore:
    score: int  # 1-5
    reason: str
    should_store: bool
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

| 假设 | 验证方式 | 风险 |
|------|---------|------|
| Mem0 的 `custom_fact_extraction_prompt` 对中文保险术语提取有效 | 单元测试 + 人工评审 | 中 |
| LanceDB 向量相似度阈值 0.9 可有效去重 | 批量测试 | 中 |
| 关键词触发误检率可控（< 10%） | 线上 A/B 测试 | 低 |
| 用户画像更新频率降低后效果不变 | 对比实验 | 低 |

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 关键词触发引入过多噪声 | 中 | 中 | 增加置信度阈值，结合语义相似度 |
| 去重阈值过高导致遗漏 | 低 | 高 | 设置为可配置项，默认 0.9 |
| 分层后查询复杂度增加 | 低 | 低 | 利用现有索引，category 过滤 |
| 记忆写入延迟增加 | 中 | 中 | 异步写入，不阻塞响应 |

---

## 五、详细代码分析

### 5.1 触发机制现状分析

**位置**: `lib/rag_engine/graph.py:129-162`

```python
def retrieve_memory(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    memory_svc = runtime.context.memory_service
    # 问题 1: 无条件执行检索，无触发判断
    memories = memory_svc.search(state["question"], state["user_id"])
    # ...
```

**问题**:
1. 每次提问都触发检索，无论是否有必要
2. 仅依赖语义相似度，无关键词/实体触发
3. 无时间衰减权重，所有记忆权重相同

**改进建议**:
```python
def should_retrieve_memory(question: str, ctx: dict, last_retrieve_time: float) -> TriggerResult:
    # 1. 关键词触发
    keywords = _extract_keywords(question)
    if keywords:
        return TriggerResult(True, "keyword", keywords, 0.9)

    # 2. 实体触发（产品名、公司名）
    entities = _extract_entities(question)
    if entities:
        return TriggerResult(True, "entity", entities, 0.8)

    # 3. 时间间隔触发（至少 30 秒）
    if time.time() - last_retrieve_time > 30:
        return TriggerResult(True, "time", [], 0.5)

    return TriggerResult(False, "skip", [], 0.0)
```

### 5.2 记忆写入现状分析

**位置**: `lib/memory/service.py:52-63`

```python
def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
    if not self._available:
        return []
    try:
        # 问题 1: 无去重检查
        # 问题 2: 无重要性判断
        ids = self._backend.add(messages, user_id=user_id, metadata=metadata or {}, run_id=session_id)
        for mid in ids:
            self._insert_metadata(mid, user_id, metadata)
        return ids
    except Exception:
        return []
```

**问题**:
1. 无去重检查，相同事实可能重复写入
2. 无重要性判断，低价值信息也存储
3. 写入同步阻塞，增加响应延迟

**改进建议**:
```python
def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
    # 1. 去重检查
    query = messages[-1]["content"] if messages else ""
    similar = self.search(query, user_id, limit=1)
    if similar and similar[0].get("score", 1.0) > 0.9:
        logger.debug(f"跳过重复记忆: {query[:50]}")
        return []

    # 2. 重要性评分（可选，高价值场景启用）
    if self._config.importance_filter:
        importance = self._score_importance(messages)
        if importance.score < 3:
            return []

    # 3. 异步写入（不阻塞响应）
    return self._backend.add(messages, user_id=user_id, metadata=metadata)
```

### 5.3 用户画像更新现状分析

**位置**: `lib/memory/service.py:160-201`

```python
def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
    try:
        # 问题 1: 每次对话都触发 LLM 调用
        llm = LLMClientFactory.create_qa_llm()
        prompt = PROFILE_EXTRACTION_PROMPT.format(question=question, answer=answer)
        raw = str(llm.chat([{"role": "user", "content": prompt}]))
        # ...

        # 问题 2: 无置信度评估
        extracted = json.loads(text)
        focus_areas = extracted.get("focus_areas", [])
        # 问题 3: 无冲突检测
        merged_areas = list({*json.loads(existing[0]), *focus_areas})
        # ...
```

**问题**:
1. 每次对话都触发 LLM 调用，成本高
2. 提取结果无置信度评估，可能引入噪声
3. 无冲突检测，新旧画像可能矛盾

**改进建议**:
```python
def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
    # 1. 频率控制：仅高置信度时更新
    extracted = self._extract_with_confidence(question, answer)
    if extracted.confidence < 0.7:
        return

    # 2. 冲突检测
    existing = self.get_user_profile(user_id)
    if existing:
        conflicts = self._detect_conflicts(existing, extracted)
        if conflicts:
            logger.info(f"检测到画像冲突，保留现有值: {conflicts}")
            return

    # 3. 写入
    self._save_profile(user_id, extracted)
```

### 5.4 上下文膨胀防护现状分析

**位置**: `lib/rag_engine/graph.py:153-155`

```python
context = "\n\n".join(parts)
if len(context) > max_chars:
    context = context[:max_chars] + "..."  # 硬截断
```

**问题**:
1. 硬截断可能丢失重要信息（截断可能发生在句子中间）
2. 无智能压缩，长记忆没有摘要机制
3. 无相关性评分，可能注入低相关记忆

**改进建议**:
```python
def compress_memory_context(memories: List[Dict], max_chars: int = 2000) -> str:
    # 1. 按相关性排序
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

    # 3. 如果仍有空间，添加摘要
    if len(selected) < len(sorted_memories) and total_chars < max_chars - 100:
        summary = _summarize_remaining(sorted_memories[len(selected):])
        selected.append(f"\n[其他 {len(sorted_memories) - len(selected)} 条记忆摘要]\n{summary}")

    return "\n".join(selected)
```

---

## 六、测试覆盖分析

### 6.1 测试文件清单

| 文件 | 覆盖模块 | 用例数 |
|------|---------|-------|
| `test_service.py` | `MemoryService` | 19 |
| `test_vector_store.py` | `LanceDBMemoryStore` | 10 |
| `test_graph.py` | LangGraph 节点 | 11 |

### 6.2 测试覆盖率估算

| 需求 | 现有测试覆盖 | 缺失场景 |
|------|-------------|---------|
| FR-001 触发机制 | ❌ 无 | 关键词触发、实体触发、时间触发测试 |
| FR-002 去重和评分 | ❌ 无 | 去重检查、重要性评分测试 |
| FR-003 记忆分层 | ⚠️ 部分 | TTL 测试有，分层逻辑无 |
| FR-004 画像置信度 | ❌ 无 | 置信度评估、冲突检测测试 |
| FR-005 上下文压缩 | ❌ 无 | 智能压缩、相关性排序测试 |

### 6.3 测试建议

```python
# 新增测试用例建议

# test_service.py
def test_add_skips_duplicate_memory():
    """测试去重：相似度 > 0.9 时跳过写入"""
    pass

def test_add_respects_importance_score():
    """测试重要性评分：低重要性不写入"""
    pass

# test_graph.py
def test_retrieve_memory_triggered_by_keyword():
    """测试关键词触发"""
    pass

def test_retrieve_memory_skips_when_no_trigger():
    """测试无触发时跳过检索"""
    pass

def test_user_profile_skips_low_confidence():
    """测试画像更新跳过低置信度结果"""
    pass
```

---

## 七、参考实现

| 项目/文档 | 参考点 |
|----------|-------|
| [Mem0 官方文档](https://docs.mem0.ai/) | 自定义 fact extraction prompt |
| [Letta 记忆架构](https://github.com/letta-ai/letta) | 短期/长期/工作记忆分层设计 |
| [LangGraph Memory](https://langchain-ai.github.io/langgraph/how-tos/memory/) | 会话级记忆管理 |
| 参考PDF《蚂蚁面试官：你的 Agent 怎么触发记忆提取？》 | 触发机制分类、时间衰减权重 |

---

## 八、改进优先级建议

| 优先级 | 改进项 | 工作量 | 影响范围 |
|--------|-------|--------|---------|
| **P0** | 关键词触发器 | 2天 | `graph.py` + 新增 `triggers.py` |
| **P0** | 记忆去重 | 1天 | `service.py` |
| **P1** | 记忆分层架构 | 3天 | `config.py` + `service.py` + 迁移 |
| **P1** | 上下文智能压缩 | 2天 | `graph.py` |
| **P2** | 用户画像置信度 | 1天 | `service.py` + `prompts.py` |
| **P2** | 时间衰减权重 | 1天 | `service.py` |
| **P3** | 用户手动管理 API | 1天 | 新增 API 端点 |

---

## 九、总结

### 9.1 主要发现

1. **触发机制单一**: 当前仅语义相似度检索，参考文章建议的 5 种触发方式仅实现 1 种
2. **去重缺失**: 相同事实可能重复写入，增加存储和检索成本
3. **无分层架构**: 所有记忆统一存储，无短/长期区分
4. **画像噪声风险**: 每次对话都更新画像，无置信度评估

### 9.2 关键风险

- 触发机制单一可能导致遗漏重要记忆
- 记忆重复写入影响检索质量
- 上下文膨胀风险（硬截断可能丢失信息）

### 9.3 下一步行动

1. **P0**: 实现关键词触发器 + 记忆去重（预计 3 天）
2. **P1**: 设计记忆分层架构（预计 3 天）
3. **P1**: 实现上下文智能压缩（预计 2 天）
