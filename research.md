# RAG 引擎检索质量深度分析报告

## 一、分析背景

参考《字节面试官怒怼："你的 RAG 系统召回了一堆垃圾，怎么优化？"》一文的 RAG 召回优化全链路方案，从四个维度——Query 理解、离线解析、在线召回、上下文生成——对当前 `scripts/lib/rag_engine/` 模块的检索实现进行全面评估。

当前系统架构：

```
RAGEngine._hybrid_search()
  ├── QueryPreprocessor.preprocess()     ← Query 理解
  ├── vector_search()                    ← 在线召回（向量）
  ├── bm25_index.search()                ← 在线召回（关键词）
  ├── reciprocal_rank_fusion()           ← 结果融合（RRF）
  └── LLMReranker.rerank()               ← 精排
```

## 二、逐模块评估

### 模块一：Query 理解

#### 当前实现

`query_preprocessor.py` 实现了两个功能：

1. **术语归一化** (`_normalize`): 基于 `synonyms.json` 同义词表，将口语化表达替换为标准术语
2. **Query 扩写** (`_expand`): 将标准术语替换为其同义词变体，生成多个 query

#### 发现的问题

##### 问题 1.1: 缺少意图识别 [高优先级]

当前系统完全没有意图识别机制。所有 query 都走同一条检索链路，无法区分：
- **知识库检索类** query（如"等待期有什么规定"）
- **计算类** query（如"帮我算一下赔付金额"）
- **流程操作类** query（如"如何退保"）

文章建议使用三级组合（规则兜底 + ML 主力 + LLM 兜底），当前系统连最简单的规则方法都没有。

**影响**：非检索类 query 会返回低质量的检索结果，浪费计算资源并影响用户体验。

##### 问题 1.2: Query 扩写策略过于简单 [中优先级]

`_expand()` 仅通过简单的字符串替换生成变体（标准术语 → 同义词），缺少：

- **LLM 驱动的 query 重写**：将口语化/模糊的 query 改写为更规范的检索 query
  - 例：用户输入"他们家理赔咋整的"，当前系统无法有效处理
  - 当前系统只能处理已有同义词映射的已知术语
- **指代消解**：多轮对话场景下的指代解析（当前系统没有多轮对话支持）
- **Query 分解**：复杂 query 拆分为多个子 query 分别检索

**当前扩写逻辑的局限**：
```python
# query_preprocessor.py:80-94
def _expand(self, query: str) -> List[str]:
    variants = [query]
    # 仅对 query 中出现的标准术语做同义词替换
    # 无法处理 query 本身就是口语化表达的情况
    # 例如 "学校摔了能报不" 无法被扩写为 "意外伤害保险保障范围"
```

##### 问题 1.3: 停用词过于激进 [中优先级]

`stopwords.txt` 和 `tokenizer.py` 中的停用词列表包含了大量在法规检索场景中可能有意义的词：

- **"规定"、"依照"、"按照"、"根据"、"符合"、"具备"** 被作为停用词过滤
- 这些词在法规文本中频繁出现，作为 query 中的限定条件时（如"**根据**保险法的规定"）是有意义的

同时，`_BUILTIN_STOPWORDS` 中还包含：
- **"怎么"、"如何"** — 这些词在意图识别中有用
- **"应该"、"需要"、"必须"** — 法规中常见的义务性表述

##### 问题 1.4: 没有 HyDE（假设文档增强）[低优先级]

文章提到 HyDE 可以有效改善短 query 的检索质量——通过 LLM 生成假设答案文档，用其 embedding 去检索而非用短 query embedding。当前系统没有此机制。

**影响**：对于"报销制度"这类极短 query，向量检索精度有限。

---

### 模块二：离线解析

#### 当前实现

- `doc_parser.py`: 支持 Markdown 文档解析，有两种分块策略（`semantic` 和 `fixed`）
- `semantic_chunker.py`: 两阶段分块——结构分块 + 语义精调
- `tokenizer.py`: jieba 分词 + 自定义词典 + 停用词过滤

#### 发现的问题

