# Actuary Sleuth RAG Engine - 综合改进方案

生成时间: 2026-03-29
源文档: research.md

本方案基于 research.md 的全面分析内容生成，包含 16 个问题的修复方案、测试改进计划、技术债务清理方案。

---

## 一、问题修复方案

---

### 🔴 运行时 Bug (P0/P1 - 必须修复) ✅

---

#### 问题 1.1: [P0] `get_index_stats()` 方法不存在 — 知识库重建崩溃 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data_importer.py:130`
- **函数**: `RegulationDataImporter.import_all()`
- **严重程度**: 🔴 P0
- **影响范围**: 任何通过 `import_all(skip_vector=False)` 的数据导入都会触发 `AttributeError`，知识库重建管线完全不可用

##### 当前代码
```python
# data_importer.py:128-131
if not skip_vector:
    index_stats = self.index_manager.get_index_stats()
    logger.info(f"向量索引统计: {index_stats}")
```

##### 修复方案
在 `VectorIndexManager` 中添加 `get_index_stats()` 方法，返回索引的文档数量和向量维度信息。同时在 `data_importer.py` 的 `import_all()` 中激活 `_ensure_embedding_setup()` 调用。

##### 代码变更

**文件 1: `scripts/lib/rag_engine/index_manager.py`** — 新增方法

```python
# index_manager.py — 在 VectorIndexManager 类末尾添加
    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        stats: Dict[str, Any] = {}
        if self.index is not None:
            try:
                from llama_index.core import VectorStoreIndex
                if isinstance(self.index, VectorStoreIndex):
                    stats['index_type'] = 'VectorStoreIndex'
                    stats['storage_context'] = str(type(self.index.storage_context).__name__)
            except Exception:
                pass
            stats['initialized'] = True
        else:
            stats['initialized'] = False
        return stats
```

**文件 2: `scripts/lib/rag_engine/data_importer.py`** — 修复 import_all()

```python
# data_importer.py — 修复 import_all() 方法中的两个问题
        if not skip_vector:
            self._ensure_embedding_setup()
            index = self.import_to_vector_db(documents, force_rebuild)
            if index is not None:
                stats['vector'] = len(documents)
                index_stats = self.index_manager.get_index_stats()
                logger.info(f"向量索引统计: {index_stats}")
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/index_manager.py` |
| 修改 | `scripts/lib/rag_engine/data_importer.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 在 VectorIndexManager 中添加 get_index_stats() | 完整实现，可扩展 | 需要了解 LlamaIndex 内部结构 | ✅ |
| B: 删除 data_importer.py 中的调用 | 最简单 | 丢失索引统计信息 | ❌ |
| C: 用 try-except 包裹调用 | 容错性好 | 隐藏潜在问题 | ❌ |

##### 测试建议
```python
def test_get_index_stats_returns_dict():
    manager = VectorIndexManager(RAGConfig())
    stats = manager.get_index_stats()
    assert isinstance(stats, dict)
    assert 'initialized' in stats
```

##### 验收标准
- [ ] `import_all(skip_vector=False)` 不再抛出 `AttributeError`
- [ ] `get_index_stats()` 返回包含 `initialized` 键的字典
- [ ] 日志输出包含索引统计信息

---

#### 问题 1.2: [P1] `_ensure_embedding_setup()` 死代码 — 独立使用时 Embedding 未初始化 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data_importer.py:43-48`
- **函数**: `RegulationDataImporter._ensure_embedding_setup()`
- **严重程度**: 🔴 P1
- **影响范围**: 独立使用 `RegulationDataImporter` 时（如 `evaluate_rag.py`），向量索引使用未配置的 embedding 模型

##### 修复方案
此问题与问题 1.1 合并修复。在 `import_all()` 的向量索引构建前添加 `self._ensure_embedding_setup()` 调用。代码变更见问题 1.1 的文件 2 修改。

##### 验收标准
- [ ] `import_all()` 在创建向量索引前调用 `_ensure_embedding_setup()`
- [ ] 独立使用 `RegulationDataImporter` 时 `Settings.embed_model` 被正确设置
- [ ] `_ensure_embedding_setup()` 只执行一次（幂等性）

---

### ⚠️ 检索质量问题 (P1/P2 - 尽快修复) ✅

---

#### 问题 2.1: [P1] 上下文窗口硬编码过小 — 检索结果信息丢失 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:256-279`
- **函数**: `RAGEngine._build_qa_prompt()`
- **严重程度**: ⚠️ P1
- **评估维度**: Context Relevance
- **影响范围**: 复杂问题（multi_hop）的回答质量，高质量检索结果被静默丢弃

##### 当前代码
```python
# rag_engine.py:259
max_chars = self.config.max_context_chars  # 默认 4000
```

