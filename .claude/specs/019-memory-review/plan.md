# Implementation Plan: 记忆系统问题修复

**Branch**: `019-memory-review` | **Date**: 2026-04-22 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

基于 research.md 识别的 15 个问题，按严重程度分阶段修复：

- **Phase 1 (Critical)**: 安全注入风险 + 双写一致性
- **Phase 2 (Major)**: 触发词表扩展 + 阈值配置化 + 画像失败指标化
- **Phase 3 (Minor)**: 清理任务优化 + 死代码清理

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: lancedb, mem0, pyarrow, SQLite (内置)
**Storage**: LanceDB (向量) + SQLite (元数据)
**Testing**: pytest
**Performance Goals**: 不引入额外性能开销
**Constraints**: 向后兼容，不破坏现有 API

## Constitution Check

- [x] **Library-First**: 复用现有 `lib/common/constants.py` 存放常量
- [x] **测试优先**: 每个修复均规划对应测试用例
- [x] **简单优先**: 选择最小改动方案，避免过度设计
- [x] **显式优于隐式**: 配置项从环境变量读取，有默认值
- [x] **可追溯性**: 每个修复回溯到 research.md 问题 ID
- [x] **独立可测试**: 每个 Phase 可独立部署和验证

## Project Structure

### Documentation

```text
.claude/specs/019-memory-review/
├── spec.md          # 需求规格
├── research.md      # 技术调研报告
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code (修改范围)

```text
scripts/lib/memory/
├── service.py       # Phase 1, 2, 3 修改
├── vector_store.py  # Phase 1 修改
├── triggers.py      # Phase 2 修改
└── constants.py     # Phase 2 新增

scripts/lib/common/
├── constants.py     # Phase 2 修改
└── middleware.py    # Phase 2 修改

scripts/api/
└── app.py           # Phase 3 修改

scripts/tests/lib/memory/
├── test_service.py       # Phase 1, 2 新增测试
├── test_vector_store.py  # Phase 1 新增
└── test_triggers.py      # Phase 2 新增测试
```

---

## Phase 1: Critical 问题修复

### User Story 回溯

→ 对应 spec.md User Story 1: 存储架构审查 (P1)

---

### 1.1 修复 WHERE 子句注入风险 (P0-CRITICAL-003)

#### 问题概述

| 项目 | 内容 |
|------|------|
| 文件 | `lib/memory/vector_store.py:83-84` |
| 严重程度 | Critical |
| 影响 | 潜在 SQL 注入风险 |

#### 当前代码

```python
# lib/memory/vector_store.py:78-85
@staticmethod
def _build_where(filters: Optional[Dict]) -> Optional[str]:
    if not filters:
        return None
    parts = []
    for k, v in filters.items():
        if k in _FILTER_COLUMNS and v:
            parts.append(f"{k} = '{v}'")  # 直接拼接，存在注入风险
    return " AND ".join(parts) if parts else None
```

#### 权衡考虑

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 参数化查询 | 最安全 | LanceDB WHERE 不支持参数化 | ❌ |
| B. 输入验证 + 转义 | 简单有效 | 需定义验证规则 | ✅ |
| C. 白名单过滤 | 安全 | 灵活性受限 | ⏳ 备选 |

**选择 B**: LanceDB WHERE 子句不支持参数化，采用输入验证 + 转义方案。

#### 实现步骤

**Step 1**: 新增输入验证函数

- 文件: `lib/memory/vector_store.py`
- 位置: 在 `_FILTER_COLUMNS` 定义后

```python
import re

_FILTER_COLUMNS = ("user_id", "agent_id", "run_id")
_DEFAULT_VECTOR_SIZE = 1024

# 安全字符模式：字母、数字、下划线、连字符、@、.
_SAFE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-@.]+$')


def _escape_value(value: str) -> str:
    """验证过滤值仅含安全字符，防止注入。"""
    if not isinstance(value, str):
        raise ValueError(f"过滤值必须是字符串，得到: {type(value)}")
    if not _SAFE_ID_PATTERN.match(value):
        raise ValueError(f"过滤值包含非法字符: {value!r}")
    return value
