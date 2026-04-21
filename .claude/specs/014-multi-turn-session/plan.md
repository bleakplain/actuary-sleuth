# Implementation Plan: 多轮会话架构增强

**Branch**: `014-multi-turn-session` | **Date**: 2026-04-17 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

实现多轮对话上下文保持功能，包括：
- **澄清式问答**（User Story 1）：检测模糊问题，主动追问
- **追问上下文继承**（User Story 2）：用 `session_context.product_type` 增强检索
- **会话持久化**（User Story 3）：`sessions.context_json` 存储
- **循环检测**（User Story 5）：中间件检测重复查询

技术方案：LangGraph 节点扩展 + 中间件模式（闭包变量）+ SQLite 存储。

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: langgraph（已安装）, sse-starlette（已安装）
**Storage**: SQLite（sessions.context_json）
**Testing**: pytest
**Performance Goals**: 中间件延迟 <= 200ms
**Constraints**: 单用户并发会话数 <= 5，会话 30 天过期

## Constitution Check

- [x] **Library-First**: 复用 `MemoryService`、`QueryPreprocessor`、`_KEYWORDS`、`trace_span`
- [x] **测试优先**: 每个中间件、Reducer、节点函数都有单元测试
- [x] **简单优先**: 使用 `sessions.context_json` 而非新建表；闭包中间件而非 DI 框架
- [x] **显式优于隐式**: `session_context` 存储用户原始表达，业务逻辑显式转换
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md User Story
- [x] **独立可测试**: User Story 1-3 可独立交付和测试

## Project Structure

### Documentation

```text
.claude/specs/014-multi-turn-session/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── lib/
│   ├── common/
│   │   └── middleware/           # 新增目录
│   │       ├── __init__.py
│   │       ├── base.py           # Protocol 定义
│   │       ├── constants.py      # TOPIC_KEYWORDS 等
│   │       ├── clarification.py  # 澄清检测
│   │       ├── session_context.py # 会话上下文
│   │       ├── loop_detection.py # 循环检测
│   │       └── iteration_limit.py # 迭代限制
│   └── rag_engine/
│       └── graph.py              # 扩展 AskState，重构 create_ask_graph
├── api/
│   ├── database.py               # 新增 get/save_session_context
│   ├── routers/
│   │   └── ask.py                # 扩展 SSE 事件，新增 skip_clarify
│   └── schemas/
│       └── ask.py                # 扩展 ChatRequest
└── migrations/
    └── 014_add_session_context.sql  # 新增
```

## Implementation Phases

---

### Phase 1: 基础设施 - 数据库迁移 & AskState 扩展

**目标**：为后续功能提供数据存储和状态管理基础。

#### 实现步骤

**1.1 数据库迁移：sessions.context_json**

- 文件: `scripts/migrations/014_add_session_context.sql`
- 操作: 新增

```sql
-- Version: 014
-- Description: 多轮会话上下文

ALTER TABLE sessions ADD COLUMN context_json TEXT DEFAULT '{}';
```

- 文件: `scripts/api/database.py`
- 操作: 扩展 `_migrate_db()`

```python
def _migrate_db():
    """增量迁移：添加新列"""
    with get_connection() as conn:
        # ... 现有迁移 ...

        # 新增：sessions.context_json
        session_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if 'context_json' not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN context_json TEXT DEFAULT '{}'")
```

**1.2 新增数据库访问函数**

- 文件: `scripts/api/database.py`
- 操作: 新增函数

```python
def get_session_context(session_id: str) -> Optional[Dict[str, Any]]:
    """获取会话上下文"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT context_json FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row and row["context_json"]:
            return json.loads(row["context_json"])
        return None


def save_session_context(session_id: str, ctx: Dict[str, Any]) -> bool:
    """保存会话上下文"""
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

**1.3 扩展 AskState**

- 文件: `scripts/lib/rag_engine/graph.py`
- 操作: 修改

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
    # === 现有字段（保持不变）===
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

    # === 新增：对话历史 ===
    messages: Annotated[List[Dict[str, str]], operator.add]

    # === 新增：会话上下文 ===
    session_context: Annotated[Dict[str, Any], merge_session_context]

    # === 新增：控制标志 ===
    skip_clarify: bool
    iteration_count: int
    next_action: Literal["clarify", "search", "generate", "end"]

    # === 新增：澄清相关 ===
    clarification_message: Optional[str]
    clarification_options: Optional[List[str]]
    loop_detected: Optional[bool]
    loop_hint: Optional[str]
```

