# RAG 检索质量改进 — 技术调研报告

生成时间: 2026-04-07
源规格: specs/003-rag-rerank-quality/spec.md

## 执行摘要

当前 RAG 系统的检索管道架构合理（Bi-Encoder + BM25 + RRF 融合），但存在三个关键缺陷：**默认 Reranker 使用 LLM 伪分数无法做阈值过滤**、**阈值过滤在 Rerank 之前执行顺序错误**、**Rerank 后缺少阈值过滤导致噪声直接送给 LLM**。改进方案核心是将默认 Reranker 切换为 GGUF（输出真实 0-1 相关性分数），修正执行顺序为"召回 → Rerank → 阈值过滤"，并新增 `rerank_min_score` 配置项。主要风险是 GGUF 模型文件可能不存在（需回退到 LLM），以及 jina-reranker-v3 的中文保险法规排序效果需要通过 eval dataset 验证。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 切换默认 Reranker | `config.py:18`, `rag_engine.py:150-173` | 需修改默认值 + 创建逻辑 |
| FR-002 Reranker 后阈值过滤 | `rag_engine.py:406-415` | 不存在，需新增 |
| FR-003 过滤顺序修正 | `rag_engine.py:406-413` | 当前 RRF 阈值在 Rerank 之前，需调整 |
| FR-004 空列表处理 | `rag_engine.py:245-251` | 已有 `if not search_results` 处理 |
| FR-005 保留 min_rrf_score | `config.py:20` | 已有，需保留为可选预过滤 |
| FR-006 评估方案 | `evaluator.py`, `eval_guide.py` | 已有框架，需设计 Reranker 专项评估 |

### 1.2 可复用组件

- **`BaseReranker`** (`reranker_base.py:8-18`): 统一 Reranker 接口，`rerank(query, candidates, top_k)` → `List[Dict]`
- **`GGUFReranker`** (`gguf_reranker_adapter.py`): 已实现 GGUF 适配器，输出 `relevance_score` (0-1 余弦相似度)
- **`GGUFCliReranker`** (`_gguf_cli.py`): llama.cpp CLI 调用封装，MLP 投影 + 余弦相似度
- **`HybridQueryConfig`** (`config.py:8-37`): 配置 dataclass，有完整的 `__post_init__` 验证
- **`RetrievalEvaluator`** (`evaluator.py`): 支持 Precision@K、Recall@K、MRR、NDCG 等指标
- **`GenerationEvaluator`** (`evaluator.py`): 支持 Faithfulness（幻觉检测）
- **`AttributionResult`** (`attribution.py`): 引用解析 + 未验证声明检测 + 数值不匹配检测
- **`eval_guide.py`**: 预定义指标阈值 + 等级解读 + 回归检测

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `config.py` | 修改 | 新增 `rerank_min_score` 字段，修改 `reranker_type` 默认值 |
| `rag_engine.py` | 修改 | 调整 `_hybrid_search()` 中阈值过滤的位置和逻辑 |
| `llm_reranker.py` | 不修改 | 回退时保持现有行为 |
| `gguf_reranker_adapter.py` | 不修改 | 已有正确实现 |
| `evaluator.py` | 可选修改 | 添加 Reranker 前后对比的评估逻辑 |

---

## 二、技术选型研究

### 2.1 技术方案对比

#### 2.1.1 默认 Reranker 选择

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| GGUF (Jina v3) | 真实 0-1 相关性分数；支持阈值过滤；本地运行无 API 依赖 | 模型文件可能不存在；Q4_K_M 量化有精度损失；每次 subprocess 启动开销 ~500ms | ✅ 推荐 |
| LLM Reranker | 已稳定运行；无需额外模型文件 | 伪分数无法做阈值过滤；每次 LLM 调用开销大；不稳定 | ❌ 不推荐作为默认 |
| BGE-Reranker (Cross-Encoder) | 文章推荐方案；中文效果好 | 需新增依赖 (transformers + torch)；需要 GPU；模型加载开销大 | ❌ 超出本次范围 |

**结论**: 使用现有 GGUF Reranker 作为默认，LLM Reranker 作为回退。

#### 2.1.2 阈值过滤策略

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| Rerank 后单层阈值 | 简单直接；基于精细分数 | 只有一个过滤点 | ✅ 推荐 |
| RRF + Rerank 双层阈值 | 更严格的质量控制 | 复杂度高；RRF 阈值可能误杀高质量候选 | ❌ 过度设计 |
| 自适应阈值 | 根据分数分布动态调整 | 实现复杂；需要历史数据 | ❌ 过度设计 |

**结论**: Rerank 后单层阈值，`min_rrf_score` 保留为可选预过滤。