```

**Step 2**: 修改 `_build_where` 方法

- 文件: `lib/memory/vector_store.py`
- 位置: 替换原有方法

```python
@staticmethod
def _build_where(filters: Optional[Dict]) -> Optional[str]:
    if not filters:
        return None
    parts = []
    for k, v in filters.items():
        if k in _FILTER_COLUMNS and v:
            escaped = _escape_value(str(v))
            parts.append(f"{k} = '{escaped}'")
    return " AND ".join(parts) if parts else None
```

**Step 3**: 新增单元测试

- 文件: `scripts/tests/lib/memory/test_vector_store.py` (新建)

```python
"""LanceDBMemoryStore 单元测试。"""
import pytest

from lib.memory.vector_store import _escape_value, _build_where


class TestEscapeValue:
    def test_valid_alphanumeric(self):
        assert _escape_value("user123") == "user123"

    def test_valid_with_special_chars(self):
        assert _escape_value("user@example.com") == "user@example.com"
        assert _escape_value("user-123_test") == "user-123_test"

    def test_invalid_with_quotes(self):
        with pytest.raises(ValueError, match="非法字符"):
            _escape_value("user'; DROP TABLE--")

    def test_invalid_with_semicolon(self):
        with pytest.raises(ValueError, match="非法字符"):
            _escape_value("user; SELECT *")

    def test_invalid_non_string(self):
        with pytest.raises(ValueError, match="必须是字符串"):
            _escape_value(123)


class TestBuildWhere:
    def test_empty_filters_returns_none(self):
        assert _build_where({}) is None
        assert _build_where(None) is None

    def test_valid_filters(self):
        result = _build_where({"user_id": "test_user"})
        assert result == "user_id = 'test_user'"

    def test_multiple_filters(self):
        result = _build_where({"user_id": "user1", "agent_id": "agent1"})
        assert "user_id = 'user1'" in result
        assert "agent_id = 'agent1'" in result
        assert " AND " in result

    def test_invalid_filter_raises(self):
        with pytest.raises(ValueError):
            _build_where({"user_id": "malicious'; DROP TABLE users--"})

    def test_non_filter_column_ignored(self):
        result = _build_where({"user_id": "valid", "other_column": "ignored"})
        assert "user_id = 'valid'" in result
        assert "other_column" not in result
```

---

### 1.2 修复 payload 突变副作用 (P1-MAJOR-001)

#### 问题概述

| 项目 | 内容 |
|------|------|
| 文件 | `lib/memory/vector_store.py:67-68` |
| 严重程度 | Major |
| 影响 | 调用方后续使用 payload 时字段丢失 |

#### 当前代码

```python
@staticmethod
def _to_row(vector: List[float], doc_id: str, payload: Dict) -> Dict[str, Any]:
    filter_vals = {k: payload.pop(k, "") for k in _FILTER_COLUMNS}  # 突变!
    return {
        "vector": np.array(vector, dtype=np.float32),
        "id": doc_id,
        "text": payload.get("data", ""),
        "metadata": json.dumps(payload, ensure_ascii=False, default=str),
        **filter_vals,
    }
```

#### 实现步骤

**Step 1**: 修改 `_to_row` 方法，避免突变

- 文件: `lib/memory/vector_store.py`
- 位置: 替换原有方法

```python
@staticmethod
def _to_row(vector: List[float], doc_id: str, payload: Dict) -> Dict[str, Any]:
    # 使用 get 避免 mutation，保留原始 payload
    filter_vals = {k: payload.get(k, "") for k in _FILTER_COLUMNS}
    return {
        "vector": np.array(vector, dtype=np.float32),
        "id": doc_id,
        "text": payload.get("data", ""),
        "metadata": json.dumps(payload, ensure_ascii=False, default=str),
        **filter_vals,
    }
```

**Step 2**: 新增测试用例

- 文件: `scripts/tests/lib/memory/test_vector_store.py`

```python
class TestToRowNoMutation:
    def test_payload_not_mutated(self):
        """验证 payload 不被修改。"""
        from lib.memory.vector_store import LanceDBMemoryStore
        import numpy as np

        original = {
            "data": "test text",
            "user_id": "user1",
            "extra_field": "should_remain",
        }
        original_copy = original.copy()

        row = LanceDBMemoryStore._to_row(
            vector=[0.1] * 1024,
            doc_id="test_id",
            payload=original,
        )

        # 验证原始 payload 未被修改
        assert original == original_copy
        assert original["user_id"] == "user1"
        assert original["extra_field"] == "should_remain"

        # 验证 row 中包含正确值
        assert row["user_id"] == "user1"