**1.4 扩展 ChatRequest**

- 文件: `scripts/api/schemas/ask.py`
- 操作: 修改

```python
class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: Optional[str] = Field(None, description="会话 ID，为空则新建会话")
    mode: str = Field("qa", pattern="^(qa|search)$", description="qa=智能问答, search=精确检索")
    debug: Optional[bool] = Field(None, description="是否记录 trace 调试信息")
    user_id: str = Field("default", description="用户 ID")
    skip_clarify: bool = Field(False, description="跳过澄清检测，直接检索")  # 新增
```

**1.5 测试**

- 文件: `scripts/tests/lib/rag_engine/test_state_merge.py`
- 操作: 新增

```python
"""AskState Reducer 合并测试"""
import pytest
from typing import Annotated
import operator


def test_operator_add_reducer():
    """验证 operator.add 正确合并列表"""
    left = {"messages": [{"role": "user", "content": "Q1"}]}
    right = {"messages": [{"role": "assistant", "content": "A1"}]}

    merged = left.copy()
    merged["messages"] = operator.add(left["messages"], right["messages"])

    assert len(merged["messages"]) == 2
    assert merged["messages"][0]["content"] == "Q1"
    assert merged["messages"][1]["content"] == "A1"


def test_merge_session_context():
    """验证 session_context 合并逻辑"""
    from lib.rag_engine.graph import merge_session_context

    # 左空，返回右
    assert merge_session_context({}, {"product_type": "重疾险"}) == {"product_type": "重疾险"}

    # 右空，返回左
    assert merge_session_context({"product_type": "医疗险"}, {}) == {"product_type": "医疗险"}

    # 实体合并，去重，限制 10 个
    left = {"mentioned_entities": ["重疾险", "泰康"]}
    right = {"mentioned_entities": ["医疗险", "重疾险"], "product_type": "医疗险"}
    merged = merge_session_context(left, right)

    assert "重疾险" in merged["mentioned_entities"]
    assert "医疗险" in merged["mentioned_entities"]
    assert "泰康" in merged["mentioned_entities"]
    assert merged["product_type"] == "医疗险"
```

---

### Phase 2: 中间件基础设施

**目标**：建立中间件模块，实现核心中间件。

#### 需求回溯

→ 对应 spec.md FR-006: 系统 SHOULD 支持中间件模式

#### 实现步骤

**2.1 创建中间件模块目录**

- 文件: `scripts/lib/common/middleware/__init__.py`
- 操作: 新增

```python
"""通用中间件模块"""
from .base import Middleware

__all__ = ["Middleware"]
```

**2.2 Middleware Protocol 定义**

- 文件: `scripts/lib/common/middleware/base.py`
- 操作: 新增

```python
"""中间件协议定义"""
from typing import Protocol, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState


class Middleware(Protocol):
    """中间件协议 - 支持前置/后置钩子

    使用 Protocol 允许鸭子类型，无需显式继承。
    """

    def before_invoke(self, state: "AskState") -> "AskState":
        """节点执行前置处理（可选实现）"""
        return state

    def after_invoke(self, state: "AskState") -> "AskState":
        """节点执行后置处理（可选实现）"""
        return state

    def on_error(self, state: "AskState", error: Exception) -> "AskState":
        """错误处理（可选实现）"""
        raise error
```

**2.3 共享常量**

- 文件: `scripts/lib/common/middleware/constants.py`
- 操作: 新增

```python
"""中间件共享常量"""

# 话题关键词
TOPIC_KEYWORDS = frozenset({
    "等待期", "犹豫期", "保费", "保额",
    "免责", "理赔", "保单", "续保"
})

# 代词关键词
PRONOUN_KEYWORDS = frozenset({
    "它", "这个产品", "该产品", "那个产品"
})

# 澄清选项
PRODUCT_TYPE_OPTIONS = ["重疾险", "医疗险", "意外险", "寿险"]
```