#### 2.1.3 阈值标定方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 网格搜索 + F1 最大化 | 文章推荐方案；简单可复现 | 需要标注数据 | ✅ 推荐设计 |
| 固定阈值 (0.5) | 最简单 | 可能不是最优 | ❌ 不够精确 |
| 基于分位数的动态阈值 | 自动适应 | 不可解释 | ❌ 不推荐 |

**结论**: 设计基于 eval dataset 的网格搜索方案，遍历 0.3-0.8 步长 0.05，找 F1 最大点。

### 2.2 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| numpy | 现有 | GGUF 分数计算 | ✅ 已安装 |
| safetensors | 现有 | MLP 投影权重加载 | ✅ 已安装 |
| llama-embedding | 现有 (tools/) | GGUF 推理 | ✅ 已有 |
| 无新增依赖 | — | — | ✅ 零新增依赖 |

---

## 三、数据流分析

### 3.1 现有数据流

```
用户查询 (Query)
    ↓
[Query 预处理] query_preprocessor.py
    ├─→ 术语标准化 ("退保" → "解除保险合同")
    ├─→ LLM Query Rewrite
    └─→ 同义词扩展 (最多 3 个变体)
    ↓
[并行检索] retrieval.py (ThreadPoolExecutor)
    ├─→ 向量检索 (Jina v5 Embedding, vector_top_k=20)
    └─→ BM25 关键词检索 (jieba 分词, keyword_top_k=20)
    ↓
[RRF 融合] fusion.py
    ├─→ 公式: score = Σ(weight / (k + rank))
    ├─→ 去重: max_chunks_per_article=3
    └─→ 返回: List[Dict] (含 'score' 字段)
    ↓
[⚠️ RRF 阈值过滤] rag_engine.py:406-410  ← 当前位置（有问题）
    ├─→ if max_score < min_rrf_score: return []
    └─→ min_rrf_score 默认 0.0 (未启用)
    ↓
[Rerank] rag_engine.py:412-413
    ├─→ LLM: rerank_score = 1.0/(rank+1)  ← 伪分数
    └─→ GGUF: rerank_score = cosine_sim    ← 真实分数
    ↓
[❌ 无后处理] ← 问题：没有阈值过滤
    ↓
[LLM 生成] rag_engine.py:253-269
    ├─→ 构建 prompt (max_context_chars=12000)
    ├─→ 调用 LLM (glm-4-flash)
    └─→ 解析引用 [来源X]
    ↓
[归因验证] attribution.py
    ├─→ 未验证声明检测
    ├─→ 数值不匹配检测
    └─→ AttributionResult
```

### 3.2 目标数据流（改进后）

```
用户查询 (Query)
    ↓
[Query 预处理] ← 不变
    ↓
[并行检索] ← 不变
    ↓
[RRF 融合] ← 不变
    ↓
[可选 RRF 预过滤] ← min_rrf_score 保留为可选
    ├─→ if min_rrf_score > 0 and max_score < min_rrf_score: return []
    └─→ 默认 0.0，不启用
    ↓
[Rerank] ← 默认 GGUF
    └─→ 输出 rerank_score (0-1 真实相关性概率)
    ↓
[✅ Rerank 后阈值过滤] ← 新增
    ├─→ if rerank_min_score > 0:
    │       过滤 rerank_score < rerank_min_score 的结果
    │       if 结果为空: logger.debug("所有结果被阈值过滤")
    └─→ rerank_min_score 默认 0.0，不启用
    ↓
[空结果处理] ← 已有 (rag_engine.py:245-251)
    └─→ return "未找到相关法规条款，请尝试换个描述方式。"
    ↓
[LLM 生成] ← 不变
    ↓
[归因验证] ← 不变
```

### 3.3 关键数据结构

#### 现有 — HybridQueryConfig

```python
@dataclass
class HybridQueryConfig:
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    enable_rerank: bool = True
    rerank_top_k: int = 5
    reranker_type: str = "llm"       # ← 需改为 "gguf"
    max_chunks_per_article: int = 3
    min_rrf_score: float = 0.0
    # ← 需新增: rerank_min_score: float = 0.0
```

#### 新增字段

```python
rerank_min_score: float = 0.0  # Reranker 后阈值过滤，0.0 = 禁用
```

#### Reranker 返回的 Dict 结构