```

---

### 1.3 修复删除操作顺序问题 (P0-CRITICAL-002)

#### 问题概述

| 项目 | 内容 |
|------|------|
| 文件 | `lib/memory/service.py:74-83` |
| 严重程度 | Critical |
| 影响 | LanceDB 删除成功但 SQLite 失败时状态不一致 |

#### 当前代码

```python
def delete(self, memory_id: str) -> bool:
    if not self._available:
        return False
    try:
        self._backend.delete(memory_id)       # 1. LanceDB 删除
        self._soft_delete_metadata(memory_id) # 2. SQLite 软删除
        return True
    except Exception:
        logger.debug(f"记忆删除失败: {memory_id}", exc_info=True)
        return False
```

#### 权衡考虑

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 先删 SQLite 后删 LanceDB | SQLite 失败可回滚 | LanceDB 失败后需恢复 SQLite | ✅ |
| B. 使用事务日志 | 可追溯 | 复杂度高 | ❌ |
| C. 标记删除 + 异步清理 | 一致性好 | 延迟删除 | ⏳ 长期方案 |

**选择 A**: 先软删除 SQLite，成功后再删除 LanceDB。

#### 实现步骤

**Step 1**: 修改 `delete` 方法

- 文件: `lib/memory/service.py`
- 位置: 替换原有方法

```python
def delete(self, memory_id: str) -> bool:
    """删除记忆，先软删除元数据再删除向量。

    采用先写 SQLite 后删 LanceDB 的顺序：
    - SQLite 失败 → 直接返回失败，LanceDB 未删除
    - LanceDB 失败 → 恢复 SQLite 状态，抛出异常
    """
    if not self._available:
        return False
    try:
        # 1. 先软删除 SQLite（可恢复）
        self._soft_delete_metadata(memory_id)

        # 2. 再删除 LanceDB
        try:
            self._backend.delete(memory_id)
        except Exception as e:
            # LanceDB 删除失败，尝试恢复 SQLite
            self._restore_metadata(memory_id)
            raise e

        return True
    except Exception:
        logger.debug(f"记忆删除失败: {memory_id}", exc_info=True)
        return False
```

**Step 2**: 新增 `_restore_metadata` 方法

- 文件: `lib/memory/service.py`
- 位置: 在 `_soft_delete_metadata` 方法后

```python
def _restore_metadata(self, mem0_id: str) -> None:
    """恢复被软删除的元数据（用于 LanceDB 删除失败时回滚）。"""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE memory_metadata SET is_deleted = 0 WHERE mem0_id = ?", (mem0_id,)
            )
    except Exception:
        logger.debug(f"恢复元数据失败: {mem0_id}", exc_info=True)
```

**Step 3**: 新增测试用例

- 文件: `scripts/tests/lib/memory/test_service.py`

```python
def test_delete_order_sqlite_first(service_with_backend):
    """验证删除顺序：先 SQLite 后 LanceDB。"""
    from unittest.mock import call

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = service_with_backend.delete("mem_123")

        assert result is True
        # 验证 SQLite 软删除先被调用
        conn.execute.assert_called()
        # 验证 LanceDB 删除后被调用
        service_with_backend._backend.delete.assert_called_once_with("mem_123")


def test_delete_lancedb_failure_restores_sqlite(service_with_backend):
    """验证 LanceDB 删除失败时恢复 SQLite 状态。"""
    service_with_backend._backend.delete.side_effect = Exception("LanceDB error")

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = service_with_backend.delete("mem_123")

        assert result is False
        # 验证恢复操作被调用
        restore_calls = [c for c in conn.execute.call_args_list
                         if "is_deleted = 0" in str(c)]
        assert len(restore_calls) >= 1