```python
# config.py — RAGConfig 中的默认值
max_context_chars: int = 4000
```

##### 修复方案
将 `max_context_chars` 默认值从 4000 提升到 8000，并在 `_build_qa_prompt()` 中添加截断日志。

##### 代码变更

**文件 1: `scripts/lib/rag_engine/config.py`** — 修改默认值

```python
# config.py:77-143 — RAGConfig 类
@dataclass
class RAGConfig:
    regulations_dir: str = "./references"
    vector_db_path: Optional[str] = None
    chunk_size: int = 1000
    chunk_overlap: int = 100
    chunking_strategy: str = "semantic"
    chunking_config: Optional[ChunkingConfig] = None
    top_k_results: int = 5
    enable_streaming: bool = False
    hybrid_config: HybridQueryConfig = None
    collection_name: str = "regulations_vectors"
    max_context_chars: int = 8000  # 从 4000 提升到 8000
    enable_faithfulness: bool = True
```

**文件 2: `scripts/lib/rag_engine/rag_engine.py`** — 添加截断日志

```python
# rag_engine.py:256-279 — 修改 _build_qa_prompt 方法
    def _build_qa_prompt(self, question: str, search_results: List[Dict[str, Any]]) -> tuple[str, int]:
        context_parts: List[str] = []
        total_chars = 0
        max_chars = self.config.max_context_chars

        for i, result in enumerate(search_results, 1):
            law_name = result.get('law_name', '未知法规')
            article = result.get('article_number', '')
            content = result.get('content', '')
            header = f"{i}. 【{law_name}】{article}\n"
            full_part = header + content

            if total_chars + len(full_part) > max_chars:
                remaining = max_chars - total_chars - 50
                if remaining > 100:
                    truncated_content = content[:remaining] + '……'
                    context_parts.append(header + truncated_content)
                    logger.info(
                        f"上下文截断: 条款 [{law_name}]{article} 从 {len(content)} 字符截断到 {remaining} 字符, "
                        f"丢弃后续 {len(search_results) - i} 条结果"
                    )
                else:
                    logger.info(
                        f"上下文空间不足，丢弃条款 [{law_name}]{article} 及后续 {len(search_results) - i} 条结果"
                    )
                break

            context_parts.append(full_part)
            total_chars += len(full_part)

        context = "\n\n".join(context_parts)
        return _QA_PROMPT_TEMPLATE.format(context=context, question=question), len(context_parts)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/config.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 提升默认值到 8000 | 简单直接，兼容现有配置 | 可能增加 token 消耗 | ✅ |
| B: 动态预算（根据模型上下文窗口） | 自适应 | 复杂，需获取模型配置 | ⏳ |
| C: 按 top_k 结果数自动调整 | 无需配置 | 不可预测，可能超出窗口 | ❌ |

##### 注意事项
- GLM-4-flash 支持 128K 上下文，8000 字符远在安全范围内
- 已有 Rerank 限制 `rerank_top_k=5`，实际进入 prompt 的结果通常不超过 5 条
- 用户可通过 `RAGConfig(max_context_chars=...)` 覆盖默认值

##### 验收标准
- [ ] `max_context_chars` 默认值为 8000
- [ ] 截断发生时输出 INFO 级别日志，包含被截断的法规名和条款号
- [ ] 5 条平均长度的法规条款（每条约 1000 字符）可以完整放入上下文
- [ ] 已有测试不受影响

---

#### 问题 2.2: [P1] `_is_relevant()` 相关性判断逻辑缺陷 — 评估指标失真 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:168-176`
- **函数**: `_is_relevant()`
- **严重程度**: ⚠️ P1
- **评估维度**: Precision@K, Recall@K
- **影响范围**: 当评估样本的 `evidence_keywords` 为空时，Precision/Recall 虚高

##### 当前代码
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
                return True  # ← 无关键词时直接返回 True
```

##### 修复方案
移除 `else: return True` 分支。当无关键词且 law_name 匹配时，要求 `source_file` 也匹配才算相关。

##### 代码变更

**文件: `scripts/lib/rag_engine/evaluator.py`** — 修改 `_is_relevant()` 函数

```python
# evaluator.py:147-178 — 替换整个函数
def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    if evidence_keywords:
        long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
        matched = sum(1 for kw in long_keywords if kw in content)
        required = min(2, len(long_keywords))
        if matched >= required:
            return True

    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set and evidence_keywords:
        if _contains_keyword(content, evidence_keywords):
            return True

    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if _contains_keyword(content, evidence_keywords):
                        return True
                elif source_file and source_file in doc_set:
                    return True

    return False
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/evaluator.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 移除 else 分支，要求 source_file 也匹配 | 严格，避免误判 | 可能漏判无关键词但确实相关的结果 | ✅ |
| B: 保留 else 但增加条款号匹配要求 | 更灵活 | 复杂度增加 | ❌ |
| C: 对无关键词样本跳过评估 | 简单 | 丢失评估覆盖 | ❌ |