```python
# GGUF Reranker 返回
{
    'content': str,
    'law_name': str,
    'article_number': str,
    'score': float,              # RRF 分数
    'rerank_score': float,       # 0-1 余弦相似度 (可用于阈值)
    'reranked': True,
}

# LLM Reranker 返回（回退场景）
{
    'content': str,
    'law_name': str,
    'article_number': str,
    'score': float,              # RRF 分数
    'rerank_score': float,       # 1.0/(rank+1) 伪分数 (不可用于阈值)
    'reranked': True,
}

# GGUF 运行时错误回退
{
    'content': str,
    'law_name': str,
    'article_number': str,
    'score': float,              # RRF 分数
    # 无 rerank_score 字段 ← 阈值过滤需处理
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] **GGUF 模型文件存在性** — 检查 `scripts/lib/rag_engine/models/reranker/jina-reranker-v3-Q4_K_M.gguf` 和 `projector.safetensors` 是否存在。验证方式: `ls -la scripts/lib/rag_engine/models/reranker/`
- [ ] **jina-reranker-v3 中文效果** — GGUF 模型英文为主，中文保险法规场景的排序质量是否优于 LLM Reranker。验证方式: 用 eval dataset 150 条样本跑 Precision@5 对比
- [ ] **GGUF 分数分布** — 实际 relevance_score 的分布范围，用于确定合理的默认阈值区间。验证方式: 收集 150 条查询的 rerank_score，分析分布
- [ ] **回退后阈值处理** — GGUF 运行时错误回退后，`rerank_score` 字段缺失，阈值过滤需安全处理。验证方式: 单元测试覆盖

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| GGUF 模型文件不存在 | 中 | 高 | 已有回退到 LLM Reranker 的逻辑 (rag_engine.py:166-171)，新增 warning 日志 |
| GGUF 中文排序效果差 | 中 | 中 | 通过 eval dataset 验证，如果效果差可回退默认值为 "llm" |
| 阈值设置过高导致空结果 | 低 | 中 | 默认 0.0 禁用；空结果时返回友好提示；日志记录 |
| subprocess 启动开销 | 低 | 低 | 每次 rerank ~500ms-2s，对 QA 场景可接受 |
| 回退时 rerank_score 缺失 | 低 | 高 | 阈值过滤前检查 `rerank_score` 是否存在，不存在则跳过过滤 |
| min_rrf_score 误杀高质量候选 | 低 | 中 | 保留但默认禁用；文档建议只在 Rerank 前做大粒度过滤 |

### 4.3 GGUF Reranker 技术细节

#### 架构

```
Python → 临时文件(.txt) → llama-embedding CLI → stdout(JSON) → Python 解析
```

- **按需启动**: 每次 rerank 请求启动新进程，无需常驻 server
- **进程隔离**: 天然并发安全，但频繁启动有开销
- **GPU 加速**: `-ngl 99` 全层 offload 到 GPU
- **响应时间**: 预估 500ms-2s/次 (含进程启动)

#### 分数计算

```python
# _gguf_cli.py:196-207
# 1. 提取特殊 token 位置的隐藏状态
query_hidden = embeddings[query_pos]     # <|rerank_token|> 位置
doc_hiddens = embeddings[doc_positions]  # <|embed_token|> 位置

# 2. MLP 投影 (2层 + ReLU)
query_embeds = projector(query_hidden)   # Linear → ReLU → Linear
doc_embeds = projector(doc_hiddens)

# 3. 余弦相似度
scores = dot(doc_embeds, query_embeds) / (norm(doc_embeds) * norm(query_embeds))
```

**分数特征**:
- 范围: [-1, 1]，实际使用中通常在 [0, 1]
- 物理意义: query-document 嵌入向量的夹角余弦值
- 可直接用于阈值过滤

#### 回退链

```
GGUF 初始化失败 (FileNotFoundError)
    → 回退到 LLM Reranker (rag_engine.py:170-171)
    → LLM 输出伪分数 rerank_score = 1.0/(rank+1)

GGUF 运行时错误 (Exception)
    → 返回原始 candidates (gguf_reranker_adapter.py:41-43)
    → 无 rerank_score 字段
```

**阈值过滤必须处理这两种回退场景**。

---

## 五、评估方案设计

### 5.1 现有评估框架能力

| 能力 | 状态 | 说明 |
|------|------|------|
| Precision@K | ✅ 已有 | RetrievalEvaluator 核心指标 |
| Recall@K | ✅ 已有 | RetrievalEvaluator 核心指标 |
| MRR | ✅ 已有 | 第一个相关结果的排名倒数 |
| NDCG | ✅ 已有 | 整体排序质量 |
| Redundancy Rate | ✅ 已有 | 结果冗余度 |
| Faithfulness | ✅ 已有 | 幻觉检测 (attribution.py) |
| Answer Relevancy | ✅ 已有 | 三级策略 (LLM Judge / RAGAS / Lightweight) |
| Answer Correctness | ✅ 已有 | 与标准答案一致性 |
| 噪声比例 | ❌ 需新增 | 送给 LLM 的 Chunk 中不相关文档占比 |
| 阈值搜索 | ❌ 需新增 | 遍历阈值找 F1 最优 |

### 5.2 评估数据集

**现有**: 150 条样本 (factual:45, multi_hop:40, negative:35, colloquial:30)

**格式**:
```python
@dataclass(frozen=True)
class EvalSample:
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]       # 证据文档文件名
    evidence_keywords: List[str]   # 证据关键词
    question_type: QuestionType
    difficulty: str                # easy/medium/hard
    topic: str
