# LLM Trace Debug 面板 — 实施方案

生成时间: 2026-04-03
源文档: brainstorm 设计讨论

---

## 一、后端：Trace 基础设施

### 任务 1.1: 创建 TraceSpan 模型和 contextvars 传播 ✅

**文件**: `scripts/lib/llm/trace.py`（新建）

- TraceSpan dataclass：span_id, trace_id, parent_span_id, name, category, input, output, metadata, start_time, end_time, error, children
- `trace_span` 上下文管理器：用 contextvars 传播 trace 上下文，自动构建调用树
- `get_current_trace()` 获取当前根 span
- `get_trace_dict()` 序列化为 dict
- `iter_spans()` 扁平迭代所有 span（用于持久化）
- category 枚举：llm, retrieval, preprocessing, rerank, root

---

### 任务 1.2: 创建 traces/spans 数据库表和 API ✅

**文件**: `scripts/api/database.py`（修改）

- 新增 `traces` 表：trace_id, message_id, created_at
- 新增 `spans` 表：trace_id, span_id, parent_span_id, name, category, input_json, output_json, metadata_json, start_time, end_time, duration_ms, status, error
- 新增 `save_trace(trace_id, message_id)` 函数
- 新增 `save_span(...)` 函数（逐 span 写入）
- 新增 `get_trace(message_id)` 函数（从 spans 行重建树）

**文件**: `scripts/api/routers/ask.py`（修改）

- 新增 `GET /api/ask/messages/{message_id}/trace` 端点

---

## 二、后端：LLM 调用点埋点

### 任务 2.1: query_preprocessor 埋点 ✅

**文件**: `scripts/lib/rag_engine/query_preprocessor.py`（修改）

- `_rewrite_with_llm()` 用 `trace_span("query_rewrite", "preprocessing")` 包裹
- 记录 input（原始 query）、output（改写后 query）、metadata（model）、error

---

### 任务 2.2: hybrid_search 拆分埋点 ✅

**文件**: `scripts/lib/rag_engine/retrieval.py`（修改）

- `vector_search()` 用 `trace_span("vector_search", "retrieval")` 包裹
- 记录 input（query, top_k）、output（结果数量）

---

### 任务 2.3: reranker 埋点 ✅

**文件**: `scripts/lib/rag_engine/llm_reranker.py`（修改）

- `_batch_rank()` 用 `trace_span("llm_rerank", "rerank")` 包裹
- 记录 input（query, candidates 数量）、output（ranked indices）、metadata（model, candidate_count）、error

---

### 任务 2.4: LLM 生成埋点 ✅

**文件**: `scripts/lib/rag_engine/rag_engine.py`（修改）

- `_do_ask()` 中 `llm_client.chat()` 调用用 `trace_span("llm_generate", "llm")` 包裹
- 记录 input（question, context_chunk_count）、output（answer_length）、metadata（model_name）

---

### 任务 2.5: SSE 推送 trace + 持久化 ✅

**文件**: `scripts/api/routers/ask.py`（修改）

- `done` 事件增加 `trace` 字段（summary + spans 列表）
- 通过 `_persist_trace()` 逐 span 写入数据库
- 新增 `_build_trace_summary()` 构建 SSE 推送数据

---

## 三、前端：Trace 面板

### 任务 3.1: 定义 Trace 类型 ✅

**文件**: `scripts/web/src/types/index.ts`（修改）

- 新增 `TraceSpan` 接口
- 新增 `TraceSummary` 接口
- 新增 `TraceData` 接口（根 span + 汇总指标 + 扁平 spans 列表）

---

### 任务 3.2: askStore 扩展 trace 管理 ✅

**文件**: `scripts/web/src/stores/askStore.ts`（修改）

- 新增 `debugOpen` 状态（持久化到 localStorage）
- 新增 `toggleDebug()` action
- 新增 `currentTrace: TraceData | null` 状态
- `onDone` 回调中接收 trace 数据并构建 TraceData
- 新增 `fetchTrace(messageId)` action 用于加载历史 trace

---

### 任务 3.3: 创建 TracePanel 组件 ✅

**文件**: `scripts/web/src/components/TracePanel.tsx`（新建）

- 可折叠面板，显示总耗时、span 数量、LLM 调用次数
- Timeline 渲染 span 树（按 parent_span_id 构建层级）
- 每个 span 可展开查看 input/output/error
- 错误 span 红色高亮 + CloseCircleOutlined
- category 彩色标签（preprocessing=紫, retrieval=蓝, rerank=橙, llm=绿）

---

### 任务 3.4: ChatPanel 集成 Debug 开关和 TracePanel ✅

**文件**: `scripts/web/src/components/ChatPanel.tsx`（修改）

- 底部输入区旁添加 Debug 开关按钮（BugOutlined icon + Tooltip）
- Debug 开启时在消息区下方显示 TracePanel
- 点击历史助手消息时加载对应 trace

---

### 任务 3.5: ask API 扩展 trace 端点 ✅

**文件**: `scripts/web/src/api/ask.ts`（修改）

- `ChatDoneData` 增加 `trace` 字段
- 新增 `fetchTrace(messageId)` 函数
- 新增 `TracePayload` 接口

---

## 四、类型检查和测试

### 任务 4.1: 运行 mypy 类型检查 ✅

- `mypy` 无新增错误

### 任务 4.2: 运行测试 ✅

- 270 passed, 2 skipped, 3 failed（均为 test_jina_adapter.py 预存失败）