**2.4 SessionContextMiddleware**

- 文件: `scripts/lib/common/middleware/session_context.py`
- 操作: 新增

```python
"""会话上下文中间件"""
import logging
from typing import TYPE_CHECKING, List

from lib.common.middleware.constants import TOPIC_KEYWORDS
from lib.common.product import _KEYWORDS

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState

logger = logging.getLogger(__name__)

MAX_ENTITIES = 10
COMPANY_KEYWORDS = frozenset({"泰康", "平安", "国寿", "太保", "新华", "人保"})


class SessionContextMiddleware:
    """会话上下文管理：加载 → 提取 → 合并 → 保存"""

    def before_invoke(self, state: "AskState") -> "AskState":
        """加载上下文"""
        session_id = state.get("session_id")
        if not session_id:
            state["session_context"] = {}
            return state

        try:
            from api.database import get_session_context
            ctx = get_session_context(session_id)
            state["session_context"] = ctx or {}
        except Exception as e:
            logger.warning(f"加载会话上下文失败: {e}")
            state["session_context"] = {}

        return state

    def after_invoke(self, state: "AskState") -> "AskState":
        """提取、合并、保存上下文"""
        question = state.get("question", "")
        answer = state.get("answer", "")
        old_ctx = state.get("session_context", {})

        # 第1层：规则匹配
        new_product_type = self._extract_product_type(question)
        new_entities = self._extract_entities(question, answer)
        new_topic = self._extract_topic(question)

        # 第2层：上下文继承
        product_type = new_product_type or old_ctx.get("product_type")

        # 合并实体
        merged_entities = list(dict.fromkeys(
            new_entities + old_ctx.get("mentioned_entities", [])
        ))[:MAX_ENTITIES]

        updated_ctx = {
            "mentioned_entities": merged_entities,
            "product_type": product_type,
            "current_topic": new_topic or old_ctx.get("current_topic"),
            "query_history": old_ctx.get("query_history", [])[-10:],
        }

        # 保存
        session_id = state.get("session_id")
        if session_id:
            try:
                from api.database import save_session_context
                save_session_context(session_id, updated_ctx)
            except Exception as e:
                logger.warning(f"保存会话上下文失败: {e}")

        state["session_context"] = updated_ctx
        return state

    def _extract_product_type(self, question: str) -> str | None:
        """提取险种类型"""
        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in question:
                    return kw
        return None

    def _extract_entities(self, question: str, answer: str) -> List[str]:
        """提取实体"""
        text = question + answer
        entities = []

        for keywords in _KEYWORDS.values():
            for kw in keywords:
                if kw in text:
                    entities.append(kw)
                    break

        for company in COMPANY_KEYWORDS:
            if company in text:
                entities.append(company)

        return list(set(entities))

    def _extract_topic(self, question: str) -> str | None:
        """提取话题"""
        for kw in TOPIC_KEYWORDS:
            if kw in question:
                return kw
        return None
```

**2.5 ClarificationMiddleware**

- 文件: `scripts/lib/common/middleware/clarification.py`
- 操作: 新增

```python
"""澄清检测中间件"""
import logging
from typing import TYPE_CHECKING

from lib.common.middleware.constants import TOPIC_KEYWORDS, PRONOUN_KEYWORDS, PRODUCT_TYPE_OPTIONS

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState

logger = logging.getLogger(__name__)


class ClarificationMiddleware:
    """检测模糊问题，触发澄清式追问"""

    def before_invoke(self, state: "AskState") -> "AskState":
        # 从 state 读取 skip_clarify 标志
        if state.get("skip_clarify", False):
            state["next_action"] = "search"
            return state

        question = state.get("question", "")
        ctx = state.get("session_context", {})

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
                "options": PRODUCT_TYPE_OPTIONS
            }

        # 规则2：代词指代消解失败
        if any(p in question for p in PRONOUN_KEYWORDS):
            if not ctx.get("mentioned_entities"):
                return {
                    "message": "请问您指的是哪个产品或险种？",
                    "options": []
                }

        return None

    def _extract_topic(self, question: str) -> str | None:
        """从问题提取话题"""
        for kw in TOPIC_KEYWORDS:
            if kw in question:
                return kw
        return None
```

