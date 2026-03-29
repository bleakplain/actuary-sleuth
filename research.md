# Actuary Sleuth RAG Engine - 全面评估研究报告

生成时间: 2026-03-29
分析范围: `scripts/lib/rag_engine/` 全模块
参考框架: [面试官：如何全面地评估一个RAG系统的性能？](https://mp.weixin.qq.com/s/ahOsCECpbQmO0C7elKFyvA)

---

## 执行摘要

本报告对 Actuary Sleuth 项目的 RAG 引擎模块进行了全面的代码审查，参照 RAG 评估框架文章的两阶段评估体系（检索阶段 + 生成阶段），从检索质量、生成质量、上下文相关性、系统架构、代码质量五个维度进行系统评估。

**主要发现：**
- 发现 **2 个运行时 Bug**（`get_index_stats()` 方法不存在、`_ensure_embedding_setup()` 死代码）
- 发现 **16 个设计/质量问题**，其中 5 个直接影响检索和生成质量
- **检索阶段**：混合检索架构合理，但存在上下文窗口过小（4000字符）、查询扩展分数膨胀、Rerank 截断丢失信息等问题
- **生成阶段**：Faithfulness 轻量级评估过于粗糙，Context Relevance 指标完全缺失
- **评估体系**：对照文章框架，10 个评估维度中仅 5 个充分实现，3 个部分实现，2 个缺失
- 测试覆盖不足，多个集成测试使用条件断言掩盖失败

---

## 一、项目概览

### 1.1 项目简介

RAG 引擎是 Actuary Sleuth（AI 精算审核助手）的核心检索组件，提供完整的检索增强生成能力：
1. **知识库构建**：解析保险法规 Markdown → 智能分块 → 向量索引（LanceDB）+ BM25 关键词索引
2. **混合检索**：向量语义检索 + BM25 关键词检索 → RRF 融合 → LLM Rerank
3. **查询预处理**：术语归一化、同义扩展、LLM 改写
4. **问答生成**：基于检索结果的法规引用回答 + 引用归因
5. **量化评估**：检索评估（Precision/Recall/MRR/NDCG/冗余率）+ 生成评估（RAGAS/轻量级）

**技术栈：** LlamaIndex + LanceDB + jieba + rank-bm25 + RAGAS + 智谱 GLM API

### 1.2 目录结构

```
scripts/lib/rag_engine/
├── __init__.py              # 模块入口，延迟导入 + 优雅降级
├── rag_engine.py            # 核心引擎 (RAGEngine, ThreadLocalSettings)
├── config.py                # 配置类 (RAGConfig, HybridQueryConfig, ChunkingConfig)
├── index_manager.py         # 向量索引生命周期管理 (VectorIndexManager)
├── data_importer.py         # 数据导入管线 (RegulationDataImporter)
├── doc_parser.py            # 文档解析 (RegulationDocParser, RegulationNodeParser)
├── semantic_chunker.py      # 语义感知分块 (SemanticChunker)
├── retrieval.py             # 混合检索入口 (hybrid_search, vector_search)
├── bm25_index.py            # BM25 全文索引 (BM25Index)
├── fusion.py                # RRF 融合 (reciprocal_rank_fusion)
├── reranker.py              # LLM 精排 (LLMReranker)
├── query_preprocessor.py    # 查询预处理 (QueryPreprocessor)
├── tokenizer.py             # 中文分词 (tokenize_chinese)
├── attribution.py           # 引用归因 (parse_citations, attribute_by_similarity)
├── evaluator.py             # 量化评估 (RetrievalEvaluator, GenerationEvaluator)
├── eval_dataset.py          # 评估数据集 (30 条默认样本)
├── llamaindex_adapter.py    # LLM/Embedding 适配器
├── exceptions.py            # 异常层级
└── data/
    ├── insurance_dict.txt   # 保险领域词典 (46 术语)
    ├── stopwords.txt        # 中文停用词 (~100)
    └── synonyms.json        # 同义词映射 (20 组)
```

### 1.3 模块依赖关系

```
rag_engine.py (主入口)
├── config.py ─────────────────────────────────┐
├── index_manager.py                           │
│   └── llamaindex_adapter.py                  │
│       └── lib/llm (LLMClientFactory)         │
├── retrieval.py                               │
│   ├── fusion.py                              │
│   ├── query_preprocessor.py                  │
│   │   └── data/synonyms.json                 │
│   └── bm25_index.py                          │
│       └── tokenizer.py                       │
│           ├── data/insurance_dict.txt        │
│           └── data/stopwords.txt             │
├── reranker.py ─── lib/llm (BaseLLMClient)    │
├── attribution.py                             │
├── data_importer.py                           │
│   ├── doc_parser.py                          │
│   │   └── semantic_chunker.py                │
│   ├── index_manager.py                       │
│   └── llamaindex_adapter.py                  │
└── evaluator.py                               │
    ├── eval_dataset.py                        │
    ├── tokenizer.py                           │
    └── [可选] ragas, datasets                 │
```

---

## 二、核心架构分析

### 2.1 整体架构

系统采用**分层 Pipeline 架构**，分为检索和生成两个阶段：

```
┌─────────────────────────────────────────────────────────────┐
│                      RAGEngine (主入口)                       │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │  ask()   │  │  search()    │  │ search_by_metadata  │   │
│  └────┬─────┘  └──────┬───────┘  └────────┬────────────┘   │
│       │               │                   │                │
│  ┌────▼───────────────▼───────────────────▼──────────┐     │
│  │              _hybrid_search()                       │     │
│  │  QueryPreprocessor → hybrid_search → LLMReranker   │     │
│  └────────────────────────┬────────────────────────────┘     │
│                           │                                 │
└───────────────────────────┼─────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
  ┌────────────┐   ┌────────────┐   ┌────────────────┐
  │ Vector DB  │   │  BM25 Index│   │ QueryPreprocessor│
  │ (LanceDB)  │   │  (joblib)  │   │ (normalize+expand)│
  └──────┬─────┘   └─────┬──────┘   └────────────────┘
         │               │
         └───────┬───────┘
                 ▼
         ┌──────────────┐
         │  RRF Fusion  │
         │ + Dedup      │
         └──────┬───────┘
                ▼
         ┌──────────────┐
         │ LLM Reranker │
         └──────┬───────┘
                ▼
         ┌──────────────┐
         │  QA Prompt   │
         │  + LLM Gen   │
         └──────┬───────┘
                ▼
         ┌──────────────┐
         │  Attribution │
         │  (引用归因)   │
         └──────────────┘
```

### 2.2 设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| **策略模式** | `doc_parser.py` | 根据 `chunking_strategy` 选择分块器 |
| **工厂模式** | `llamaindex_adapter.py` | `get_embedding_model()` 按 provider 创建适配器 |
| **适配器模式** | `llamaindex_adapter.py` | `ClientLLMAdapter` 桥接 `BaseLLMClient` → LlamaIndex `LLM` |
| **单例模式(隐式)** | `retrieval.py` | `_default_preprocessor` 全局懒加载 |
| **线程本地存储** | `rag_engine.py` | `ThreadLocalSettings` 管理全局 Settings |

### 2.3 关键抽象

```python
# 核心配置层级
RAGConfig
├── HybridQueryConfig  (vector_top_k, keyword_top_k, rrf_k, weights, rerank)
└── ChunkingConfig     (strategy, sizes, overlap, merge)

# 检索结果统一格式
Dict[str, Any] = {
    'law_name': str,         # 法规名称
    'article_number': str,   # 条款号 "第一条 总则"
    'content': str,          # 条款正文
    'category': str,         # 产品分类
    'source_file': str,      # 源文件名
    'hierarchy_path': str,   # 层级路径
    'score': float,          # RRF 融合分数
}

# 查询预处理结果
PreprocessedQuery = (original, normalized, expanded[], did_expand)
```

---

## 三、数据流分析

### 3.1 主要数据流：问答模式

```
用户提问 "退保能拿回多少钱"
    │
    ▼
QueryPreprocessor.preprocess()
    ├── _normalize("退保" → "解除保险合同")
    ├── _rewrite_with_llm() → "保险合同解除后现金价值如何计算"
    └── _expand() → ["保险合同解除后...", "终止保险合同后...", "退保价值后..."]
    │
    ▼
hybrid_search() [并行]
    ├── vector_search(normalized, top_k=20)
    └── bm25_index.search(normalized, top_k=20)
    │
    ├── [如果 did_expand] 并行搜索每个扩展 query
    │
    ▼
reciprocal_rank_fusion()
    ├── RRF 打分: score = Σ weight / (k + rank + 1)
    └── _deduplicate_by_article(max_chunks=3)
    │
    ▼
LLMReranker.rerank() [可选]
    ├── 截取 max_candidates=20
    ├── LLM 批量排序 → [3,1,5,2,4]
    └── 赋分: score = 1/(rank+1)
    │
    ▼
_build_qa_prompt()
    ├── 格式化: "1. 【法规名】第X条\n内容"
    ├── 硬限制: max_context_chars=4000  ← ⚠️ 过小
    └── 超限截断: content[:remaining] + '……'
    │
    ▼
LLMClient.generate(prompt)
    │
    ▼
parse_citations(answer, sources)
    ├── 提取 [来源X] 标记
    └── _detect_unverified_claims() → 检测未引用的事实性陈述
```

### 3.2 主要数据流：数据导入

```
references/*.md
    │
    ▼
RegulationDocParser.parse_all()
    ├── _clean_content() → 去目录、空行
    ├── extract_law_name() → 提取法规名称
    │
    ├── [strategy="semantic"] SemanticChunker.chunk()
    │   ├── _split_by_structure() → 按标题/条款分割
    │   ├── _merge_short_segments() → 合并短片段 (阈值 300 字符)
    │   ├── _split_long_segments() → 拆分长片段 (>1500 字符)
    │   ├── _build_nodes() → TextNode + metadata
    │   ├── _semantic_refine() → 语义精调 (>max_size 的节点)
    │   └── _add_overlap() → 添加 3 句重叠窗口
    │
    └── [strategy="fixed"] RegulationNodeParser._parse_article_nodes()
        ├── 正则匹配 "第X条"
        ├── 过滤 <=20 字符的短条款
        └── 创建 TextNode + metadata
    │
    ▼
VectorIndexManager.create_index()
    ├── TextNode → VectorStoreIndex (LanceDB)
    └── StorageContext → LanceDBVectorStore
    │
    ▼
BM25Index.build()
    ├── tokenize_chinese() → jieba 分词 + 停用词过滤
    ├── BM25Okapi → 倒排索引
    └── joblib.dump() → bm25_index.pkl
```

---

## 四、核心模块详解

### 4.1 rag_engine.py — 核心引擎

#### 功能描述
统一的 RAG 查询引擎，提供 `ask()`（问答）、`search()`（检索）、`chat()`（聊天）三种接口。通过工厂函数 `create_qa_engine()` 和 `create_audit_engine()` 创建不同场景的引擎。

#### 关键类/函数

- **`ThreadLocalSettings`**：解决 LlamaIndex 全局 `Settings` 的线程安全问题
- **`RAGEngine.initialize()`**：线程安全的懒初始化
- **`RAGEngine._hybrid_search()`**：核心检索 pipeline — 预处理 → 混合检索 → RRF 融合 → LLM Rerank
- **`RAGEngine._build_qa_prompt()`**：构建 QA 提示词，有 4000 字符上下文预算

#### 关键代码

```python
# rag_engine.py:78-82 — 全局 Settings 写入无锁保护
def apply(self) -> None:
    if hasattr(self._local, 'initialized') and self._local.initialized:
        Settings.llm = self._local.llm       # ← 无锁！多线程竞态
        Settings.embed_model = self._local.embed_model
```

```python
# rag_engine.py:256-279 — 上下文窗口硬限制
def _build_qa_prompt(self, question, search_results):
    max_chars = self.config.max_context_chars  # 默认 4000
    for i, result in enumerate(search_results, 1):
        if total_chars + len(full_part) > max_chars:
            remaining = max_chars - total_chars - 50
            if remaining > 100:
                truncated_content = content[:remaining] + '……'
                context_parts.append(header + truncated_content)
            break  # ← 后续结果直接丢弃，无日志
```

---

### 4.2 retrieval.py — 混合检索

#### 功能描述
执行向量检索和 BM25 关键词检索的并行调用，处理查询扩展后的多次检索，最终调用 RRF 融合。

#### 关键代码

```python
# retrieval.py:77-106 — 并行检索 + 扩展查询
with ThreadPoolExecutor(max_workers=2) as executor:
    future_vector = executor.submit(vector_search, index, preprocessed.normalized, vector_top_k, filters)
    future_keyword = executor.submit(bm25_index.search, preprocessed.normalized, top_k=keyword_top_k, filters=filters)

if preprocessed.did_expand:
    expanded_queries = preprocessed.expanded[1:]  # 去掉原始 query
    with ThreadPoolExecutor(max_workers=min(8, 2 * len(expanded_queries))) as executor:
        for expanded_query in expanded_queries:
            vector_futures.append(executor.submit(vector_search, ...))
            keyword_futures.append(executor.submit(bm25_index.search, ...))
    for fv in vector_futures:
        vector_nodes.extend(fv.result())  # ← 直接 extend，无去重
```

---

### 4.3 fusion.py — RRF 融合

#### 功能描述
实现 Reciprocal Rank Fusion 算法，融合向量和关键词两路检索结果，并按法规+条款去重。

#### 算法

```
RRF_score(chunk) = Σ_{result_list L} weight_L / (k + rank_L + 1)

其中 k=60 (标准值)，rank 从 0 开始
```

#### 关键代码

```python
# fusion.py:73-91 — 按法规条款去重
def _deduplicate_by_article(results, max_chunks=3):
    grouped = {(r['law_name'], r['article_number']): [...] for r in results}
    for chunks in grouped.values():
        chunks.sort(key=lambda x: x['score'], reverse=True)
        deduped.extend(chunks[:max_chunks])  # 每条款最多 3 个 chunk
```

---

### 4.4 semantic_chunker.py — 语义感知分块

#### 功能描述
两阶段分块：先按 Markdown 标题层级和条款标记做结构分割，再用 LlamaIndex 的 SemanticSplitterNodeParser 做语义精调。支持短片段合并、长片段拆分、重叠窗口。

#### Pipeline

```
原始文档 → 结构分割 → 合并短片段 → 拆分长片段 → 构建节点
         → [可选] 语义精调 → [可选] 添加重叠窗口
```

---

### 4.5 reranker.py — LLM 精排

#### 功能描述
使用 LLM 对检索候选进行批量排序。将所有候选编号后发送给 LLM，要求按相关性排序并返回编号序列。

#### 关键代码

```python
# reranker.py:71-91 — 批量排序
_BATCH_RERANK_PROMPT = """请根据用户问题，对以下法规条款按相关性从高到低排序。
只输出排序后的编号，用逗号分隔。"""

def _batch_rank(self, query, candidates):
    # 构建编号列表: [1] 法规A 第X条\n内容 (截断800字)
    # 调用 LLM → 解析 "2,5,1,4,3" → [1,4,0,3,2] (0-indexed)
    # 未出现的编号追加到末尾
```

---

### 4.6 query_preprocessor.py — 查询预处理

#### 功能描述
三步预处理：术语归一化（口语→标准）→ LLM 改写 → 同义扩展。基于 `data/synonyms.json` 的 20 组同义词映射。

#### 关键代码

```python
# query_preprocessor.py:62-82 — 预处理流程
def preprocess(self, query):
    normalized = self._normalize(query)       # "退保" → "解除保险合同"
    rewritten = self._rewrite_with_llm(query) # LLM 改写 (>8字符才触发)
    if rewritten and rewritten != normalized:
        normalized = rewritten                # LLM 结果覆盖归一化结果
    expanded = self._expand(normalized)       # 生成同义变体
    return PreprocessedQuery(original, normalized, expanded, did_expand)
```

---

### 4.7 evaluator.py — 量化评估

#### 功能描述
分层评估体系：
- **RetrievalEvaluator**：Precision@K, Recall@K, MRR, NDCG, 冗余率
- **GenerationEvaluator**：RAGAS（faithfulness, answer_relevancy, answer_correctness）或轻量级 token 覆盖率指标

#### 关键代码

```python
# evaluator.py:147-178 — 相关性判断逻辑
def _is_relevant(result, evidence_docs, evidence_keywords):
    # 路径1: 关键词匹配 (需 >=2 个关键词命中)
    # 路径2: source_file 匹配 + 关键词命中
    # 路径3: law_name 匹配 (stem 匹配) + 关键词命中
    # 路径4: law_name 匹配但无关键词 → 直接返回 True ← ⚠️ 可能误判！
```

---

## 五、RAG 评估框架对照分析

基于参考文章《面试官：如何全面地评估一个RAG系统的性能？》的评估维度，逐项对照当前系统实现：

### 5.1 检索阶段评估

| 评估维度 | 文章定义 | 当前实现 | 状态 | 差距分析 |
|---------|---------|---------|------|---------|
| **Precision@K** | 检索结果中相关文档的比例 | ✅ 已实现 | 充分 | `_is_relevant()` 有误判风险（law_name 匹配但无关键词时直接返回 True） |
| **Recall@K** | 所有相关文档被检索到的比例 | ✅ 已实现 | 充分 | 以 `evidence_docs` 数量为分母，合理 |
| **MRR** | 第一个相关文档的排名位置 | ✅ 已实现 | 充分 | 标准实现 |
| **NDCG** | 整个排序列表的质量 | ⚠️ 部分实现 | 基本可用 | 仅支持二值相关性（相关/不相关），不支持多级（非常相关/部分相关） |
| **Context Relevance** | 上下文中对回答有用的内容比例 | ❌ 未实现 | **缺失** | 仅间接通过冗余率反映，但冗余率衡量的是结果间重复度，不是与问题的相关性 |

### 5.2 生成阶段评估

| 评估维度 | 文章定义 | 当前实现 | 状态 | 差距分析 |
|---------|---------|---------|------|---------|
| **Faithfulness** | 回答是否忠实于检索文档，有无幻觉 | ⚠️ 部分实现 | 不足 | RAGAS 可用时可用；轻量级用 token 覆盖率，过于粗糙，无法有效检测幻觉 |
| **Answer Relevance** | 回答是否切题 | ⚠️ 部分实现 | 不足 | RAGAS 可用时可用；轻量级用 Jaccard 相似度，粒度粗 |
| **Answer Correctness** | 回答覆盖标准答案的程度 | ⚠️ 部分实现 | 不足 | RAGAS 可用时可用；轻量级用 token overlap，同义不同词会低估 |

### 5.3 传统 NLP 指标

| 指标 | 文章评价 | 当前实现 | 状态 |
|------|---------|---------|------|
| **BLEU/ROUGE** | 仅看表面文字重叠，不理解语义，只能辅助参考 | ❌ 未实现 | 可选，非必要 |
| **BERTScore** | 用 Embedding 计算语义相似度，但依赖参考答案 | ❌ 未实现 | 可选 |

### 5.4 工程实践

| 维度 | 文章建议 | 当前实现 | 状态 |
|------|---------|---------|------|
| **LLM-as-Judge** | 用 GPT-4 级模型自动评估 | ✅ RAGAS + 智谱 GLM | 充分 |
| **分层评估体系** | 底层细粒度 + 中层端到端 + 上层人工 | ⚠️ 部分实现 | 缺少人工校准闭环 |
| **端到端闭环** | 检索指标 + 生成指标 + 用户反馈 | ⚠️ 部分实现 | 缺少用户反馈机制 |

### 5.5 综合评估矩阵

```
                    检索阶段                生成阶段
                ┌──────────────┐    ┌──────────────┐
                │ Precision@K  │    │ Faithfulness │
                │ Recall@K     │    │ Answer Relev.│
已充分实现 ✅    │ MRR          │    │              │
                │ 冗余率       │    │              │
                └──────────────┘    └──────────────┘

                ┌──────────────┐    ┌──────────────┐
                │ NDCG (仅二值)│    │ Faithfulness │
部分实现 ⚠️     │              │    │ (仅轻量级)   │
                │              │    │ Answer Relev.│
                │              │    │ (仅轻量级)   │
                └──────────────┘    └──────────────┘

                ┌──────────────┐    ┌──────────────┐
完全缺失 ❌     │ Context      │    │              │
                │ Relevance    │    │              │
                └──────────────┘    └──────────────┘
```

---

## 六、潜在问题分析

### 6.1 问题分类汇总

| 类型 | 数量 | 严重性分布 |
|------|------|-----------|
| 🔴 运行时 Bug | 2 | P0/P1 |
| ⚠️ 检索质量问题 | 5 | P1/P2 |
| ⚡ 代码质量问题 | 5 | P2/P3 |
| 🏗️ 设计缺陷 | 4 | P2/P3 |

### 6.2 详细问题列表

---

#### 问题 6.2.1: `get_index_stats()` 方法不存在 — 运行时崩溃

- **文件**: `scripts/lib/rag_engine/data_importer.py:130`
- **类型**: 🔴 Bug
- **严重程度**: P0

**问题描述**:
`RegulationDataImporter.import_all()` 调用 `self.index_manager.get_index_stats()`，但 `VectorIndexManager` 类中不存在该方法。当 `skip_vector=False`（默认值）时会触发 `AttributeError`。

**当前代码**:
```python
# data_importer.py:128-131
if not skip_vector:
    index_stats = self.index_manager.get_index_stats()  # ← 方法不存在！
    logger.info(f"向量索引统计: {index_stats}")
```

**影响分析**:
任何通过 `import_all(skip_vector=False)` 的数据导入都会崩溃。知识库重建管线不可用。

**建议修复**:
在 `VectorIndexManager` 中添加 `get_index_stats()` 方法，或在 `data_importer.py` 中移除该调用。

---

#### 问题 6.2.2: `_ensure_embedding_setup()` 是死代码 — 独立使用时 Embedding 未初始化

- **文件**: `scripts/lib/rag_engine/data_importer.py:43-48`
- **类型**: 🔴 Bug
- **严重程度**: P1

**问题描述**:
`RegulationDataImporter._ensure_embedding_setup()` 方法存在但从未被调用。当 `RegulationDataImporter` 不通过 `RAGEngine` 而是独立使用时，全局 `Settings.embed_model` 不会被设置，导致索引构建使用默认或错误的 embedding 模型。

**当前代码**:
```python
# data_importer.py:43-48
def _ensure_embedding_setup(self) -> None:
    """确保 embedding 模型已配置"""
    if not hasattr(Settings, 'embed_model') or Settings.embed_model is None:
        embed_config = LLMClientFactory.get_embedding_config()
        Settings.embed_model = get_embedding_model(embed_config)
# ← 此方法在 import_all() 中从未被调用
```

**影响分析**:
如果通过 `evaluate_rag.py` 或其他脚本独立使用 `RegulationDataImporter`，向量索引会使用未配置的 embedding 模型，导致检索质量严重下降。

**建议修复**:
在 `import_all()` 中，创建索引前调用 `self._ensure_embedding_setup()`。

---

#### 问题 6.2.3: 上下文窗口硬编码过小 — 检索结果信息丢失

- **文件**: `scripts/lib/rag_engine/rag_engine.py:256-279`
- **类型**: ⚠️ 检索质量
- **严重程度**: P1
- **评估维度**: Context Relevance

**问题描述**:
`_build_qa_prompt()` 将 `max_context_chars` 默认设为 4000 字符。对于复杂的保险法规问题（如 multi_hop 类型），需要引用多条法规条款，4000 字符可能仅能容纳 2-3 条完整条款。超出的检索结果被静默截断或丢弃，无任何日志记录。

**当前代码**:
```python
# rag_engine.py:268-273
if total_chars + len(full_part) > max_chars:
    remaining = max_chars - total_chars - 50
    if remaining > 100:
        truncated_content = content[:remaining] + '……'
        context_parts.append(header + truncated_content)
    break  # ← 后续所有结果直接丢弃
```

**影响分析**:
参考评估框架文章中 **Context Relevance** 的定义——"检索回来的整体上下文中，有多大比例的内容对回答用户问题确实有用"。当前 4000 字符限制导致：
1. 高质量检索结果被丢弃，LLM 无法利用（Context Relevance 实际为零）
2. 条款被截断（`……`），关键数字/规定丢失
3. 无日志记录，问题难以诊断

**建议修复**:
- 将 `max_context_chars` 提升到 8000-10000 字符（GLM-4-flash 支持 128K 上下文）
- 添加日志记录截断事件
- 考虑在 Rerank 阶段就根据上下文预算限制候选数量

---

#### 问题 6.2.4: `_is_relevant()` 相关性判断逻辑缺陷 — 评估指标失真

- **文件**: `scripts/lib/rag_engine/evaluator.py:168-176`
- **类型**: ⚠️ 检索质量
- **严重程度**: P1
- **评估维度**: Precision@K, Recall@K

**问题描述**:
当 `law_name` 与证据文档匹配但 `evidence_keywords` 为空时，函数直接返回 `True`，即使检索结果的内容与问题完全无关。

**当前代码**:
```python
# evaluator.py:168-176
if law_name and evidence_docs:
    for doc in evidence_docs:
        doc_stem = doc.replace('.md', '').replace('_', '')
        if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
            if evidence_keywords:
                if _contains_keyword(content, evidence_keywords):
                    return True
            else:
                return True  # ← 无关键词时，仅匹配 law_name 就算相关！
```

**影响分析**:
如果某些评估样本的 `evidence_keywords` 为空，任何来自同名法规的结果都被判为相关，导致 Precision/Recall 指标虚高，无法真实反映检索质量。

**建议修复**:
移除 `else: return True` 分支，或要求至少有一个弱相关性信号。

---

#### 问题 6.2.5: 检索后过滤导致 Top-K 结果不足

- **文件**: `scripts/lib/rag_engine/rag_engine.py:309-313`
- **类型**: ⚠️ 检索质量
- **严重程度**: P2
- **评估维度**: Recall@K

**问题描述**:
`search()` 方法在混合检索和 Rerank **之后**才应用元数据过滤。如果用户要求 `category="健康险"` 过滤，但 Rerank 后的 Top-K 结果中只有 2 条符合条件，最终只返回 2 条结果。

**当前代码**:
```python
# rag_engine.py:302-313
if use_hybrid:
    results = self._hybrid_search(query_text, top_k, filters)
if filters:
    results = self._apply_filters(results, filters)  # ← 后置过滤
if top_k:
    results = results[:top_k]
```

**影响分析**:
用户可能得到远少于预期的结果。更严重的是，`_hybrid_search()` 内部已将 filters 传递给向量检索侧（生效），但 BM25 侧是全量遍历后过滤。两路结果在 RRF 融合后，再经过一次后置过滤，导致结果数量不可预测。

**建议修复**:
将过滤逻辑下推到检索阶段，或在后置过滤后回溯补充结果。

---

#### 问题 6.2.6: 查询扩展导致 RRF 分数膨胀

- **文件**: `scripts/lib/rag_engine/retrieval.py:90-106`
- **类型**: ⚠️ 检索质量
- **严重程度**: P2
- **评估维度**: NDCG, MRR

**问题描述**:
当查询预处理生成扩展变体时，每个变体都独立执行向量和 BM25 检索，所有结果合并后送入 RRF 融合。同一个 chunk 在多个变体的检索结果中出现多次，每次出现都会累加 RRF 分数。

**当前代码**:
```python
# retrieval.py:103-106
for fv in vector_futures:
    vector_nodes.extend(fv.result())  # ← 直接 extend，无去重
for fk in keyword_futures:
    keyword_nodes.extend(_to_node_with_scores(fk.result()))
# → 同一 chunk 在 vector_nodes 中可能出现多次
```

**影响分析**:
查询扩展本应提高召回率（Recall），但分数膨胀可能导致排序偏差——一个在所有扩展 query 中都出现的普通 chunk 可能排在一个只在原始 query 中出现但高度相关的 chunk 之前（影响 NDCG 和 MRR）。

**建议修复**:
在 RRF 融合前对扩展 query 的结果做归一化处理（如除以扩展 query 数量），或降低扩展结果的权重。

---

#### 问题 6.2.7: LLM Rerank 内容截断丢失关键信息

- **文件**: `scripts/lib/rag_engine/reranker.py:78`
- **类型**: ⚠️ 检索质量
- **严重程度**: P2
- **评估维度**: NDCG, Precision@K

**问题描述**:
Reranker 将每个候选的内容截断到 800 字符。对于保险法规条款，800 字符可能刚好截断到关键数字（如等待期天数、赔付比例）或法律条文的核心规定。

**当前代码**:
```python
# reranker.py:78
truncated = content[:800] if len(content) > 800 else content
```

**影响分析**:
LLM 在不完整的条款内容上做相关性判断，可能产生错误排序。例如，一条包含 "等待期不得超过90天" 的条款，如果 "90天" 在 800 字符之后被截断，LLM 可能认为该条款与等待期问题无关，导致 NDCG 下降。

**建议修复**:
- 将截断长度提升到 1200-1500 字符
- 添加截断标记（如 `[内容已截断]`）让 LLM 知道信息不完整
- 或者只发送条款的首尾各 400 字符（保留开头定义和结尾规定）

---

#### 问题 6.2.8: 轻量级 Faithfulness 评估方式过于粗糙

- **文件**: `scripts/lib/rag_engine/evaluator.py:576-590`
- **类型**: ⚠️ 检索质量
- **严重程度**: P1
- **评估维度**: Faithfulness

**问题描述**:
当 RAGAS 不可用时，`_compute_faithfulness()` 使用 token 覆盖率来衡量忠实度——计算答案中出现在检索上下文中的 token 比例。参考文章中 Faithfulness 的正确定义是"将答案拆分为独立事实性陈述，逐一验证是否被上下文支持"，当前实现有严重偏差：

1. **无法检测幻觉**：如果 LLM 编造了 "等待期为180天"（上下文中是 "90天"），token 覆盖率只会因为 "180" 和 "天" 这两个词而略微降低
2. **Token 级粒度太粗**：中文分词后单个 token（如 "天"、"元"）几乎没有区分度
3. **方向不精确**：计算的是 token 级别的覆盖，而非 claim 级别的验证

**当前代码**:
```python
# evaluator.py:586-590
@staticmethod
def _compute_faithfulness(contexts: List[str], answer: str) -> float:
    """答案 token 对检索上下文 token 的覆盖率"""
    if not contexts:
        return 0.0
    return GenerationEvaluator._token_overlap(' '.join(contexts), answer)
```

**影响分析**:
轻量级 Faithfulness 指标可能给出虚高的分数（如 0.8+），掩盖 LLM 幻觉问题。在 RAGAS 不可用的环境下（如 CI/CD 或离线评估），这个指标几乎无效。

**建议修复**:
- 使用基于 N-gram 的覆盖率（bigram/trigram 而非 unigram）
- 或实现简化的 claim-based 验证：拆分答案为句子，检查每个句子是否能在上下文中找到高相似度的支撑

---

#### 问题 6.2.9: 评估缺少 Context Relevance 指标

- **文件**: `scripts/lib/rag_engine/evaluator.py`
- **类型**: ⚠️ 检索质量
- **严重程度**: P2
- **评估维度**: Context Relevance

**问题描述**:
参考评估框架文章，**Context Relevance** 是 RAG 评估的关键指标——"检索回来的整体上下文中，有多大比例的内容对回答用户问题确实有用"。当前评估体系完全没有这个指标。

当前只有 Redundancy Rate（冗余率）间接反映了上下文质量，但它衡量的是检索结果之间的重复度，而非检索结果与问题的相关性。

**影响分析**:
无法发现"检索了很多 Chunk 但大部分是噪音"的情况。一个 Precision=0.8、Recall=0.6 的检索结果，如果 Context Relevance 很低，说明虽然找对了一些文档，但引入了大量噪声，反而可能干扰 LLM 生成。

**建议修复**:
添加 Context Relevance 指标——可以是 token 级的（上下文中与问题 query 相关的 token 比例），也可以是句子级的（上下文中有多少句子与问题相关）。

---

#### 问题 6.2.10: `ThreadLocalSettings.apply()` 线程安全缺陷

- **文件**: `scripts/lib/rag_engine/rag_engine.py:78-82`
- **类型**: ⚡ 代码质量
- **严重程度**: P2

**问题描述**:
`apply()` 方法将线程本地的 LLM/Embedding 配置写入全局 `Settings` 对象，但没有加锁。

```python
# rag_engine.py:78-82
def apply(self) -> None:
    if hasattr(self._local, 'initialized') and self._local.initialized:
        Settings.llm = self._local.llm       # ← 竞态写入
        Settings.embed_model = self._local.embed_model
```

**影响分析**:
在多线程场景下（如 Web 服务处理并发请求），可能导致一个线程使用了另一个线程的 LLM 配置。

**建议修复**:
在 `apply()` 中添加锁保护。

---

#### 问题 6.2.11: Reranker fallback 路径修改原始数据

- **文件**: `scripts/lib/rag_engine/reranker.py:56-58`
- **类型**: ⚡ 代码质量
- **严重程度**: P3

**问题描述**:
当 LLM Rerank 失败时，fallback 路径直接修改原始 `candidates` 列表中的字典对象（`r['reranked'] = False`），而成功路径使用 `dict(candidate)` 创建了浅拷贝。

```python
# reranker.py:56-58 (fallback)
for r in fallback:
    r['reranked'] = False  # ← 修改原始 dict！

# reranker.py:62-67 (成功路径)
result = dict(candidate)  # ← 浅拷贝，安全
result['rerank_score'] = 1.0 / (rank + 1)
```

**建议修复**:
fallback 路径也使用 `dict(r)` 创建副本。

---

#### 问题 6.2.12: `_detect_unverified_claims()` 覆盖检测逻辑错误

- **文件**: `scripts/lib/rag_engine/attribution.py:106-127`
- **类型**: ⚡ 代码质量
- **严重程度**: P2
- **评估维度**: Faithfulness

**问题描述**:
该函数使用 `re.split(r'\[来源(\d+)\]', answer)` 分割文本后，用索引判断段落是否被引用覆盖。但 `re.split` 的结果是：偶数索引为文本段，奇数索引为捕获组（来源编号数字）。当前代码没有区分文本段和编号残留。

```python
# attribution.py:118
if segment[-1].isdigit():
    continue  # ← "等待期90天" 如果以数字结尾也会被跳过！
```

**影响分析**:
1. 以数字结尾的事实性陈述（如 "等待期为90天"）被误判为引用编号残留而跳过
2. 真正未被引用覆盖的事实性陈述可能被漏检
3. `pos` 变量被计算但从未使用（死代码）

**建议修复**:
重写覆盖检测逻辑，使用 `re.finditer` 计算字符级覆盖范围。

---

#### 问题 6.2.13: 配置类和评估报告类未使用 frozen=True

- **文件**: `scripts/lib/rag_engine/config.py`, `scripts/lib/rag_engine/evaluator.py`
- **类型**: 🏗️ 设计
- **严重程度**: P3

**问题描述**:
`RAGConfig`、`HybridQueryConfig`、`ChunkingConfig`、`RetrievalEvalReport`、`GenerationEvalReport`、`RAGEvalReport` 均未使用 `frozen=True`，违反了 CLAUDE.md 规范。同一模块中的 `EvalSample` 正确使用了 `frozen=True`，风格不一致。

---

#### 问题 6.2.14: 测试断言条件化 — 掩盖失败

- **文件**: `scripts/tests/integration/test_rag_integration.py`
- **类型**: ⚡ 代码质量
- **严重程度**: P2

**问题描述**:
多个集成测试使用 `if results:` 条件断言，测试在检索返回空结果时仍然通过。

```python
# test_rag_integration.py (多处)
results = engine.search("等待期", top_k=5)
if results:  # ← 空结果也通过
    assert any('等待期' in r.get('content', '') for r in results)
```

**影响分析**:
如果检索管线有回归 bug 导致返回空结果，测试仍然通过，无法起到防护作用。

**建议修复**:
使用 `assert results, "检索应返回结果"` 确保非空。

---

#### 问题 6.2.15: BM25 索引未包含在备份中

- **文件**: `scripts/lib/rag_engine/data_importer.py:192`
- **类型**: 🏗️ 设计
- **严重程度**: P3

**问题描述**:
`rebuild_knowledge_base()` 只备份 LanceDB 向量索引，不备份 `bm25_index.pkl`。如果重建失败，BM25 索引丢失，混合检索退化为纯向量检索。

---

#### 问题 6.2.16: `hybrid` 分块策略在 config 中定义但未实现

- **文件**: `scripts/lib/rag_engine/config.py`, `scripts/lib/rag_engine/doc_parser.py`
- **类型**: 🏗️ 设计
- **严重程度**: P3

**问题描述**:
`ChunkingConfig` 验证 `"hybrid"` 为合法策略值，但 `doc_parser.py` 和 `semantic_chunker.py` 都未实现该策略。只有 `"semantic"` 和默认（article-based）被处理。

---

## 七、测试覆盖分析

### 7.1 测试文件清单

| 文件 | 类型 | 覆盖模块 |
|------|------|----------|
| `scripts/tests/integration/test_rag_integration.py` | 集成测试 | 全流程 (文档解析→向量索引→检索→混合搜索) |
| `scripts/tests/unit/test_rag_engine_trust.py` | 单元测试 | QA 提示词模板 (引用格式、专家人设、冲突处理) |
| `scripts/tests/utils/rag_fixtures.py` | 测试夹具 | 共享 fixtures (临时数据库、样本文档、引擎) |

### 7.2 测试覆盖率估算

| 模块 | 覆盖率估算 | 备注 |
|------|-----------|------|
| rag_engine.py | 60% | 核心流程覆盖，边界情况不足 |
| retrieval.py | 40% | 基本检索覆盖，查询扩展路径未测试 |
| fusion.py | 20% | 间接通过集成测试覆盖 |
| reranker.py | 10% | 仅有间接测试，LLM 失败路径未覆盖 |
| query_preprocessor.py | 5% | 几乎无测试 |
| semantic_chunker.py | 30% | 通过数据导入间接测试 |
| bm25_index.py | 30% | 通过集成测试间接覆盖 |
| attribution.py | 5% | 几乎无测试 |
| evaluator.py | 40% | 评估逻辑有测试，轻量级指标未验证 |
| tokenizer.py | 5% | 通过 BM25 间接使用，无独立测试 |

### 7.3 测试建议

1. **reranker 单元测试**：覆盖 LLM 失败 fallback、解析异常输入、截断场景
2. **query_preprocessor 单元测试**：覆盖术语归一化、同义扩展、LLM 失败降级
3. **attribution 单元测试**：覆盖引用解析、未验证陈述检测（特别是以数字结尾的陈述）
4. **fusion 单元测试**：覆盖 RRF 分数计算、去重逻辑、空输入
5. **evaluator 单元测试**：覆盖 `_is_relevant()` 的所有分支、轻量级指标准确性
6. **集成测试改进**：移除条件断言，使用确定性断言

---

## 八、技术债务

### 8.1 已识别的技术债务

| # | 债务描述 | 位置 | 优先级 |
|---|---------|------|--------|
| 1 | `get_index_stats()` 方法缺失导致导入管线崩溃 | data_importer.py:130 → index_manager.py | P0 |
| 2 | `_ensure_embedding_setup()` 死代码 | data_importer.py:43-48 | P1 |
| 3 | 上下文窗口 4000 字符过小 | rag_engine.py:259 | P1 |
| 4 | `_is_relevant()` 无关键词时误判 | evaluator.py:176 | P1 |
| 5 | 轻量级 Faithfulness 过于粗糙 | evaluator.py:576-590 | P1 |
| 6 | `_detect_unverified_claims()` 逻辑错误 | attribution.py:106-127 | P2 |
| 7 | `ThreadLocalSettings.apply()` 无锁保护 | rag_engine.py:78-82 | P2 |
| 8 | 缺少 Context Relevance 评估指标 | evaluator.py | P2 |
| 9 | 检索后过滤导致结果不足 | rag_engine.py:309-313 | P2 |
| 10 | 查询扩展 RRF 分数膨胀 | retrieval.py:90-106 | P2 |
| 11 | Rerank 内容截断 800 字符过小 | reranker.py:78 | P2 |
| 12 | 配置类和报告类未 frozen | config.py, evaluator.py | P3 |
| 13 | 测试条件断言掩盖失败 | test_rag_integration.py | P2 |
| 14 | Embedding fallback 模式重复 8 次 | rag_fixtures.py, test_rag_integration.py | P3 |
| 15 | `__init__.py` 导入时调用 `logging.basicConfig()` | __init__.py:41-45 | P3 |
| 16 | `hybrid` 分块策略未实现 | config.py, doc_parser.py | P3 |

### 8.2 优先级建议

**立即修复（P0）：**
1. 修复 `get_index_stats()` 崩溃 — 影响知识库重建

**短期修复（P1）：**
2. 激活 `_ensure_embedding_setup()` — 影响独立使用场景
3. 提升上下文窗口大小到 8000-10000 — 直接影响回答质量
4. 修复 `_is_relevant()` 误判 — 影响评估准确性
5. 改进轻量级 Faithfulness — 影响离线评估有效性

**中期改进（P2）：**
6. 添加 Context Relevance 指标
7. 修复 `_detect_unverified_claims()` 逻辑
8. 解决查询扩展分数膨胀
9. 提升 Rerank 截断长度
10. 修复测试条件断言

---

## 九、改进建议

### 9.1 检索质量改进

1. **动态上下文预算**: 根据检索结果数量和 LLM 上下文窗口动态调整 `max_context_chars`
2. **查询扩展权重衰减**: 对扩展 query 的 RRF 分数做归一化（除以 query 数量）
3. **Rerank 内容策略优化**: 将 800 字符截断改为首尾保留策略或提升到 1500 字符
4. **添加 Context Relevance 指标**: 在评估中增加上下文相关性度量

### 9.2 代码质量改进

1. **统一 frozen dataclass**: 所有配置和报告类使用 `frozen=True`
2. **提取 Embedding fallback 为共享 fixture**: 消除 8 处重复代码
3. **移除 `__init__.py` 中的 `logging.basicConfig()`**: 避免导入副作用
4. **修复 attribution 覆盖检测**: 使用字符级 span 而非 split 索引

### 9.3 架构改进

1. **将过滤下推到检索层**: 在向量检索和 BM25 检索阶段就应用过滤
2. **实现 `hybrid` 分块策略或移除配置项**: 避免死配置
3. **考虑增量索引更新**: 支持单文档的增删改

---

## 十、总结

### 10.1 主要发现

1. **架构设计合理**: 混合检索（向量+BM25）+ RRF 融合 + LLM Rerank 的 pipeline 是业界推荐的 RAG 架构
2. **中文领域适配充分**: 自定义词典（46术语）、停用词（~100）、同义词映射（20组）覆盖了核心保险术语
3. **优雅降级设计好**: 各模块在依赖缺失或 LLM 失败时都有合理的 fallback
4. **评估体系有框架**: 检索评估指标完整，支持 RAGAS 和轻量级两种模式
5. **但有 2 个运行时 Bug** 和 5 个直接影响检索/生成质量的问题需要修复

### 10.2 RAG 评估框架对照总结

对照参考文章的评估维度：

| 维度类别 | 充分 | 部分 | 缺失 |
|---------|------|------|------|
| 检索阶段 | 4 (Precision, Recall, MRR, 冗余率) | 1 (NDCG) | 1 (Context Relevance) |
| 生成阶段 | 0 | 3 (Faithfulness, Answer Relevancy, Correctness) | 0 |
| 工程实践 | 1 (LLM-as-Judge) | 1 (分层评估) | 1 (人工校准) |
| **合计** | **5** | **5** | **3** |

**最关键的三个差距：**
1. **Context Relevance 完全缺失** — 无法度量"检索上下文中有多少真正有用"
2. **Faithfulness 轻量级实现不可靠** — token 覆盖率无法检测幻觉
3. **NDCG 仅支持二值相关性** — 无法区分"非常相关"和"勉强相关"

### 10.3 关键风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 知识库重建崩溃 (P0) | 无法更新法规数据 | 修复 `get_index_stats()` |
| 上下文窗口过小 (P1) | 复杂问题回答质量下降 | 提升 `max_context_chars` |
| Faithfulness 指标失效 (P1) | 无法检测 LLM 幻觉 | 实现 claim-based 验证 |
| 查询扩展分数膨胀 (P2) | 排序偏差 | RRF 分数归一化 |
| 线程安全缺陷 (P2) | 并发场景配置错乱 | 添加锁保护 |

### 10.4 下一步行动

1. **立即修复** P0 Bug（`get_index_stats()` 缺失）
2. **提升上下文窗口** 到 8000-10000 字符
3. **激活** `_ensure_embedding_setup()` 调用
4. **添加** Context Relevance 评估指标
5. **改进** 轻量级 Faithfulness 为 N-gram 或 claim-based 验证
6. **修复** `_detect_unverified_claims()` 覆盖检测逻辑
7. **补充** 核心模块的单元测试（reranker, preprocessor, attribution）

---

## 附录

### A. 完整文件清单

```
scripts/lib/rag_engine/__init__.py
scripts/lib/rag_engine/rag_engine.py
scripts/lib/rag_engine/config.py
scripts/lib/rag_engine/index_manager.py
scripts/lib/rag_engine/data_importer.py
scripts/lib/rag_engine/doc_parser.py
scripts/lib/rag_engine/semantic_chunker.py
scripts/lib/rag_engine/retrieval.py
scripts/lib/rag_engine/bm25_index.py
scripts/lib/rag_engine/fusion.py
scripts/lib/rag_engine/reranker.py
scripts/lib/rag_engine/query_preprocessor.py
scripts/lib/rag_engine/tokenizer.py
scripts/lib/rag_engine/attribution.py
scripts/lib/rag_engine/evaluator.py
scripts/lib/rag_engine/eval_dataset.py
scripts/lib/rag_engine/llamaindex_adapter.py
scripts/lib/rag_engine/exceptions.py
scripts/lib/rag_engine/data/insurance_dict.txt
scripts/lib/rag_engine/data/stopwords.txt
scripts/lib/rag_engine/data/synonyms.json
scripts/tests/integration/test_rag_integration.py
scripts/tests/unit/test_rag_engine_trust.py
scripts/tests/utils/rag_fixtures.py
scripts/evaluate_rag.py
```

### B. 关键配置

```json
{
  "ollama": { "embed_model": "nomic-embed-text" },
  "llm": { "provider": "zhipu", "model": "glm-4-flash" },
  "regulation_search": { "default_top_k": 5 }
}
```

```python
# 默认 RAG 配置
HybridQueryConfig(
    vector_top_k=20, keyword_top_k=20, rrf_k=60,
    vector_weight=1.0, keyword_weight=1.0,
    enable_rerank=True, rerank_top_k=5
)
ChunkingConfig(
    strategy="semantic", min_chunk_size=200, max_chunk_size=1500,
    target_chunk_size=800, overlap_sentences=3,
    enable_semantic_merge=True, merge_short_threshold=300
)
RAGConfig(
    top_k_results=5, max_context_chars=4000,  # ← 过小
    chunking_strategy="semantic"
)
```

### C. 外部依赖

| 库 | 版本 | 用途 |
|----|------|------|
| llama-index-core | >=0.10.0 | RAG 框架核心 |
| llama-index-vector-stores-lancedb | >=0.1.0 | LanceDB 向量存储 |
| llama-index-llms-ollama | >=0.1.0 | Ollama LLM 适配 |
| llama-index-embeddings-ollama | >=0.1.0 | Ollama Embedding 适配 |
| lancedb | >=0.5.0 | 向量数据库 |
| pyarrow | >=14.0.0 | Arrow 格式 |
| jieba | >=0.42.1 | 中文分词 |
| rank-bm25 | >=0.2.2 | BM25 检索 |
| joblib | - | BM25 索引序列化 |
| ragas | 可选 | RAG 自动化评估 |
| datasets | 可选 | RAGAS 数据格式 |

### D. 参考资料

- [面试官：如何全面地评估一个RAG系统的性能？](https://mp.weixin.qq.com/s/ahOsCECpbQmO0C7elKFyvA)
- RAGAS: Automated Evaluation of Retrieval Augmented Generation
- Reciprocal Rank Fusion (RRF) — Cormack et al., 2009