##### 问题 2.1: VectorIndexManager 中 SentenceSplitter 与 SemanticChunker 冲突 [高优先级]

`index_manager.py:27-31` 中：
```python
Settings.text_splitter = SentenceSplitter(
    chunk_size=self.config.chunk_size,  # 默认 1000
    chunk_overlap=self.config.chunk_overlap,  # 默认 100
    separator="\n\n",
)
```

当使用 `semantic` 分块策略时，`RegulationDataImporter` 先用 `SemanticChunker` 将文档分好块（Document 级别），然后传给 `VectorIndexManager.create_index()`。但 `VectorIndexManager.__init__` 会设置全局 `Settings.text_splitter = SentenceSplitter`。

LlamaIndex 的 `VectorStoreIndex.from_documents()` 在构建索引时，如果检测到文档是 Document 类型，可能会再次使用 `Settings.text_splitter` 进行二次分块，导致已经精心切分的语义 chunk 被再次切割。

**影响**：离线阶段精心设计的语义分块可能被二次破坏，chunk 质量下降。

##### 问题 2.2: 语义分块器中的 embedding 调用开销 [中优先级]

`SemanticChunker._semantically_similar()` 和 `_semantic_refine()` 都会调用 embedding 模型：

- **合并判断** (`_merge_short_segments`): 每对相邻 segment 都做一次 embedding + 余弦相似度计算
- **语义精调** (`_semantic_refine`): 对超过 `_max_size` 的节点用 `SemanticSplitterNodeParser` 分割

**问题**：
1. 合并判断阶段对每对 segment 分别调用 `get_text_embedding`（单条请求），没有利用批量 API
2. 如果 embedding 服务是远程 API（如智谱 embedding-3），大量单条请求会导致严重延迟
3. `_semantic_refine` 依赖 `SemanticSplitterNodeParser`，它内部也需要大量 embedding 调用

##### 问题 2.3: overlap 仅在同一章节内生效 [低优先级]

`semantic_chunker.py:330-331`：
```python
if self._overlap_sentences > 0 and i > 0:
    if self._same_section(segments[i - 1], seg):
        # 仅在同一章节内才添加 overlap
```

章节边界处没有 overlap，可能导致跨章节的语义断裂。

##### 问题 2.4: 仅支持 Markdown 格式 [中优先级]

当前系统只解析 `*.md` 文件。如果法规来源包含 PDF、Word 等格式，需要先手动转换为 Markdown。对于 PDF 多栏排版、扫描件 OCR 等问题完全没有处理能力。

**注意**：这可能是当前项目的有意设计选择（法规文档已全部转换为 Markdown），但如果未来需要接入更多数据源，将成为瓶颈。

##### 问题 2.5: 层级信息保留不完整 [低优先级]

`hierarchy_path` 元数据格式为 `法规名 > 章节 > 标题 > 条款号`，但：
- 没有保存层级深度信息（level）
- chunk 中没有保存其在原文中的位置信息（字符偏移量）
- 无法支持"定位到原文"的功能

---

### 模块三：在线召回

#### 当前实现

- `retrieval.py`: 混合检索（向量 + BM25），使用 `ThreadPoolExecutor` 并行执行
- `fusion.py`: RRF (Reciprocal Rank Fusion) 融合，按 `(law_name, article_number)` 去重
- `reranker.py`: LLM-as-Judge 精排，4 级评分（0-3）

#### 发现的问题

##### 问题 3.1: Reranker 使用 LLM 而非 Cross-Encoder [高优先级]

`reranker.py` 使用 LLM (generate API) 做精排，存在严重问题：

1. **延迟极高**：每个候选文档都需要一次 LLM 调用（串行执行），假设 20 个候选文档，LLM 调用需要 20 × 2-5s = 40-100s
2. **评分粒度粗糙**：仅 4 级评分（0-3），区分度不足
3. **评分解析脆弱**：`_parse_score` 只取第一个数字字符，如果 LLM 返回 "3分，因为..." 会得到 3，但如果返回 "相关性评分为 3" 会得到 3（第一个数字字符），如果返回 "这个条款是 1 分" 也会得到 1
4. **截断丢失信息**：content 超过 500 字符会被截断 (`content[:500] + "..."`)，可能丢失关键信息
5. **没有批量推理**：串行处理每个候选，无法利用 batch 推理

