# 多轮会话架构增强 - 技术调研报告

生成时间: 2026-04-17 18:30:00
源规格: .claude/specs/014-multi-turn-session/spec.md

## 执行摘要

本报告基于 spec.md 对多轮会话架构增强功能进行技术调研。核心发现：
1. 现有 LangGraph 工作流结构清晰，可直接扩展节点
2. `sessions` 表缺少 `context_json` 字段，需数据库迁移
3. `lib/session/` 模块不存在，需新建中间件目录结构
4. `MemoryService` 和 `QueryPreprocessor` 已成熟，可直接复用
5. `AskState` 需扩展 7 个新字段支持多轮上下文

主要风险：LangGraph 条件路由与并行 fan-out 的正确实现需验证。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 多轮上下文 | `lib/rag_engine/graph.py` | 需扩展 AskState |
| FR-002 会话持久化 | `api/database.py` | sessions 表缺 context_json |
| FR-003 澄清式问答 | 新增 | 需创建 `lib/session/` 模块 |
| FR-004 矛盾检测 | 新增 | Phase 2 |
| FR-005 循环检测 | 新增 | 需创建中间件 |
| FR-006 中间件模式 | 新增 | 参考 DeerFlow 实现 |

### 1.2 可复用组件

**直接复用（无需修改）**：

| 组件 | 位置 | 复用场景 |
|------|------|---------|
| `MemoryService.search()` | `lib/memory/service.py:33` | retrieve_memory 节点 |
| `MemoryService.get_user_profile()` | `lib/memory/service.py:109` | retrieve_memory 节点 |
| `MemoryService.update_user_profile()` | `lib/memory/service.py:158` | update_profile 节点 |
| `QueryPreprocessor` | `lib/rag_engine/query_preprocessor.py` | rag_search 增强后调用 |
| `_KEYWORDS` | `lib/common/product.py:24` | 实体提取词典 |
| `trace_span` | `lib/llm/trace.py` | 所有节点追踪 |
| `get_messages()` | `api/database.py:343` | load_context 节点 |

**需扩展**：

| 组件 | 当前实现 | 扩展内容 |
|------|---------|---------|
| `AskState` | `graph.py:23` | 新增 7 个字段 |
| `sessions` 表 | `database.py:19` | 新增 `context_json` 列 |
| `ChatRequest` | `schemas/ask.py:5` | 新增 `skip_clarify` 参数 |
| `create_ask_graph()` | `graph.py:169` | 重构节点和边 |

### 1.3 需要新增的模块

| 模块路径 | 操作 | 说明 |
|---------|------|------|
| `lib/common/middleware/__init__.py` | 新增 | 模块入口 |
| `lib/common/middleware/base.py` | 新增 | Middleware Protocol 定义 |
| `lib/common/middleware/clarification.py` | 新增 | 澄清检测中间件 |
| `lib/common/middleware/session_context.py` | 新增 | 会话上下文中间件 |
| `lib/common/middleware/loop_detection.py` | 新增 | 循环检测中间件（通用） |
| `lib/common/middleware/iteration_limit.py` | 新增 | 迭代限制中间件（通用） |
| `lib/common/middleware/contradiction.py` | 新增 | 矛盾检测中间件（Phase 2） |
| `scripts/migrations/014_add_session_context.sql` | 新增 | 数据库迁移 |

**模块归属分析**：

| 中间件 | 职责 | 归属 | 复用场景 |
|--------|------|------|---------|
| LoopDetectionMiddleware | 检测重复查询 | 通用 | 任何 LLM 调用场景 |
| IterationLimitMiddleware | 迭代次数限制 | 通用 | 任何循环工作流 |
| ClarificationMiddleware | 检测模糊问题 | 问答 | ask graph |
| SessionContextMiddleware | 会话上下文管理 | 会话 | ask graph |
| ContradictionMiddleware | 检测上下文矛盾 | 对话 | Phase 2 |

