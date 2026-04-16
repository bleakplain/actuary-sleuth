# Feature Specification: RAG 性能优化 — 三级缓存 + 全链路异步

**Feature Branch**: `011-rag-perf-cache`
**Created**: 2026-04-15
**Status**: Draft
**Input**: 性能优化：设计三级缓存架构（Embedding/检索结果/答案缓存），配合全链路异步和 HNSW 索引调优，热门查询首字响应时间从 5s 降至 50ms 以内。

## Performance Baseline (Current State)

### 端到端延迟分解（首次查询，无缓存）

| 阶段 | 耗时估算 | 说明 |
|------|----------|------|
| Embedding API 调用 | 200-500ms | 每次实时调用，无缓存 |
| LanceDB 向量搜索 | 100-300ms | 无索引优化，全量扫描 |
| BM25 关键词搜索 | 10-50ms | 索引已磁盘缓存 |
| RRF 融合 | ~5ms | 内存计算 |
| Rerank LLM 调用 | 1-3s | 阻塞式调用 |
| 生成 LLM 调用 | 2-5s | 阻塞式调用 |
| 伪流式返回 | 额外延迟 | asyncio.sleep(0.01) 人为分块 |
| **总计** | **4-9s** | |

### 已有优化基础

- HTTP 连接池 (pool_maxsize=20)
- BM25 索引磁盘缓存（pickle 序列化）
- 检索阶段并行（vector + keyword，ThreadPool 2 workers）
- 查询扩展并行（最多 3 条扩展查询）
- 熔断器 + 指数退避重试
- `llm/cache.py` 已实现（TTL 1h，LRU 1000 条）但**未接入 RAG 流程**

### 关键缺失

- 无 Embedding 缓存
- 无检索结果缓存
- LLM 缓存已实现未接入
- 伪流式（非原生 LLM 流式）
- graph 中节点顺序执行，无并行
- LanceDB 无索引优化

## User Scenarios & Testing

### User Story 1 - 热门查询缓存命中快速响应 (Priority: P1)

作为精算审核人员，当我重复查询相似条款时（如"等待期条款要求"），系统应从缓存直接返回结果，首字响应在 50ms 以内。

**Why this priority**: 审核场景中大量查询具有重复性（同类产品、相似条款），缓存命中率高，直接提升日常使用体验。

**Independent Test**:
1. 发送查询 A，记录完整响应时间 T1
2. 再次发送相同查询 A，记录首字响应时间 T2
3. 验证 T2 < 50ms

**Acceptance Scenarios**:

1. **Given** 查询 A 已成功执行并缓存, **When** 用户再次发送相同查询 A, **Then** 首字响应时间 < 50ms
2. **Given** 查询 A 的 Embedding 已缓存, **When** 语义相似查询 B 进入检索阶段, **Then** 跳过 Embedding API 调用，使用缓存的相似 Embedding
3. **Given** 检索结果已缓存, **When** 相同查询命中检索缓存, **Then** 跳过向量搜索和 BM25 搜索，直接返回缓存结果
4. **Given** LLM 答案已缓存, **When** 相同查询命中答案缓存, **Then** 跳过 LLM 调用，直接流式返回缓存答案

---

### User Story 2 - 首次查询原生流式输出 (Priority: P1)

作为精算审核人员，当我发起首次查询时，应在 LLM 开始生成后立即看到输出流式呈现，而不是等待完整生成后才看到内容。

**Why this priority**: 首次查询无法命中缓存，原生流式是改善用户感知响应时间的唯一手段。首字时间从 5-9s 降至 <200ms。

**Independent Test**:
1. 发送首次查询，测量从请求发出到 UI 显示第一个 token 的时间
2. 验证首字时间 < 200ms
3. 验证 token 逐个到达，无大块等待

**Acceptance Scenarios**:

1. **Given** 首次查询（无缓存）, **When** RAG 检索完成后 LLM 开始生成, **Then** 首字时间（TTFT）< 200ms
2. **Given** LLM 正在流式生成, **When** 每个 token 产生时, **Then** 通过 SSE 实时推送到前端
3. **Given** 流式输出中断（网络/LLM 错误）, **Then** 前端收到 error 事件并显示错误提示

---

### User Story 3 - 三级缓存架构 (Priority: P1)

系统实现三级缓存，热数据内存优先、冷数据 SQLite 持久化，进程重启后能快速恢复缓存热数据。

**Why this priority**: 三级缓存是达成 50ms 目标的核心架构，缓存命中率直接决定热门查询的响应速度。

**Independent Test**:
1. 检查 Embedding 缓存：对相同文本两次调用，第二次应从缓存返回
2. 检查检索结果缓存：对相同查询两次检索，第二次应跳过搜索
3. 检查答案缓存：对相同查询两次生成，第二次应跳过 LLM 调用
4. 重启进程后发送缓存命中查询，验证 SQLite 层缓存有效

**Acceptance Scenarios**:

1. **Given** Embedding 缓存启用, **When** 对文本 T 计算 Embedding, **Then** 结果存入内存缓存和 SQLite 持久化
2. **Given** 检索缓存启用, **When** 对查询 Q 执行检索, **Then** 结果（向量+BM25+RRF）存入缓存
3. **Given** 答案缓存启用, **When** 对查询 Q 生成答案, **Then** 最终答案存入缓存，后续相同查询直接返回
4. **Given** 进程重启, **When** 缓存查询时, **Then** 从 SQLite 加载持久化数据到内存缓存（懒加载）
5. **Given** 缓存容量达上限, **When** 写入新缓存条目, **Then** LRU 策略淘汰最久未使用条目

