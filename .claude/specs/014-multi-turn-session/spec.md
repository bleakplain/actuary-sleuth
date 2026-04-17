# Feature Specification: 多轮会话架构增强

**Feature Branch**: `014-multi-turn-session`
**Created**: 2026-04-17
**Status**: Draft
**Input**: 深入了解当前 actuary-sleuth 会话实现细节，参考 DeerFlow LangGraph 架构，实现多轮对话上下文保持

## User Scenarios & Testing

### User Story 1 - 澄清式问答 (Priority: P1)

**精算师**在审核保险产品条款时，遇到模糊的法规表述，向系统提问。系统检测到问题不够明确，主动追问以获取更完整的需求背景，确保回答的准确性。

**Why this priority**: 保险法规条款专业性强，用户问题描述往往不够精确，澄清式问答能显著提升回答质量和用户满意度。

**Independent Test**:
1. 提交一个模糊问题（如 "健康险等待期"）
2. 验证系统是否主动追问（如 "请问是哪类健康险？医疗险还是重疾险？"）
3. 用户补充信息后，验证回答是否更准确

**Acceptance Scenarios**:

1. **Given** 用户提问 "健康险等待期是多少", **When** 系统检测到问题缺少险种类型上下文, **Then** 系统返回追问 "请问您咨询的是医疗险还是重疾险的等待期？"
2. **Given** 用户补充 "医疗险", **When** 系统结合上下文重新检索, **Then** 返回准确的法规条款和等待期要求
3. **Given** 用户问题足够明确（如 "短期健康险等待期不得超过多少天"）, **When** 系统判断无需澄清, **Then** 直接返回答案

---

### User Story 2 - 打断与追问 (Priority: P1)

**合规专员**在查看系统回答后，发现需要进一步追问某个细节，或想跳转到另一个话题。系统保持会话上下文，无需用户重复描述背景。

**Why this priority**: 审核工作流中用户经常需要基于之前的回答进行追问，上下文保持能大幅提升效率。

**Independent Test**:
1. 用户提问 "重疾险的等待期要求"
2. 系统返回答案
3. 用户追问 "那犹豫期呢？"
4. 验证系统是否理解 "犹豫期" 仍指重疾险

**Acceptance Scenarios**:

1. **Given** 用户已询问 "重疾险等待期", **When** 用户追问 "犹豫期呢？", **Then** 系统理解上下文为重疾险的犹豫期要求
2. **Given** 用户追问与之前话题无关的问题, **When** 系统检测到话题切换, **Then** 开启新的上下文分支，但保留历史对话记录
3. **Given** 会话中有多个话题分支, **When** 用户回溯到之前的话题, **Then** 系统能恢复该话题的上下文

---

### User Story 3 - 中断恢复 (Priority: P1)

**精算师**在审核过程中需要离开（如开会、下班），第二天回来后能恢复之前的会话状态，包括对话历史和上下文。

**Why this priority**: 审核任务往往跨多个工作日，会话持久化是实际工作场景的刚需。

**Independent Test**:
1. 用户进行多轮对话
2. 关闭浏览器或刷新页面
3. 重新打开系统
4. 验证会话历史是否完整恢复

**Acceptance Scenarios**:

1. **Given** 用户已进行 5 轮对话, **When** 用户关闭浏览器后重新打开, **Then** 显示完整的对话历史
2. **Given** 会话中包含追问上下文, **When** 恢复会话, **Then** 上下文信息（如险种类型）仍然有效
3. **Given** 会话超过 30 天未活跃, **When** 用户尝试恢复, **Then** 系统提示会话已过期，建议开启新对话

---

### User Story 4 - 矛盾检测 (Priority: P2)

**合规专员**在多轮对话中表达了不一致的需求（如先问医疗险，后问重疾险但未明确切换），系统自动识别矛盾并请求确认。

**Why this priority**: 多轮对话中用户可能忘记切换上下文，矛盾检测能避免错误回答。

**Independent Test**:
1. 用户询问医疗险等待期
2. 用户追问 "那保费呢"（未指明切换到重疾险）
3. 验证系统是否检测到潜在矛盾并请求确认

**Acceptance Scenarios**:

1. **Given** 用户之前讨论医疗险, **When** 用户问 "保费怎么算" 且上下文检测到潜在矛盾, **Then** 系统提示 "您之前询问的是医疗险，现在想了解医疗险还是重疾险的保费？"
2. **Given** 多轮对话中用户修正了之前的信息, **When** 系统检测到矛盾, **Then** 高亮显示矛盾点并请求用户确认
3. **Given** 用户明确确认切换话题, **When** 系统收到确认, **Then** 更新会话上下文并继续

---

### User Story 5 - 自动循环干预 (Priority: P2)

**精算师**在对话中陷入无效循环（如反复问同一个问题），系统检测到循环后自动干预，提供替代建议或请求人工介入。

**Why this priority**: 避免用户在死循环中浪费时间，提升用户体验。

**Independent Test**:
1. 用户连续 3 次问类似问题
2. 验证系统是否检测到循环并给出干预提示

**Acceptance Scenarios**:

1. **Given** 用户连续 3 次询问类似的等待期问题, **When** 系统检测到工具调用循环, **Then** 返回提示 "检测到您可能在寻找更精确的信息，建议您提供具体的险种名称"
2. **Given** 检索结果持续不理想, **When** 系统检测到无效检索循环, **Then** 建议用户换种方式描述问题
3. **Given** LLM 生成回答后用户反复追问相同内容, **When** 系统检测到语义重复, **Then** 提供已回答过的关键信息摘要

---

### Edge Cases

- 用户输入纯数字或无意义字符时，系统如何响应？
- 多个用户同时使用同一账号，会话如何隔离？
- 网络中断导致请求失败，如何恢复？
- 会话上下文超过最大 token 限制，如何压缩或裁剪？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持多轮对话上下文保持，包括险种类型、产品名称等关键信息
- **FR-002**: 系统 MUST 支持会话状态持久化，用户关闭浏览器后能恢复历史对话
- **FR-003**: 系统 MUST 实现澄清式问答，当用户问题不够明确时主动追问
- **FR-004**: 系统 MUST 实现矛盾检测，识别多轮对话中的上下文冲突
- **FR-005**: 系统 MUST 实现循环检测，当检测到无效重复时提供干预建议
- **FR-006**: 系统 SHOULD 支持中间件模式，在节点函数内调用，便于横切关注点的扩展
- **FR-007**: 系统 SHOULD 支持会话状态检查点（Checkpoint），支持从任意节点恢复