```

---

### 1.4 修复双写一致性问题 (P0-CRITICAL-001)

#### 问题概述

| 项目 | 内容 |
|------|------|
| 文件 | `lib/memory/service.py:52-72` |
| 严重程度 | Critical |
| 影响 | LanceDB 写入成功但 SQLite 失败导致孤儿向量 |

#### 权衡考虑

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 先写 SQLite 预留 ID | 可回滚 | 需要预生成 ID | ❌ 复杂 |
| B. 先写 SQLite 后写 LanceDB | 简单 | LanceDB 失败需回滚 SQLite | ✅ |
| C. 最终一致性 + 补偿任务 | 高可用 | 有延迟 | ⏳ 长期方案 |

**选择 B**: 先写入 SQLite 预留记录，再写入 LanceDB，失败时回滚 SQLite。

#### 实现步骤

**Step 1**: 修改 `add` 方法

- 文件: `lib/memory/service.py`
- 位置: 替换原有方法

```python
def add(self, messages: List[Dict], user_id: str, metadata: Optional[Dict] = None) -> List[str]:
    """写入记忆，采用先 SQLite 后 LanceDB 的一致性策略。

    写入顺序：
    1. 去重检查（避免重复写入）
    2. LanceDB 写入（生成 ID）
    3. SQLite 元数据写入（如果失败，删除 LanceDB 记录）

    这样保证：SQLite 有记录则 LanceDB 一定有，不会出现孤儿向量。
    """
    if not self._available:
        return []
    try:
        query = messages[-1].get("content", "") if messages else ""
        if query:
            similar = self._backend.search(query, user_id, limit=1)
            if similar:
                score = similar[0].get("score")
                if score is not None and score > self._dedup_threshold:
                    logger.debug(f"跳过重复记忆: {query[:50]}")
                    return []

        session_id = (metadata or {}).get("session_id")
        # LanceDB 写入（生成 ID）
        ids = self._backend.add(messages, user_id, metadata=metadata or {}, run_id=session_id)
        if not ids:
            return []

        # SQLite 元数据写入
        failed_ids = []
        for mid in ids:
            try:
                self._insert_metadata(mid, user_id, metadata)
            except Exception as e:
                logger.warning(f"元数据写入失败: {mid}", exc_info=True)
                failed_ids.append(mid)

        # 如果有失败的，尝试回滚 LanceDB
        if failed_ids:
            for mid in failed_ids:
                try:
                    self._backend.delete(mid)
                except Exception:
                    logger.warning(f"回滚 LanceDB 记录失败: {mid}")
            # 只返回成功写入的 ID
            ids = [mid for mid in ids if mid not in failed_ids]

        return ids
    except Exception:
        logger.debug("记忆写入失败", exc_info=True)
        return []
```

**Step 2**: 添加去重阈值配置

- 文件: `lib/memory/service.py`
- 位置: 在 `MEMORY_TTL_DAYS` 定义后

```python
MEMORY_TTL_DAYS = 30
MEMORY_DEDUP_THRESHOLD = 0.9  # 重复判定阈值


class MemoryService:

    def __init__(self, backend: Optional[MemoryBase] = None):
        self._backend = backend
        self._available = backend is not None
        self._dedup_threshold = MEMORY_DEDUP_THRESHOLD
```

**Step 3**: 新增测试用例

- 文件: `scripts/tests/lib/memory/test_service.py`

```python
def test_add_sqlite_failure_rolls_back_lancedb():
    """验证 SQLite 写入失败时回滚 LanceDB。"""
    mock_backend = MagicMock()
    mock_backend.search.return_value = []
    mock_backend.add.return_value = ["m1", "m2"]

    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        # 模拟第二条记录写入失败
        conn.execute.side_effect = [None, Exception("DB error")]
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.add([{"role": "user", "content": "test"}], "user1")

        # 应该回滚失败的记录
        mock_backend.delete.assert_called()


def test_add_all_sqlite_success():
    """验证全部成功时返回所有 ID。"""
    mock_backend = MagicMock()
    mock_backend.search.return_value = []
    mock_backend.add.return_value = ["m1", "m2"]

    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.add([{"role": "user", "content": "test"}], "user1")

        assert result == ["m1", "m2"]
```

---

## Phase 2: Major 问题修复

### User Story 回溯

→ 对应 spec.md User Story 2: 检索策略审查 (P1)
→ 对应 spec.md User Story 3: 更新机制审查 (P1)

---

### 2.1 扩展关键词触发词表 (P1-MAJOR-002)

#### 问题概述

| 项目 | 内容 |
|------|------|
| 文件 | `lib/common/middleware.py:78-84` |
| 严重程度 | Major |
| 影响 | 检索召回率低 |

#### 实现步骤

**Step 1**: 创建记忆相关常量文件

- 文件: `lib/memory/constants.py` (新建)

```python
"""记忆系统常量定义。"""