代码中已标注 `后续可替换为 Cross-Encoder 实现（sentence-transformers）`，说明开发者已意识到此问题。

**文章建议**：使用 Cross-Encoder（如 BGE-reranker-base）做精排，精度更高且延迟更低。

##### 问题 3.2: RRF 融合没有加权 [中优先级]

`fusion.py` 的 RRF 实现对向量和 BM25 两路结果给相同权重：

```python
for result_list in (vector_results, keyword_results):
    for rank, scored in enumerate(result_list):
        scores[key] += 1.0 / (k + rank + 1)
```

文章建议根据场景调整权重（如短 query 场景下关键词更重要，可设向量 0.3、文本 0.7）。当前实现不支持加权 RRF。

**影响**：对于"车险理赔流程"这类 query，BM25 的精确匹配应给更高权重，但当前无法调节。

##### 问题 3.3: 检索候选集太小 [中优先级]

`HybridQueryConfig` 默认值：
- `vector_top_k = 5`
- `keyword_top_k = 5`

文章建议粗召回阶段取 Top 50-100，精排后取 Top 5-10。当前系统直接从 Top 5 的候选集中做精排，精排的优化空间非常有限。

**影响**：如果真正相关的文档排在第 6-10 位，精排根本无法将其提上来。

##### 问题 3.4: 去重策略过于激进 [高优先级]

`fusion.py:19-26`：
```python
def _deduplicate_by_article(results):
    seen = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', '未知'))
        if key not in seen or r.get('score', 0) > seen[key].get('score', 0):
            seen[key] = r
    return list(seen.values())
```

按 `(law_name, article_number)` 去重，只保留 RRF 分数最高的一个 chunk。问题：

1. **同一法规同一条款可能被分成多个 chunk**（语义分块后），去重会丢弃其他 chunk
2. **长条款的不同部分可能各自包含不同关键信息**，去重后只保留一个可能丢失信息
3. **RRF 分数最高的不一定是最相关的 chunk**（RRF 分数反映的是在两路检索中的排名，不直接反映相关性）

##### 问题 3.5: BM25 索引的 query 预处理与文档预处理不对称 [中优先级]

BM25 搜索时，query 的分词使用 `tokenize_chinese(query)`（`bm25_index.py:107`），但 query 在进入 BM25 搜索前已经被 `QueryPreprocessor._normalize()` 处理过（术语归一化）。

问题在于：**文档侧的分词是在索引构建时完成的**，使用的是原始文档文本。如果 query 被归一化后的术语与文档中的原始术语不一致（虽然同义词替换应该向标准术语看齐），可能导致 BM25 匹配失败。

例如：
- 文档中有"保险销售"（原始文本）
- query "怎么推销保险" → 归一化后变成 "怎么保险销售保险"（"推销"→"保险销售"）
- 但 BM25 搜索时会对归一化后的 query 再分词，可能产生不同的 token

##### 问题 3.6: 向量检索没有 metadata pre-filtering 优化 [低优先级]

`vector_search()` 使用 LlamaIndex 的 `ExactMatchFilter`，但向量检索时 filter 是作为 post-filter 还是 pre-filter 取决于底层实现。如果 LanceDB 不支持高效的 pre-filtering，所有 top_k 结果都在全量向量上搜索后再过滤，效率较低。

##### 问题 3.7: 扩写 query 的检索结果直接合并，没有 score 衰减 [低优先级]

`retrieval.py:94-100`：扩写 query 的检索结果直接 extend 到原始结果列表中，所有结果在 RRF 中平等竞争排名。这意味着扩写 query 返回的不相关结果可能干扰原始 query 的排序。

**文章建议**：对扩写 query 的结果应给予较低权重或做 score 衰减。

---

### 模块四：上下文生成

#### 当前实现

