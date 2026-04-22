# 记忆系统深度 Review - 技术调研报告

生成时间: 2026-04-22
源规格: .claude/specs/019-memory-review/spec.md

## 执行摘要

本次调研深入分析了记忆系统的存储、检索、更新、删除四个维度，共识别 **15 个问题**（3 Critical、5 Major、7 Minor）。

核心风险：**LanceDB + SQLite 双写无事务保证**，可能导致数据不一致；**关键词触发词表过小**，影响检索召回率；**画像与记忆分离**，缺乏同步机制。

---

## 一、存储架构分析

### 1.1 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                     MemoryService (门面)                     │
├────────────────────────────┬────────────────────────────────┤
│     LanceDB (向量存储)      │   SQLite (元数据存储)          │
│  - vector: float32[1024]   │   - memory_metadata 表         │
│  - id, text, metadata      │   - user_profiles 表           │
│  - user_id, agent_id       │   - TTL, access_count          │
└────────────────────────────┴────────────────────────────────┘
```

### 1.2 问题清单

#### ❌ P0-CRITICAL-001: 双写无事务保证

**位置**: `lib/memory/service.py:66-68`

```python
ids = self._backend.add(messages, user_id, metadata=metadata or {}, run_id=session_id)
for mid in ids:
    self._insert_metadata(mid, user_id, metadata)  # 可能失败
```

**问题**:
1. LanceDB 写入成功后，SQLite 写入可能失败
2. 失败后 LanceDB 中存在孤儿向量，但 SQLite 无记录
3. 后续检索可能找到向量，但无 TTL/访问统计元数据

**影响**: 数据不一致，可能导致检索异常或清理失效

**建议**:
- 方案A: 改为先写 SQLite，成功后再写 LanceDB，失败时回滚 SQLite
- 方案B: 引入后台任务定期检测孤儿向量
- 方案C: 使用单存储（LanceDB 存储全部元数据）

---

#### ❌ P0-CRITICAL-002: 删除操作部分失败导致状态不一致

**位置**: `lib/memory/service.py:74-83`

```python
def delete(self, memory_id: str) -> bool:
    try:
        self._backend.delete(memory_id)       # 1. LanceDB 删除
        self._soft_delete_metadata(memory_id) # 2. SQLite 软删除
        return True
    except Exception:
        return False
```

**问题**:
1. 如果步骤 1 成功但步骤 2 失败 → LanceDB 已删除，SQLite 仍标记为活跃
2. 如果步骤 1 失败但步骤 2 成功 → LanceDB 存在孤儿向量，SQLite 标记已删除

**影响**: 存储膨胀或元数据脏数据

**建议**: 先软删除 SQLite，成功后再删除 LanceDB

---

#### ❌ P0-CRITICAL-003: WHERE 子句拼接存在注入风险

**位置**: `lib/memory/vector_store.py:83-84`

```python
parts.append(f"{k} = '{v}'")  # v 直接拼接
```

**问题**: 虽然当前调用来自内部代码，但缺少输入验证

**影响**: 如果 user_id 来自用户输入，可能被注入

**建议**: 使用参数化查询或验证 user_id 格式

---

#### ⚠️ P1-MAJOR-001: payload 突变副作用

**位置**: `lib/memory/vector_store.py:67-68`

```python
@staticmethod
def _to_row(vector: List[float], doc_id: str, payload: Dict) -> Dict[str, Any]:
    filter_vals = {k: payload.pop(k, "") for k in _FILTER_COLUMNS}  # 突变!
```

**问题**: `payload.pop()` 会修改传入的字典，调用方后续使用 payload 时可能缺失字段

**影响**: 难以追踪的 bug

**建议**: 改为 `payload.get(k, "")` 或先 `copy()`

---

## 二、检索策略分析

### 2.1 触发机制流程

```
用户问题
    │
    ▼
┌─────────────────────────────────────┐
│ should_retrieve_memory()            │
│                                     │
│ 1. TOPIC_KEYWORDS (6词) ──► 触发    │
│ 2. COMPANY_KEYWORDS (6词) ──► 触发  │
│ 3. mentioned_entities ──► 触发      │
│ 4. current_topic ──► 触发           │
│ 5. 时间间隔 > 60s ──► 触发          │
│                                     │
│ 全部不满足 ──► 跳过检索              │
└─────────────────────────────────────┘
    │
    ▼