**2.6 LoopDetectionMiddleware**

- 文件: `scripts/lib/common/middleware/loop_detection.py`
- 操作: 新增

```python
"""循环检测中间件"""
import hashlib
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState

logger = logging.getLogger(__name__)


class LoopDetectionMiddleware:
    """检测重复查询或无效循环

    使用 DeerFlow 模式：最近 N 条中重复占比超过一半视为循环
    """

    LOOP_THRESHOLD = 3

    def after_invoke(self, state: "AskState") -> "AskState":
        ctx = state.get("session_context", {})
        history = list(ctx.get("query_history", []))

        # 记录当前问题签名
        question_hash = self._hash_question(state.get("question", ""))
        history.append(question_hash)

        # 检测循环
        if self._detect_loop(history):
            state["loop_detected"] = True
            state["loop_hint"] = self._generate_hint()

        # 更新 history（保留最近 10 条）
        ctx["query_history"] = history[-10:]
        state["session_context"] = ctx

        return state

    def _hash_question(self, question: str) -> str:
        """问题签名"""
        normalized = question.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()[:8]

    def _detect_loop(self, history: List[str]) -> bool:
        """检测最近 N 条中重复占比超过一半"""
        if len(history) < self.LOOP_THRESHOLD:
            return False
        recent = history[-self.LOOP_THRESHOLD:]
        return len(set(recent)) < len(recent) / 2

    def _generate_hint(self) -> str:
        """生成干预提示"""
        return (
            "检测到您可能遇到了问题，建议：\n"
            "1. 提供更具体的产品名称\n"
            "2. 明确险种类型（重疾险/医疗险/意外险）\n"
            "3. 如需人工帮助，请联系客服"
        )
```

**2.7 IterationLimitMiddleware**

- 文件: `scripts/lib/common/middleware/iteration_limit.py`
- 操作: 新增

```python
"""迭代限制中间件"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.rag_engine.graph import AskState


class IterationLimitMiddleware:
    """迭代次数限制"""

    MAX_ITERATIONS = 10

    def after_invoke(self, state: "AskState") -> "AskState":
        count = state.get("iteration_count", 0) + 1
        state["iteration_count"] = count

        if count >= self.MAX_ITERATIONS:
            state["error"] = "达到最大迭代次数，请简化问题或重新开始对话"
            state["next_action"] = "end"

        return state
```

**2.8 测试**

- 文件: `scripts/tests/lib/common/middleware/test_middlewares.py`
- 操作: 新增

```python
"""中间件单元测试"""
import pytest


class TestSessionContextMiddleware:
    def test_before_invoke_loads_context(self):
        """验证 before_invoke 加载上下文"""
        from lib.common.middleware.session_context import SessionContextMiddleware

        mw = SessionContextMiddleware()
        state = {"session_id": "test_session", "question": "测试"}

        result = mw.before_invoke(state)

        assert "session_context" in result
        assert isinstance(result["session_context"], dict)

    def test_extract_product_type(self):
        """验证险种类型提取"""
        from lib.common.middleware.session_context import SessionContextMiddleware

        mw = SessionContextMiddleware()

        assert mw._extract_product_type("重疾险等待期") == "重疾险"
        assert mw._extract_product_type("医疗险保费") == "医疗险"
        assert mw._extract_product_type("等待期") is None


class TestClarificationMiddleware:
    def test_needs_clarification_without_product_type(self):
        """验证无险种类型时触发澄清"""
        from lib.common.middleware.clarification import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {},
            "skip_clarify": False,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "clarify"
        assert "clarification_message" in result

    def test_skip_clarify_flag(self):
        """验证 skip_clarify 跳过检测"""
        from lib.common.middleware.clarification import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {},
            "skip_clarify": True,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "search"

    def test_no_clarification_with_product_type(self):
        """验证有险种类型时无需澄清"""
        from lib.common.middleware.clarification import ClarificationMiddleware

        mw = ClarificationMiddleware()
        state = {
            "question": "等待期是多少？",
            "session_context": {"product_type": "重疾险"},
            "skip_clarify": False,
        }

        result = mw.before_invoke(state)

        assert result["next_action"] == "search"


class TestLoopDetectionMiddleware:
    def test_detects_loop(self):
        """验证循环检测"""
        from lib.common.middleware.loop_detection import LoopDetectionMiddleware

        mw = LoopDetectionMiddleware()

        # 相同问题哈希
        hash_val = mw._hash_question("等待期")

        state = {
            "question": "等待期",
            "session_context": {"query_history": [hash_val, hash_val]},
        }

        result = mw.after_invoke(state)

        assert result.get("loop_detected") is True

    def test_no_loop_with_different_questions(self):
        """验证不同问题不触发循环"""
        from lib.common.middleware.loop_detection import LoopDetectionMiddleware

        mw = LoopDetectionMiddleware()

        state = {
            "question": "犹豫期",
            "session_context": {"query_history": ["a", "b", "c"]},
        }

        result = mw.after_invoke(state)

        assert result.get("loop_detected") is not True
```