`rag_engine.py` 中的 `_build_qa_prompt()` 构建简单的 prompt，将检索结果格式化为上下文。

#### 发现的问题

##### 问题 4.1: 上下文窗口没有长度控制 [中优先级]

```python
def _build_qa_prompt(self, question, search_results):
    context_parts = []
    for i, result in enumerate(search_results, 1):
        # 没有对 context 总长度做限制
        context_parts.append(f"{i}. 【{law_name}】{article}\n{content}")
    context = "\n\n".join(context_parts)
    return _QA_PROMPT_TEMPLATE.format(context=context, question=question)
```

如果检索返回 5 个长 chunk，总 context 可能超过 LLM 的有效处理窗口，导致：
- LLM 无法充分利用所有上下文
- 响应延迟增加
- Token 费用增加

**建议**：添加 context 总长度上限，超过时截断或减少 chunk 数量。

##### 问题 4.2: Prompt 模板缺少 few-shot 示例 [低优先级]

当前 QA prompt 模板是简单的指令式，没有 few-shot 示例。对于复杂的多跳推理问题（如评估数据集中的 MULTI_HOP 类型），few-shot 示例可以显著提升答案质量。

---

### 模块五：评估体系

#### 当前实现

- `evaluator.py`: 支持 Precision@K, Recall@K, MRR, NDCG, 冗余率
- `eval_dataset.py`: 30 条评估样本，覆盖 factual/multi_hop/negative/colloquial 四种题型

#### 发现的问题

##### 问题 5.1: 相关性判断过于宽松 [高优先级]

`evaluator.py:141-163` 的 `_is_relevant()` 函数：

```python
def _is_relevant(result, evidence_docs, evidence_keywords):
    # 1. source_file 匹配 → 相关
    if source_file and source_file in doc_set:
        return True
    # 2. 关键词匹配 → 相关（仅要求 len(kw) >= 2）
    if any(kw in content for kw in evidence_keywords if len(kw) >= 2):
        return True
    # 3. law_name 子串匹配 → 相关
    if law_name:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and doc_stem in law_name:
                return True
```

问题：
1. **source_file 匹配过于粗粒度**：只要 chunk 来自正确的文件就判定为相关，但一个文件可能包含几百个 chunk，大部分可能与具体问题无关
2. **关键词子串匹配过于宽松**：`"的"` 被过滤了但 `"规定"`（2 字符）不会被过滤，而"规定"在法规文档中几乎每段都有
3. **没有考虑相关性程度**：只做二值判断（相关/不相关），对排序质量评估不敏感

##### 问题 5.2: 评估数据集覆盖不足 [中优先级]

当前评估数据集 30 条样本，对于正式评估来说样本量偏小。且缺少：
- **时效性查询**（如"最新的理赔流程"）— 文章特别提到的问题
- **数值精确匹配**（如"免赔额 5000 元"）
- **专有名词/编号查询**（如"国寿福条款"）

---

### 模块六：架构与工程问题

##### 问题 6.1: VectorDB 类存在但未在主流程中使用 [低优先级]

`vector_store.py` 实现了独立的 `VectorDB` 类（直接操作 LanceDB），但主流程通过 LlamaIndex 的 `LanceDBVectorStore` 间接使用 LanceDB。`VectorDB` 类看起来是早期的独立实现，目前已冗余。

##### 问题 6.2: Reranker 串行调用 LLM [高优先级 - 性能]

```python
# reranker.py:56-59
for candidate in candidates:
    score = self._score_relevance(query, candidate)
    scored.append((candidate, score))
```

串行调用 LLM 对每个候选打分，是系统最大的性能瓶颈。

##### 问题 6.3: ThreadLocalSettings 的全局状态管理复杂 [低优先级]

`rag_engine.py` 中的 `ThreadLocalSettings` 试图解决 LlamaIndex 全局 `Settings` 的线程安全问题，但实现复杂且容易出错。如果多个 RAGEngine 实例使用不同的 LLM 配置，可能出现状态混乱。

##### 问题 6.4: embedding 模型选择有限 [中优先级]

