# Actuary Sleuth RAG Engine - 知识库建设深度研究报告

生成时间: 2026-03-28
分析范围: `scripts/lib/rag_engine/` — 聚焦知识库构建链路

---

## 执行摘要

本报告深度分析 Actuary Sleuth 项目的 RAG 引擎知识库建设流程，并以微信公众号文章《5000份文档扔进去就算建好知识库了？》提出的五步最佳实践为参照进行评估。

**核心发现：**

- 知识库构建链路为 **Markdown → Parse → Chunk → Embed → Index（LanceDB + BM25）**，架构设计合理，采用两阶段语义分块和混合检索策略
- **已修复的重大问题**：批量 Reranker（消除 20 次串行 LLM 调用）、消除双重分块、提升评估严格度、完善停用词、加权 RRF 融合
- **仍存在 3 个 P0 问题**：Overlap 语义失效、层级路径仅记录当前标题、RegulationNodeParser 未匹配纯文本条款标记
- **5 个 P1 问题**：BM25 pickle 安全风险、`get_index_stats()` 方法不存在、向量/BM25 索引一致性无保障、Embedding 不区分 query/text 模式、`_MAX_CHUNKS_PER_ARTICLE=2` 过于激进
- **总体评价**：知识库建设的「骨架」已搭建完成，但在**内容清洗、层级元数据、索引一致性**三个环节仍需加固

---

## 一、项目概览

### 1.1 模块简介

`scripts/lib/rag_engine/` 是 Actuary Sleuth 项目的法规检索增强生成引擎，提供：

- 知识库构建：法规 Markdown 文档 → 向量索引 + BM25 关键词索引
- 混合检索：向量语义检索 + BM25 关键词检索，RRF 融合 + LLM Rerank
- 问答生成：基于检索结果的 LLM 生成答案
- 评估体系：检索评估 + 生成评估 + 端到端评估

技术栈：LlamaIndex + LanceDB + rank_bm25 + jieba + 智谱 AI (GLM 系列)

### 1.2 目录结构

```
scripts/lib/rag_engine/
├── __init__.py                 # 模块入口，统一导出
├── config.py                   # 配置定义 (RAGConfig, ChunkingConfig, HybridQueryConfig)
├── exceptions.py               # 异常定义
├── data_importer.py            # 数据导入编排（构建入口）
├── doc_parser.py               # 文档解析（策略分发）
├── semantic_chunker.py         # 语义感知分块（核心）
├── index_manager.py            # 向量索引管理
├── vector_store.py             # LanceDB 封装（旧代码，已被 index_manager 取代）
├── bm25_index.py               # BM25 索引管理
├── fusion.py                   # RRF 结果融合
├── retrieval.py                # 检索逻辑（向量+BM25+扩展查询）
├── query_preprocessor.py       # Query 预处理（归一化+扩展+LLM重写）
├── reranker.py                 # LLM 精排
├── tokenizer.py                # 中文分词（jieba + 自定义词典）
├── rag_engine.py               # 统一 RAG 引擎（查询入口）
├── llamaindex_adapter.py       # LLM/Embedding 适配器
├── evaluator.py                # 评估模块
├── eval_dataset.py             # 评估数据集
└── data/
    ├── insurance_dict.txt      # 46 个保险领域术语
    ├── stopwords.txt           # 8 行停用词
    └── synonyms.json           # 20 组同义词映射
```

### 1.3 模块依赖关系

```
data_importer.py (构建入口)
├── doc_parser.py (文档解析)
│   ├── semantic_chunker.py (语义分块)
│   │   └── llamaindex_adapter.py (SemanticSplitterNodeParser)
│   └── RegulationNodeParser (条款分块 - fixed 策略)
├── index_manager.py (向量索引)
│   └── llamaindex_adapter.py (Embedding 模型)
│       └── ZhipuEmbeddingAdapter / OllamaEmbedding
└── bm25_index.py (BM25 索引)
    └── tokenizer.py (jieba 分词)
        └── data/insurance_dict.txt
        └── data/stopwords.txt
```

---

## 二、知识库建设链路分析

### 2.1 完整构建流程

```
references/*.md (14 份法规文档)
       │
       ▼
RegulationDataImporter.import_all()
       │
       ├── Step 1: RegulationDocParser.parse_all()
       │       │
       │       ├── SimpleDirectoryReader.load_data()  → List[Document]
       │       │
       │       └── SemanticChunker.chunk(documents)   → List[TextNode]
       │               │
       │               ├── _split_by_structure()      → 结构分割
       │               ├── _merge_short_segments()    → 短段合并
       │               ├── _split_long_segments()     → 长段拆分
       │               ├── _build_nodes_with_overlap() → Overlap + 元数据
       │               └── _semantic_refine()         → 语义精调 (可选)
       │
       ├── Step 2: VectorIndexManager.create_index()
       │       │
       │       └── VectorStoreIndex(nodes, storage_context)
       │               │
       │               └── LanceDBVectorStore → 持久化到磁盘
       │
       └── Step 3: BM25Index.build(documents, path)
               │
               ├── tokenize_chinese(doc.text) × N  → 分词语料
               ├── BM25Okapi(tokenized_corpus)      → BM25 模型
               └── pickle.dump() → bm25_index.pkl  → 持久化到磁盘
```