---

### Phase 3: LangGraph 工作流重构 - User Story 1, 2, 3 (P1)

**目标**：重构 `create_ask_graph()`，实现澄清式问答和上下文继承。

#### 需求回溯

→ 对应 spec.md User Story 1: 澄清式问答
→ 对应 spec.md User Story 2: 打断与追问
→ 对应 spec.md User Story 3: 中断恢复

#### 实现步骤

**3.1 重构 create_ask_graph()**

- 文件: `scripts/lib/rag_engine/graph.py`
- 操作: 大幅修改

```python
from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime

from lib.common.middleware.clarification import ClarificationMiddleware
from lib.common.middleware.session_context import SessionContextMiddleware
from lib.common.middleware.loop_detection import LoopDetectionMiddleware
from lib.common.middleware.iteration_limit import IterationLimitMiddleware


def create_ask_graph():
    """创建审核问答工作流图（多轮对话增强版）"""
    # 中间件实例（闭包变量）
    clarification_mw = ClarificationMiddleware()
    context_mw = SessionContextMiddleware()
    loop_mw = LoopDetectionMiddleware()
    limit_mw = IterationLimitMiddleware()

    # === 节点函数 ===

    def load_context(state: AskState) -> dict:
        """加载会话上下文和对话历史"""
        # 加载 session_context
        result = context_mw.before_invoke(state)
        # 加载对话历史
        from api.database import get_messages
        history = get_messages(state.get("session_id", ""))
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        return {"session_context": result.get("session_context", {}), "messages": messages}

    def clarify_check(state: AskState) -> dict:
        """澄清检测"""
        return clarification_mw.before_invoke(state)

    def rag_search(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
        """增强版 RAG 检索：用 session_context.product_type 增强查询"""
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

    def generate(state: AskState, *, runtime: Runtime[GraphContext]) -> dict:
        """LLM 生成答案 + 后置中间件"""
        # 核心生成逻辑
        engine = runtime.context.rag_engine
        llm = runtime.context.llm_client

        with trace_span("graph_generate", "llm", model=getattr(llm, 'model', '')) as span:
            span.input = {
                "question": state["question"],
                "context_chunk_count": len(state["search_results"]),
                "has_memory_context": bool(state.get("memory_context")),
            }

            user_prompt, included_count = RAGEngine._build_qa_prompt(
                engine.config.generation, state["question"], state["search_results"]
            )
            messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
            if state.get("memory_context"):
                messages.append({"role": "system", "content": f"【用户历史信息】\n{state['memory_context']}"})

            with trace_span("llm_generate", "llm", model=getattr(llm, 'model', '')) as inner:
                inner.input = {"question": state["question"], "user_prompt": user_prompt}
                messages.append({"role": "user", "content": user_prompt})
                answer = llm.chat(messages)
                answer_str = str(answer)
                inner.output = {"answer_length": len(answer_str)}

            included_sources = state["search_results"][:included_count] if state["search_results"] else []
            attribution = parse_citations(answer_str, included_sources)

            result = {
                "answer": answer_str,
                "sources": state["search_results"],
                "citations": [
                    {"source_idx": c.source_idx, "law_name": c.law_name, "article_number": c.article_number, "content": c.content}
                    for c in attribution.citations
                ],
                "unverified_claims": attribution.unverified_claims,
                "content_mismatches": attribution.content_mismatches,
            }
            span.output = {"answer_length": len(answer_str), "citation_count": len(attribution.citations)}

        # 后置中间件
        result = loop_mw.after_invoke(result)
        result = limit_mw.after_invoke(result)

        return result

    def save_context(state: AskState) -> dict:
        """保存会话上下文"""
        return context_mw.after_invoke(state)

    # === 路由函数 ===

    def route_by_action(state: AskState) -> str:
        """根据 next_action 路由"""
        action = state.get("next_action", "search")
        if action == "clarify":
            return "clarify"
        return "search"

    # === 构建图 ===

    graph = StateGraph(AskState, context_schema=GraphContext)
    graph.add_node("load_context", load_context)
    graph.add_node("clarify_check", clarify_check)
    graph.add_node("parallel_retrieval_entry", lambda state: {})  # 虚拟节点
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("rag_search", rag_search)
    graph.add_node("generate", generate)
    graph.add_node("extract_memory", extract_memory)
    graph.add_node("update_profile", update_user_profile)
    graph.add_node("save_context", save_context)

    # 入口边
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "clarify_check")

    # 条件路由
    graph.add_conditional_edges(
        "clarify_check",
        route_by_action,
        {"clarify": END, "search": "parallel_retrieval_entry"}
    )

    # 并行 fan-out
    graph.add_edge("parallel_retrieval_entry", "retrieve_memory")
    graph.add_edge("parallel_retrieval_entry", "rag_search")

    # 并行 fan-in
    graph.add_edge("retrieve_memory", "generate")
    graph.add_edge("rag_search", "generate")

    # 后处理流水线
    graph.add_edge("generate", "extract_memory")
    graph.add_edge("extract_memory", "update_profile")
    graph.add_edge("update_profile", "save_context")
    graph.add_edge("save_context", END)

    return graph.compile()
```