### Key Entities

- **AskState**: LangGraph 工作流状态，包含 question、messages（对话历史）、session_context（会话上下文）、memory_context（跨会话记忆）、iteration_count、next_action
- **Middleware**: 中间件协议，包含 before_invoke、after_invoke 方法（Protocol 鸭子类型）
- **session_context**: 会话上下文，存储于 sessions.context_json，包含 mentioned_entities、product_type、current_topic、query_history
- **messages**: 当前会话的对话历史，在 load_context 节点从 messages 表加载，格式为 `[{"role": "user/assistant", "content": "..."}]`

## Success Criteria

- **SC-001**: 多轮对话准确率 >= 90%（基于人工评估）
- **SC-002**: 会话恢复成功率 >= 99%
- **SC-003**: 澄清式问答触发准确率 >= 80%（避免不必要的追问）
- **SC-004**: 矛盾检测召回率 >= 70%，误报率 <= 10%
- **SC-005**: 中间件引入后，请求延迟增加 <= 200ms

## Assumptions

- 用户使用中文进行对话，系统暂不处理多语言场景
- 会话并发量 <= 100 QPS，单用户并发会话数 <= 5
- 会话状态存储使用 SQLite，未来可扩展到 PostgreSQL
- 中间件实现参考 DeerFlow 架构，但无需沙箱隔离（审核场景不需要代码执行）
- 现有 LangGraph 工作流（`graph.py`）需要重构，保持 API 兼容

## Technical Reference

### 核心概念说明

**AskState**：现有 LangGraph 工作流状态（`lib/rag_engine/graph.py`），生命周期是一次 `ask()` 调用。多轮上下文通过新增 `session_context` 字段实现，不引入新的 SessionState 概念。

### 现有基础设施（直接复用）

| 组件 | 位置 | 现状 |
|------|------|------|
| CacheManager | `lib/common/cache.py` | 三级缓存已完善（embedding/retrieval/generation） |
| TraceSpan | `lib/llm/trace.py` | Span 追踪 + 跨线程传播 + DB 持久化 |
| MemoryService | `lib/memory/service.py` | 长短期记忆管理 |
| logging | 标准库 | 结构化日志已在使用 |

### Middleware 基类设计

```python
from abc import ABC, abstractmethod
from typing import Protocol

class Middleware(Protocol):
    """中间件协议 - 支持前置/后置钩子"""
    
    def before_invoke(self, state: AskState) -> AskState:
        """节点执行前置处理（可选实现）"""
        return state
    
    def after_invoke(self, state: AskState) -> AskState:
        """节点执行后置处理（可选实现）"""
        return state
    def on_error(self, state: AskState, error: Exception) -> AskState:
        """错误处理（可选实现）"""
        raise error
```

**设计要点**：
1. 使用 `Protocol` 而非 `ABC`，允许鸭子类型
2. 每个中间件单一职责
3. 词汇配置复用现有 `lib/common/product.py`，不新增配置加载器
4. 默认实现为透传，子类按需覆写
5. `on_error` 提供统一异常处理入口，避免错误处理散落各处

### 中间件清单（按单一职责拆分，参考 DeerFlow）

**设计原则**：
1. 每个中间件只负责一件事（单一职责）
2. 复用现有词汇配置（`lib/common/product.py`），不新增配置加载器
3. 中间件作为闭包变量，在节点函数内直接调用（参考 DeerFlow）

| 中间件 | 职责 | 使用节点 |
|--------|------|---------|
| **ClarificationMiddleware** | 检测模糊问题，生成追问 | clarify_check |
| **SessionContextMiddleware** | 会话上下文加载/更新/保存 | load_context, save_context |
| **LoopDetectionMiddleware** | 检测重复查询循环 | generate |
| **IterationLimitMiddleware** | 迭代次数限制 | generate |
| **ContradictionMiddleware** | 检测上下文矛盾（Phase 2） | clarify_check |

**与 DeerFlow 对比**：

| DeerFlow 中间件 | 是否引入 | 原因 |
|----------------|---------|------|
| ClarificationMiddleware | ✅ | 澄清式问答核心需求 |
| MemoryMiddleware | ❌ | 已有 MemoryService |
| LoopDetectionMiddleware | ✅ | 避免用户陷入死循环 |
| SandboxMiddleware | ❌ | 无代码执行需求 |
| SubagentLimitMiddleware | ❌ | 无多代理协作 |
| SummarizationMiddleware | ⚠️ Phase 2 | 长对话压缩 |
| 其他 12 个 | ❌ | 审核场景不需要 |

---

### 中间件实现

#### 1. ClarificationMiddleware（澄清检测）

```python
# lib/common/middleware/clarification.py
from lib.common.product import get_category
from lib.session.constants import TOPIC_KEYWORDS, PRONOUN_KEYWORDS

class ClarificationMiddleware:
    """检测模糊问题，触发澄清式追问

    Phase 1: 基于规则的检测
    Phase 2: 可扩展为 LLM 辅助判断
    """

    def before_invoke(self, state: AskState) -> AskState:
        # 从 state 读取 skip_clarify 标志（前端用户选择澄清选项后设为 True）
        if state.get("skip_clarify", False):
            state["next_action"] = "search"
            return state

        question = state["question"]
        ctx = state.get("session_context", {})

        # 检测是否需要澄清
        clarification = self._check(question, ctx)
        if clarification:
            state["next_action"] = "clarify"
            state["clarification_message"] = clarification["message"]
            state["clarification_options"] = clarification.get("options", [])
        else:
            state["next_action"] = "search"

        return state

    def _check(self, question: str, ctx: dict) -> dict | None:
        """返回澄清问题，None 表示无需澄清"""

        # 规则1：有话题但无险种类型
        topic = self._extract_topic(question)
        if topic and not ctx.get("product_type"):
            return {
                "message": f"请问您咨询的是哪种险种的{topic}？",
                "options": ["重疾险", "医疗险", "意外险", "寿险"]
            }

        # 规则2：代词指代消解失败
        if any(p in question for p in PRONOUN_KEYWORDS):
            if not ctx.get("mentioned_entities"):
                return {
                    "message": "请问您指的是哪个产品或险种？",
                    "options": []
                }

        # 规则3：险种切换未明确（需要上下文）
        # 示例：之前讨论重疾险，现在问"医疗险的保费"
        # 暂不实现，Phase 2 通过 ContradictionMiddleware 处理

        return None

    def _extract_topic(self, question: str) -> str | None:
        """从问题提取话题关键词"""
        for kw in TOPIC_KEYWORDS:
            if kw in question:
                return kw
        return None
```