**路径选择理由**：
- `lib/common/middleware/` 放置通用中间件，与 `cache.py`、`database.py` 同级
- `LoopDetection`、`IterationLimit` 可被未来其他 LangGraph 工作流（如 audit graph）复用
- 避免包名过窄（`lib/session/` 暗示仅会话相关，实际只有 1 个是）

---

## 二、技术选型研究

### 2.1 会话上下文存储方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **sessions.context_json** | 简单、与现有架构一致、无需新表 | JSON 字段查询性能一般 | ✅ 推荐 |
| 新建 session_context 表 | 结构化查询、索引友好 | 增加表数量、JOIN 开销 | ❌ 过度设计 |
| Redis 缓存 | 高性能、天然过期 | 引入新依赖、持久化复杂 | ❌ 不需要 |

**选择理由**：
- SQLite 不支持 JSON 字段索引，但 `context_json` 主要用于加载/保存，不需要复杂查询
- 会话上下文按 `session_id` 单条读写，不存在性能瓶颈

### 2.2 中间件实现方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **闭包变量（DeerFlow）** | 简单、编译时绑定、无依赖注入复杂度 | 中间件状态需线程安全 | ✅ 推荐 |
| 类装饰器模式 | 灵活、可组合 | 增加复杂度、与 LangGraph 节点函数不自然 | ❌ 不自然 |
| 依赖注入容器 | 解耦、易测试 | 引入框架依赖、学习成本 | ❌ 过度设计 |

**选择理由**：
- DeerFlow 已验证闭包方案可行
- 中间件在 `create_ask_graph()` 内创建，与节点函数形成闭包
- 每次请求复用同一中间件实例，简单高效

### 2.3 LangGraph 并行执行方案

| 方案 | 实现方式 | 选择 |
|------|---------|------|
| **START 多边** | `graph.add_edge(START, "A"); graph.add_edge(START, "B")` | ✅ 当前实现 |
| 虚拟节点 fan-out | 新增空节点作为分支点 | ✅ spec.md 选择（更清晰） |

**当前代码**（`graph.py:178-179`）：
```python
graph.add_edge(START, "retrieve_memory")
graph.add_edge(START, "rag_search")
```

**spec.md 设计**：
```python
graph.add_edge("parallel_retrieval_entry", "retrieve_memory")
graph.add_edge("parallel_retrieval_entry", "rag_search")
```

**对比**：两者效果相同，虚拟节点更清晰地表达"并行入口"语义。

### 2.4 依赖分析

| 依赖 | 当前版本 | 用途 | 兼容性 |
|------|---------|------|--------|
| `langgraph` | 已安装 | StateGraph, Runtime | ✅ 需验证条件路由 |
| `typing_extensions` | 已安装 | TypedDict, Annotated | ✅ 兼容 |
| `sse_starlette` | 已安装 | SSE 响应 | ✅ 已使用 |

**需要验证的 LangGraph 功能**：
1. `add_conditional_edges()` 返回多个目标时的行为
2. `Annotated` 类型 Reducer 的正确合并

---

## 三、数据流分析

### 3.1 现有数据流

```
POST /api/ask
    │
    ▼
AskState(question, session_id, user_id, ...)
    │
    ▼
START ──┬──► retrieve_memory ──┐
        │                      │
        └──► rag_search ───────┴──► generate ──► extract_memory ──► update_profile ──► END
                                    │
                                    ▼
                            {answer, sources, citations, ...}
```

**特点**：
- `retrieve_memory` 和 `rag_search` 并行执行
- `generate` 等待两者完成后执行
- 无条件路由，线性流水线

### 3.2 新增/变更的数据流

```
POST /api/ask
    │
    ▼
AskState(question, session_id, skip_clarify, ...)
    │
    ▼
START ──► load_context ──► clarify_check ──┬─(clarify)──► END (SSE: clarify event)
                                          │
                                          └─(search)──► parallel_retrieval_entry
                                                              │
                                               ┌──────────────┴──────────────┐
                                               ▼                             ▼
                                        retrieve_memory              rag_search
                                                                     (用 product_type 增强)
                                               └──────────────┬──────────────┘
                                                              ▼
                                                        generate
                                                              │
                                                              ▼
                                                       extract_memory
                                                              │
                                                              ▼
                                                       update_profile
                                                              │
                                                              ▼
                                                       save_context ──► END
```