### 2.2 构建入口：data_importer.py

`RegulationDataImporter.import_all()` 是知识库构建的编排入口：

```python
# data_importer.py:70-152
def import_all(self, file_pattern="*.md", force_rebuild=False, skip_vector=False):
    # Step 1: 解析文档
    documents = self.parse_documents(file_pattern)
    # Step 2: 向量索引
    if not skip_vector:
        self.import_to_vector_db(documents, force_rebuild)
    # Step 3: BM25 索引
    BM25Index.build(documents, bm25_path)
```

**问题**：向量索引和 BM25 索引使用同一份 `documents` 列表，但创建过程是串行的，如果向量索引创建成功但 BM25 索引创建失败，会导致两个索引不一致。

---

## 三、参考文章五步框架评估

参考文章提出的知识库建设最佳实践五步框架：

| 步骤 | 最佳实践 | 当前实现 | 评估 |
|------|---------|---------|------|
| 1. 多格式解析 | PDF/Word/HTML/Markdown 统一解析 | 仅支持 Markdown | **P2 - 功能局限** |
| 2. 内容清洗 | 去噪、去格式、标准化 | 无清洗步骤 | **P0 - 缺失关键环节** |
| 3. 三层分块 | 结构分块 + 语义分块 + 长度平衡 | 已实现 | **已覆盖** |
| 4. 层级标签 | 完整层级路径 + 元数据 | 实现有缺陷 | **P0 - 层级路径不完整** |
| 5. 模块协调 | 解析-分块-索引的协调一致 | 部分实现 | **P1 - 一致性保障不足** |

---

## 四、核心模块详解

### 4.1 语义分块器 — semantic_chunker.py

**职责**：将法规文档切分为语义完整的 chunk，保留文档结构和层级信息。

#### 两阶段分块策略

**第一阶段：结构分块** `_split_by_structure()`

```python
# semantic_chunker.py:131-177
# 按 #{1,3} 标题和 第X条 条款标记分割
_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+)$')
_ARTICLE_PATTERN = re.compile(r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$')
```

结构分割逻辑：
1. 遇到 `#{1,3}` 标题行 → 刷新当前缓冲，记录新标题
2. 遇到 `第X条` 条款行 → 刷新当前缓冲，记录新条款号
3. 非特殊行 → 追加到当前缓冲

**第二阶段：语义精调** `_semantic_refine()`

```python
# semantic_chunker.py:77-106
splitter = SemanticSplitterNodeParser(
    buffer_size=1,
    breakpoint_percentile_threshold=95,
    embed_model=embed_model,
)
```

对超过 `max_chunk_size`（1500 字符）的 chunk 使用 LlamaIndex 的 SemanticSplitterNodeParser 进行语义边界切分。

#### 后处理管线

```
_split_by_structure()      # 结构分割
       ↓
_merge_short_segments()     # 短段合并 (< 300 字符)
       ↓
_split_long_segments()      # 长段拆分 (> 1500 字符)
       ↓
_build_nodes_with_overlap() # Overlap + 元数据构建
       ↓
_semantic_refine()          # 语义精调 (可选)
```

#### 配置参数

```python
# config.py:31-75
@dataclass
class ChunkingConfig:
    min_chunk_size: int = 200
    max_chunk_size: int = 1500
    target_chunk_size: int = 800
    overlap_sentences: int = 3
    enable_semantic_merge: bool = True
    merge_short_threshold: int = 300
    split_long_chunks: bool = True
```

---

### 4.2 文档解析器 — doc_parser.py

**职责**：加载法规文档并按策略分发到不同分块器。

**策略模式**：
- `semantic`（默认）：使用 `SemanticChunker`
- `fixed`：使用 `RegulationNodeParser`

```python
# doc_parser.py:259-266
if self.chunking_strategy == "semantic":
    text_nodes = self.chunker.chunk(documents)
else:
    text_nodes = self.node_parser._parse_nodes(documents)
```

两种策略都最终返回 `List[Document]`（通过 TextNode → Document 转换）。

#### extract_law_name()

```python
# doc_parser.py:41-71
def extract_law_name(text: str, metadata: dict) -> str:
```