#### 2. SessionContextMiddleware（会话上下文管理）

```python
# lib/common/middleware/session_context.py
from lib.common.product import _KEYWORDS

MAX_ENTITIES = 10  # 实体列表上限

class SessionContextMiddleware:
    """会话上下文管理：加载 → 提取 → 合并 → 保存
    
    提取策略（Phase 1）：
    1. 规则匹配：关键词词典匹配（快速、低成本）
    2. 上下文继承：未匹配到时继承上一轮的值（保持一致性）
    
    Phase 2 增强：
    3. LLM 提取：规则失败且上下文为空时调用 LLM
    """
    
    # 关键词词典
    TOPIC_KEYWORDS = frozenset({
        "等待期", "犹豫期", "保费", "保额",
        "免责", "理赔", "保单", "续保"
    })
    
    COMPANY_KEYWORDS = frozenset({
        "泰康", "平安", "国寿", "太保", "新华", "人保"
    })
    
    def before_invoke(self, state: AskState) -> AskState:
        """加载上下文"""
        session_id = state["session_id"]
        ctx = self._load(session_id)
        state["session_context"] = ctx
        return state
    
    def after_invoke(self, state: AskState) -> AskState:
        """提取、合并、保存上下文"""
        question = state["question"]
        answer = state.get("answer", "")
        old_ctx = state.get("session_context", {})
        
        # 第1层：规则匹配
        new_product_type = self._extract_product_type(question)
        new_entities = self._extract_entities(question, answer)
        new_topic = self._extract_topic(question)
        
        # 第2层：上下文继承（保持一致性）
        product_type = new_product_type or old_ctx.get("product_type")
        
        # 合并实体（新实体优先，限制数量）
        merged_entities = list(dict.fromkeys(
            new_entities + old_ctx.get("mentioned_entities", [])
        ))[:MAX_ENTITIES]
        
        # 构建更新后的上下文
        updated_ctx = {
            "mentioned_entities": merged_entities,
            "product_type": product_type,
            "current_topic": new_topic or old_ctx.get("current_topic"),
            "query_history": old_ctx.get("query_history", [])[-10:],
        }
        
        # 保存
        self._save(state["session_id"], updated_ctx)
        state["session_context"] = updated_ctx
        
        return state
    
    def _extract_product_type(self, question: str) -> str | None:
        """提取险种类型（规则匹配）"""
        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in question:
                    return kw
        return None
    
    def _extract_entities(self, question: str, answer: str) -> List[str]:
        """提取实体（险种 + 公司）"""
        text = question + answer
        entities = []
        
        # 险种实体
        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in text:
                    entities.append(kw)
                    break  # 每种险种只添加一次
        
        # 公司实体
        for company in self.COMPANY_KEYWORDS:
            if company in text:
                entities.append(company)
        
        return list(set(entities))
    
    def _extract_topic(self, question: str) -> str | None:
        """提取话题"""
        for kw in self.TOPIC_KEYWORDS:
            if kw in question:
                return kw
        return None
    
    def _load(self, session_id: str) -> dict:
        """从 DB 加载"""
        from api.database import get_session_context
        return get_session_context(session_id) or {}
    
    def _save(self, session_id: str, ctx: dict) -> None:
        """保存到 DB"""
        from api.database import save_session_context
        save_session_context(session_id, ctx)
```

**提取示例**：

| 用户输入 | 规则匹配结果 | 继承后结果 |
|---------|-------------|-----------|
| "重疾险等待期是多少？" | product_type="重疾险", topic="等待期" | 同左 |
| "犹豫期呢？" | product_type=None, topic="犹豫期" | product_type="重疾险"（继承） |
| "泰康的那个产品" | entities=["泰康"], product_type=None | product_type="重疾险"（继承） |
| "保费怎么算" | topic="保费", product_type=None | product_type="重疾险"（继承） |

#### 3. LoopDetectionMiddleware（循环检测）

```python
# lib/common/middleware/loop_detection.py
import hashlib

class LoopDetectionMiddleware:
    """检测重复查询或无效循环

    Phase 1: 基于问题哈希的精确匹配
    Phase 2: 可扩展为语义相似度检测
    """

    LOOP_THRESHOLD = 3  # 最近N条中重复占比超过一半视为循环

    def after_invoke(self, state: AskState) -> AskState:
        ctx = state.get("session_context", {})
        history = ctx.get("query_history", [])

        # 记录当前问题签名
        question_hash = self._hash_question(state["question"])
        history.append(question_hash)

        # 检测循环
        if self._detect_loop(history):
            state["loop_detected"] = True
            state["loop_hint"] = self._generate_hint()

        # 保留最近10条
        ctx["query_history"] = history[-10:]

        return state

    def _hash_question(self, question: str) -> str:
        """问题签名（Phase 1: 精确匹配）"""
        # 标准化：去除空格、转小写
        normalized = question.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()[:8]

    def _detect_loop(self, history: List[str]) -> bool:
        """检测最近 N 条中重复占比超过一半（DeerFlow 模式）"""
        if len(history) < self.LOOP_THRESHOLD:
            return False
        recent = history[-self.LOOP_THRESHOLD:]
        # 超过一半是重复的，视为循环
        return len(set(recent)) < len(recent) / 2

    def _generate_hint(self) -> str:
        """生成干预提示"""
        return (
            "💡 检测到您可能遇到了问题，建议：\n"
            "1. 提供更具体的产品名称\n"
            "2. 明确险种类型（重疾险/医疗险/意外险）\n"
            "3. 如需人工帮助，请联系客服"
        )
```