**3.2 扩展 SSE 事件处理**

- 文件: `scripts/api/routers/ask.py`
- 操作: 修改 `event_stream()`

```python
async def event_stream():
    # ... 初始化 ...

    async def stream_with_clarification():
        # 构建初始 state
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
            skip_clarify=req.skip_clarify,
            iteration_count=0,
            next_action="search",
            clarification_message=None,
            clarification_options=None,
            loop_detected=None,
            loop_hint=None,
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
            return

        # 正常返回：流式输出答案
        answer = result.get("answer", "")
        for i in range(0, len(answer), 4):
            chunk = answer[i : i + 4]
            yield {
                "event": "message",
                "data": json.dumps({"type": "token", "data": chunk}, ensure_ascii=False)
            }

        # 返回完成事件
        msg_id = add_message(
            session_id,
            "assistant",
            answer,
            citations=result.get("citations", []),
            sources=result.get("sources", []),
        )

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
                    "loop_detected": result.get("loop_detected"),
                    "loop_hint": result.get("loop_hint"),
                }
            }, ensure_ascii=False)
        }

    return EventSourceResponse(stream_with_clarification())
```

**3.3 新增 API 端点**

- 文件: `scripts/api/routers/ask.py`
- 操作: 新增

```python
from fastapi import HTTPException

@router.get("/sessions/{session_id}/context")
async def get_session_context_endpoint(session_id: str):
    """获取会话上下文"""
    from api.database import get_session_context
    ctx = get_session_context(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "context": ctx}


@router.put("/sessions/{session_id}/context")
async def update_session_context_endpoint(session_id: str, context: dict):
    """更新会话上下文（澄清选择后调用）"""
    from api.database import save_session_context, get_session_context

    # 合并现有上下文
    existing = get_session_context(session_id) or {}
    merged = {**existing, **context}

    success = save_session_context(session_id, merged)
    if not success:
        raise HTTPException(status_code=500, detail="保存失败")

    return {"session_id": session_id, "context": merged}
```

**3.4 测试**

- 文件: `scripts/tests/lib/rag_engine/test_graph_multi_turn.py`
- 操作: 新增