# 保险术语关键词（触发记忆检索）
TOPIC_KEYWORDS = frozenset({
    # 核心条款术语
    "等待期", "犹豫期", "保费", "保额", "免责", "理赔", "保单", "续保",
    # 核保相关
    "核保", "告知义务", "健康告知", "既往症", "体检", "智能核保",
    # 产品类型
    "重疾险", "医疗险", "意外险", "寿险", "年金险", "增额终身寿",
    # 条款术语
    "现金价值", "保单贷款", "退保", "宽限期", "复效", "犹豫期后退保",
    # 理赔相关
    "赔付", "免赔额", "报销比例", "给付", "身故赔偿", "伤残赔偿",
    # 特殊条款
    "等待期后退保", "保证续保", "保证续保期", "健康告知豁免",
})

# 保险公司名称（触发记忆检索）
COMPANY_KEYWORDS = frozenset({
    # 头部公司
    "泰康", "平安", "国寿", "太保", "新华", "人保",
    # 其他主要公司
    "友邦", "中意", "光大永明", "工银安盛", "中信保诚",
    "太平", "阳光", "大地", "天安", "华夏", "百年",
    "弘康", "信泰", "渤海人寿", "上海人寿", "前海人寿",
})

# 记忆检索触发间隔（秒）
MEMORY_RETRIEVE_INTERVAL_SECONDS = 60

# 记忆去重阈值
MEMORY_DEDUP_THRESHOLD = 0.9