#### 4. IterationLimitMiddleware（迭代限制）

```python
# lib/common/middleware/iteration_limit.py

class IterationLimitMiddleware:
    """迭代次数限制"""
    
    MAX_ITERATIONS = 10
    
    def after_invoke(self, state: AskState) -> AskState:
        count = state.get("iteration_count", 0) + 1
        state["iteration_count"] = count
        
        if count >= self.MAX_ITERATIONS:
            state["error"] = "达到最大迭代次数，请简化问题或重新开始对话"
            state["next_action"] = "end"
        
        return state
```

#### 5. ContradictionMiddleware（矛盾检测 - Phase 2）

```python
# lib/common/middleware/contradiction.py
from lib.session.constants import TOPIC_KEYWORDS

class ContradictionMiddleware:
    """检测多轮对话中的上下文矛盾（Phase 2 实现）"""
    
    def before_invoke(self, state: AskState) -> AskState:
        """检测潜在矛盾"""
        question = state["question"]
        ctx = state.get("session_context", {})
        
        # TODO: Phase 2 实现
        # - 使用 LLM 判断问题是否与当前上下文冲突
        # - 检测险种切换未明确声明的情况
        
        return state
```

---

### 中间件在 LangGraph 中的使用方式

**设计原则**：中间件作为闭包变量，在节点函数内直接调用。每个中间件只执行一次，在正确的时机触发。

**数据流关系**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据流关系                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  sessions.context_json                                               │
│        │                                                             │
│        ▼                                                             │
│  load_context (SessionContextMiddleware)                                │
│        │                                                             │
│        ▼                                                             │
│  state.session_context ────────────────┬───────────────────────────┐│
│        │                               │                           ││
│        ▼                               ▼                           ││
│  clarify_check              retrieve_memory    rag_search          ││
│        │                         │                  │              ││
│        │                         │                  ▼              ││
│        │                         │         query = product_type + Q ││
│        │                         │                  │              ││
│        │                         ▼                  ▼              ││
│        │                   memory_context      search_results       ││
│        │                         │                  │              ││
│        └─────────────────────────┴──────────────────┘              ││
│                                    │                                ││
│                                    ▼                                ││
│                               generate                               ││
│                                                                      ││
│  Mem0 (跨会话记忆)                                                   ││
│        │                                                             ││
│        ▼                                                             ││
│  retrieve_memory ──► memory_context                                  ││
│                                                                      ││
└─────────────────────────────────────────────────────────────────────┘

关键点：
- session_context 在 load_context 加载，后续节点都能访问
- retrieve_memory 不依赖 session_context，可以与 rag_search 并行
- rag_search 用 session_context.product_type 增强查询词
- memory_context 用于 LLM 生成个性化回答
```

```python
# lib/rag_engine/graph.py
from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

def create_ask_graph():
    """创建审核问答工作流图

    注意：skip_clarify 从 AskState.skip_clarify 读取，不作为 graph 参数
    """
    # 中间件实例（闭包变量）
    clarification_mw = ClarificationMiddleware()
    context_mw = SessionContextMiddleware()
    loop_mw = LoopDetectionMiddleware()
    limit_mw = IterationLimitMiddleware()

    # 入口节点：加载上下文和对话历史
    def load_context(state: AskState) -> dict:
        # 加载 session_context
        result = context_mw.before_invoke(state)
        # 加载对话历史
        from api.database import get_messages
        history = get_messages(state["session_id"])
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        return {"session_context": result.get("session_context", {}), "messages": messages}

    # 澄清检测节点
    def clarify_check(state: AskState) -> dict:
        return clarification_mw.before_invoke(state)

    # 条件路由函数
    def route_by_action(state: AskState) -> str:
        """根据 next_action 路由"""
        action = state.get("next_action", "search")
        if action == "clarify":
            return "clarify"  # 返回澄清问题，不进入检索
        return "search"  # 进入检索流程

    # 增强版 rag_search：用 session_context.product_type 增强查询词
    def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
        engine = runtime.context.rag_engine
        question = state["question"]

        # 用 session_context 增强查询
        ctx = state.get("session_context", {})
        if ctx.get("product_type"):
            question = f"{ctx['product_type']} {question}"

        with trace_span("graph_retrieve", "rag") as span:
            span.input = {"question": question, "original": state["question"]}
            results = engine.search(question)
            span.output = {"result_count": len(results), "enhanced_query": question}
        return {"search_results": results}

    # 生成节点：在生成后执行循环检测和迭代限制
    def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
        # 先执行原有 generate 逻辑
        result = _generate_core(state, runtime=runtime)

        # 生成后执行后置中间件
        result = loop_mw.after_invoke(result)
        result = limit_mw.after_invoke(result)

        return result

    def _generate_core(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
        """核心生成逻辑（内部实现）"""
        engine = runtime.context.rag_engine
        llm = runtime.context.llm_client
        # ... 原有 generate 逻辑 ...
        return result

    # 保存上下文节点
    def save_context(state: AskState) -> dict:
        return context_mw.after_invoke(state)

    # 构建图
    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("load_context", load_context)
    graph.add_node("clarify_check", clarify_check)
    graph.add_node("parallel_retrieval_entry", lambda state: {})  # 虚拟节点：触发并行 fan-out
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_user_profile)
    graph.add_node("save_context", save_context)

    # 入口边
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "clarify_check")

    # 条件路由：clarify 直接结束，search 进入 parallel_retrieval_entry
    graph.add_conditional_edges(
        "clarify_check",
        route_by_action,
        {"clarify": END, "search": "parallel_retrieval_entry"}
    )

    # 并行 fan-out：parallel_retrieval_entry 同时启动 retrieve_memory 和 rag_search
    graph.add_edge("parallel_retrieval_entry", "retrieve_memory")
    graph.add_edge("parallel_retrieval_entry", "rag_search")

    # 并行 fan-in：两者汇聚到 generate
    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")

    # 后处理流水线
    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("update_profile", "save_context")
    graph.add_edge("save_context", END)

    return graph.compile()