```python
"""多轮对话工作流测试"""
import pytest
from unittest.mock import MagicMock, patch


def test_load_context_node():
    """验证 load_context 加载上下文和历史"""
    from lib.rag_engine.graph import create_ask_graph, AskState, GraphContext

    # Mock 依赖
    memory_svc = MagicMock()
    memory_svc.get_user_profile.return_value = None
    engine = MagicMock()
    engine.search.return_value = []
    engine.config.generation.max_context_chars = 12000
    llm = MagicMock()

    context = GraphContext(rag_engine=engine, llm_client=llm, memory_service=memory_svc)

    with patch("api.database.get_messages") as mock_get_messages, \
         patch("api.database.get_session_context") as mock_get_ctx:
        mock_get_messages.return_value = [
            {"role": "user", "content": "重疾险等待期"},
            {"role": "assistant", "content": "等待期是180天"},
        ]
        mock_get_ctx.return_value = {"product_type": "重疾险"}

        graph = create_ask_graph()
        state = AskState(
            question="犹豫期呢？",
            mode="qa",
            user_id="test",
            session_id="test_session",
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
            skip_clarify=True,
            iteration_count=0,
            next_action="search",
            clarification_message=None,
            clarification_options=None,
            loop_detected=None,
            loop_hint=None,
        )

        result = graph.invoke(state, context=context)

        # 验证上下文加载
        assert result.get("session_context", {}).get("product_type") == "重疾险"
        # 验证历史加载
        assert len(result.get("messages", [])) >= 2


def test_rag_search_with_context_enhancement():
    """验证 rag_search 用 product_type 增强查询"""
    from lib.rag_engine.graph import AskState, GraphContext
    from langgraph.runtime import Runtime

    engine = MagicMock()
    engine.search.return_value = [{"content": "test"}]
    llm = MagicMock()
    memory_svc = MagicMock()

    context = Runtime(context=GraphContext(
        rag_engine=engine,
        llm_client=llm,
        memory_service=memory_svc,
    ))

    state = AskState(
        question="犹豫期呢？",
        mode="qa",
        user_id="test",
        session_id="test",
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
        session_context={"product_type": "重疾险"},
        skip_clarify=True,
        iteration_count=0,
        next_action="search",
        clarification_message=None,
        clarification_options=None,
        loop_detected=None,
        loop_hint=None,
    )

    # 调用 rag_search 节点函数
    from lib.rag_engine.graph import rag_search
    result = rag_search(state, runtime=context)

    # 验证查询增强
    engine.search.assert_called_once()
    called_query = engine.search.call_args[0][0]
    assert "重疾险" in called_query
    assert "犹豫期" in called_query
```

---

### Phase 4: 增强功能 - User Story 5 (P2)

**目标**：实现循环检测和干预提示。

#### 需求回溯

→ 对应 spec.md User Story 5: 自动循环干预

#### 实现步骤

**4.1 集成 LoopDetectionMiddleware**

已在 Phase 2 实现，Phase 3 已集成到 `generate` 节点。

**4.2 前端显示 loop_hint**

- 文件: 前端代码（不在本项目范围）

**4.3 测试**

已在 Phase 2 测试覆盖。

---

## Complexity Tracking

无违反项。所有设计遵循简单优先原则。

---

## Appendix

### 执行顺序建议

```
Phase 1 (基础设施) ──► Phase 2 (中间件) ──► Phase 3 (工作流重构) ──► Phase 4 (增强)
     │                     │                      │                    │
     │                     │                      │                    │
     └─────────────────────┴──────────────────────┴────────────────────┘
         数据库 + State         中间件实现          节点重构            循环检测
```

**推荐顺序**：Phase 1 → Phase 2 → Phase 3 → Phase 4（串行依赖）

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 澄清式问答 | 模糊问题返回 clarify 事件，用户选择后准确检索 | `test_clarification_flow` |
| US-2 追问上下文 | "犹豫期呢？" 检索词包含"重疾险" | `test_rag_search_with_context_enhancement` |
| US-3 中断恢复 | 会话历史和上下文完整恢复 | `test_load_context_node` |
| US-5 循环检测 | 连续相似问题触发 loop_hint | `test_detects_loop` |

### 工作量估算

| Phase | 工作量 |
|-------|--------|
| Phase 1 | 1 天 |
| Phase 2 | 1.5 天 |
| Phase 3 | 2 天 |
| Phase 4 | 0.5 天 |
| **总计** | **5 天** |