`llamaindex_adapter.py` 仅支持两种 embedding provider：
- `zhipu` (embedding-3)
- `ollama` (nomic-embed-text)

文章建议中文场景优先使用 BGE-M3，当前系统不支持。对于保险领域这种垂直场景，通用 embedding 模型对专业术语的理解可能不够准确。

##### 问题 6.5: 没有 embedding 缓存 [中优先级]

无论是离线阶段（分块 embedding）还是在线阶段（query embedding），都没有缓存机制。文章建议对常见 query 的 embedding 结果缓存到 Redis，避免重复 API 调用。

---

## 三、问题优先级总结

### P0 - 必须修复（直接影响检索质量）

| # | 问题 | 模块 | 影响 |
|---|------|------|------|
| 1 | SentenceSplitter 与 SemanticChunker 冲突导致二次分块 | 离线解析 | 精心设计的语义 chunk 被破坏 |
| 2 | Reranker 使用 LLM 串行精排，延迟极高且评分粗糙 | 在线召回 | 检索端到端延迟 40-100s |
| 3 | 检索候选集太小（vector_top_k=5, keyword_top_k=5） | 在线召回 | 精排优化空间有限 |
| 4 | 去重策略过于激进（按法规+条款号去重） | 在线召回 | 相关 chunk 被丢弃 |

### P1 - 建议修复（显著影响检索质量）

| # | 问题 | 模块 | 影响 |
|---|------|------|------|
| 5 | 停用词包含法规检索中有意义的词 | Query 理解 | 关键检索词被过滤 |
| 6 | 缺少意图识别 | Query 理解 | 非 query 类型无法正确路由 |
| 7 | Query 扩写策略过于简单 | Query 理解 | 口语化 query 检索效果差 |
| 8 | RRF 融合不支持加权 | 在线召回 | 无法根据场景调整检索策略 |
| 9 | 评估相关性判断过于宽松 | 评估 | 评估结果不准确，无法指导优化 |
| 10 | 上下文窗口没有长度控制 | 生成 | 长 context 浪费 token 并降低质量 |

### P2 - 可选优化

| # | 问题 | 模块 | 影响 |
|---|------|------|------|
| 11 | 语义分块器 embedding 调用未批量化 | 离线解析 | 索引构建速度慢 |
| 12 | 没有 HyDE | Query 理解 | 短 query 向量检索精度有限 |
| 13 | 仅支持 Markdown | 离线解析 | 数据源扩展受限 |
| 14 | embedding 模型选择有限 | 架构 | 领域术语理解不足 |
| 15 | 没有 embedding 缓存 | 架构 | 重复 API 调用浪费资源 |
| 16 | 扩写 query 结果无 score 衰减 | 在线召回 | 扩写噪声干扰排序 |
| 17 | VectorDB 类冗余 | 架构 | 代码维护负担 |

## 四、与文章最佳实践对照

| 文章建议 | 当前状态 | 差距 |
|---------|---------|------|
| 混合检索（向量+BM25） | ✅ 已实现 | - |
| RRF 融合 | ✅ 已实现 | 不支持加权 |
| Rerank 精排 | ⚠️ 用 LLM 替代 Cross-Encoder | 精度低、延迟高 |
| Query 意图识别 | ❌ 未实现 | 完全缺失 |
| Query 重写（LLM 驱动） | ❌ 未实现 | 仅有同义词替换 |
| Query 扩写 | ⚠️ 部分实现 | 仅基于同义词，无 LLM 驱动 |
| HyDE | ❌ 未实现 | - |
| 语义分块 | ✅ 已实现 | 有二次分块 bug |
| 重叠窗口 | ✅ 已实现 | 仅同章节内 |
| 层级信息保留 | ⚠️ 部分实现 | 缺少位置信息 |
| Embedding 缓存 | ❌ 未实现 | - |
| 全链路异步流水线 | ❌ 未实现 | 有部分 ThreadPoolExecutor |
| 量化评估（MRR/NDCG） | ✅ 已实现 | 相关性判断不够准确 |