##### 验收标准
- [ ] 当 `evidence_keywords` 为空时，仅 `law_name` 匹配不再返回 True
- [ ] 当 `evidence_keywords` 为空且 `source_file` 匹配时，返回 True
- [ ] 当 `evidence_keywords` 非空时，行为不变
- [ ] 已有测试通过

---

#### 问题 2.3: [P1] 轻量级 Faithfulness 评估方式过于粗糙 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:576-590`
- **函数**: `GenerationEvaluator._compute_faithfulness()`
- **严重程度**: ⚠️ P1
- **评估维度**: Faithfulness
- **影响范围**: RAGAS 不可用时的离线评估几乎无效

##### 当前代码
```python
# evaluator.py:586-590
@staticmethod
def _compute_faithfulness(contexts: List[str], answer: str) -> float:
    """答案 token 对检索上下文 token 的覆盖率"""
    if not contexts:
        return 0.0
    return GenerationEvaluator._token_overlap(' '.join(contexts), answer)
```

##### 修复方案
将 token 级覆盖率改为 bigram 级覆盖率。bigram 比 unigram 更能捕捉事实性陈述（如 "90天"、"等待期"），且计算成本仍然很低。

##### 代码变更

**文件: `scripts/lib/rag_engine/evaluator.py`** — 替换三个方法

```python
# evaluator.py — 替换 _token_overlap, _compute_faithfulness, _compute_correctness
    @staticmethod
    def _token_bigrams(text: str) -> Set[str]:
        """提取文本的 bigram 集合"""
        tokens = tokenize_chinese(text)
        return {tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1)} if len(tokens) >= 2 else set()

    @staticmethod
    def _bigram_overlap(text_a: str, text_b: str) -> float:
        """计算 text_a 的 bigram 对 text_b 的覆盖率"""
        bigrams_a = GenerationEvaluator._token_bigrams(text_a)
        bigrams_b = GenerationEvaluator._token_bigrams(text_b)
        if not bigrams_a or not bigrams_b:
            return 0.0
        covered = bigrams_a & bigrams_b
        return len(covered) / len(bigrams_a)

    @staticmethod
    def _compute_faithfulness(contexts: List[str], answer: str) -> float:
        """答案 bigram 对检索上下文 bigram 的覆盖率"""
        if not contexts or not answer:
            return 0.0
        return GenerationEvaluator._bigram_overlap(answer, ' '.join(contexts))

    @staticmethod
    def _compute_correctness(answer: str, ground_truth: str) -> float:
        """标准答案 bigram 对答案 bigram 的覆盖率"""
        if not answer or not ground_truth:
            return 0.0
        return GenerationEvaluator._bigram_overlap(ground_truth, answer)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/evaluator.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: bigram 覆盖率 | 比 unigram 更精确，计算快 | 仍非 claim 级验证 | ✅ |
| B: 句子级相似度验证 | 更接近 claim-based | 需要调用 embedding，成本高 | ❌ |
| C: NLI 模型判断 | 最准确 | 需要额外模型，复杂度高 | ❌ |

##### 验收标准
- [ ] `_compute_faithfulness()` 使用 bigram 而非 unigram
- [ ] 幻觉内容（如 "180天" vs "90天"）的 bigram 覆盖率明显低于原文内容
- [ ] 空输入返回 0.0
- [ ] `_compute_correctness()` 同步使用 bigram
- [ ] 已有测试通过（轻量级评估的测试如有）

---

#### 问题 2.4: [P2] 检索后过滤导致 Top-K 结果不足 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:309-313`
- **函数**: `RAGEngine.search()`
- **严重程度**: ⚠️ P2
- **评估维度**: Recall@K

##### 修复方案
当使用混合检索时，`_hybrid_search()` 内部已经将 filters 传递给向量检索和 BM25 检索。因此 `search()` 中的后置过滤是重复的。移除 `search()` 中的后置过滤，仅依赖检索层内部的过滤。

##### 代码变更

**文件: `scripts/lib/rag_engine/rag_engine.py`** — 修改 search() 方法

```python
# rag_engine.py:288-319 — 替换 search() 方法
    def search(
        self,
        query_text: str,
        top_k: int = None,
        use_hybrid: bool = True,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """检索模式：返回结构化法规列表"""
        if not self._initialized:
            if not self.initialize():
                return []

        _thread_settings.apply()

        try:
            if use_hybrid:
                results = self._hybrid_search(query_text, top_k, filters)
            else:
                response = self.query_engine.query(query_text)
                results = self._extract_results_from_response(response)

            if top_k:
                results = results[:top_k]

            return results

        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"搜索出错: {e}")
            return []
```