**关键变更**：

| 变更点 | 说明 |
|-------|------|
| 新增 `load_context` | 加载 `session_context` + `messages` |
| 新增 `clarify_check` | 条件路由：clarify 或 search |
| 新增 `parallel_retrieval_entry` | 虚拟节点，触发并行 fan-out |
| `rag_search` 增强 | 用 `session_context.product_type` 前缀增强查询 |
| 新增 `save_context` | 保存 `session_context` 到 DB |

### 3.3 关键数据结构

**AskState 扩展**（`lib/rag_engine/graph.py`）：

```python
from typing import Annotated, Literal
import operator

def merge_session_context(left: dict, right: dict) -> dict:
    """会话上下文合并 Reducer"""
    if not left:
        return right
    if not right:
        return left
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
    # === 现有字段 ===
    question: str
    mode: str
    user_id: str
    session_id: str
    search_results: List[Dict[str, Any]]
    memory_context: str
    answer: str
    sources: List[Dict[str, Any]]
    citations: List[Dict[str, str]]
    unverified_claims: List[str]
    content_mismatches: List[Dict[str, Any]]
    faithfulness_score: Optional[float]
    error: Optional[str]

    # === 新增字段 ===
    messages: Annotated[List[Dict[str, str]], operator.add]
    session_context: Annotated[Dict[str, Any], merge_session_context]
    skip_clarify: bool
    iteration_count: int
    next_action: Literal["clarify", "search", "generate", "end"]
    clarification_message: Optional[str]
    clarification_options: Optional[List[str]]
```

**session_context 结构**（存储于 `sessions.context_json`）：

```python
{
    "mentioned_entities": ["重疾险", "泰康"],  # 最多 10 个
    "product_type": "重疾险",                  # 当前险种
    "current_topic": "等待期",                 # 当前话题
    "query_history": ["a1b2c3d4", ...]        # 循环检测用，最多 10 条
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

| # | 假设 | 验证方式 | 风险 |
|---|------|---------|------|
| 1 | LangGraph `add_conditional_edges` 可以返回特定目标节点名 | 编写最小测试用例 | 低 |
| 2 | `Annotated[..., operator.add]` Reducer 在并行节点输出时正确合并 | 编写单元测试 | 中 |
| 3 | `SessionContextMiddleware` 在 `load_context` 和 `save_context` 间正确传递状态 | 端到端测试 | 低 |
| 4 | SSE `event: "clarify"` 能被前端 EventSource 正确解析 | 前端联调 | 低 |
| 5 | `QueryPreprocessor` 与 `rag_search` 增强不冲突 | 单元测试 | 低 |

**假设 2 验证代码**：

```python
# tests/lib/rag_engine/test_state_merge.py
from typing import Annotated
import operator
from typing_extensions import TypedDict

def test_annotated_reducer_with_parallel_outputs():
    """验证并行节点输出时 Reducer 正确合并"""

    class State(TypedDict):
        values: Annotated[list, operator.add]

    # 模拟并行节点输出
    left = {"values": [1, 2]}
    right = {"values": [3, 4]}

    # LangGraph 内部合并逻辑
    merged = left.copy()
    merged["values"] = operator.add(left["values"], right["values"])

    assert merged["values"] == [1, 2, 3, 4], "Reducer 应正确合并"