```

**中间件实例创建时机与生命周期**：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     中间件生命周期（DeerFlow 模式）                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  API 启动时                                                              │
│      │                                                                   │
│      ▼                                                                   │
│  create_ask_graph() 被调用                                               │
│      │                                                                   │
│      ▼                                                                   │
│  ┌─────────────────────────────────────────┐                            │
│  │  中间件实例创建（闭包变量）               │                            │
│  │  - clarification_mw = ...              │                            │
│  │  - context_mw = ...                    │                            │
│  │  - loop_mw = ...                       │                            │
│  │  - limit_mw = ...                      │                            │
│  └─────────────────────────────────────────┘                            │
│      │                                                                   │
│      ▼                                                                   │
│  graph.compile() 返回编译后的图                                          │
│      │                                                                   │
│      ▼                                                                   │
│  全局单例 graph 被缓存在依赖注入容器                                       │
│      │                                                                   │
│      ▼                                                                   │
│  每次请求：graph.invoke(state, context=context)                          │
│      │                                                                   │
│      └──────────► 中间件实例复用（同一个实例）                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

关键点：
1. 中间件在 create_ask_graph() 内创建，与节点函数形成闭包
2. graph.compile() 后，中间件实例被"冻结"在节点函数中
3. 每次请求复用同一中间件实例（有状态中间件需注意线程安全）
4. 有状态中间件（如 LoopDetectionMiddleware）使用 deque 等线程安全结构
```

### 完整工作流图（新旧节点组合）

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              多轮对话工作流                                               │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│  START ──► load_context ──► clarify_check ──┬─(clarify)──► END (SSE 返回澄清问题)       │
│                                             │                                            │
│                                             └─(search)──► parallel_retrieval_entry      │
│                                                             │                            │
│                                              ┌────────────┴────────────┐               │
│                                              │                         │               │
│                                              ▼                         ▼               │
│                                      retrieve_memory            rag_search           │
│                                              │               (用 product_type 增强)  │
│                                              │                         │               │
│                                              └────────────┬────────────┘               │
│                                                           │                            │
│                                                           ▼                            │
│                                                    generate                          │
│                                                           │                            │
│                                                           ▼                            │
│                                                    extract_memory                      │
│                                                           │                            │
│                                                           ▼                            │
│                                                    update_profile                      │
│                                                           │                            │
│                                                           ▼                            │
│                                                    save_context ──► END               │
│                                                                                          │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│  并行说明：                                                                               │
│                                                                                          │
│  parallel_retrieval_entry: 虚拟节点（空操作），用于触发并行 fan-out                        │
│  retrieve_memory: 从 Mem0 检索跨会话记忆，不依赖 session_context                         │
│  rag_search: 用 session_context.product_type 增强查询词后检索法规                        │
│  两者并行执行，最后汇聚到 generate                                                        │
│                                                                                          │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│  澄清流程：                                                                               │
│                                                                                          │
│  1. 用户输入 "等待期是多少？"                                                              │
│  2. clarify_check 检测到缺少险种类型，设置 next_action="clarify"                          │
│  3. SSE 返回 event: "clarify", data: {"message": "...", "options": [...]}                │
│  4. 前端展示澄清选项，用户选择 "重疾险"                                                     │
│  5. PUT /api/sessions/{id}/context {"product_type": "重疾险"}                            │
│  6. 前端重发 POST /api/ask (携带 skip_clarify=true)                                       │
│  7. clarify_check 从 state.skip_clarify 读取标志，跳过检测                                │
│  8. rag_search 用 "重疾险 等待期" 进行检索                                                │
│                                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**节点职责**：

| 节点 | 来源 | 职责 | 触发中间件 |
|------|------|------|-----------|
| load_context | 新增 | 加载 session_context + messages | SessionContextMiddleware.before |
| clarify_check | 新增 | 检测是否需要澄清 | ClarificationMiddleware.before |
| parallel_retrieval_entry | 新增 | 虚拟节点，触发并行 fan-out | - |
| retrieve_memory | 现有 | 检索跨会话记忆（不依赖 session_context） | - |
| rag_search | 现有+增强 | 用 product_type 增强查询词后检索法规 | - |
| generate | 现有+包装 | LLM 生成答案 | LoopDetection, IterationLimit.after |
| extract_memory | 现有 | 写入记忆 | - |
| update_profile | 现有 | 更新用户画像 | - |
| save_context | 新增 | 保存 session_context | SessionContextMiddleware.after |

**路由逻辑**：

```python
def route_by_action(state: AskState) -> str:
    """根据 next_action 决定下一步"""
    action = state.get("next_action", "search")
    if action == "clarify":
        return "clarify"  # 返回澄清问题，直接结束
    return "search"  # 进入正常检索流程
```

**rag_search 增强**（内部实现，节点名仍为 `rag_search`）：

```python
def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
    engine = runtime.context.rag_engine
    question = state["question"]

    # 用 session_context 增强查询
    ctx = state.get("session_context", {})
    if ctx.get("product_type"):
        question = f"{ctx['product_type']} {question}"

    results = engine.search(question)
    return {"search_results": results}
```

**增强示例**：

| 原始问题 | session_context.product_type | 增强后查询 |
|---------|------------------------------|-----------|
| "犹豫期呢？" | "重疾险" | "重疾险 犹豫期呢？" |
| "等待期是多少" | "医疗险" | "医疗险 等待期是多少" |
| "泰康的产品条款" | null | "泰康的产品条款"（无增强）|

**与 QueryPreprocessor 的协同关系**：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Query 处理流程（两层协同）                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  用户输入 "犹豫期呢？"                                                     │
│      │                                                                   │
│      ▼                                                                   │
│  ┌─────────────────────────────────────────┐                            │
│  │ graph 层：rag_search 节点                │                            │
│  │                                          │                            │
│  │  session_context.product_type = "重疾险" │                            │
│  │  enhanced_query = "重疾险 犹豫期呢？"     │                            │
│  │                                          │                            │
│  │  职责：补充上下文（用户隐含意图）         │                            │
│  └─────────────────────────────────────────┘                            │
│      │                                                                   │
│      ▼ engine.search(enhanced_query)                                     │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │ engine 层：QueryPreprocessor             │                            │
│  │                                          │                            │
│  │  归一化: "重疾险 犹豫期"（去掉"呢"）      │                            │
│  │  扩写: ["重疾险 犹豫期",                 │                            │
│  │         "重大疾病保险 犹豫期", ...]      │                            │
│  │                                          │                            │
│  │  职责：规范化表达（术语统一、同义词扩写） │                            │
│  └─────────────────────────────────────────┘                            │
│      │                                                                   │
│      ▼ hybrid_search(expanded_queries)                                   │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │ retrieval 层：向量 + BM25 检索           │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