同时删除 `_apply_filters` 方法（已无调用方）。

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 移除后置过滤，依赖检索层过滤 | 消除重复，结果更可预测 | 纯向量检索模式可能不受过滤 | ✅ |
| B: 后置过滤后回溯补充 | 结果数量稳定 | 实现复杂，增加延迟 | ❌ |
| C: 保持现状 | 无改动 | 重复过滤导致结果不足 | ❌ |

##### 验收标准
- [ ] `search(filters=...)` 的过滤行为由检索层内部处理
- [ ] 移除重复过滤后，测试通过
- [ ] `search_by_metadata()` 行为不变

---

#### 问题 2.5: [P2] 查询扩展导致 RRF 分数膨胀 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/retrieval.py:90-106`
- **函数**: `hybrid_search()`
- **严重程度**: ⚠️ P2
- **评估维度**: NDCG, MRR

##### 当前代码
```python
# retrieval.py:103-106
for fv in vector_futures:
    vector_nodes.extend(fv.result())  # 直接 extend，无去重
for fk in keyword_futures:
    keyword_nodes.extend(_to_node_with_scores(fk.result()))
```

##### 修复方案
在 `fusion.py` 中添加 `num_queries` 参数，对来自扩展 query 的结果应用衰减权重（除以总 query 数量），使原始 query 的分数权重高于扩展 query。

##### 代码变更

**文件 1: `scripts/lib/rag_engine/retrieval.py`** — 传递 num_queries

```python
# retrieval.py:108-112 — 修改 hybrid_search 返回调用
    total_queries = 1 + (len(preprocessed.expanded) - 1 if preprocessed.did_expand else 0)
    return reciprocal_rank_fusion(
        vector_nodes, keyword_nodes, k=k,
        vector_weight=vector_weight, keyword_weight=keyword_weight,
        max_chunks_per_article=max_chunks_per_article,
        num_queries=total_queries,
    )
```

**文件 2: `scripts/lib/rag_engine/fusion.py`** — 添加衰减权重

```python
# fusion.py:19-70 — 替换 reciprocal_rank_fusion 函数签名和实现
def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
    max_chunks_per_article: int = 3,
    num_queries: int = 1,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion 融合两路检索结果"""
    if not vector_results and not keyword_results:
        return []

    scores: Dict[str, float] = defaultdict(float)
    chunks = {}

    expansion_decay = 1.0 / num_queries if num_queries > 1 else 1.0

    for rank, scored in enumerate(vector_results):
        key = _chunk_key(scored)
        scores[key] += vector_weight / (k + rank + 1) * expansion_decay
        chunks[key] = scored.node

    for rank, scored in enumerate(keyword_results):
        key = _chunk_key(scored)
        scores[key] += keyword_weight / (k + rank + 1) * expansion_decay
        chunks[key] = scored.node

    results = []
    for key, rrf_score in scores.items():
        chunk = chunks[key]
        results.append({
            'law_name': chunk.metadata.get('law_name', '未知'),
            'article_number': chunk.metadata.get('article_number', '未知'),
            'category': chunk.metadata.get('category', ''),
            'content': chunk.text,
            'source_file': chunk.metadata.get('source_file', ''),
            'hierarchy_path': chunk.metadata.get('hierarchy_path', ''),
            'score': rrf_score,
        })

    results = _deduplicate_by_article(results, max_chunks_per_article)
    return sorted(results, key=lambda x: x['score'], reverse=True)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/retrieval.py` |
| 修改 | `scripts/lib/rag_engine/fusion.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 扩展结果分数除以总 query 数 | 简单有效，防止膨胀 | 降低扩展结果的区分度 | ✅ |
| B: 扩展结果使用独立权重参数 | 灵活可调 | 增加配置复杂度 | ❌ |
| C: 不做处理 | 最简单 | 分数膨胀导致排序偏差 | ❌ |

##### 注意事项
- `num_queries` 默认为 1，不启用查询扩展时行为不变
- 衰减应用于所有结果（包括原始 query 的结果），确保公平性

##### 验收标准
- [ ] 不启用查询扩展时，RRF 分数与之前一致
- [ ] 启用查询扩展时，同一 chunk 在多个 query 中出现不会导致分数不成比例膨胀
- [ ] `reciprocal_rank_fusion()` 签名向后兼容（`num_queries` 有默认值）

---

#### 问题 2.6: [P2] LLM Rerank 内容截断丢失关键信息 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/reranker.py:78`
- **函数**: `LLMReranker._batch_rank()`
- **严重程度**: ⚠️ P2
- **评估维度**: NDCG, Precision@K

