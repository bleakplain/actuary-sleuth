# Feature Specification: RAG 检索质量改进 — GGUF Reranker 默认化 + 阈值过滤

**Feature Branch**: `003-rag-rerank-quality`
**Created**: 2026-04-07
**Status**: Draft
**Input**: 深入了解 RAG 检索的代码实现，参考微信文章评估是否存在 Bi-Encoder 召回精度低、缺少 Rerank、缺少阈值过滤、缺少领域微调等问题，并设计改进方案

## 问题诊断

### 文章核心观点

参考文章《京东面试官连环问："你 RAG 召回了 20 条，有 15 条是垃圾，Rerank 怎么做的？"》指出 RAG 系统四大常见问题：

1. **Bi-Encoder 召回精度低** — 只衡量话题相似性，无法判断答案相关性
2. **缺少 Cross-Encoder Reranker** — 召回后没有精排步骤，噪声文档直接送给 LLM
3. **缺少阈值过滤** — 没有对相关性分数做阈值过滤，低质量文档导致幻觉
4. **缺少领域微调** — 通用 Reranker 在专业领域表现欠佳

### 当前系统现状

| 问题 | 当前系统 | 风险等级 |
|------|---------|---------|
| Bi-Encoder 精度 | 已有混合检索 (Bi-Encoder + BM25 + RRF) | 中 |
| Cross-Encoder Rerank | 有 GGUF Reranker (Jina v3) 但非默认，默认 LLM Reranker | 中高 |
| 阈值过滤 | `min_rrf_score=0.0` 未启用，Reranker 分数无阈值 | **高** |
| 领域微调 | 无 | 低（本次不涉及） |

### 确认的代码级问题

1. **LLM Reranker 分数是伪分数** (`llm_reranker.py:71`)
   - `rerank_score = 1.0 / (rank + 1)` 只是排名的数学变换，不是真正的相关性概率
   - 无法用于阈值判断

2. **GGUF Reranker 不是默认选项** (`rag_engine.py:162-163`)
   - `reranker_type` 默认 `"llm"`，GGUF 需要手动配置
   - GGUF 模型文件缺失时静默回退到 LLM Reranker

3. **阈值过滤在 Rerank 之前** (`rag_engine.py:406-413`)
   - `min_rrf_score` 检查在 Rerank 之前（line 406-410）
   - Rerank 之后没有对 `relevance_score` 做阈值过滤
   - 正确顺序应该是：召回 → Rerank → 阈值过滤

4. **RRF 阈值未启用** (`config.py`)
   - `min_rrf_score: float = 0.0`，等于不过滤

5. **GGUF 量化 + 中文场景** (`_gguf_cli.py`)
   - Q4_K_M 量化对排序精度有损失
   - jina-reranker-v3 英文为主，中文保险法规效果需要验证

## User Scenarios & Testing

### User Story 1 - 切换默认 Reranker 为 GGUF (Priority: P1)

作为系统管理员，我希望将默认 Reranker 从 LLM 切换为 GGUF (Jina Reranker v3)，以便获得真正的相关性概率分数用于后续阈值过滤。

**Why this priority**: GGUF Reranker 输出 0-1 相关性分数，是阈值过滤的前提。LLM Reranker 的伪分数无法用于阈值判断。

**Independent Test**: 修改 `reranker_type` 默认值为 `"gguf"`，确认系统启动时使用 GGUF Reranker，且对查询结果输出 `relevance_score`。

**Acceptance Scenarios**:

1. **Given** GGUF 模型文件存在, **When** 系统初始化 Reranker, **Then** 默认使用 GGUF Reranker 而非 LLM Reranker
2. **Given** GGUF 模型文件不存在, **When** 系统初始化 Reranker, **Then** 回退到 LLM Reranker 并记录 warning 日志
3. **Given** GGUF Reranker 完成 Rerank, **When** 返回结果, **Then** 每条结果包含 `relevance_score` (0-1 浮点数)

---

### User Story 2 - Reranker 后阈值过滤 (Priority: P1)

作为系统管理员，我希望在 Reranker 精排之后增加阈值过滤，将低于阈值的文档丢弃，避免噪声文档送给 LLM 导致幻觉。

**Why this priority**: 这是文章强调的核心问题——"宁缺毋滥"。低于阈值的文档直接丢弃，不追加凑数。

**Independent Test**: 配置 `rerank_min_score` 阈值，执行查询，验证低于阈值的文档被过滤掉。