关键点：
- graph 层增强：补充 session_context 中隐含的险种类型（多轮对话上下文）
- engine 层预处理：规范化术语表达、生成检索变体（单轮 query 优化）
- 两者协同工作，不重复、不冲突
```

### AskState 扩展

**设计原则**：
1. 扩展现有 `AskState`，不引入新的 `SessionState`
2. 使用 Reducer 处理状态合并，避免手动管理
3. 列表字段设置上限，防止无限增长
4. messages 字段存储当前会话的对话历史，支持多轮上下文

```python
# lib/rag_engine/graph.py - 扩展 AskState
from typing import Annotated, Literal
import operator

def merge_session_context(left: dict, right: dict) -> dict:
    """会话上下文合并 Reducer"""
    if not left:
        return right
    if not right:
        return left

    # 合并实体列表（新实体优先，限制数量）
    MAX_ENTITIES = 10
    merged_entities = list(dict.fromkeys(
        right.get("mentioned_entities", []) + left.get("mentioned_entities", [])
    ))[:MAX_ENTITIES]

    return {
        **left,
        **right,
        "mentioned_entities": merged_entities,
    }

class AskState(TypedDict):
    # === 现有字段（保持不变）===
    question: str
    mode: str
    user_id: str
    session_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str              # 来自 MemoryService（跨会话记忆）
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]

    # === 新增：对话历史 ===
    messages: Annotated[List[Dict[str, str]], operator.add]
    # 格式：[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    # 用于多轮对话上下文，在 load_context 节点从 DB 加载

    # === 新增：会话上下文 ===
    session_context: Annotated[Dict[str, Any], merge_session_context]
    # 示例：{"mentioned_entities": ["重疾险"], "product_type": "重疾险", "current_topic": "等待期"}

    # === 新增：控制标志 ===
    skip_clarify: bool              # 跳过澄清检测（前端用户选择澄清选项后设为 True）
    iteration_count: int            # 循环计数器
    next_action: Literal["clarify", "search", "generate", "end"]  # 路由控制

    # === 新增：澄清相关 ===
    clarification_message: Optional[str]      # 澄清问题文本
    clarification_options: Optional[List[str]]  # 澄清选项列表
```

**上下文分层**：

| 层级 | 存储位置 | 内容 | 生命周期 | 用途 |
|------|---------|------|----------|------|
| 跨会话记忆 | MemoryService | 用户画像、历史偏好 | 30天+ | 个性化推荐 |
| **会话上下文** | sessions.context_json | 当前险种、话题、实体 | 会话级 | 多轮指代消解 |
| 对话历史 | messages 表 | 完整对话记录 | 会话级 | 展示、追溯 |

**session_context 结构**：

```python
{
    # 实体列表（最多10个，新实体在前）- 存储用户原始表达
    "mentioned_entities": ["重疾险", "泰康", "健康保险管理办法"],
    
    # 当前险种类型 - 存储用户原始表达，直接用于检索和展示
    "product_type": "重疾险",  # or None
    
    # 当前话题 - 存储用户原始表达
    "current_topic": "等待期",  # or None
    
    # 查询历史（用于循环检测，最多保留10条）
    "query_history": ["a1b2c3d4", ...]
}
```

**设计决策**：session_context 存储**用户原始表达**而非枚举值

| 存储方式 | 示例 | 优点 | 缺点 |
|---------|------|------|------|
| 枚举值 | `CRITICAL_ILLNESS` | 与代码枚举一致 | 需要转换才能用于检索/展示 |
| **用户表达** | `重疾险` | 直接用于检索/展示 | 业务逻辑需要时再转换 |

**使用示例**：

```python
# 检索：直接使用
query = f"{session_context.get('product_type', '')} {question}"
# query = "重疾险 犹豫期"

# 展示：直接使用
message = f"您正在咨询{session_context['product_type']}相关问题"

# 业务逻辑：需要时转换
def start_audit(product_type: str):
    from lib.common.product import from_label
    category = from_label(product_type)  # "重疾险" → ProductCategory.CRITICAL_ILLNESS
    return AuditService.start(category)
```

### Checkpoint 与中断恢复

**设计决策**：使用两种机制配合

| 机制 | 用途 | 实现方式 |
|------|------|---------|
| **session_context** | 多轮对话上下文保持 | 手动存储到 sessions.context_json |
| **LangGraph Checkpoint** | 工作流中断恢复 | SqliteSaver（Phase 2） |

**Phase 1 实现**：session_context 手动保存

```python
# SessionContextMiddleware 负责加载和保存
class SessionContextMiddleware:
    def before_invoke(self, state):
        ctx = load_from_db(state["session_id"])
        state["session_context"] = ctx
        return state
    
    def after_invoke(self, state):
        save_to_db(state["session_id"], state["session_context"])
        return state
```

**Phase 2 增强**：集成 LangGraph SqliteSaver

```python
from langgraph.checkpoint.sqlite import SqliteSaver

def create_ask_graph():
    # ... 节点定义 ...
    
    # 编译时注入 Checkpointer
    checkpointer = SqliteSaver("checkpoints.db")
    return graph.compile(checkpointer=checkpointer)

# 恢复执行
result = app.invoke(
    initial_state,
    config={"configurable": {"thread_id": session_id}}
)
```

**为什么 Phase 1 不用 SqliteSaver**：
1. 当前工作流是线性流水线，没有复杂的循环/分支
2. session_context 已能满足多轮上下文需求
3. SqliteSaver 增加复杂度，需要额外的状态管理

### LangGraph 工作流

**工作流设计原则**：
1. 澄清检测应在检索前，避免浪费检索资源
2. 新旧节点按职责组合，保持现有节点不变
3. 中间件在正确的时机触发，不重复执行

**条件路由**：

```python
def route_by_action(state: AskState) -> str:
    """根据 next_action 路由"""
    action = state.get("next_action", "search")
    if action == "clarify":
        return "clarify"  # 返回澄清问题，不进入检索
    return "search"