---

### User Story 4 - LanceDB 向量索引优化 (Priority: P2)

向量搜索使用 LanceDB 内置索引优化（IVF_PQ 或类似），提升首次查询的向量检索速度。

**Why this priority**: 首次查询无法命中缓存，向量索引优化直接减少检索延迟。

**Independent Test**:
1. 对比优化前后的向量搜索延迟（同数据集、同查询）
2. 验证搜索结果质量不受影响（召回率偏差 < 5%）

**Acceptance Scenarios**:

1. **Given** LanceDB 索引优化配置启用, **When** 知识库构建完成, **Then** 自动创建优化索引
2. **Given** 优化索引已创建, **When** 执行向量搜索, **Then** 搜索延迟降低 50% 以上
3. **Given** 优化索引已创建, **When** 执行向量搜索, **Then** 搜索结果与优化前一致（召回率偏差 < 5%）

---

### User Story 5 - Graph 节点并行执行 (Priority: P2)

LangGraph 工作流中独立节点并行执行，减少端到端等待时间。

**Why this priority**: 当前 graph 中 memory retrieval 和 RAG search 是串行的，但可以并行执行。

**Independent Test**:
1. 添加日志记录各节点开始/结束时间
2. 验证 memory retrieval 和 RAG search 并行执行

**Acceptance Scenarios**:

1. **Given** graph 中有独立节点, **When** 工作流执行, **Then** 独立节点并行执行
2. **Given** 节点间存在数据依赖, **When** 工作流执行, **Then** 依赖节点顺序执行

---

### User Story 6 - 缓存统计与监控 (Priority: P3)

系统提供缓存命中率、各级缓存大小、平均响应时间等指标，方便评估优化效果。

**Why this priority**: 没有度量就无法验证优化效果，但功能上不影响核心链路。

**Independent Test**:
1. 调用监控接口，验证返回缓存统计数据
2. 发送多次查询后验证命中率 > 0

**Acceptance Scenarios**:

1. **Given** 系统运行中, **When** 查询缓存统计接口, **Then** 返回各级缓存的命中率、大小、TTL 等信息
2. **Given** 缓存命中/未命中, **When** 每次查询, **Then** 记录缓存命中日志（DEBUG 级别）

---

## Edge Cases

- 缓存一致性：知识库更新后，相关缓存是否自动失效？
- 并发写入：多线程同时查询相同 key 时，是否避免缓存击穿（cache stampede）？
- 缓存序列化：Embedding 向量（float array）的 SQLite 存储效率？
- 流式中断恢复：LLM 流式输出中断后，部分结果是否缓存？
- 大查询结果：检索结果缓存条目过大时的存储策略？
- 数据库迁移：SQLite 缓存表的结构变更策略？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 实现三级缓存架构：Embedding 缓存、检索结果缓存、LLM 答案缓存
- **FR-002**: 缓存 MUST 采用内存 + SQLite 两级存储，热数据内存优先，冷数据 SQLite 持久化
- **FR-003**: 系统 MUST 支持原生 LLM 流式输出（非伪流式），通过 SSE 推送到前端
- **FR-004**: 系统 MUST 将已实现但未接入的 `llm/cache.py` 集成到 RAG 流程中
- **FR-005**: 系统 MUST 优化 LanceDB 向量索引配置，提升首次查询检索速度
- **FR-006**: 缓存 MUST 支持 TTL 过期策略和 LRU 淘汰策略
- **FR-007**: 缓存 MUST 线程安全，支持并发读写
- **FR-008**: 热门查询缓存命中时，首字响应时间 MUST < 50ms
- **FR-009**: 首次查询 LLM 流式首字时间 MUST < 200ms（检索完成后）
- **FR-010**: 系统 MUST 在 graph 中并行执行独立节点（memory retrieval + RAG search）
- **FR-011**: 缓存 MUST 在知识库版本变更时自动失效或标记过期
- **FR-012**: [NEEDS CLARIFICATION] 缓存失效策略：知识库更新是全量失效还是按文档粒度失效？

### Key Entities

- **CacheEntry**: 缓存条目，包含 key、value、TTL、创建时间、访问时间、命中次数
- **CacheStats**: 缓存统计，包含命中率、大小、淘汰次数
- **CacheLayer**: 缓存层级（L1 Memory / L2 SQLite），统一接口
- **StreamChunk**: 流式输出块，包含 token、索引、是否结束

## Success Criteria

- **SC-001**: 热门查询缓存命中首字响应 < 50ms（p99）
- **SC-002**: 首次查询流式首字时间 < 200ms（p99，从检索完成到首 token）
- **SC-003**: 缓存命中率 > 30%（典型审核场景下）
- **SC-004**: 向量检索延迟降低 50% 以上（首次查询，同数据集对比）
- **SC-005**: 不引入新的外部服务依赖（Redis 等）
- **SC-006**: 所有现有测试通过，新增缓存相关测试覆盖率 > 80%

## Assumptions

- 保持 LanceDB 向量库，不切换到 Qdrant/Milvus
- 缓存基础设施仅使用内存 + SQLite，不引入 Redis
- 知识库数据规模在百万级 chunk 以下（当前量级）
- 单机部署，无分布式缓存需求
- 现有 `llm/cache.py` 的接口设计可复用或扩展
- LLM 提供商（Zhipu）支持原生流式输出 API
- 前端已支持 SSE EventSource 接收流式数据