##### 当前代码
```python
# reranker.py:78
truncated = content[:800] if len(content) > 800 else content
```

##### 修复方案
将截断长度从 800 提升到 1500 字符，并在截断时添加标记。

##### 代码变更

**文件: `scripts/lib/rag_engine/reranker.py`** — 修改 _batch_rank 方法

```python
# reranker.py:73-79 — 替换内容截断逻辑
    def _batch_rank(self, query: str, candidates: List[Dict[str, Any]]) -> tuple:
        """返回 (ranked_indices, did_rerank)"""
        parts = []
        for i, candidate in enumerate(candidates, 1):
            content = candidate.get('content', '')
            law_name = candidate.get('law_name', '')
            article = candidate.get('article_number', '')
            truncated = content[:1500] if len(content) > 1500 else content
            if len(content) > 1500:
                truncated += '\n[内容已截断]'
            parts.append(f"[{i}] 【{law_name}】{article}\n{truncated}")
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/reranker.py` |

##### 验收标准
- [ ] 截断长度为 1500 字符
- [ ] 截断时附加 `[内容已截断]` 标记
- [ ] 未截断的内容不受影响

---

#### 问题 2.7: [P2] 评估缺少 Context Relevance 指标 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py`
- **严重程度**: ⚠️ P2
- **评估维度**: Context Relevance

##### 修复方案
添加 `_compute_context_relevance()` 函数，计算检索上下文中与问题 query 的 bigram 重叠度。在 `RetrievalEvalReport` 中添加字段，在 `evaluate()` 中计算，在 `evaluate_batch()` 中聚合。

##### 代码变更

**文件: `scripts/lib/rag_engine/evaluator.py`**

1. 在 `RetrievalEvalReport` 中添加字段：
```python
@dataclass
class RetrievalEvalReport:
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    context_relevance: float = 0.0  # 新增
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)
```

2. 在 `to_dict()` 和 `print_report()` 中添加 `context_relevance`。

3. 添加计算函数：
```python
# evaluator.py — 在 _compute_redundancy_rate 后面添加
def _compute_context_relevance(query: str, results: List[Dict[str, Any]]) -> float:
    """计算检索上下文中与问题 query 的 bigram 重叠度"""
    if not query or not results:
        return 0.0
    query_bigrams = GenerationEvaluator._token_bigrams(query)
    if not query_bigrams:
        return 0.0
    context_text = ' '.join(r.get('content', '') for r in results)
    context_bigrams = GenerationEvaluator._token_bigrams(context_text)
    if not context_bigrams:
        return 0.0
    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)
```

4. 在 `RetrievalEvaluator.evaluate()` 返回值中添加 `'context_relevance': context_relevance`。

5. 在 `evaluate_batch()` 聚合中添加 `context_relevance`。

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/evaluator.py` |

##### 验收标准
- [ ] `RetrievalEvalReport` 包含 `context_relevance` 字段
- [ ] `context_relevance` 值在 0.0-1.0 范围内
- [ ] 检索结果与问题高度相关时 `context_relevance` 较高
- [ ] `print_report()` 输出包含新指标

---

### ⚡ 代码质量问题 (P2/P3) ✅

---

#### 问题 3.1: [P2] `_detect_unverified_claims()` 覆盖检测逻辑错误 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/attribution.py:106-127`
- **函数**: `_detect_unverified_claims()`
- **严重程度**: ⚡ P2
- **评估维度**: Faithfulness

##### 修复方案
使用 `re.finditer` 计算字符级覆盖范围，替代不可靠的 split 索引判断。移除死代码 `pos` 变量。

##### 代码变更

**文件: `scripts/lib/rag_engine/attribution.py`** — 替换 _detect_unverified_claims 函数

```python
# attribution.py:88-129 — 替换整个函数
def _detect_unverified_claims(
    answer: str,
    cited_indices: set[int],
) -> List[str]:
    """检测未被引用标注覆盖的事实性陈述"""
    if not answer:
        return []

    covered_spans: List[Tuple[int, int]] = []
    for match in _SOURCE_TAG_PATTERN.finditer(answer):
        covered_spans.append((match.start(), match.end()))

    segments = _SOURCE_TAG_PATTERN.split(answer)
    unverified: List[str] = []

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        if len(segment) <= 2:
            continue

        if segment.isdigit():
            continue

        start_pos = answer.find(segment)
        is_covered = False
        for cov_start, cov_end in covered_spans:
            if cov_start - 5 <= start_pos <= cov_end + 5:
                is_covered = True
                break

        if is_covered:
            continue

        for pattern in _FACTUAL_PATTERNS:
            if pattern.search(segment):
                unverified.append(segment)
                break

    return unverified
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/attribution.py` |