# 在 clarify_check 节点后添加条件边
graph.add_conditional_edges("clarify_check", route_by_action)
```

### 数据库扩展

```sql
-- 扩展 sessions 表
ALTER TABLE sessions ADD COLUMN context_json TEXT DEFAULT '{}';
-- context_json 示例：
-- {"mentioned_entities": ["重疾险"], "product_type": "重疾险", "current_topic": "等待期"}
```

**数据模型映射**：

| 概念 | 存储位置 | 说明 |
|------|---------|------|
| 问答会话 | sessions 表 | id, title, user_id, context_json, created_at |
| 对话历史 | messages 表 | 问答记录 |

### API 设计

**新增端点**：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/sessions/{id}/context` | GET | 获取会话上下文 |
| `/api/sessions/{id}/context` | PUT | 更新会话上下文 |

**现有端点扩展**：

`POST /api/ask` - 扩展支持澄清返回（SSE 流式响应）

**请求参数扩展**：

```python
class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    mode: str = "rag"
    debug: Optional[bool] = None
    skip_clarify: bool = False  # 跳过澄清检测，直接检索
```

**SSE 事件类型扩展**：

```typescript
// SSE 事件类型
type SSEEvent =
  | { event: "message"; data: { type: "token"; data: string } }
  | { event: "message"; data: { type: "done"; data: DoneData } }
  | { event: "message"; data: { type: "error"; data: string } }
  | { event: "clarify"; data: ClarifyData };  // 新增：澄清事件

interface ClarifyData {
  message: string;          // 澄清问题
  options?: string[];       // 澄清选项
  session_context: {        // 当前会话上下文
    current_topic?: string;
  };
}

interface DoneData {
  session_id: string;
  message_id: int;
  answer?: string;          // 流式返回时已通过 token 发送
  citations: Citation[];
  sources: Source[];
  session_context: SessionContext;
}
```

**SSE 心跳机制**（防止长对话连接超时）：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     SSE 心跳流程                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  后端                                                                     │
│      │                                                                   │
│      ├── 每 30 秒发送心跳事件                                             │
│      │   event: heartbeat                                                │
│      │   data: {"ts": 1234567890}                                        │
│      │                                                                   │
│      ├── LLM 生成时暂停心跳（避免干扰流式输出）                            │
│      │                                                                   │
│  前端                                                                     │
│      │                                                                   │
│      ├── 收到 heartbeat 事件：更新最后活跃时间                             │
│      │                                                                   │
│      ├── 超过 60 秒未收到任何事件：触发重连                                │
│      │                                                                   │
│      └── 重连时携带 last_event_id（断点续传）                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

```python
# 后端心跳实现（api/routers/ask.py）
import asyncio

async def stream_with_heartbeat(stream_generator, heartbeat_interval=30):
    """SSE 流式输出 + 心跳维持"""
    last_heartbeat = asyncio.get_event_loop().time()

    async for event in stream_generator:
        # 发送业务事件
        yield event
        last_heartbeat = asyncio.get_event_loop().time()

        # 检查是否需要心跳
        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= heartbeat_interval:
            yield {
                "event": "heartbeat",
                "data": json.dumps({"ts": int(now)})
            }
            last_heartbeat = now
```

```typescript
// 前端心跳处理
function handleSSEEvent(event: MessageEvent) {
  if (event.event === "heartbeat") {
    state.lastHeartbeat = Date.now();
    return;  // 心跳事件不显示
  }
  // ... 其他事件处理 ...
}

// 连接超时检测
setInterval(() => {
  if (Date.now() - state.lastHeartbeat > 60000) {
    reconnect();
  }
}, 10000);
```

**SSE 响应示例（需要澄清）**：

```
event: clarify
data: {"message": "请问您咨询的是哪种险种的等待期？", "options": ["重疾险", "医疗险", "意外险", "寿险"], "session_context": {"current_topic": "等待期"}}
```

**SSE 响应示例（正常返回）**：

```
event: message
data: {"type": "token", "data": "根据《健康保险管理办法》"}

event: message
data: {"type": "token", "data": "第十七条规定..."}

event: message
data: {"type": "done", "data": {"session_id": "xxx", "message_id": 123, "citations": [...], "sources": [...], "session_context": {"product_type": "重疾险", "current_topic": "等待期"}}}
```

**后端实现要点**：

```python
# api/routers/ask.py
async def event_stream():
    # ... 初始化 ...

    async def stream_with_clarification():
        # 构建初始 state，skip_clarify 从请求参数传入
        state = AskState(
            question=req.question,
            mode=req.mode,
            user_id=req.user_id,
            session_id=session_id,
            search_results=[],
            memory_context="",
            answer="",
            sources=[],
            citations=[],
            unverified_claims=[],
            content_mismatches=[],
            faithfulness_score=None,
            error=None,
            messages=[],
            session_context={},
            skip_clarify=req.skip_clarify,  # 从请求参数传入
            iteration_count=0,
            next_action="search",
            clarification_message=None,
            clarification_options=None,
        )

        # 执行工作流
        result = await asyncio.to_thread(graph.invoke, state, context=context)

        # 检查是否需要澄清
        if result.get("next_action") == "clarify":
            yield {
                "event": "clarify",
                "data": json.dumps({
                    "message": result.get("clarification_message", ""),
                    "options": result.get("clarification_options", []),
                    "session_context": result.get("session_context", {}),
                }, ensure_ascii=False)
            }
            return  # 提前结束流

        # 正常返回：流式输出答案
        answer = result.get("answer", "")
        for i in range(0, len(answer), 4):
            chunk = answer[i : i + 4]
            yield {
                "event": "message",
                "data": json.dumps({"type": "token", "data": chunk}, ensure_ascii=False)
            }

        # 返回完成事件
        yield {
            "event": "message",
            "data": json.dumps({
                "type": "done",
                "data": {
                    "session_id": session_id,
                    "message_id": msg_id,
                    "citations": result.get("citations", []),
                    "sources": result.get("sources", []),
                    "session_context": result.get("session_context", {}),
                }
            }, ensure_ascii=False)
        }

    return EventSourceResponse(stream_with_clarification())
```