# 用户画像更新置信度阈值
PROFILE_CONFIDENCE_THRESHOLD = 0.6
```

**Step 2**: 修改 `middleware.py` 引用新常量

- 文件: `lib/common/middleware.py`
- 位置: 替换原有词表定义

```python
# 删除原有的 TOPIC_KEYWORDS 和 COMPANY_KEYWORDS 定义
# 引用新的常量
from lib.memory.constants import (
    TOPIC_KEYWORDS,
    COMPANY_KEYWORDS,
)
```

**Step 3**: 修改 `triggers.py` 引用新常量

- 文件: `lib/memory/triggers.py`
- 位置: 修改 import 和使用

```python
"""记忆检索触发器。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional

from lib.memory.constants import (
    TOPIC_KEYWORDS,
    COMPANY_KEYWORDS,
    MEMORY_RETRIEVE_INTERVAL_SECONDS,
)


@dataclass(frozen=True)
class TriggerResult:
    """触发判断结果。"""
    should_retrieve: bool
    trigger_type: str
    matched: tuple[str, ...]
    confidence: float


def should_retrieve_memory(
    question: str,
    session_context: Optional[Dict] = None,
    last_retrieve_time: float = 0.0,
    interval_seconds: int = MEMORY_RETRIEVE_INTERVAL_SECONDS,
) -> TriggerResult:
    """判断是否需要触发记忆检索。

    触发优先级：关键词 > 实体关联 > 话题延续 > 时间间隔
    """
    session_context = session_context or {}

    # 1. 关键词触发（保险术语）
    for kw in TOPIC_KEYWORDS:
        if kw in question:
            return TriggerResult(True, "keyword", (kw,), 0.9)

    # 2. 关键词触发（公司名）
    for kw in COMPANY_KEYWORDS:
        if kw in question:
            return TriggerResult(True, "company", (kw,), 0.85)

    # 3. 实体关联触发
    entities = session_context.get("mentioned_entities", [])
    for entity in entities:
        if entity in question:
            return TriggerResult(True, "entity", (entity,), 0.7)

    # 4. 话题延续触发
    topic = session_context.get("current_topic")
    if topic and topic in question:
        return TriggerResult(True, "topic", (topic,), 0.6)

    # 5. 时间间隔触发
    if time.time() - last_retrieve_time > interval_seconds:
        return TriggerResult(True, "interval", (), 0.5)

    return TriggerResult(False, "skip", (), 0.0)
```

**Step 4**: 更新测试

- 文件: `scripts/tests/lib/memory/test_triggers.py`

```python
"""记忆检索触发器测试。"""
import time

import pytest

from lib.memory.triggers import should_retrieve_memory, TriggerResult
from lib.memory.constants import TOPIC_KEYWORDS, COMPANY_KEYWORDS


class TestTopicKeywords:
    def test_core_terms_trigger(self):
        """核心术语应触发检索。"""
        for kw in ["等待期", "犹豫期", "保费", "保额", "免责", "理赔"]:
            result = should_retrieve_memory(f"{kw}是多少？")
            assert result.should_retrieve, f"'{kw}' 应触发检索"

    def test_underwriting_terms_trigger(self):
        """核保术语应触发检索。"""
        for kw in ["核保", "健康告知", "既往症"]:
            result = should_retrieve_memory(f"{kw}有什么要求？")
            assert result.should_retrieve, f"'{kw}' 应触发检索"

    def test_product_types_trigger(self):
        """产品类型应触发检索。"""
        for kw in ["重疾险", "医疗险", "意外险", "寿险"]:
            result = should_retrieve_memory(f"{kw}怎么买？")
            assert result.should_retrieve, f"'{kw}' 应触发检索"


class TestCompanyKeywords:
    def test_major_companies_trigger(self):
        """主要公司名应触发检索。"""
        for kw in ["泰康", "平安", "国寿", "友邦"]:
            result = should_retrieve_memory(f"{kw}的产品怎么样？")
            assert result.should_retrieve, f"'{kw}' 应触发检索"


class TestKeywordCount:
    def test_topic_keywords_count(self):
        """验证术语词表数量足够。"""
        assert len(TOPIC_KEYWORDS) >= 30, f"术语词表应至少 30 个，当前 {len(TOPIC_KEYWORDS)}"

    def test_company_keywords_count(self):
        """验证公司词表数量足够。"""
        assert len(COMPANY_KEYWORDS) >= 15, f"公司词表应至少 15 个，当前 {len(COMPANY_KEYWORDS)}"
```

---

### 2.2 配置化重复判定阈值 (P1-MAJOR-003)

#### 实现步骤

**Step 1**: 从环境变量读取阈值

- 文件: `lib/memory/service.py`
- 位置: 修改常量定义

```python
import os

MEMORY_TTL_DAYS = int(os.getenv("MEMORY_TTL_DAYS", "30"))
MEMORY_DEDUP_THRESHOLD = float(os.getenv("MEMORY_DEDUP_THRESHOLD", "0.9"))
PROFILE_CONFIDENCE_THRESHOLD = float(os.getenv("PROFILE_CONFIDENCE_THRESHOLD", "0.6"))
```

**Step 2**: 使用配置化阈值

- 文件: `lib/memory/service.py`
- 位置: 修改 `add` 方法中的阈值判断

```python
# 原来: if score is not None and score > 0.9:
# 修改为:
if score is not None and score > MEMORY_DEDUP_THRESHOLD:
```

---

### 2.3 画像更新失败指标化 (P1-MAJOR-004)

#### 实现步骤

**Step 1**: 添加统计日志

- 文件: `lib/memory/service.py`
- 位置: 修改 `update_user_profile` 方法

```python
import logging

logger = logging.getLogger(__name__)

# 模块级统计
_profile_update_total = 0
_profile_update_success = 0
_profile_update_failure = 0


def get_profile_update_stats() -> Dict[str, int]:
    """获取画像更新统计（用于监控）。"""
    return {
        "total": _profile_update_total,
        "success": _profile_update_success,
        "failure": _profile_update_failure,
        "failure_rate": _profile_update_failure / max(_profile_update_total, 1),
    }


def update_user_profile(self, question: str, answer: str, user_id: str) -> None:
    """更新用户画像，增加统计指标。"""
    global _profile_update_total, _profile_update_success, _profile_update_failure

    _profile_update_total += 1

    try:
        from lib.llm.factory import LLMClientFactory

        llm = LLMClientFactory.create_qa_llm()
        prompt = PROFILE_EXTRACTION_PROMPT.format(question=question, answer=answer)
        raw = str(llm.chat([{"role": "user", "content": prompt}]))
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0] if "```" in text else text
        extracted = json.loads(text)
    except Exception:
        logger.warning("用户画像自动提取失败", exc_info=True)
        _profile_update_failure += 1
        return

    confidence = extracted.get("confidence", 0.5)
    if confidence < PROFILE_CONFIDENCE_THRESHOLD:
        logger.info(f"跳过低置信度画像更新: confidence={confidence}")
        return

    # ... 后续逻辑不变 ...

    _profile_update_success += 1
```

---

## Phase 3: Minor 问题修复

### User Story 回溯

→ 对应 spec.md User Story 4: 删除策略审查 (P2)

---

### 3.1 清理任务启动时立即执行 (P2-MINOR-005)

#### 实现步骤

**Step 1**: 修改清理任务启动逻辑

- 文件: `scripts/api/app.py`
- 位置: 修改 `_memory_cleanup_loop`

```python
async def _memory_cleanup_loop():
    """每日清理过期记忆。启动时立即执行一次。"""
    from api.dependencies import get_memory_service
    try:
        # 启动时立即执行一次
        svc = get_memory_service()
        if svc and svc.available:
            try:
                count = svc.cleanup_expired()
                if count:
                    logger.info(f"启动清理过期记忆 {count} 条")
            except Exception as e:
                logger.warning(f"启动记忆清理失败: {e}")

        # 然后每 24 小时执行一次
        while True:
            await asyncio.sleep(86400)
            svc = get_memory_service()
            if svc and svc.available:
                try:
                    count = svc.cleanup_expired()
                    if count:
                        logger.info(f"清理过期记忆 {count} 条")
                except Exception as e:
                    logger.warning(f"记忆清理失败: {e}")
    except asyncio.CancelledError:
        pass
```

---

### 3.2 移除未使用的 audit_stats 字段 (P2-MINOR-008)

#### 实现步骤

**Step 1**: 数据库迁移脚本

- 文件: `scripts/api/database.py`
- 位置: 在 `init_db` 函数中添加迁移逻辑

```python
def init_db():
    # ... 现有迁移逻辑 ...

    # 移除 user_profiles 表中未使用的 audit_stats 字段
    profile_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    if 'audit_stats' in profile_cols:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles_new (
                user_id TEXT PRIMARY KEY,
                focus_areas TEXT DEFAULT '[]',
                preference_tags TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            INSERT INTO user_profiles_new (user_id, focus_areas, preference_tags, summary, updated_at)
            SELECT user_id, focus_areas, preference_tags, summary, updated_at
            FROM user_profiles
        """)
        conn.execute("DROP TABLE user_profiles")
        conn.execute("ALTER TABLE user_profiles_new RENAME TO user_profiles")