Mem0Memory.search() ──► 语义向量检索
    │
    ▼
compress_memory_context() ──► 按 score 排序截断
```

### 2.2 问题清单

#### ⚠️ P1-MAJOR-002: 关键词触发词表过小

**位置**: `lib/common/middleware.py:78-84`

```python
TOPIC_KEYWORDS = frozenset({
    "等待期", "犹豫期", "保费", "保额",
    "免责", "理赔", "保单", "续保"
})  # 仅 8 个词

COMPANY_KEYWORDS = frozenset({"泰康", "平安", "国寿", "太保", "新华", "人保"})  # 仅 6 个公司
```

**问题**:
1. 保险行业术语远不止 8 个（如：核保、保全、现金价值、犹豫期后退保...）
2. 保险公司不止 6 家（如：友邦、中意、光大永明...）
3. 用户新词汇不在词表中会导致漏召回

**影响**: 检索召回率低，用户相关问题无法触发记忆检索

**建议**:
- 扩展词表至 50+ 核心术语
- 支持配置文件动态加载
- 考虑 NER 或规则匹配增强

---

#### ⚠️ P1-MAJOR-003: 重复判定阈值硬编码

**位置**: `lib/memory/service.py:61`

```python
if score is not None and score > 0.9:
    logger.debug(f"跳过重复记忆: {query[:50]}")
    return []
```

**问题**:
1. 阈值 0.9 硬编码，无法根据业务调整
2. 不同 embedding 模型的相似度分布不同
3. 语义相似但业务不同的场景可能被误去重

**场景示例**:
- 用户问 "等待期是多少" → 记录 "等待期 90 天"
- 用户问 "等待期可以延长吗" → score 可能 > 0.9，被跳过

**影响**: 用户真实需求被误判为重复

**建议**: 配置化阈值，或根据记忆类型区分

---

#### ⚠️ P1-MAJOR-004: LLM 提取失败静默跳过

**位置**: `lib/memory/service.py:180-182`

```python
except Exception:
    logger.debug("用户画像自动提取失败，跳过", exc_info=True)
    return  # 静默返回，调用方无感知
```

**问题**:
1. 失败只打印 debug 日志，生产环境可能不输出
2. 无法追踪画像更新失败率
3. 无法识别系统性问题（如 LLM 配置错误）

**影响**: 画像系统可能完全失效而不被发现

**建议**:
- 增加指标统计（成功/失败计数）
- 失败率达到阈值时告警
- 返回结果中包含状态

---

#### ⚠️ P1-MAJOR-005: 画像与记忆分离无同步

**位置**:
- `lib/memory/service.py:121-139` (get_user_profile)
- `lib/memory/service.py:168-214` (update_user_profile)

**问题**:
1. `user_profiles` 表存储用户画像
2. `memory_metadata` 表存储记忆元数据
3. 两者独立更新，无同步机制

**场景示例**:
- 用户说 "我对重疾险不感兴趣了，改关注医疗险"
- 画像可能更新，但历史记忆仍包含重疾险内容
- 检索时仍会召回重疾险相关记忆

**影响**: 记忆内容与用户当前偏好不一致

**建议**:
- 画像更新时考虑关联记忆
- 检索时结合画像权重调整召回

---

#### 💡 P2-MINOR-001: 时间间隔触发可能过于频繁

**位置**: `lib/memory/triggers.py:54`

```python
if time.time() - last_retrieve_time > interval_seconds:  # 默认 60s
    return TriggerResult(True, "interval", (), 0.5)
```

**问题**: 60 秒后任何问题都会触发记忆检索

**影响**: 可能增加不必要的向量检索开销

**建议**: 可考虑提高到 5 分钟，或仅在相关问题触发

---

#### 💡 P2-MINOR-002: session_context 状态易丢失

**位置**: `lib/rag_engine/graph.py:144`

```python
ctx["_last_memory_retrieve"] = time.time()
```

**问题**:
1. `_last_memory_retrieve` 存在内存中的 session_context
2. 服务重启后状态丢失
3. 下次请求会重新触发检索（实际可能是好事）

**影响**: 轻微，但需了解行为

---

## 三、更新机制分析

### 3.1 记忆写入流程

```
用户对话
    │
    ▼