### 前端交互流程

**澄清式问答完整流程**：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              澄清式问答流程（SSE 版本）                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. 用户输入问题 "等待期是多少？"                                             │
│     │                                                                        │
│     ▼                                                                        │
│  2. POST /api/ask (SSE)                                                      │
│     │                                                                        │
│     ▼                                                                        │
│  3. 接收 SSE 事件                                                            │
│     │                                                                        │
│     ├── event: "clarify" ──► 显示澄清选项                                    │
│     │       data: {"message": "...", "options": [...]}                      │
│     │               │                                                        │
│     │               ▼                                                        │
│     │          4. 用户选择 "重疾险"                                          │
│     │               │                                                        │
│     │               ▼                                                        │
│     │          5. PUT /api/sessions/{id}/context                            │
│     │             {"product_type": "重疾险"}                                 │
│     │               │                                                        │
│     │               ▼                                                        │
│     │          6. 重发 POST /api/ask (skip_clarify=true)                    │
│     │               │                                                        │
│     └───────────────┼───────────────────────────────────────────────────────│
│                     │                                                        │
│                     ▼                                                        │
│  7. event: "message" data: {"type": "token", "data": "..."}                 │
│     │                                                                        │
│     ▼                                                                        │
│  8. event: "message" data: {"type": "done", "data": {...}}                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**前端状态管理**：

```typescript
// 前端维护的状态
interface AskState {
  question: string;
  sessionId: string;
  sessionContext: SessionContext;
  clarificationNeeded: boolean;
  clarificationMessage?: string;
  clarificationOptions?: string[];
  skipClarify: boolean;  // 是否跳过澄清检测
}

// SSE 事件处理
function handleSSEEvent(event: MessageEvent) {
  const eventType = event.event;  // "message" | "clarify"

  if (eventType === "clarify") {
    const data = JSON.parse(event.data);
    state.clarificationNeeded = true;
    state.clarificationMessage = data.message;
    state.clarificationOptions = data.options;
    state.sessionContext = data.session_context;
    // 渲染澄清选项 UI
    renderClarificationUI(data.message, data.options);
    return;  // 停止处理后续事件
  }

  // 正常 message 事件
  const data = JSON.parse(event.data);
  if (data.type === "token") {
    appendAnswer(data.data);
  } else if (data.type === "done") {
    state.sessionContext = data.session_context;
    finalizeAnswer(data);
  }
}

// 用户选择后的处理
async function handleClarification(option: string) {
  // 1. 更新上下文
  await fetch(`/api/sessions/${sessionId}/context`, {
    method: 'PUT',
    body: JSON.stringify({ product_type: option })
  });

  // 2. 重发原问题，跳过澄清检测
  state.skipClarify = true;
  await askQuestion(originalQuestion);
}
```

**前端配置**：

```typescript
// 澄清选项配置
const CLARIFICATION_CONFIG = {
  auto_submit: true,   // 选择后自动重发
  timeout_ms: 30000,   // 澄清超时时间
  max_retries: 2,      // 最大重试次数
};

// SSE 连接配置
const SSE_CONFIG = {
  withCredentials: false,
  heartbeatInterval: 30000,  // 心跳间隔
  reconnectAttempts: 3,      // 重连次数
};
```

### 数据库迁移

**迁移脚本**：`scripts/migrations/014_add_session_context.sql`

```sql
-- Version: 014
-- Description: 多轮会话上下文

ALTER TABLE sessions ADD COLUMN context_json TEXT DEFAULT '{}';
```

**回滚脚本**：`scripts/migrations/014_rollback.sql`

```sql
-- Version: 014 rollback
ALTER TABLE sessions DROP COLUMN context_json;
```

### 共享常量

```python
# lib/common/middleware/constants.py
"""多轮会话共享常量"""

# 话题关键词（与 insurance_dict.txt 保持一致）
TOPIC_KEYWORDS = frozenset({
    "等待期", "犹豫期", "保费", "保额", 
    "免责", "理赔", "保单", "续保"
})

# 代词关键词
PRONOUN_KEYWORDS = frozenset({
    "它", "这个产品", "该产品", "那个产品"
})

# 澄清选项（直接使用中文，存储时无需转换）
PRODUCT_TYPE_OPTIONS = ["重疾险", "医疗险", "意外险", "寿险"]
```

### 错误处理策略

**中间件失败处理**：

| 场景 | 处理方式 | 影响 |
|------|---------|------|
| SessionContextMiddleware 加载失败 | 返回空上下文 `{}`，继续执行 | 不影响主流程 |
| SessionContextMiddleware 保存失败 | 记录日志，不中断流程 | 本次对话上下文丢失 |
| ClarificationMiddleware 异常 | 跳过澄清，直接进入检索 | 可能返回不够准确的答案 |
| LoopDetectionMiddleware 异常 | 跳过循环检测 | 用户可能陷入循环 |
| IterationLimitMiddleware 异常 | 跳过计数限制 | 理论上可能无限循环 |

**实现示例**：

```python
class SessionContextMiddleware:
    def before_invoke(self, state: AskState) -> AskState:
        try:
            ctx = self._load(state["session_id"])
            state["session_context"] = ctx
        except Exception as e:
            logger.warning(f"加载会话上下文失败: {e}")
            state["session_context"] = {}  # 降级为空上下文
        return state
    
    def after_invoke(self, state: AskState) -> AskState:
        try:
            # ... 更新逻辑 ...
            self._save(state["session_id"], updated_ctx)
        except Exception as e:
            logger.warning(f"保存会话上下文失败: {e}")
            # 不中断流程，继续执行
        return state
```

**数据库失败处理**：

```python
# api/database.py
def save_session_context(session_id: str, ctx: dict) -> bool:
    """保存会话上下文，失败时记录日志但不抛异常"""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE sessions SET context_json = ? WHERE id = ?",
                (json.dumps(ctx, ensure_ascii=False), session_id)
            )
        return True
    except Exception as e:
        logger.error(f"保存会话上下文失败: session_id={session_id}, error={e}")
        return False
```

## Out of Scope

- 审核工作流改造（独立 feature）
- 多租户架构
- 实时协作
- 语音交互
- 多模态输入