##### 验收标准
- [ ] "等待期为90天" 这类以数字结尾的事实性陈述不被误跳过
- [ ] 有 `[来源1]` 标记覆盖的段落不被报告为未验证
- [ ] 无引用标记的事实性数字陈述被正确检测
- [ ] 死代码 `pos` 变量已移除

---

#### 问题 3.2: [P2] `ThreadLocalSettings.apply()` 线程安全缺陷 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:78-82`
- **函数**: `ThreadLocalSettings.apply()`
- **严重程度**: ⚡ P2

##### 修复方案
在 `apply()` 方法中添加锁保护，复用 `__init__` 中已创建的 `self._lock`。

##### 代码变更

**文件: `scripts/lib/rag_engine/rag_engine.py`** — 修改 apply() 和 reset()

```python
# rag_engine.py:78-89 — 替换 apply() 和 reset()
    def apply(self) -> None:
        """应用线程配置到全局 Settings"""
        if hasattr(self._local, 'initialized') and self._local.initialized:
            with self._lock:
                Settings.llm = self._local.llm
                Settings.embed_model = self._local.embed_model

    def reset(self) -> None:
        """重置为全局默认配置"""
        with self._lock:
            if self._global_backup:
                Settings.llm = self._global_backup['llm']
                Settings.embed_model = self._global_backup['embed_model']
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

##### 验收标准
- [ ] `apply()` 在写入全局 Settings 时持有锁
- [ ] 多线程并发调用 `apply()` 不会产生竞态条件

---

#### 问题 3.3: [P3] Reranker fallback 路径修改原始数据 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/reranker.py:56-58`
- **严重程度**: ⚡ P3

##### 修复方案
fallback 路径使用 `dict(candidates[i])` 创建浅拷贝。

##### 代码变更

**文件: `scripts/lib/rag_engine/reranker.py`** — 修改 fallback 路径

```python
# reranker.py:55-59 — 替换 fallback 路径
        if not did_rerank:
            fallback = [dict(candidates[i]) for i in range(top_k)]
            for r in fallback:
                r['reranked'] = False
            return fallback
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/reranker.py` |

##### 验收标准
- [ ] fallback 路径不修改原始 candidates 列表
- [ ] 成功路径和 fallback 路径都创建副本

---

### 🏗️ 设计缺陷 (P2/P3) ✅

---

#### 问题 4.1: [P2] 测试断言条件化 — 掩盖失败 ✅

##### 问题概述
- **文件**: `scripts/tests/integration/test_rag_integration.py`
- **严重程度**: ⚡ P2

##### 修复方案
将 `if results:` 条件断言改为 `assert results` 确定性断言。

##### 代码变更

**文件: `scripts/tests/integration/test_rag_integration.py`**

将所有类似代码：
```python
results = engine.search("等待期", top_k=5)
if results:
    assert any('等待期' in r.get('content', '') for r in results)
```

替换为：
```python
results = engine.search("等待期", top_k=5)
assert results, "检索应返回结果"
assert any('等待期' in r.get('content', '') for r in results)
```

##### 验收标准
- [ ] 检索返回空结果时测试失败而非通过
- [ ] 所有原有通过的测试继续通过

---

#### 问题 4.2: [P3] BM25 索引未包含在备份中 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data_importer.py:192`
- **严重程度**: 🏗️ P3

##### 修复方案
在 `rebuild_knowledge_base()` 的备份步骤中，同时备份 BM25 索引文件。

##### 代码变更

**文件: `scripts/lib/rag_engine/data_importer.py`** — 修改 rebuild_knowledge_base

在备份步骤中添加：
```python
                bm25_path = vector_db_path.parent / "bm25_index.pkl"
                if bm25_path.exists():
                    import shutil
                    shutil.copy2(bm25_path, backup_dir / "bm25_index.pkl")
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/data_importer.py` |

##### 验收标准
- [ ] 重建时 BM25 索引被备份到同一备份目录
- [ ] BM25 索引文件不存在时不报错

---

#### 问题 4.3: [P3] `hybrid` 分块策略在 config 中定义但未实现 ✅

##### 问题概述
- **文件**: `scripts/lib/rag_engine/config.py`, `scripts/lib/rag_engine/doc_parser.py`
- **严重程度**: 🏗️ P3

##### 修复方案
从 `ChunkingConfig.__post_init__` 的合法策略列表中移除 `"hybrid"`。

##### 代码变更

**文件: `scripts/lib/rag_engine/config.py`** — 修改 ChunkingConfig 验证

```python
# config.py:47-49 — 修改策略验证
    def __post_init__(self):
        if self.strategy not in ("fixed", "semantic"):
            raise ValueError(
                f"Invalid chunking strategy: {self.strategy}. "
                f"Must be 'fixed' or 'semantic'."
            )
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/config.py` |