```

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| LangGraph 版本不兼容条件路由语法 | 低 | 高 | 编译时检查，固定 langgraph 版本 |
| 中间件有状态导致并发问题 | 中 | 高 | `LoopDetectionMiddleware` 使用 `state.query_history` 而非实例变量 |
| `context_json` 迁移失败 | 低 | 高 | 迁移脚本使用 `ALTER TABLE ... ADD COLUMN` 兼容已有数据 |
| SSE 连接超时导致澄清失败 | 中 | 中 | 实现 30 秒心跳机制（spec.md 已定义） |
| 澄清触发率过高影响用户体验 | 中 | 中 | 调整 `ClarificationMiddleware._check()` 规则，配置阈值 |

---

## 五、实现优先级建议

### Phase 1（P1 - 核心功能）

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 1. 数据库迁移：`sessions.context_json` | 0.5 天 | 无 |
| 2. 扩展 `AskState` 和 `merge_session_context` | 0.5 天 | 无 |
| 3. 实现 `SessionContextMiddleware` | 1 天 | 1, 2 |
| 4. 重构 `create_ask_graph()`：新增节点和边 | 1 天 | 3 |
| 5. 实现 `ClarificationMiddleware` | 1 天 | 4 |
| 6. SSE `clarify` 事件支持 | 0.5 天 | 5 |
| 7. 新增 API 端点：GET/PUT `/api/sessions/{id}/context` | 0.5 天 | 1 |

**预计总工作量**：5 天

### Phase 2（P2 - 增强功能）

| 任务 | 工作量 |
|------|--------|
| `LoopDetectionMiddleware` | 0.5 天 |
| `IterationLimitMiddleware` | 0.5 天 |
| `ContradictionMiddleware` | 1 天 |
| LangGraph SqliteSaver Checkpoint | 1 天 |
| 长对话压缩 `SummarizationMiddleware` | 2 天 |

---

## 六、测试策略

### 6.1 单元测试

| 测试文件 | 测试内容 |
|---------|---------|
| `tests/lib/session/test_middlewares.py` | 各中间件的 before/after_invoke |
| `tests/lib/rag_engine/test_state_merge.py` | Reducer 合并逻辑 |
| `tests/lib/session/test_session_context.py` | context_json 序列化/反序列化 |

### 6.2 集成测试

| 测试场景 | 验证点 |
|---------|--------|
| 澄清流程 | 模糊问题 → clarify 事件 → 用户选择 → 重新检索 |
| 上下文继承 | "重疾险等待期" → "犹豫期呢？" → 检索词包含"重疾险" |
| 循环检测 | 连续 3 次相似问题 → 触发 loop_hint |
| 中断恢复 | 创建会话 → 关闭 → 重新打开 → 历史恢复 |

### 6.3 端到端测试

```python
# tests/e2e/test_multi_turn.py
import pytest
from fastapi.testclient import TestClient

def test_clarification_flow(client: TestClient):
    """测试完整澄清流程"""
    # 1. 发送模糊问题
    response = client.post("/api/ask", json={"question": "等待期是多少？"})
    events = list(response.iter_lines())

    # 2. 验证返回 clarify 事件
    assert any('event: clarify' in e for e in events)

    # 3. 模拟用户选择
    # ...

    # 4. 验证重新检索返回正确答案
```

---

## 七、参考实现

| 参考 | 说明 |
|------|------|
| [DeerFlow LangGraph Deep Dive](file:///mnt/d/work/ai-learning/deerflow_langgraph_deep_dive.md) | 中间件模式、Reducer 设计、线程安全 |
| [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/) | StateGraph API、条件路由、并行执行 |
| [Mem0 文档](https://docs.mem0.ai/) | 记忆存储接口（已有 Mem0Memory 实现） |

---

## 八、总结

### 8.1 主要发现

1. **架构兼容性好**：现有 LangGraph 工作流可直接扩展，无需大规模重构
2. **复用度高**：`MemoryService`、`QueryPreprocessor`、`_KEYWORDS` 等均可直接复用
3. **迁移成本低**：仅需添加一个 `context_json` 列，无破坏性变更

### 8.2 关键风险

1. **LangGraph 并行合并**：需验证 `Annotated` Reducer 在并行节点输出时的正确行为
2. **中间件线程安全**：`LoopDetectionMiddleware` 等有状态中间件需谨慎设计

### 8.3 下一步行动

1. 执行 `/gen-plan` 生成详细实现计划
2. 创建 worktree 进行开发
3. 按 Phase 1 任务清单逐项实现