extract_memory() ──► add()
    │                    │
    │                    ▼
    │              检查重复 (score > 0.9)
    │                    │
    │                    ▼ (不重复)
    │              Mem0Memory.add() ──► Mem0 LLM 提取事实
    │                    │
    │                    ▼
    │              LanceDB 写入向量
    │                    │
    │                    ▼
    │              SQLite 写入元数据
    │
    ▼
update_user_profile() ──► LLM 提取画像
    │
    ▼
SQLite 写入 user_profiles
```

### 3.2 问题清单

#### 💡 P2-MINOR-003: 置信度阈值缺乏依据

**位置**: `lib/memory/service.py:185`

```python
if confidence < 0.6:
    logger.debug(f"跳过低置信度画像更新: confidence={confidence}")
    return
```

**问题**: 阈值 0.6 来源不明，无评估数据支持

**影响**: 可能误判边界情况

**建议**: 通过评估数据调优阈值

---

#### 💡 P2-MINOR-004: 宽松的 JSON 解析

**位置**: `lib/memory/service.py:176-179`

```python
if text.startswith("```"):
    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    text = text.rsplit("```", 1)[0] if "```" in text else text
extracted = json.loads(text)
```

**问题**: Markdown 代码块处理逻辑不够健壮

**场景示例**:
- LLM 返回 ` ```json\n{...}\n``` `
- 当前逻辑可能解析失败

**建议**: 使用正则提取 JSON 块

---

## 四、删除策略分析

### 4.1 清理机制流程

```
app.py: _memory_cleanup_loop() (每 24h)
    │
    ▼
cleanup_expired()
    │
    ├─── 查询过期记忆 (expires_at < now)
    │         │
    │         ▼
    │    _purge_memories() ──► 删除 LanceDB + 软删除 SQLite
    │
    └─── 查询不活跃记忆 (60 天未访问 + access_count = 0)
              │
              ▼
         _purge_memories()
```

### 4.2 问题清单

#### 💡 P2-MINOR-005: 清理任务启动后 24h 才首次执行

**位置**: `scripts/api/app.py:136-137`

```python
async def _memory_cleanup_loop():
    while True:
        await asyncio.sleep(86400)  # 先 sleep，再清理
        svc = get_memory_service()
        ...
```

**问题**: 服务启动后需要等待 24 小时才执行首次清理

**影响**: 服务重启后，过期记忆堆积 24 小时

**建议**: 启动时立即执行一次清理

---

#### 💡 P2-MINOR-006: TTL 固定 30 天无法区分重要性

**位置**: `lib/memory/service.py:15`

```python
MEMORY_TTL_DAYS = 30  # 所有记忆统一 TTL
```

**问题**: 无法区分重要/不重要记忆

**场景示例**:
- 用户明确表达的偏好 → 应长期保留
- 临时问题上下文 → 可短期过期

**建议**: 支持按 category 设置不同 TTL

---

#### 💡 P2-MINOR-007: cleanup 不重试失败项

**位置**: `lib/memory/service.py:223-224`

```python
except Exception:
    logger.debug(f"清理记忆失败: {mem_id}", exc_info=True)
    # 继续下一条，不重试