##### 验收标准
- [ ] `ChunkingConfig(strategy="hybrid")` 抛出 `ValueError`
- [ ] `ChunkingConfig(strategy="semantic")` 和 `ChunkingConfig(strategy="fixed")` 正常工作

---

## 二、测试覆盖改进方案

### 2.1 新增测试计划

#### 优先级 P1（核心模块）

**1. `scripts/tests/unit/test_reranker.py`** — Reranker 单元测试
```python
class TestLLMReranker:
    def test_rerank_success_returns_ranked_results(self):
        """正常排序返回正确顺序"""

    def test_rerank_llm_failure_returns_original_order(self):
        """LLM 失败时返回原始顺序并标记 reranked=False"""

    def test_rerank_fallback_does_not_mutate_original(self):
        """fallback 路径不修改原始 candidates"""

    def test_parse_ranking_valid_input(self):
        """解析有效排序输出"""

    def test_parse_ranking_incomplete_output(self):
        """解析不完整输出，缺失编号追加到末尾"""

    def test_parse_ranking_invalid_numbers(self):
        """解析包含超范围数字的输出"""

    def test_parse_ranking_duplicates(self):
        """解析包含重复编号的输出"""

    def test_content_truncation_with_marker(self):
        """超长内容截断并添加标记"""

    def test_rerank_empty_candidates(self):
        """空候选列表返回空结果"""

    def test_rerank_disabled(self):
        """禁用 rerank 时直接返回 top_k"""
```

**2. `scripts/tests/unit/test_query_preprocessor.py`** — 查询预处理单元测试
```python
class TestQueryPreprocessor:
    def test_normalize_colloquial_terms(self):
        """口语化术语归一化"""

    def test_normalize_longest_match_first(self):
        """最长匹配优先"""

    def test_expand_generates_synonym_variants(self):
        """同义扩展生成变体"""

    def test_expand_deduplicates(self):
        """扩展结果去重"""

    def test_llm_rewrite_skipped_for_short_query(self):
        """短查询（<=8字符）跳过 LLM 改写"""

    def test_llm_rewrite_failure_fallback(self):
        """LLM 改写失败时使用归一化结果"""

    def test_llm_rewrite_overrides_normalization(self):
        """LLM 改写结果覆盖归一化结果"""

    def test_preprocess_full_pipeline(self):
        """完整预处理流程"""
```

**3. `scripts/tests/unit/test_fusion.py`** — RRF 融合单元测试
```python
class TestReciprocalRankFusion:
    def test_empty_inputs(self):
        """空输入返回空列表"""

    def test_vector_only(self):
        """仅有向量结果"""

    def test_keyword_only(self):
        """仅有关键词结果"""

    def test_fusion_combines_scores(self):
        """两路结果正确融合"""

    def test_deduplicate_by_article(self):
        """按法规+条款去重"""

    def test_deduplicate_max_chunks(self):
        """max_chunks_per_article 限制"""

    def test_expansion_decay(self):
        """扩展 query 分数衰减"""

    def test_weights(self):
        """vector_weight 和 keyword_weight 影响"""
```

#### 优先级 P2（辅助模块）

**4. `scripts/tests/unit/test_attribution.py`** — 引用归因单元测试
```python
class TestParseCitations:
    def test_parse_valid_citations(self):
        """解析有效引用标记"""

    def test_parse_uncited_sources(self):
        """识别未引用的来源"""

    def test_empty_answer(self):
        """空回答返回空结果"""

class TestDetectUnverifiedClaims:
    def test_number_ending_claim_detected(self):
        """以数字结尾的事实性陈述被检测"""

    def test_cited_claim_not_reported(self):
        """有引用标记的陈述不被报告"""

    def test_legal_obligation_detected(self):
        """法律义务关键词被检测"""

    def test_no_factual_content(self):
        """无非事实性内容时返回空列表"""
```

**5. `scripts/tests/unit/test_evaluator.py`** — 评估器单元测试
```python
class TestIsRelevant:
    def test_keyword_match(self):
        """关键词匹配返回 True"""

    def test_source_file_match(self):
        """source_file 匹配返回 True"""

    def test_law_name_match_no_keywords(self):
        """law_name 匹配但无关键词且无 source_file 返回 False"""

    def test_no_match(self):
        """无匹配返回 False"""

class TestContextRelevance:
    def test_high_relevance(self):
        """上下文与问题高度相关"""

    def test_low_relevance(self):
        """上下文与问题无关"""

    def test_empty_inputs(self):
        """空输入返回 0.0"""

class TestLightweightFaithfulness:
    def test_bigram_overlap(self):
        """bigram 覆盖率计算"""

    def test_hallucination_detected(self):
        """幻觉内容 bigram 覆盖率低"""
```