法规名称提取优先级：`metadata['law_name']` > Markdown 标题 > 文件名。包含多条启发式规则：
- 跳过「第X部分」和序号标题
- 按「(」「（」「YYYY年」截断
- 长度 > 5 字符才采纳

---

### 4.3 向量索引 — index_manager.py

**职责**：创建和管理 LanceDB 向量索引。

```python
# index_manager.py:27-62
def create_index(self, documents, force_rebuild=False):
    if not force_rebuild:
        loaded_index = self._load_existing_index()
        if loaded_index:
            return loaded_index

    nodes = [TextNode(text=doc.text, metadata=doc.metadata) for doc in documents]
    self.index = VectorStoreIndex(nodes, storage_context=storage_context)
    return self.index
```

**关键设计**：Document → TextNode 转换后直接传入 `VectorStoreIndex(nodes, ...)`，避免 LlamaIndex 默认的 SentenceSplitter 二次分块（此前已修复的 P0 bug）。

---

### 4.4 BM25 索引 — bm25_index.py

**职责**：构建、持久化和查询 BM25 关键词索引。

```python
# bm25_index.py:32-61
@classmethod
def build(cls, documents, index_path):
    tokenized_corpus = [tokenize_chinese(doc.text) for doc in documents]
    bm25 = BM25Okapi(tokenized_corpus)
    nodes = list(documents)
    cls._save(index, index_path)
```

**检索流程**：query → tokenize_chinese → BM25Okapi.get_scores → top_k 过滤

支持元数据过滤：`filters={'law_name': 'xxx'}` 直接在 BM25 结果上过滤。

---

### 4.5 中文分词 — tokenizer.py

**职责**：基于 jieba 的中文分词，支持保险领域自定义词典和停用词。

```python
# tokenizer.py:60-80
def tokenize_chinese(text: str) -> List[str]:
    tokens = jieba.lcut(text)
    for t in tokens:
        if t in stopwords: continue
        if len(t) == 1 and t not in _SINGLE_CHAR_WHITELIST: continue
        result.append(t)
```

**自定义词典**：46 个保险领域术语（`data/insurance_dict.txt`），如「现金价值」「保证续保」「犹豫期」等。

**停用词**：从 `data/stopwords.txt` 加载（约 150 个），回退到内置最小集（约 45 个）。

**单字白名单**：`{'险', '保', '赔', '费', '额', '期', '率', '金'}` — 保险领域高频单字。

---

### 4.6 Embedding 适配 — llamaindex_adapter.py

**职责**：将自定义 LLM/Embedding 客户端适配到 LlamaIndex 接口。

支持两个 Embedding 提供者：
- **智谱 AI**：`embedding-3` 模型，通过 HTTP API 调用
- **Ollama**：`nomic-embed-text` 模型，本地推理

```python
# llamaindex_adapter.py:155-159
def _get_query_embedding(self, query: str) -> List[float]:
    return self._get_embedding(query)

def _get_text_embedding(self, text: str) -> List[float]:
    return self._get_embedding(query)
```

**两个方法实现完全相同**，不区分 query 和 text 模式。

---

### 4.7 数据文件

| 文件 | 内容 | 用途 |
|------|------|------|
| `insurance_dict.txt` | 46 个保险术语 + 词频 | jieba 自定义词典 |
| `stopwords.txt` | ~150 个停用词（8 行） | 分词过滤 |
| `synonyms.json` | 20 组同义词映射 | Query 预处理（归一化+扩展） |

---

## 五、潜在问题分析

### 5.1 问题分类汇总

| 类型 | 数量 | 严重性分布 |
|------|------|-----------|
| 🔴 P0 Bug | 3 | 影响检索质量 |
| ⚠️ P1 问题 | 5 | 影响稳定性/安全性 |
| 🟡 P2 问题 | 4 | 影响功能完整性 |
| 🔵 P3 问题 | 2 | 代码质量 |

---

### 5.2 P0 级问题

#### 问题 5.2.1: Overlap 在语义精调阶段被破坏

- **文件**: `semantic_chunker.py:62-65`
- **类型**: 🔴 Bug
- **严重程度**: P0

**问题描述**:

构建管线中，overlap 在语义精调**之前**添加，但语义精调会**重新切分** chunk，导致 overlap 被破坏或失效。

```python
# semantic_chunker.py:53-67 — 执行顺序
def _chunk_single_document(self, doc):
    segments = self._split_by_structure(lines, ...)   # 1. 结构分割
    segments = self._merge_short_segments(segments)     # 2. 短段合并
    segments = self._split_long_segments(segments)      # 3. 长段拆分

    nodes = self._build_nodes_with_overlap(segments, ...)  # 4. 添加 overlap ← 在这里

    if self._use_semantic_split:
        nodes = self._semantic_refine(nodes)               # 5. 语义精调 ← 重新切分，破坏 overlap
```

在步骤 4 中，每个 chunk 前面被拼接了前一个 chunk 的最后 3 句话。但步骤 5 的 `SemanticSplitterNodeParser` 会基于嵌入相似度重新切分这些已经加了 overlap 的文本，导致：
1. Overlap 句子可能被切到新的子 chunk 中间，而非位于边界
2. Overlap 区域被重复嵌入，可能影响检索排序
3. 如果精调产生 3+ 个子 chunk，中间的 chunk 不包含任何原始 overlap 信息

**影响分析**:
- Overlap 的设计初衷是保留上下文连续性，但被语义精调破坏后效果不可预测
- 可能导致跨 chunk 边界的信息丢失，影响检索召回率

**建议修复**:
将 overlap 移到语义精调**之后**执行，或者在 `_semantic_refine()` 内部处理 overlap。

---

#### 问题 5.2.2: hierarchy_path 仅记录当前标题，不保留完整层级路径

- **文件**: `semantic_chunker.py:270-275`
- **类型**: 🔴 Bug
- **严重程度**: P0

**问题描述**:

`hierarchy_path` 元数据只记录当前 segment 所属的标题和条款号，不保留标题的层级栈。当一个法规文档有多层标题（如「第一章 > 第二节 > 第X条」）时，level-1 标题会被 level-2/3 标题覆盖。

```python
# semantic_chunker.py:270-275
hierarchy_parts: List[str] = []
if seg['heading']:
    hierarchy_parts.append(seg['heading'])    # 只有当前 heading
if seg['article']:
    hierarchy_parts.append(seg['article'])    # 只有当前条款号
hierarchy_path = ' > '.join(hierarchy_parts)
```

而 `_split_by_structure()` 中，`current_heading` 在每次遇到新标题时被直接覆盖：

```python
# semantic_chunker.py:154-161
if level == 1 and not current_heading:
    current_heading = title     # 第一个 level-1 标题
    continue

current_heading = title          # ← 后续标题直接覆盖！
```

**影响分析**:
- 对于「保险法 > 第二章 > 第二节 > 第X条」这种多层结构，检索结果中的 `hierarchy_path` 可能只显示「第二节 > 第X条」，丢失了「保险法 > 第二章」
- 参考文章强调「层级标签是知识库的导航系统」，不完整的层级路径会影响定位和上下文理解

**建议修复**:
维护一个标题栈 `heading_stack`，每遇到新标题时 push/pop，`hierarchy_path` 使用完整栈路径。

---

#### 问题 5.2.3: SemanticChunker 不匹配纯文本条款标记

- **文件**: `semantic_chunker.py:21-23`
- **类型**: 🔴 Bug
- **严重程度**: P0

**问题描述**:

`SemanticChunker`（默认 semantic 策略）的条款匹配模式要求 `第X条` 前必须有 `#{1,3}` Markdown 标题前缀：

```python
# semantic_chunker.py:21-23
_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
```

这意味着 semantic 策略下，**没有 Markdown 标题前缀的纯文本「第X条」不会被识别为条款标记**，它们会被合并到前一个 segment 中。

相比之下，`RegulationNodeParser`（fixed 策略）的第三个模式可以匹配纯文本 `第X条`：

```python
# doc_parser.py:131
r'^第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
```

两个分块器对条款标记的识别能力不一致。

**影响分析**:
- 如果法规文档的条款标记没有 `#` 前缀（如纯文本格式），semantic 策略会将整段文本作为一个大 chunk
- 实际数据（14 份 `references/*.md`）需要确认是否所有条款都有 `#` 前缀

**建议修复**:
在 `_split_by_structure()` 中增加对纯文本 `第X条` 的匹配，与 `RegulationNodeParser` 保持一致。

---

### 5.3 P1 级问题

#### 问题 5.3.1: BM25 索引使用 pickle 持久化，存在安全风险

- **文件**: `bm25_index.py:74-75, 131-135`
- **类型**: ⚠️ 安全
- **严重程度**: P1

```python
# bm25_index.py:74-75
with open(index_path, 'rb') as f:
    data = pickle.load(f)

# bm25_index.py:131-135
with open(path, 'wb') as f:
    pickle.dump({'bm25': index._bm25, 'nodes': index._nodes}, f)
```

`pickle.load()` 反序列化不受信任的数据可导致任意代码执行。虽然此处文件是系统自建的，但如果攻击者能替换 `bm25_index.pkl` 文件，即可实现 RCE。

此外，pickle 不保证跨版本兼容性。`rank_bm25` 或 Python 升级后，旧索引文件可能无法加载。

**建议修复**:
使用更安全的序列化方式（如 `safetensors`、`joblib`），或至少对 pickle 文件做完整性校验。

---

#### 问题 5.3.2: `get_index_stats()` 方法不存在

- **文件**: `data_importer.py:130`
- **类型**: ⚠️ Bug
- **严重程度**: P1

```python
# data_importer.py:130
index_stats = self.index_manager.get_index_stats()
logger.info(f"索引统计: {index_stats}")
```

`VectorIndexManager` 类（`index_manager.py`）中没有定义 `get_index_stats()` 方法。调用时会抛出 `AttributeError`，但被外层 `import_to_vector_db` 的返回值逻辑吞掉（`stats['vector'] = len(documents)` 已经在此之前执行）。

**影响分析**:
- 每次构建知识库时这行代码都会抛异常，但由于 `import_to_vector_db` 返回 True，不会阻断流程
- 实际上可能被 try-except 捕获，导致静默失败

**建议修复**:
在 `VectorIndexManager` 中添加 `get_index_stats()` 方法，或删除此调用。

---

#### 问题 5.3.3: 向量索引与 BM25 索引无一致性保障

- **文件**: `data_importer.py:122-142`
- **类型**: ⚠️ 设计
- **严重程度**: P1

```python
# data_importer.py:122-142
if not skip_vector:
    if self.import_to_vector_db(documents, force_rebuild):
        stats['vector'] = len(documents)

# BM25 索引独立构建
BM25Index.build(documents, bm25_path)
stats['bm25'] = len(documents)
```

两个索引使用同一份 `documents` 列表，但：
1. 如果向量索引创建成功、BM25 创建失败 → 两个索引不同步
2. 如果部分重建（`force_rebuild=True` 但 BM25 路径写入失败） → 不一致
3. 没有事务性保障或原子性检查

**建议修复**:
在 `import_all()` 结束时校验两个索引的文档数量是否一致，不一致时告警或自动回滚。

---

#### 问题 5.3.4: Embedding 不区分 query 和 text 模式

- **文件**: `llamaindex_adapter.py:155-159`
- **类型**: ⚠️ 性能
- **严重程度**: P1

```python
# llamaindex_adapter.py:155-159
def _get_query_embedding(self, query: str) -> List[float]:
    return self._get_embedding(query)

def _get_text_embedding(self, text: str) -> List[float]:
    return self._get_embedding(query)  # ← 同一个实现
```

智谱 `embedding-3` 模型支持 query/text 两种嵌入模式，通过 API 参数区分。当前实现未利用此特性。

**影响分析**:
- 索引构建时的 text embedding 和查询时的 query embedding 使用相同模式，可能降低检索相关性
- 这是 RAG 系统的常见优化点，区分两种模式通常能显著提升检索质量

**建议修复**:
在 API 调用中添加 `encoding_type` 参数区分 query 和 text 模式。

---

#### 问题 5.3.5: `_MAX_CHUNKS_PER_ARTICLE=2` 去重过于激进

- **文件**: `fusion.py:19`
- **类型**: ⚠️ 设计
- **严重程度**: P1

```python
# fusion.py:19
_MAX_CHUNKS_PER_ARTICLE = 2
```

RRF 融合后按 `(law_name, article_number)` 去重，每条款最多保留 2 个 chunk。

**影响分析**:
- 对于长条款（如超过 1500 字符被拆分为 3+ 个 chunk），第 3 个及之后的 chunk 永远无法出现在结果中
- 如果一个长条款的关键信息恰好在第 3 个 chunk 中，检索将完全遗漏

**建议修复**:
考虑增大到 3-5，或基于 chunk 总长度动态调整。

---

### 5.4 P2 级问题

#### 问题 5.4.1: 无内容清洗步骤

- **文件**: `semantic_chunker.py`, `doc_parser.py`
- **类型**: 🟡 功能缺失
- **严重程度**: P2

参考文章强调「内容清洗是知识库质量的基础」，包括：
- 去除页眉页脚、目录、编号等噪音
- 标准化格式（全角/半角、繁简转换）
- 处理表格、列表等特殊格式

当前实现直接将 Markdown 原文传入分块器，没有任何清洗步骤。如果法规文档中包含目录、页眉页脚等噪音，这些内容会被原样索引。

**建议修复**:
在 `doc_parser.py` 或 `semantic_chunker.py` 中添加预处理步骤，过滤目录、空行、页眉页脚等。

---

#### 问题 5.4.2: 仅支持 Markdown 格式

- **文件**: `doc_parser.py:239-257`
- **类型**: 🟡 功能局限
- **严重程度**: P2

```python
# doc_parser.py:248
md_files = sorted(self.regulations_dir.glob(file_pattern))  # 默认 "*.md"
```

当前仅支持 Markdown 格式的法规文档。实际业务中，法规可能以 PDF、Word、HTML 等格式存在。

**建议修复**:
集成 Unstructured 或 MarkItDown 等多格式解析库。

---

#### 问题 5.4.3: fixed 策略下 chunk 缺少 hierarchy_path 元数据

- **文件**: `doc_parser.py:200-208`
- **类型**: 🟡 功能缺失
- **严重程度**: P2

```python
# doc_parser.py:200-208
return TextNode(
    text=full_content,
    metadata={
        'law_name': law_name,
        'article_number': article_title,
        'category': category,
        'source_file': source_file,
        # ← 缺少 hierarchy_path
    }
)
```

`RegulationNodeParser._create_node()` 构建的 metadata 中没有 `hierarchy_path` 字段。如果使用 fixed 策略构建知识库，检索结果中将缺少层级路径信息。

**建议修复**:
在 `_create_node()` 中添加 `hierarchy_path` 元数据。

---

#### 问题 5.4.4: vector_store.py 是遗留代码，未被主链路使用

- **文件**: `vector_store.py` (376 行)
- **类型**: 🟡 技术债务
- **严重程度**: P2

`VectorDB` 类是一个独立的 LanceDB 封装，使用 `print()` 而非 `logger`，接口设计与 LlamaIndex 不兼容。当前主链路使用 `index_manager.py` + `LlamaIndex LanceDBVectorStore`，`vector_store.py` 已无调用方。

**建议修复**:
标记为废弃或直接删除，减少维护负担。

---

### 5.5 P3 级问题

#### 问题 5.5.1: vector_store.py 全部使用 print() 而非 logger

- **文件**: `vector_store.py` 全文
- **类型**: 🔵 代码质量
- **严重程度**: P3

整个 `vector_store.py` 文件（376 行）中使用 `print()` 输出日志信息，不符合项目日志规范。其他模块均使用 `logging.getLogger(__name__)`。

---

#### 问题 5.5.2: `_merge_short_segments()` 不检查合并后上限

- **文件**: `semantic_chunker.py:179-199`
- **类型**: 🔵 代码质量
- **严重程度**: P3

```python
# semantic_chunker.py:179-199
def _merge_short_segments(self, segments):
    for seg in segments:
        buffer_segments.append(seg)
        buffer_text += ('\n\n' if buffer_text else '') + seg['text']

        if len(buffer_text) >= self.config.merge_short_threshold:
            merged.append(self._combine_segments(buffer_segments, buffer_text))
            buffer_segments = []
            buffer_text = ''
```

合并只检查了下限（`>= merge_short_threshold`），但没有检查合并后是否超过 `max_chunk_size`。如果多个短段连续累积，可能产生超大 chunk。

虽然有后续的 `_split_long_segments()` 兜底，但如果 `split_long_chunks=False`（配置可关闭），则可能产生超大 chunk。

---

## 六、系统流程走查

### 6.1 知识库构建完整流程

```
用户执行 import_all(force_rebuild=True)
       │
       ▼
Step 1: SimpleDirectoryReader.load_data()
  │  读取 references/*.md → 14 个 Document
  │  每个 Document = {text: 完整文档, metadata: {file_name: ...}}
  │
  ▼
Step 2: SemanticChunker.chunk(documents)
  │
  ├── _split_by_structure(lines)
  │    按 #{1,3} 标题 + #{1,3}第X条 切分
  │    输出: List[{text, heading, article, heading_level}]
  │
  ├── _merge_short_segments(segments)
  │    合并 < 300 字符的连续短段
  │
  ├── _split_long_segments(segments)
  │    拆分 > 1500 字符的长段（按句号/分号分割）
  │
  ├── _build_nodes_with_overlap(segments)
  │    为每个 segment 创建 TextNode
  │    拼接前一个 segment 的最后 3 句话作为 overlap
  │    附加元数据: law_name, article_number, category, hierarchy_path, source_file
  │
  └── _semantic_refine(nodes)
       对 > 1500 字符的 node 使用 SemanticSplitterNodeParser 精调
       ⚠️ 此步骤会破坏已添加的 overlap
  │
  ▼
Step 3: VectorIndexManager.create_index(nodes)
  │
  ├── Document → TextNode 转换 (避免双重分块)
  ├── LanceDBVectorStore(uri, table_name)
  ├── VectorStoreIndex(nodes, storage_context)
  │    → 对每个 node 调用 embed_model 获取向量
  │    → 存入 LanceDB
  │
  ▼
Step 4: BM25Index.build(nodes, path)
  │
  ├── 对每个 node 调用 tokenize_chinese(text)
  │    → jieba.lcut + 停用词过滤 + 单字过滤
  ├── BM25Okapi(tokenized_corpus)
  ├── pickle.dump({bm25, nodes}) → bm25_index.pkl
  │
  ▼
完成: stats = {parsed: N, vector: N, bm25: N}
```

### 6.2 关键代码路径

| 步骤 | 文件:行号 | 作用 |
|------|----------|------|
| 文档加载 | `doc_parser.py:248-257` | SimpleDirectoryReader 加载 Markdown |
| 法规名提取 | `doc_parser.py:41-71` | 启发式提取法规名称 |
| 结构分割 | `semantic_chunker.py:131-177` | 按标题/条款分割 |
| 短段合并 | `semantic_chunker.py:179-199` | 合并 < 300 字符短段 |
| 长段拆分 | `semantic_chunker.py:211-253` | 按句子拆分 > 1500 字符长段 |
| Overlap 构建 | `semantic_chunker.py:255-293` | 3 句 overlap + 元数据 |
| 语义精调 | `semantic_chunker.py:77-106` | SemanticSplitterNodeParser |
| 向量索引 | `index_manager.py:27-62` | LanceDB VectorStoreIndex |
| BM25 索引 | `bm25_index.py:32-61` | BM25Okapi + pickle |
| 中文分词 | `tokenizer.py:60-80` | jieba + 自定义词典 |

---

## 七、测试覆盖分析

### 7.1 测试文件清单

| 测试文件 | 覆盖模块 |
|---------|---------|
| `test_semantic_chunker.py` | SemanticChunker |
| `test_doc_parser.py` | RegulationDocParser, RegulationNodeParser |
| `test_bm25_index.py` | BM25Index |
| `test_tokenizer.py` | tokenize_chinese |
| `test_fusion.py` | reciprocal_rank_fusion, _deduplicate |
| `test_reranker.py` | LLMReranker |
| `test_query_preprocessor.py` | QueryPreprocessor |
| `test_config.py` | RAGConfig, ChunkingConfig |
| `test_retrieval.py` | hybrid_search, vector_search |
| `test_evaluator.py` | RetrievalEvaluator |
| `test_rag_engine.py` | RAGEngine |
| `test_index_manager.py` | VectorIndexManager |
| `test_data_importer.py` | RegulationDataImporter |

### 7.2 测试覆盖率估算

| 模块 | 覆盖率 | 备注 |
|------|--------|------|
| semantic_chunker.py | ~70% | 核心分块逻辑有覆盖，但 overlap+semantic_refine 的交互未测试 |
| doc_parser.py | ~60% | 法规名提取有测试，但 fixed 策略缺少 hierarchy_path 测试 |
| bm25_index.py | ~80% | build/load/search 有覆盖 |
| tokenizer.py | ~75% | 分词和过滤有测试 |
| fusion.py | ~85% | RRF 融合和去重有覆盖 |
| index_manager.py | ~50% | 基本创建有测试，但异常路径覆盖不足 |
| data_importer.py | ~40% | 缺少索引一致性测试 |

### 7.3 测试建议

1. **添加 overlap + semantic_refine 交互测试**：验证 overlap 在精调后是否仍有效
2. **添加层级路径完整性测试**：验证多层标题文档的 `hierarchy_path`
3. **添加索引一致性测试**：验证向量索引和 BM25 索引的文档数量匹配
4. **添加大文档边界测试**：验证超长文档（> 10000 字符）的分块行为

---

## 八、技术债务

| 优先级 | 债务描述 | 位置 | 建议处理 |
|--------|---------|------|---------|
| P0 | Overlap 在语义精调后失效 | `semantic_chunker.py:62-65` | 调整执行顺序 |
| P0 | hierarchy_path 不完整 | `semantic_chunker.py:270-275` | 维护标题栈 |
| P0 | 纯文本第X条不被识别 | `semantic_chunker.py:21-23` | 增加无前缀匹配 |
| P1 | pickle 安全/兼容性 | `bm25_index.py:74` | 替换序列化方案 |
| P1 | get_index_stats() 不存在 | `data_importer.py:130` | 添加方法或删除调用 |
| P1 | 索引一致性无保障 | `data_importer.py:122-142` | 添加校验逻辑 |
| P1 | Embedding 不分 query/text | `llamaindex_adapter.py:155-159` | 添加模式区分 |
| P1 | 去重阈值过于激进 | `fusion.py:19` | 增大到 3-5 |
| P2 | 无内容清洗 | `doc_parser.py` | 添加预处理 |
| P2 | 仅支持 Markdown | `doc_parser.py:248` | 集成多格式解析 |
| P2 | fixed 策略缺 hierarchy_path | `doc_parser.py:200-208` | 补充元数据 |
| P2 | 遗留 vector_store.py | `vector_store.py` | 删除或标记废弃 |

---

## 九、改进建议

### 9.1 知识库构建质量提升

1. **添加内容清洗层**（对应参考文章 Step 2）
   - 在 `doc_parser.py` 中增加 `_clean_content()` 方法
   - 过滤目录行（如「目录」「第一章」）、空行、页眉页脚
   - 标准化全角/半角字符

2. **完善层级元数据**（对应参考文章 Step 4）
   - 维护标题栈而非单一变量
   - `hierarchy_path` 应包含完整路径，如「保险法 > 第二章 > 第二节 > 第X条」
   - 添加 `hierarchy_level` 元数据（1=法规, 2=章, 3=节, 4=条）

3. **保障索引一致性**（对应参考文章 Step 5）
   - `import_all()` 结束时校验向量索引和 BM25 索引的文档数量
   - 添加构建版本号，检测索引版本与代码版本是否匹配
   - 失败时自动回滚（删除不完整的索引）

### 9.2 分块策略优化

1. **修复 Overlap 与语义精调的交互**
   - 方案 A：将 overlap 移到语义精调之后
   - 方案 B：在 `_semantic_refine()` 中为子 chunk 保留 overlap

2. **增加纯文本条款匹配**
   - 在 `_split_by_structure()` 中添加对无 `#` 前缀的 `第X条` 的匹配
   - 与 `RegulationNodeParser` 的匹配逻辑保持一致

3. **动态调整去重阈值**
   - 将 `_MAX_CHUNKS_PER_ARTICLE` 改为可配置参数
   - 基于条款长度动态调整（短条款保留 1 个，长条款保留 3-5 个）

### 9.3 安全与稳定性

1. **替换 pickle 序列化**
   - 使用 `joblib` 或 `safetensors` 替代
   - 或对 pickle 文件添加 hash 校验

2. **添加构建健康检查**
   - 构建完成后输出统计报告：chunk 数量、平均长度、长度分布
   - 异常检测：空 chunk、超大 chunk、缺失元数据的 chunk

---

## 十、总结

### 10.1 主要发现

Actuary Sleuth 的 RAG 知识库建设链路整体设计合理，采用了业界推荐的两阶段分块（结构 + 语义）和混合检索（向量 + BM25 + RRF）策略。近期修复的批量 Reranker、消除双重分块等问题显著提升了系统质量。

但仍存在三个核心短板：

1. **内容清洗缺失**：参考文章五步框架中，第二步「内容清洗」完全未实现，文档中的噪音内容会被原样索引
2. **层级元数据不完整**：`hierarchy_path` 只记录当前标题，丢失了上层标题信息，影响检索结果的定位能力
3. **Overlap 与语义精调冲突**：两个机制的执行顺序导致 overlap 被破坏，降低了跨 chunk 边界的信息连续性

### 10.2 关键风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Overlap 失效 | 跨 chunk 边界信息丢失，影响召回率 | 调整执行顺序 |
| 层级路径不完整 | 检索结果无法精确定位到章节 | 维护标题栈 |
| 索引不一致 | 向量和 BM25 结果不匹配 | 添加一致性校验 |
| pickle 安全 | 潜在 RCE 风险 | 替换序列化方案 |

### 10.3 下一步行动

**立即修复（P0）**：
1. 调整 `_chunk_single_document()` 中 overlap 和 semantic_refine 的执行顺序
2. 在 `_split_by_structure()` 中维护标题栈，构建完整 hierarchy_path
3. 在 `_ARTICLE_PATTERN` 中增加对纯文本 `第X条` 的匹配

**短期改进（P1）**：
4. 替换 pickle 序列化方案
5. 修复/删除 `get_index_stats()` 调用
6. 添加索引一致性校验
7. 区分 query/text embedding 模式
8. 增大 `_MAX_CHUNKS_PER_ARTICLE` 阈值

**中期优化（P2）**：
9. 添加内容清洗预处理层
10. 集成多格式文档解析（PDF/Word）
11. 清理遗留的 `vector_store.py`

---

## 附录

### A. 参考文章五步框架对照

| 步骤 | 参考文章要求 | 当前实现 | 差距 |
|------|------------|---------|------|
| 1. 多格式解析 | PDF/Word/HTML/Markdown | 仅 Markdown | 需扩展 |
| 2. 内容清洗 | 去噪、去格式、标准化 | 无 | 需新增 |
| 3. 三层分块 | 结构+语义+长度平衡 | 已实现 | ✅ |
| 4. 层级标签 | 完整路径+元数据 | 有缺陷 | 需修复 |
| 5. 模块协调 | 一致性保障 | 部分实现 | 需加强 |

### B. 关键配置项

```python
# ChunkingConfig (config.py:31-75)
min_chunk_size = 200
max_chunk_size = 1500
target_chunk_size = 800
overlap_sentences = 3
merge_short_threshold = 300

# HybridQueryConfig (config.py:9-27)
vector_top_k = 20
keyword_top_k = 20
rrf_k = 60
vector_weight = 1.0
keyword_weight = 1.0
rerank_top_k = 5

# RAGConfig (config.py:78-143)
chunking_strategy = "semantic"
collection_name = "regulations_vectors"
```

### C. 外部依赖

| 库 | 版本要求 | 用途 |
|----|---------|------|
| llama-index-core | - | RAG 框架 |
| llama-index-vector-stores-lancedb | - | 向量存储 |
| lancedb | - | 嵌入式向量数据库 |
| rank_bm25 | - | BM25 关键词检索 |
| jieba | - | 中文分词 |
| requests | - | HTTP API 调用 |
| pyarrow | - | LanceDB 依赖 |

### D. 数据文件

| 文件 | 行数 | 内容 |
|------|------|------|
| `data/insurance_dict.txt` | 46 行 | 保险领域术语词典 |
| `data/stopwords.txt` | 8 行 | ~150 个停用词 |
| `data/synonyms.json` | 21 行 | 20 组同义词映射 |

### E. 法规文档数据源

`references/` 目录下 14 份 Markdown 格式的保险法规文件（`01_*.md` 至 `14_*.md`），是知识库的原始数据源。