```

**问题**: 单条清理失败后继续，可能导致部分记忆永久堆积

**影响**: 少量孤儿数据

**建议**: 记录失败 ID，下次 cleanup 优先重试

---

## 五、数据流与状态管理

### 5.1 完整数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                         LangGraph 工作流                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  load_session_context()  ──►  从 SQLite 加载 session_context        │
│           │                                                         │
│           ▼                                                         │
│  clarify_user_query()    ──►  澄清检测 + 循环检测                    │
│           │                                                         │
│           ▼                                                         │
│  retrieve_memory()       ──►  触发判断 → 语义检索 → 压缩上下文       │
│           │                                                         │
│           ▼                                                         │
│  rag_search()            ──►  RAG 知识库检索                        │
│           │                                                         │
│           ▼                                                         │
│  generate()              ──►  LLM 生成回答                          │
│           │                                                         │
│           ▼                                                         │
│  extract_memory()        ──►  写入记忆 (LanceDB + SQLite)           │
│           │                                                         │
│           ▼                                                         │
│  update_user_profile()   ──►  更新用户画像                          │
│           │                                                         │
│           ▼                                                         │
│  save_session_context()  ──►  保存到 SQLite                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 未使用字段

#### 💡 P2-MINOR-008: audit_stats 字段未使用

**位置**: `scripts/api/database.py:328`

```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    focus_areas TEXT DEFAULT '[]',
    preference_tags TEXT DEFAULT '[]',
    audit_stats TEXT DEFAULT '{}',  -- 从未使用
    summary TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```

**问题**: `audit_stats` 字段从未被写入或读取

**影响**: 死代码，增加维护成本

**建议**: 移除或实现功能

---

## 六、问题汇总

| ID | 严重程度 | 问题 | 位置 | 影响 |
|----|---------|------|------|------|
| P0-CRITICAL-001 | Critical | 双写无事务保证 | service.py:66-68 | 数据不一致 |
| P0-CRITICAL-002 | Critical | 删除部分失败状态不一致 | service.py:74-83 | 存储膨胀 |
| P0-CRITICAL-003 | Critical | WHERE 子句拼接注入风险 | vector_store.py:83-84 | 安全隐患 |
| P1-MAJOR-001 | Major | payload 突变副作用 | vector_store.py:67-68 | 难以追踪 bug |
| P1-MAJOR-002 | Major | 关键词触发词表过小 | middleware.py:78-84 | 检索召回率低 |
| P1-MAJOR-003 | Major | 重复判定阈值硬编码 | service.py:61 | 误去重 |
| P1-MAJOR-004 | Major | LLM 提取失败静默跳过 | service.py:180-182 | 画像系统可能失效 |
| P1-MAJOR-005 | Major | 画像与记忆分离无同步 | service.py | 记忆与偏好不一致 |
| P2-MINOR-001 | Minor | 时间间隔触发过于频繁 | triggers.py:54 | 不必要检索 |
| P2-MINOR-002 | Minor | session_context 状态易丢失 | graph.py:144 | 轻微影响 |
| P2-MINOR-003 | Minor | 置信度阈值缺乏依据 | service.py:185 | 边界误判 |
| P2-MINOR-004 | Minor | 宽松的 JSON 解析 | service.py:176-179 | 解析失败 |
| P2-MINOR-005 | Minor | 清理任务启动后 24h 才首次执行 | app.py:136-137 | 过期记忆堆积 |
| P2-MINOR-006 | Minor | TTL 固定无法区分重要性 | service.py:15 | 重要性无区分 |
| P2-MINOR-007 | Minor | cleanup 不重试失败项 | service.py:223-224 | 少量孤儿数据 |
| P2-MINOR-008 | Minor | audit_stats 字段未使用 | database.py:328 | 死代码 |

---

## 七、改进建议优先级

### 第一优先级（Critical）

1. **解决双写一致性问题**
   - 短期：先写 SQLite，成功后写 LanceDB，失败回滚
   - 长期：考虑单存储架构或引入分布式事务

2. **修复 WHERE 子句注入风险**
   - 添加 user_id 格式验证（UUID 或字母数字）

### 第二优先级（Major）

3. **扩展触发词表**
   - 收集保险行业核心术语 50+
   - 支持配置文件动态加载

4. **配置化重复判定阈值**
   - 移至 settings.json

5. **画像更新失败指标化**
   - 添加 Prometheus 指标

### 第三优先级（Minor）

6. **清理任务启动时立即执行**
7. **支持按 category 设置 TTL**
8. **移除未使用的 audit_stats 字段**

---

## 八、测试覆盖评估

| 模块 | 测试文件 | 覆盖率评估 |
|------|---------|-----------|
| MemoryService | test_service.py | 良好，覆盖主流程和异常 |
| Triggers | test_triggers.py | 良好，覆盖所有触发类型 |
| Graph | test_graph.py | 良好，覆盖工作流节点 |
| VectorStore | 无 | **缺失** |

**建议**: 为 LanceDBMemoryStore 添加单元测试

---

## 九、下一步行动

1. **立即处理** P0-CRITICAL-003（注入风险）
2. **短期规划** 解决 P0-CRITICAL-001/002（双写一致性）
3. **中期优化** 扩展触发词表、配置化阈值
4. **长期改进** 考虑单存储架构或引入消息队列保证最终一致性