```

### 5.3 评估方案

#### 阶段一: 基线测量（改进前）

```bash
# 使用当前默认配置 (LLM Reranker, 无阈值过滤)
python scripts/evaluate_rag.py --mode retrieval --top-k 5
```

**记录指标**: Precision@5, Recall@5, NDCG@5, MRR, 噪声比例

#### 阶段二: GGUF Reranker 对比

```bash
# 使用 GGUF Reranker，无阈值过滤
# 需临时修改 reranker_type="gguf"
python scripts/evaluate_rag.py --mode retrieval --top-k 5
```

**记录指标**: 同上 + rerank_score 分布统计

#### 阶段三: 阈值搜索

```python
# 伪代码：遍历不同阈值，找 F1 最优
thresholds = [i * 0.05 for i in range(6, 17)]  # 0.3 到 0.8
for threshold in thresholds:
    # 启用 rerank_min_score=threshold
    # 运行检索评估
    # 计算 Precision@5, Recall@5, F1@5
# 选择 F1 最高的阈值
```

#### 阶段四: 最终对比

| 指标 | 基线 (LLM) | GGUF | GGUF + 阈值 |
|------|-----------|------|------------|
| Precision@5 | ? | ? | ? |
| Recall@5 | ? | ? | ? |
| NDCG@5 | ? | ? | ? |
| 噪声比例 | ? | ? | ? |
| 平均延迟 | ? | ? | ? |

### 5.4 新增评估指标: 噪声比例

```python
def compute_noise_ratio(
    results: List[Dict],
    sample: EvalSample,
) -> float:
    """送给 LLM 的 Chunk 中不相关文档的占比"""
    if not results:
        return 0.0
    irrelevant_count = sum(
        1 for r in results
        if not _is_relevant(r, sample.evidence_docs, sample.evidence_keywords)
    )
    return irrelevant_count / len(results)
```

### 5.5 评估入口

- **CLI**: `python scripts/evaluate_rag.py --mode retrieval`
- **API**: `POST /api/eval/evaluations` (异步任务)
- **代码**: `RetrievalEvaluator.evaluate_batch(samples, top_k=5)`

---

## 六、改动范围精确分析

### 6.1 config.py 修改

```python
# 行 18: 修改默认值
reranker_type: str = "gguf"          # 原: "llm"

# 行 20 后: 新增字段
rerank_min_score: float = 0.0        # Reranker 后阈值过滤

# __post_init__ 新增验证
if not 0.0 <= self.rerank_min_score <= 1.0:
    raise ValueError(...)
```

### 6.2 rag_engine.py 修改

```python
# _hybrid_search() 方法 (行 379-415)
# 修改前:
#   406-410: min_rrf_score 过滤
#   412-413: Rerank

# 修改后:
#   406-410: min_rrf_score 预过滤 (保留，可选)
#   412-413: Rerank (不变)
#   414+: 新增 rerank_min_score 过滤
if config.rerank_min_score > 0:
    results = [
        r for r in results
        if r.get('rerank_score', 0) >= config.rerank_min_score
    ]
```

### 6.3 回退安全性

```python
# GGUF 运行时错误回退后无 rerank_score 字段
# r.get('rerank_score', 0) → 默认 0 → 被过滤
# 解决方案: 只对 reranked=True 的结果做阈值过滤
if config.rerank_min_score > 0:
    results = [
        r for r in results
        if not r.get('reranked', False)  # 未 rerank 的保留
        or r.get('rerank_score', 0) >= config.rerank_min_score
    ]
```

### 6.4 影响范围

- **修改文件**: `config.py` (2处), `rag_engine.py` (1处)
- **新增测试**: config 验证测试, 阈值过滤逻辑测试
- **不影响**: LLM Reranker, GGUF adapter, evaluator, attribution, retrieval, fusion
- **向后兼容**: `rerank_min_score=0.0` 禁用时行为不变

---

## 七、参考实现

- [Jina Reranker v3](https://huggingface.co/jinaai/jina-reranker-v3-turbo) — 当前 GGUF 模型的原始模型
- [BGE-Reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) — 文章推荐的中文 Cross-Encoder 方案（本次不采用，留后续）
- [文章: 京东面试官连环问 Rerank](https://mp.weixin.qq.com/s/1GZtibu07K2rzhGF-PZJ2Q) — 问题诊断的参考来源