**Acceptance Scenarios**:

1. **Given** Reranker 返回 5 条结果且 `rerank_min_score=0.5`, **When** 其中 2 条分数低于 0.5, **Then** 只返回 3 条高分结果
2. **Given** Reranker 返回的所有结果分数都低于阈值, **When** 执行查询, **Then** 返回空列表，LLM 收到"无相关内容"提示
3. **Given** `rerank_min_score=0.0`（默认禁用）, **When** 执行查询, **Then** 不做阈值过滤，保持向后兼容

---

### User Story 3 - 阈值过滤顺序修正 (Priority: P1)

作为系统管理员，我希望阈值过滤的执行顺序修正为：召回 → Rerank → 阈值过滤，而非当前的 召回 → RRF阈值 → Rerank。

**Why this priority**: 当前 `min_rrf_score` 检查在 Rerank 之前，这意味着可能把 Reranker 会给出高分的候选文档提前过滤掉了。阈值过滤应该基于更精细的 Reranker 分数。

**Independent Test**: 验证执行顺序为 Rerank → 阈值过滤。

**Acceptance Scenarios**:

1. **Given** 候选文档 RRF 分数低但 Reranker 给出高分, **When** 执行查询, **Then** 该文档不被提前过滤，由 Reranker 分数决定去留
2. **Given** 旧的 `min_rrf_score` 配置, **When** 升级后, **Then** `min_rrf_score` 配置仍然生效但变为可选的预过滤

---

### User Story 4 - 评估方案设计 (Priority: P2)

作为开发者，我需要一套评估方案来量化阈值过滤的效果，包括改进前后的 Precision@K、噪声比例和幻觉率对比。

**Why this priority**: 方案设计阶段需要明确如何衡量改进效果，为后续实现提供验收标准。

**Independent Test**: 基于现有 eval dataset 设计评估流程文档。

**Acceptance Scenarios**:

1. **Given** 现有 eval dataset, **When** 设计评估方案, **Then** 方案覆盖 Precision@K、噪声比例、幻觉率三个指标
2. **Given** 评估方案, **When** 需要标定最优阈值, **Then** 方案包含阈值搜索流程（遍历 0.3-0.8，找 F1 最大点）

---

### Edge Cases

- GGUF 模型文件不存在时的优雅降级？
- 阈值设置过高导致所有查询都返回空结果？
- 中文保险法规中 GGUF Reranker 的实际排序质量是否优于 LLM Reranker？需要验证。
- Rerank 返回空列表时 LLM 端的行为？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 将默认 `reranker_type` 从 `"llm"` 改为 `"gguf"`
- **FR-002**: 系统 MUST 在 Reranker 精排之后增加 `rerank_min_score` 阈值过滤（默认 0.0 禁用）
- **FR-003**: 系统 MUST 将阈值过滤执行顺序修正为：召回 → Rerank → 阈值过滤
- **FR-004**: 系统 MUST 在 Reranker 返回空列表时，向 LLM 传递"未找到相关内容"的提示
- **FR-005**: 系统 MUST 保留 `min_rrf_score` 作为可选的预过滤机制，向后兼容
- **FR-006**: 系统 MUST 设计基于 eval dataset 的评估方案，覆盖 Precision@K、噪声比例、幻觉率

### Key Entities

- **Reranker Score**: GGUF Reranker 输出的 0-1 相关性概率，用于阈值过滤
- **RRF Score**: Reciprocal Rank Fusion 融合分数，用于预过滤（可选）
- **rerank_min_score**: 新增配置项，Reranker 后阈值过滤的分数阈值
- **min_rrf_score**: 现有配置项，RRF 后预过滤的分数阈值（保留）

## Success Criteria

- **SC-001**: 默认 Reranker 切换为 GGUF 后，系统正常启动并完成 Rerank
- **SC-002**: 启用 `rerank_min_score` 后，低分文档被过滤，送给 LLM 的文档噪声比例降低
- **SC-003**: 评估方案可量化改进前后的 Precision@K 和噪声比例

## Assumptions

- GGUF 模型文件 (`jina-reranker-v3-Q4_K_M.gguf`) 已存在于 `data/` 目录
- jina-reranker-v3 的中文排序质量可接受（需验证）
- 现有 eval dataset 可用于评估对比
- 本次不涉及 Reranker 领域微调（优先级低，留后续）
- 本次不涉及 Cross-Encoder 模型替换（使用现有 GGUF 模型）