---

## 三、技术债务清理方案

### 3.1 清理路线图

**第一阶段（本次）— 修复 13 个问题：**
- P0: 1 个
- P1: 4 个
- P2: 8 个

**第二阶段（后续）— 3 个低优先级债务：**
- P3: 配置类 frozen 化（需设计评审）
- P3: Embedding fixture 去重
- P3: `__init__.py` 日志副作用

---

## 附录

### 执行顺序建议

```
Phase 1 (P0-P1 — 必须修复):
  1.1 get_index_stats() 缺失         → 修复 data_importer + index_manager
  1.2 _ensure_embedding_setup() 死代码 → 激活调用
  2.1 上下文窗口过小                 → 提升 max_context_chars 到 8000
  2.2 _is_relevant() 误判             → 修复 else 分支
  2.3 轻量级 Faithfulness 粗糙        → 改为 bigram

Phase 2 (P2 — 尽快修复):
  2.4 检索后过滤重复                  → 移除 search() 后置过滤
  2.5 查询扩展分数膨胀                → 添加扩展衰减权重
  2.6 Rerank 截断过小                 → 提升到 1500 字符
  2.7 缺少 Context Relevance          → 新增指标
  3.1 _detect_unverified_claims() 逻辑错误 → 重写
  3.2 ThreadLocalSettings 无锁        → 添加锁
  4.1 测试条件断言                    → 改为确定性断言

Phase 3 (P3 — 建议修复):
  3.3 Reranker fallback 原始数据修改   → 创建副本
  4.2 BM25 备份                       → 添加到备份步骤
  4.3 hybrid 策略死配置               → 从合法值中移除
```

### 变更摘要

| 文件 | 变更类型 | 涉及问题 |
|------|---------|---------|
| `scripts/lib/rag_engine/index_manager.py` | 新增方法 | 1.1 |
| `scripts/lib/rag_engine/data_importer.py` | 修改 | 1.1, 1.2, 4.2 |
| `scripts/lib/rag_engine/config.py` | 修改默认值 | 2.1, 4.3 |
| `scripts/lib/rag_engine/rag_engine.py` | 修改 | 2.1, 2.4, 3.2 |
| `scripts/lib/rag_engine/evaluator.py` | 修改 | 2.2, 2.3, 2.7 |
| `scripts/lib/rag_engine/retrieval.py` | 修改 | 2.5 |
| `scripts/lib/rag_engine/fusion.py` | 修改 | 2.5 |
| `scripts/lib/rag_engine/reranker.py` | 修改 | 2.6, 3.3 |
| `scripts/lib/rag_engine/attribution.py` | 修改 | 3.1 |
| `scripts/tests/integration/test_rag_integration.py` | 修改 | 4.1 |
| `scripts/tests/unit/test_reranker.py` | 新增 | 测试改进 |
| `scripts/tests/unit/test_query_preprocessor.py` | 新增 | 测试改进 |
| `scripts/tests/unit/test_fusion.py` | 新增 | 测试改进 |
| `scripts/tests/unit/test_attribution.py` | 新增 | 测试改进 |
| `scripts/tests/unit/test_evaluator.py` | 新增 | 测试改进 |

### 验收标准总结

#### 功能验收标准
- [ ] `import_all(skip_vector=False)` 不崩溃
- [ ] 独立使用 `RegulationDataImporter` 时 embedding 模型正确初始化
- [ ] 上下文窗口默认值 8000 字符，截断有日志
- [ ] `_is_relevant()` 无关键词时不会误判为相关
- [ ] 轻量级 Faithfulness 使用 bigram 覆盖率
- [ ] 检索后过滤不再重复执行
- [ ] 查询扩展分数有衰减机制
- [ ] Rerank 截断长度 1500 字符
- [ ] Context Relevance 指标已添加
- [ ] `_detect_unverified_claims()` 正确处理数字结尾陈述
- [ ] `ThreadLocalSettings.apply()` 线程安全
- [ ] 测试断言不再条件化
- [ ] BM25 索引包含在备份中
- [ ] `"hybrid"` 策略不再被接受

#### 质量验收标准
- [ ] `pytest scripts/tests/` 全部通过
- [ ] `mypy scripts/lib/rag_engine/` 无错误
- [ ] 新增单元测试覆盖 reranker, preprocessor, fusion, attribution, evaluator

#### 部署验收标准
- [ ] `RAGConfig(max_context_chars=4000)` 仍可使用（向后兼容）
- [ ] `reciprocal_rank_fusion()` 签名向后兼容（`num_queries` 有默认值）
- [ ] 已有评估脚本 `evaluate_rag.py` 正常运行
- [ ] 知识库重建管线正常工作