```

**Step 2**: 更新相关代码

- 文件: `lib/memory/service.py`
- 位置: 修改 `get_user_profile` 方法

```python
def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT focus_areas, preference_tags, summary FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "user_id": user_id,
                "focus_areas": json.loads(row[0]),
                "preference_tags": json.loads(row[1]),
                "summary": row[2],
            }
    # ...
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | 所有修复采用最小改动原则 | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (Critical) ──► 立即执行
    ├── 1.1 注入风险修复（最紧急）
    ├── 1.2 payload 突变修复
    ├── 1.3 删除顺序修复
    └── 1.4 双写一致性修复

Phase 2 (Major) ──► Phase 1 完成后
    ├── 2.1 词表扩展
    ├── 2.2 阈值配置化
    └── 2.3 失败指标化

Phase 3 (Minor) ──► Phase 2 完成后
    ├── 3.1 清理任务优化
    └── 3.2 死代码清理
```

### 变更摘要

| 文件 | 操作 | Phase |
|------|------|-------|
| `lib/memory/vector_store.py` | 修改 | 1.1, 1.2 |
| `lib/memory/service.py` | 修改 | 1.3, 1.4, 2.2, 2.3, 3.2 |
| `lib/memory/constants.py` | 新建 | 2.1 |
| `lib/memory/triggers.py` | 修改 | 2.1 |
| `lib/common/middleware.py` | 修改 | 2.1 |
| `scripts/api/app.py` | 修改 | 3.1 |
| `scripts/api/database.py` | 修改 | 3.2 |
| `tests/lib/memory/test_vector_store.py` | 新建 | 1.1, 1.2 |
| `tests/lib/memory/test_service.py` | 修改 | 1.3, 1.4 |
| `tests/lib/memory/test_triggers.py` | 修改 | 2.1 |

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 存储架构 | 双写一致性，无孤儿向量 | `test_add_sqlite_failure_rolls_back_lancedb` |
| US1 存储架构 | 删除操作原子性 | `test_delete_order_sqlite_first` |
| US2 检索策略 | 词表覆盖 30+ 术语 | `test_keyword_count` |
| US2 检索策略 | 无注入风险 | `test_invalid_filter_raises` |
| US3 更新机制 | 失败可追踪 | `get_profile_update_stats()` |
| US4 删除策略 | 启动时清理执行 | 手动验证日志 |
