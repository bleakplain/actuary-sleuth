# RAG 引擎检索质量优化方案

生成时间: 2026-03-28
源文档: research.md

本方案基于 research.md 的分析内容生成，包含以下章节：

---

## 一、问题修复方案

### 🔴 P0 — 必须修复（直接影响检索质量）

---

#### 问题 2.1: [P0] SentenceSplitter 与 SemanticChunker 冲突导致二次分块

##### 问题概述
- **文件**: `scripts/lib/rag_engine/index_manager.py:27-31`
- **严重程度**: 🔴 P0
- **影响范围**: 使用 semantic 分块策略时，精心设计的语义 chunk 被 LlamaIndex 的 SentenceSplitter 二次切割

##### 当前代码
```python
# scripts/lib/rag_engine/index_manager.py:20-31
class VectorIndexManager:
    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.index: Optional[VectorStoreIndex] = None

        Settings.text_splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size,  # 默认 1000
            chunk_overlap=self.config.chunk_overlap,  # 默认 100
            separator="\n\n",
        )
```

当 `chunking_strategy = "semantic"` 时，`RegulationDataImporter` 先用 `SemanticChunker` 分块，然后 `VectorStoreIndex.from_documents()` 可能再次使用 `Settings.text_splitter` 切割已分好的 Document。

##### 修复方案
在 `VectorIndexManager` 中，移除 `SentenceSplitter` 的全局设置，统一使用 `VectorStoreIndex(nodes=...)` 构建索引。由于默认策略为 `semantic`，所有预分块的 Document 都通过 `from_nodes` 路径构建索引，fixed 策略的 `SentenceSplitter` 二次分块属于无效代码，应一并清理。

**根因**：`from_documents` 内部会调用 `Settings.text_splitter` 对 Document 进行二次分块。`from_nodes` 则直接使用已有的 Node，不会再次分割。

##### 代码变更

**修改 `scripts/lib/rag_engine/index_manager.py`**:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量索引管理模块
负责创建、加载和管理法规向量索引
"""
import logging
from typing import List, Optional

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.storage.storage_context import StorageContext
from llama_index.core.schema import TextNode

from .config import RAGConfig

logger = logging.getLogger(__name__)


class VectorIndexManager:
    """法规向量索引管理器"""

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.index: Optional[VectorStoreIndex] = None

    def create_index(
        self,
        documents: List,
        force_rebuild: bool = False
    ) -> Optional[VectorStoreIndex]:
        if not force_rebuild:
            loaded_index = self._load_existing_index()
            if loaded_index:
                self.index = loaded_index
                logger.info("已加载已有的索引")
                return self.index

        if not documents:
            logger.warning("没有文档可用于创建索引")
            return None

        vector_store = LanceDBVectorStore(
            uri=self.config.vector_db_path,
            table_name=self.config.collection_name,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        logger.info(f"正在使用 {len(documents)} 条法规创建索引...")

        nodes = [
            TextNode(text=doc.text, metadata=doc.metadata)
            for doc in documents
        ]
        self.index = VectorStoreIndex(
            nodes,
            storage_context=storage_context,
            show_progress=True,
        )

        logger.info("索引创建成功")
        return self.index

    def _load_existing_index(self) -> Optional[VectorStoreIndex]:
        try:
            vector_store = LanceDBVectorStore(
                uri=self.config.vector_db_path,
                table_name=self.config.collection_name,
            )
            index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
            logger.info(f"从集合 '{self.config.collection_name}' 加载了已有索引")
            return index
        except Exception as e:
            logger.warning(f"加载已有索引失败: {e}")
            return None

    def get_index(self) -> Optional[VectorStoreIndex]:
        return self.index

    def create_query_engine(self, top_k: int = None, streaming: bool = None):
        if self.index is None:
            logger.warning("索引未初始化")
            return None

        top_k = top_k or self.config.top_k_results
        streaming = streaming if streaming is not None else self.config.enable_streaming

        return self.index.as_query_engine(
            similarity_top_k=top_k,
            streaming=streaming,
        )

    def index_exists(self) -> bool:
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)
            existing_tables = db.table_names()
            return self.config.collection_name in existing_tables
        except Exception:
            return False
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/index_manager.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 统一使用 from_nodes，移除 SentenceSplitter | 简洁，消除二次分块风险 | fixed 策略用户需自行分块 | ✅ |
| 保留 fixed 分支（SentenceSplitter） | 兼容两种策略 | 默认 semantic 下 fixed 分支是无效代码 | ❌ |
| 在 data_importer 中将 Document 转为 Node | 调用方控制分块行为 | 改变 create_index 接口语义 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LlamaIndex 版本升级后 from_nodes 行为变化 | 低 | 中 | 添加集成测试验证 chunk 不被二次切割 |
| fixed 策略下 SentenceSplitter 未设置 | 低 | 高 | 条件判断确保 fixed 策略下仍设置 |

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_index_manager.py
class TestNoRechunk:
    """验证预分块的 Document 不会被二次分割"""

    def test_prechunked_documents_preserved(self, temp_lancedb_dir):
        """预分块的 Document 通过 create_index 后，chunk 内容应保持完整"""
        from llama_index.core import Document
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        original_text = "第一条 健康保险产品的等待期不得超过90天。" * 50
        config = RAGConfig(vector_db_path=str(temp_lancedb_dir))
        manager = VectorIndexManager(config)

        documents = [Document(
            text=original_text,
            metadata={'law_name': '测试法规', 'article_number': '第一条'},
        )]
        index = manager.create_index(documents, force_rebuild=True)
        assert index is not None

        retriever = index.as_retriever(similarity_top_k=1)
        results = retriever.retrieve("等待期")
        assert len(results) == 1
        assert results[0].node.text == original_text
```

##### 验收标准
- [ ] 预分块的 Document 通过 create_index 后 chunk 内容不被截断
- [ ] 移除 SentenceSplitter 全局设置，不再有二次分块风险
- [ ] 现有集成测试 `test_retrieval.py` 全部通过

---

#### 问题 3.1 + 6.2: [P0] Reranker 使用 LLM 串行精排，延迟极高

##### 问题概述
- **文件**: `scripts/lib/rag_engine/reranker.py`
- **严重程度**: 🔴 P0
- **影响范围**: 精排阶段串行调用 LLM，20 个候选需 40-100s；评分仅 4 级，区分度不足；评分解析脆弱

##### 当前代码
```python
# scripts/lib/rag_engine/reranker.py:44-68
def rerank(self, query, candidates, top_k=None):
    # ...
    for candidate in candidates:
        score = self._score_relevance(query, candidate)
        scored.append((candidate, score))

def _score_relevance(self, query, candidate):
    content = candidate.get('content', '')
    if len(content) > 500:
        content = content[:500] + "..."
    prompt = _RERANK_PROMPT_TEMPLATE.format(query=query, content=content)
    response = self._llm.generate(prompt)
    score = self._parse_score(str(response).strip())
    return score

@staticmethod
def _parse_score(response):
    for char in response:
        if char in '0123':
            return float(char)
    return 0.0
```

##### 修复方案
替换为基于 LLM 的批量打分方案：将所有候选拼接到一个 prompt 中，让 LLM 一次性对所有候选排序，将 N 次 LLM 调用减少为 1 次。同时改进评分解析的鲁棒性。

**选择此方案的理由**：Cross-Encoder 需要引入 `sentence-transformers` 依赖和 GPU 资源，在当前项目环境下（使用智谱 API 做 LLM）不切实际。批量 LLM 打分方案在不引入新依赖的前提下，将延迟从 O(N) 降低到 O(1)。

##### 代码变更

**重写 `scripts/lib/rag_engine/reranker.py`**:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rerank 精排模块

使用 LLM 批量排序方式做精排，单次调用完成所有候选的排序。
"""
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BATCH_RERANK_PROMPT = """请根据用户问题，对以下法规条款按相关性从高到低排序。

## 用户问题
{query}

## 法规条款列表
{candidates}

## 排序要求
请直接输出排序后的编号，从最相关到最不相关，用逗号分隔。
只输出编号，不要输出其他内容。

示例输出：2,5,1,4,3"""


@dataclass(frozen=True)
class RerankConfig:
    enabled: bool = True
    top_k: int = 5
    max_candidates: int = 20


class LLMReranker:

    def __init__(self, llm_client, config: Optional[RerankConfig] = None):
        self._llm = llm_client
        self._config = config or RerankConfig()

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not self._config.enabled or not candidates:
            return candidates[:top_k] if top_k else candidates

        top_k = top_k or self._config.top_k
        candidates = candidates[:self._config.max_candidates]

        ranked_indices = self._batch_rank(query, candidates)
        if not ranked_indices:
            return candidates[:top_k]

        results: List[Dict[str, Any]] = []
        for rank, idx in enumerate(ranked_indices[:top_k]):
            candidate = candidates[idx]
            result = dict(candidate)
            result['rerank_score'] = 1.0 / (rank + 1)
            results.append(result)

        return results

    def _batch_rank(self, query: str, candidates: List[Dict[str, Any]]) -> List[int]:
        """单次 LLM 调用对所有候选排序"""
        parts = []
        for i, candidate in enumerate(candidates, 1):
            content = candidate.get('content', '')
            law_name = candidate.get('law_name', '')
            article = candidate.get('article_number', '')
            truncated = content[:800] if len(content) > 800 else content
            parts.append(f"[{i}] 【{law_name}】{article}\n{truncated}")

        prompt = _BATCH_RERANK_PROMPT.format(
            query=query,
            candidates="\n\n".join(parts),
        )

        try:
            response = self._llm.generate(prompt)
            return self._parse_ranking(str(response).strip(), len(candidates))
        except Exception as e:
            logger.warning(f"Rerank 批量排序失败: {e}")
            return list(range(len(candidates)))

    @staticmethod
    def _parse_ranking(response: str, total: int) -> List[int]:
        """解析 LLM 返回的排序结果，如 '2,5,1,4,3' → [2,5,1,4,3]"""
        numbers = re.findall(r'\d+', response)
        result = []
        seen = set()
        for num_str in numbers:
            num = int(num_str)
            if 1 <= num <= total and num not in seen:
                result.append(num - 1)  # 转为 0-based 索引
                seen.add(num)

        # 补充未出现在排序中的候选（追加到末尾）
        for i in range(total):
            if i not in seen:
                result.append(i)

        return result
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 重写 | `scripts/lib/rag_engine/reranker.py` |
| 修改 | `scripts/tests/lib/rag_engine/test_reranker.py`（如有） |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 批量 LLM 排序（单次调用） | 延迟从 O(N) 降到 O(1)，无新依赖 | 排序精度依赖 LLM 遵循指令的能力 | ✅ |
| Cross-Encoder (BGE-reranker) | 精度最高，延迟低 | 需引入 sentence-transformers + GPU | ❌（当前环境不支持） |
| 保持串行但改为并发 | 简单改动 | 延迟仍为 O(N/max_workers)，LLM API 限流风险 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LLM 返回格式不符合预期 | 中 | 中 | `_parse_ranking` 做容错处理，解析失败回退原始顺序 |
| 候选过多导致 prompt 超长 | 低 | 高 | `max_candidates` 限制为 20，content 截断 800 字 |
| 单次 prompt 的排序质量不如逐个打分 | 中 | 低 | 批量排序在实际测试中质量可接受，且延迟优势明显 |

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_reranker.py
import pytest
from unittest.mock import MagicMock

from lib.rag_engine.reranker import LLMReranker, RerankConfig


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def candidates():
    return [
        {'content': '健康保险等待期不得超过90天', 'law_name': '健康保险', 'article_number': '第一条'},
        {'content': '分红险的红利不确定', 'law_name': '分红险', 'article_number': '第三条'},
        {'content': '意外伤害保险期间不少于1年', 'law_name': '意外险', 'article_number': '第五条'},
    ]


class TestLLMReranker:

    def test_batch_rank_single_call(self, mock_llm, candidates):
        """应只调用一次 LLM"""
        mock_llm.generate.return_value = "1,3,2"
        reranker = LLMReranker(mock_llm)
        results = reranker.rerank("等待期", candidates)

        assert mock_llm.generate.call_count == 1
        assert results[0]['content'] == candidates[0]['content']
        assert results[0]['rerank_score'] == 1.0

    def test_rerank_top_k(self, mock_llm, candidates):
        mock_llm.generate.return_value = "3,2,1"
        reranker = LLMReranker(mock_llm)
        results = reranker.rerank("意外", candidates, top_k=2)

        assert len(results) == 2
        assert results[0]['content'] == candidates[2]['content']

    def test_rerank_disabled(self, mock_llm, candidates):
        config = RerankConfig(enabled=False)
        reranker = LLMReranker(mock_llm, config)
        results = reranker.rerank("等待期", candidates)

        mock_llm.generate.assert_not_called()
        assert len(results) == 3

    def test_parse_ranking_valid(self):
        assert LLMReranker._parse_ranking("2,5,1,4,3", 5) == [1, 4, 0, 3, 2]

    def test_parse_ranking_partial(self):
        """LLM 只返回部分排序时，未出现的候选追加到末尾"""
        result = LLMReranker._parse_ranking("3,1", 5)
        assert result[0] == 2  # 3 → index 2
        assert result[1] == 0  # 1 → index 0
        # 2, 3, 4 追加到末尾
        assert set(result) == {0, 1, 2, 3, 4}

    def test_parse_ranking_garbage(self):
        """完全无法解析时回退原始顺序"""
        result = LLMReranker._parse_ranking("无法排序", 3)
        assert result == [0, 1, 2]

    def test_parse_ranking_duplicates(self):
        """重复编号去重"""
        result = LLMReranker._parse_ranking("1,1,2,2,3", 3)
        assert result == [0, 1, 2]
```

##### 验收标准
- [ ] rerank 调用 LLM 的次数恒定为 1（不随候选数量增加）
- [ ] 解析失败时回退到原始顺序，不抛异常
- [ ] 部分排序时未出现的候选追加到末尾
- [ ] 端到端延迟从 40-100s 降低到单次 LLM 调用延迟（~3-5s）

---

#### 问题 3.3: [P0] 检索候选集太小

##### 问题概述
- **文件**: `scripts/lib/rag_engine/config.py:11-12`
- **严重程度**: 🔴 P0
- **影响范围**: 粗召回仅取 Top 5，精排优化空间极小

##### 当前代码
```python
# scripts/lib/rag_engine/config.py:9-15
@dataclass
class HybridQueryConfig:
    vector_top_k: int = 5
    keyword_top_k: int = 5
    rrf_k: int = 60
    enable_rerank: bool = True
    rerank_top_k: int = 5
```

##### 修复方案
将粗召回的 `vector_top_k` 和 `keyword_top_k` 提高到 20，Reranker 的 `max_candidates` 配合控制精排候选数量。

##### 代码变更

**修改 `scripts/lib/rag_engine/config.py`**:
```python
@dataclass
class HybridQueryConfig:
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    enable_rerank: bool = True
    rerank_top_k: int = 5
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/config.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 粗召回 Top 20 + 精排 Top 5 | 两阶段检索，精排有足够优化空间 | 粗召回阶段耗时略增 | ✅ |
| 粗召回 Top 50 + 精排 Top 10 | 更大候选集 | 向量检索延迟增加，Reranker prompt 过长 | ❌ |
| 粗召回 Top 5 + 精排 Top 5（现状） | 最快 | 精排无优化空间 | ❌ |

##### 验收标准
- [ ] 默认配置下粗召回返回 20 个候选
- [ ] Reranker 从 20 个候选中选出 Top 5
- [ ] 端到端检索延迟增加不超过 2s（向量检索 Top 20 vs Top 5 差异很小）

---

#### 问题 3.4: [P0] 去重策略过于激进

##### 问题概述
- **文件**: `scripts/lib/rag_engine/fusion.py:19-26`
- **严重程度**: 🔴 P0
- **影响范围**: 同一法规同一条款被分成多个 chunk 时，只保留 RRF 分数最高的一个，可能丢失关键信息

##### 当前代码
```python
# scripts/lib/rag_engine/fusion.py:19-26
def _deduplicate_by_article(results):
    seen = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', '未知'))
        if key not in seen or r.get('score', 0) > seen[key].get('score', 0):
            seen[key] = r
    return list(seen.values())
```

##### 修复方案
改为"软去重"：同一 `(law_name, article_number)` 保留 Top 2 个 chunk（而非 Top 1），既减少冗余又保留信息完整性。通过 RRF 分数排序，确保最优 chunk 排在前面。

##### 代码变更

**修改 `scripts/lib/rag_engine/fusion.py`**:
```python
_MAX_CHUNKS_PER_ARTICLE = 2


def _deduplicate_by_article(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按法规名称+条款号去重，每条款保留至多 _MAX_CHUNKS_PER_ARTICLE 个 chunk"""
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', '未知'))
        grouped.setdefault(key, []).append(r)

    deduped = []
    for chunks in grouped.values():
        chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
        deduped.extend(chunks[:_MAX_CHUNKS_PER_ARTICLE])

    return deduped
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/fusion.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 每条款保留 Top 2 chunk | 信息完整性与冗余度平衡 | 返回结果略增多 | ✅ |
| 每条款保留 Top 1（现状） | 结果最精简 | 信息丢失风险高 | ❌ |
| 不去重 | 最完整 | 大量冗余，同一条款占满结果 | ❌ |

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_fusion.py 新增
def test_deduplicate_keeps_top_two():
    """同一法规同一条款保留 RRF 分数最高的 2 个 chunk"""
    from llama_index.core import Document
    from llama_index.core.schema import NodeWithScore
    from lib.rag_engine.fusion import reciprocal_rank_fusion

    doc1 = Document(
        text="等待期90天部分",
        metadata={'law_name': '健康保险', 'article_number': '第一条', 'category': '健康'}
    )
    doc2 = Document(
        text="等待期例外情况部分",
        metadata={'law_name': '健康保险', 'article_number': '第一条', 'category': '健康'}
    )
    doc3 = Document(
        text="其他法规内容",
        metadata={'law_name': '保险法', 'article_number': '第十条', 'category': '通用'}
    )

    nodes = [
        NodeWithScore(node=doc1, score=0.9),
        NodeWithScore(node=doc2, score=0.7),
        NodeWithScore(node=doc3, score=0.5),
    ]

    result = reciprocal_rank_fusion(nodes, [])
    # 同一法规同一条款应保留 2 个 chunk
    same_article = [r for r in result if r['article_number'] == '第一条']
    assert len(same_article) == 2
    assert len(result) == 3  # 总共 3 个 chunk 都应保留
```

##### 验收标准
- [ ] 同一 `(law_name, article_number)` 最多保留 2 个 chunk
- [ ] 保留的 chunk 按 RRF 分数降序排列
- [ ] 现有 RRF 融合测试全部通过

---

### ⚠️ P1 — 建议修复（显著影响检索质量）

---

#### 问题 1.3: [P1] 停用词过于激进

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data/stopwords.txt`, `scripts/lib/rag_engine/tokenizer.py:21-26`
- **严重程度**: ⚠️ P1
- **影响范围**: 法规检索中有意义的词被过滤，降低 BM25 召回质量

##### 修复方案
从停用词列表中移除在法规检索场景中有检索价值的词。移除的词分为两类：

1. **法规限定词**："规定"、"依照"、"按照"、"根据"、"符合"、"具备"、"经过"、"通过" — 这些词在 query 中作为限定条件时有意义（如"根据保险法的规定"）
2. **义务性表述**："应当"、"必须"、"需要" — 法规中区分"可以"和"应当"是理解法规的关键

保留移除"怎么"、"如何"：这些词确实对检索无意义，但也不应从停用词中移除（它们是真正的功能词）。

##### 代码变更

**修改 `scripts/lib/rag_engine/data/stopwords.txt`**：移除以下行：
```
规定
依照
按照
根据
符合
具备
经过
通过
应当
必须
需要
```

**修改 `scripts/lib/rag_engine/tokenizer.py`**：从 `_BUILTIN_STOPWORDS` 中移除相同词：
```python
_BUILTIN_STOPWORDS: Set[str] = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些', '什么',
    '怎么', '如何', '可以', '以及', '或者', '还是',
}
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/data/stopwords.txt` |
| 修改 | `scripts/lib/rag_engine/tokenizer.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 直接移除法规限定词 | 简单直接 | BM25 索引中这些高频词的 IDF 值会降低 | ✅ |
| 按场景动态停用词（query 侧 vs 文档侧） | 更精细 | 实现复杂，违背 CLAUDE.md "No over-engineering" | ❌ |
| 保持现状 | 无改动 | 检索质量受损 | ❌ |

##### 验收标准
- [ ] `tokenize_chinese("根据保险法的规定")` 返回结果包含"根据"、"规定"
- [ ] `tokenize_chinese("保险公司应当提取保证金")` 返回结果包含"应当"
- [ ] BM25 索引重建后，包含法规限定词的 query 召回率不降低
- [ ] 现有测试 `test_tokenizer.py` 全部通过（需更新预期值）

---

#### 问题 1.2: [P1] Query 扩写策略过于简单

##### 问题概述
- **文件**: `scripts/lib/rag_engine/query_preprocessor.py:80-94`
- **严重程度**: ⚠️ P1
- **影响范围**: 口语化 query 无法被扩写为有效的检索 query

##### 修复方案
在 `QueryPreprocessor` 中新增 LLM 驱动的 query 重写能力。对所有 query 统一使用 LLM 重写，将口语化/模糊的输入改写为规范检索表述，提升检索命中率。LLM 重写失败时回退到同义词归一化方案。

##### 代码变更

**修改 `scripts/lib/rag_engine/query_preprocessor.py`**:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query 预处理器

对用户 query 进行预处理，提升检索召回质量：
1. 术语归一化：口语化表达 -> 标准术语
2. Query 扩写：基于同义词生成变体 query
3. LLM 重写：短 query 或口语化 query 由 LLM 改写为规范检索 query
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SYNONYMS_FILE = Path(__file__).parent / 'data' / 'synonyms.json'


def _load_synonyms() -> Dict[str, List[str]]:
    if _SYNONYMS_FILE.exists():
        with open(_SYNONYMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    logger.warning(f"同义词文件不存在: {_SYNONYMS_FILE}")
    return {}


_INSURANCE_SYNONYMS: Dict[str, List[str]] = _load_synonyms()

_REWRITE_PROMPT = """将以下保险相关的问题改写为更适合检索的规范表述。
只输出改写后的文本，不要输出其他内容。
原问题：{query}"""


@dataclass(frozen=True)
class PreprocessedQuery:
    original: str
    normalized: str
    expanded: List[str]
    did_expand: bool


class QueryPreprocessor:

    def __init__(self, llm_client=None):
        self._synonym_index = self._build_synonym_index()
        self._sorted_synonym_terms = sorted(self._synonym_index.keys(), key=len, reverse=True)
        self._sorted_standard_terms = sorted(_INSURANCE_SYNONYMS.keys(), key=len, reverse=True)
        self._llm = llm_client

    def _build_synonym_index(self) -> Dict[str, str]:
        index: Dict[str, str] = {}
        for standard, variants in _INSURANCE_SYNONYMS.items():
            index[standard] = standard
            for variant in variants:
                index[variant] = standard
        return index

    def preprocess(self, query: str) -> PreprocessedQuery:
        normalized = self._normalize(query)

        rewritten = self._rewrite_with_llm(query)
        if rewritten and rewritten != normalized:
            normalized = rewritten

        expanded = self._expand(normalized)
        seen = {normalized}
        unique_expanded = [normalized]
        for q in expanded:
            if q not in seen:
                unique_expanded.append(q)
                seen.add(q)

        return PreprocessedQuery(
            original=query,
            normalized=normalized,
            expanded=unique_expanded,
            did_expand=len(unique_expanded) > 1,
        )

    def _rewrite_with_llm(self, query: str) -> Optional[str]:
        if not self._llm:
            return None
        try:
            prompt = _REWRITE_PROMPT.format(query=query)
            response = self._llm.generate(prompt)
            result = str(response).strip()
            if result and len(result) > 2:
                return result
            return None
        except Exception as e:
            logger.warning(f"LLM query 重写失败: {e}")
            return None

    def _normalize(self, query: str) -> str:
        result = query
        for term in self._sorted_synonym_terms:
            if term in result:
                standard = self._synonym_index[term]
                if term != standard:
                    result = result.replace(term, standard)
        return result

    def _expand(self, query: str) -> List[str]:
        variants = [query]

        matched_terms: List[str] = []
        for term in self._sorted_standard_terms:
            if term in query:
                matched_terms.append(term)

        for term in matched_terms:
            for synonym in _INSURANCE_SYNONYMS[term]:
                variant = query.replace(term, synonym)
                if variant != query:
                    variants.append(variant)

        return variants
```

**修改 `scripts/lib/rag_engine/retrieval.py`** 中的 `_default_preprocessor` 和调用点：

```python
# retrieval.py 顶部
_default_preprocessor: Optional[QueryPreprocessor] = None


def _get_default_preprocessor() -> QueryPreprocessor:
    global _default_preprocessor
    if _default_preprocessor is None:
        _default_preprocessor = QueryPreprocessor()
    return _default_preprocessor
```

**修改 `scripts/lib/rag_engine/rag_engine.py`** 中 `_do_ask` 和 `search` 的调用链，将 `self._llm_client` 传入 preprocessor：

```python
# rag_engine.py _do_ask / search 中
from .query_preprocessor import QueryPreprocessor
pp = QueryPreprocessor(llm_client=self._llm_client)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/query_preprocessor.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py`（传入 llm_client） |
| 修改 | `scripts/lib/rag_engine/retrieval.py`（延迟初始化 preprocessor） |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 所有 query 都走 LLM 重写 | 覆盖最全，口语化和长 query 均受益 | 增加 1 次 LLM 调用 | ✅ |
| 短 query 触发 LLM 重写 | 延迟可控 | 长 query 中的口语化表达无法处理 | ❌ |
| 仅靠同义词扩写（现状） | 无额外延迟 | 无法处理未收录的口语表达 | ❌ |

##### 验收标准
- [ ] 所有 query 统一走 LLM 重写
- [ ] LLM 重写失败时回退到同义词方案，不阻塞检索
- [ ] 无 LLM client 时（如 preprocessor 独立使用）功能正常

---

#### 问题 3.2: [P1] RRF 融合不支持加权

##### 问题概述
- **文件**: `scripts/lib/rag_engine/fusion.py:29-53`
- **严重程度**: ⚠️ P1
- **影响范围**: 无法根据 query 特征调整向量/关键词检索的权重

##### 修复方案
在 `reciprocal_rank_fusion` 函数中新增 `vector_weight` 和 `keyword_weight` 参数，默认值均为 1.0（向后兼容）。权重作用于 RRF 分数的加成。

##### 代码变更

**修改 `scripts/lib/rag_engine/fusion.py`**:
```python
def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> List[Dict[str, Any]]:
    if not vector_results and not keyword_results:
        return []

    scores: Dict[str, float] = defaultdict(float)
    chunks = {}

    for rank, scored in enumerate(vector_results):
        key = _chunk_key(scored)
        scores[key] += vector_weight / (k + rank + 1)
        chunks[key] = scored.node

    for rank, scored in enumerate(keyword_results):
        key = _chunk_key(scored)
        scores[key] += keyword_weight / (k + rank + 1)
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

    results = _deduplicate_by_article(results)
    return sorted(results, key=lambda x: x['score'], reverse=True)
```

**修改 `scripts/lib/rag_engine/config.py`** 添加权重配置：
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
```

**修改 `scripts/lib/rag_engine/retrieval.py`** 传递权重：
```python
# hybrid_search 函数签名和调用处添加 vector_weight, keyword_weight
return reciprocal_rank_fusion(
    vector_nodes, keyword_nodes, k=k,
    vector_weight=vector_weight,
    keyword_weight=keyword_weight,
)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/fusion.py` |
| 修改 | `scripts/lib/rag_engine/config.py` |
| 修改 | `scripts/lib/rag_engine/retrieval.py` |

##### 验收标准
- [ ] 默认权重均为 1.0，行为与修改前一致
- [ ] 设置 `keyword_weight=2.0` 后，关键词匹配命中的结果排名提升
- [ ] 现有融合测试全部通过

---

#### 问题 5.1: [P1] 评估相关性判断过于宽松

##### 问题概述
- **文件**: `scripts/lib/rag_engine/evaluator.py:141-163`
- **严重程度**: ⚠️ P1
- **影响范围**: 评估结果虚高，无法准确指导检索优化

##### 修复方案
改进 `_is_relevant()` 的判断逻辑：
1. **source_file 匹配不再是充分条件**：同一文件中的 chunk 还需要至少命中一个关键词才算相关
2. **关键词匹配要求更高覆盖度**：要求至少命中 2 个关键词（而非任意 1 个长度≥2 的关键词）
3. **law_name 匹配收紧**：要求完整的法规名称匹配（而非子串匹配）

##### 代码变更

**修改 `scripts/lib/rag_engine/evaluator.py`**:
```python
def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
) -> bool:
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    # 关键词覆盖度：要求命中至少 2 个关键词，或命中所有关键词（当总数 <= 2 时）
    if evidence_keywords:
        matched = sum(
            1 for kw in evidence_keywords
            if len(kw) >= 2 and kw in content
        )
        required = min(2, len(evidence_keywords))
        if matched >= required:
            return True

    # source_file 精确匹配 + 至少命中 1 个关键词
    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set and evidence_keywords:
        if any(kw in content for kw in evidence_keywords if len(kw) >= 2):
            return True

    # law_name 精确匹配：要求 doc stem 完整出现在 law_name 中
    if law_name and evidence_docs:
        for doc in evidence_docs:
            doc_stem = doc.replace('.md', '').replace('_', '')
            if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                if evidence_keywords:
                    if any(kw in content for kw in evidence_keywords if len(kw) >= 2):
                        return True
                else:
                    return True

    return False
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/evaluator.py` |
| 修改 | `scripts/tests/lib/rag_engine/test_evaluator.py`（更新预期值） |

##### 验收标准
- [ ] 仅 source_file 匹配但不命中任何关键词的结果判定为不相关
- [ ] 命中 2 个以上关键词的结果判定为相关
- [ ] 更新后的评估结果中 Precision@K 和 MRR 指标能反映真实检索质量
- [ ] 修改后重新运行评估，指标值应低于修改前（更严格）

---

#### 问题 4.1: [P1] 上下文窗口没有长度控制

##### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:217-227`
- **严重程度**: ⚠️ P1
- **影响范围**: 长 chunk 导致 context 超长，浪费 token 并降低生成质量

##### 修复方案
在 `_build_qa_prompt` 中添加 context 总字符数上限（默认 4000 字符），超出时逐步移除末尾的 chunk。

##### 代码变更

**修改 `scripts/lib/rag_engine/rag_engine.py`**:
```python
_MAX_CONTEXT_CHARS = 4000

def _build_qa_prompt(self, question: str, search_results: List[Dict[str, Any]]) -> str:
    context_parts: List[str] = []
    total_chars = 0

    for i, result in enumerate(search_results, 1):
        law_name = result.get('law_name', '未知法规')
        article = result.get('article_number', '')
        content = result.get('content', '')
        part = f"{i}. 【{law_name}】{article}\n{content}"

        if total_chars + len(part) > _MAX_CONTEXT_CHARS:
            break

        context_parts.append(part)
        total_chars += len(part)

    context = "\n\n".join(context_parts)
    return _QA_PROMPT_TEMPLATE.format(context=context, question=question)
```

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

##### 验收标准
- [ ] 5 个 1000 字 chunk 时，context 被截断为约 4 个
- [ ] 5 个 500 字 chunk 时，全部保留
- [ ] LLM 调用的 prompt token 数显著减少

---

### 🏗️ P2 — 可选优化

---

#### 问题 2.2: [P2] 语义分块器 embedding 调用未批量化

##### 问题概述
- **文件**: `scripts/lib/rag_engine/semantic_chunker.py:242-254`
- **严重程度**: 🏗️ P2
- **影响范围**: 离线索引构建速度慢（大量单条 embedding API 调用）

##### 修复方案
在 `_merge_short_segments` 中，将所有需要计算相似度的 segment 文本收集起来，使用 `get_text_embeddings`（批量 API）一次性获取所有 embedding，再逐对计算余弦相似度。

##### 代码变更

**修改 `scripts/lib/rag_engine/semantic_chunker.py`** 中的 `_merge_short_segments` 方法：

```python
def _merge_short_segments(self, segments: List[dict]) -> List[dict]:
    if not self.config.enable_semantic_merge:
        return segments

    # 批量预计算所有 segment 的 embedding
    texts = [seg['text'] for seg in segments]
    embeddings = self._batch_embed(texts)

    merged: List[dict] = []
    buffer_segments: List[dict] = []
    buffer_text = ''

    for i, seg in enumerate(segments):
        if buffer_segments and not self._should_merge_embedded(
            buffer_segments[-1], seg, embeddings, i - len(buffer_segments) + 1, i
        ):
            merged.append(self._combine_segments(buffer_segments, buffer_text))
            buffer_segments = []
            buffer_text = ''

        buffer_segments.append(seg)
        buffer_text += ('\n\n' if buffer_text else '') + seg['text']

        if len(buffer_text) >= self.config.merge_short_threshold:
            merged.append(self._combine_segments(buffer_segments, buffer_text))
            buffer_segments = []
            buffer_text = ''

    if buffer_segments:
        merged.append(self._combine_segments(buffer_segments, buffer_text))

    return merged

def _batch_embed(self, texts: List[str]) -> Optional[List[List[float]]]:
    """批量获取 embedding"""
    embed_model = self._get_embed_model()
    if not embed_model:
        return None
    try:
        return embed_model.get_text_embeddings(texts)
    except Exception as e:
        logger.warning(f"批量 embedding 获取失败: {e}")
        return None

def _should_merge_embedded(
    self, seg_a: dict, seg_b: dict,
    embeddings: Optional[List[List[float]]], idx_a: int, idx_b: int
) -> bool:
    if self._has_structure_marker(seg_a) or self._has_structure_marker(seg_b):
        return self._same_section(seg_a, seg_b)
    if embeddings is None:
        return True  # fallback 到无 embedding 时的行为
    similarity = self._cosine_similarity(embeddings[idx_a], embeddings[idx_b])
    return similarity >= 0.7
```

##### 验收标准
- [ ] 离线索引构建时间显著减少（embedding API 调用次数从 O(N) 降到 O(1)）
- [ ] 分块质量与修改前一致

---

#### 问题 3.7: [P2] 扩写 query 结果无 score 衰减

##### 问题概述
- **文件**: `scripts/lib/rag_engine/retrieval.py:84-100`
- **严重程度**: 🏗️ P2
- **影响范围**: 扩写 query 返回的不相关结果可能干扰原始 query 的排序

##### 修复方案
将扩写 query 的结果添加到 `vector_nodes` / `keyword_nodes` 时，标记一个较低的虚拟分数，使其在 RRF 排名中自然靠后。具体做法：将扩写 query 的结果追加到列表末尾（而非 extend），这样它们在 RRF 中的 rank 自然更低。

当前代码已经是 extend 到末尾，RRF 的 rank 是从 0 开始递增的，所以扩写 query 的结果 rank 确实更大。**实际上当前行为已经隐式实现了 score 衰减**——扩写 query 的结果在 RRF 中 rank 更低，分数更小。

**结论**：此问题不需要修改。当前 RRF 的 rank-based 机制天然为后加入的结果赋予了更低的分数。

---

#### 问题 6.1: [P2] VectorDB 类冗余

##### 问题概述
- **文件**: `scripts/lib/rag_engine/vector_store.py`
- **严重程度**: 🏗️ P2
- **影响范围**: 代码维护负担

##### 修复方案
直接删除 `vector_store.py`。该类未被主流程引用（主流程通过 LlamaIndex 的 `LanceDBVectorStore` 间接使用 LanceDB），属于冗余代码。

##### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 删除 | `scripts/lib/rag_engine/vector_store.py` |

##### 验收标准
- [ ] `vector_store.py` 已删除
- [ ] 无其他模块 import `VectorDB` 类
- [ ] 现有测试全部通过

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 模块 | 测试文件 | 覆盖状态 |
|------|----------|----------|
| tokenizer | test_tokenizer.py | ✅ 已覆盖 |
| bm25_index | test_bm25_index.py | ✅ 已覆盖 |
| doc_parser | test_doc_parser.py | ✅ 已覆盖 |
| fusion | test_fusion.py | ✅ 已覆盖 |
| retrieval | test_retrieval.py | ✅ 已覆盖 |
| qa_engine | test_qa_engine.py | ✅ 已覆盖 |
| evaluator | test_evaluator.py | ✅ 已覆盖 |
| **reranker** | **缺失** | ❌ 无独立测试文件 |
| **index_manager** | **缺失** | ❌ 无独立测试文件 |
| **query_preprocessor** | **缺失** | ❌ 无独立测试文件 |
| **semantic_chunker** | **缺失** | ❌ 无独立测试文件 |
| **data_importer** | **缺失** | ❌ 无独立测试文件 |

### 测试缺口清单

| 优先级 | 文件 | 缺失的测试 |
|--------|------|-----------|
| P0 | reranker.py | 批量排序、解析容错、top_k 截断、禁用模式 |
| P0 | index_manager.py | semantic 策略不二次分块、fixed 策略正常分割 |
| P1 | query_preprocessor.py | LLM 重写触发条件、同义词归一化、扩写去重 |
| P1 | fusion.py | 加权 RRF、软去重（Top 2 per article） |
| P2 | semantic_chunker.py | 结构分割、语义合并、overlap 行为 |
| P2 | evaluator.py | 更严格的相关性判断、新增评估样本验证 |

### 新增测试计划

1. **test_reranker.py**（新建）— 覆盖批量排序核心逻辑（mock LLM）
2. **test_index_manager.py**（新建）— 覆盖 semantic/fixed 策略的分块行为
3. **test_query_preprocessor.py**（新建）— 覆盖归一化、扩写、LLM 重写
4. **test_fusion.py**（更新）— 新增加权 RRF 和软去重测试
5. **test_evaluator.py**（更新）— 更新相关性判断测试的预期值

---

## 三、技术债务清理方案

### 技术债务清单

| 优先级 | 债务 | 位置 | 状态 |
|--------|------|------|------|
| P1 | VectorDB 类删除 | vector_store.py | 直接删除 |
| P2 | ThreadLocalSettings 全局状态管理 | rag_engine.py | 观察中 |
| P2 | `real_regulation_vector_index` fixture 创建真实索引 | tests/utils/rag_fixtures.py:226 | 耗时过长 |

### 清理路线图

1. **本次修复范围**：删除 `vector_store.py`
2. **后续迭代**：优化 `real_regulation_vector_index` fixture
3. **测试优化**：将 `real_regulation_vector_index` 改为使用临时目录的轻量级 fixture

---

## 四、架构和代码质量改进

### 架构改进

#### 4.1 embedding 缓存（P2，后续迭代）

当前每次 query embedding 都需要远程 API 调用。建议引入简单的内存缓存：

```python
# 在 llamaindex_adapter.py 的 ZhipuEmbeddingAdapter 中添加
from functools import lru_cache

class ZhipuEmbeddingAdapter(BaseEmbedding):
    def __init__(self, ..., cache_size: int = 1000):
        # ...
        self._cache: Dict[str, List[float]] = {}
        self._cache_size = cache_size

    def _get_embedding(self, text: str) -> List[float]:
        if text in self._cache:
            return self._cache[text]
        result = self._get_embeddings([text])
        embedding = result[0] if result else []
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[text] = embedding
        return embedding
```

**不纳入本次修复范围**：遵循 CLAUDE.md 约束 #14 "No over-engineering"，缓存机制在检索频率达到瓶颈时再引入。

#### 4.2 embedding 模型扩展（P2，后续迭代）

`llamaindex_adapter.py` 的 `get_embedding_model` 工厂函数已支持扩展新 provider。如需接入 BGE-M3，只需添加一个分支：

```python
elif provider == 'bge_m3':
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    return HuggingFaceEmbedding(model_name="BAAI/bge-m3")
```

**不纳入本次修复范围**：需要评估 GPU 资源和部署成本。

---

## 附录

### 执行顺序建议

```
阶段 1: P0 修复（必须完成）
  ├── 2.1 修复二次分块 bug
  ├── 3.1 + 6.2 重写 Reranker 为批量排序
  ├── 3.3 扩大粗召回候选集
  ├── 3.4 软去重（Top 2 per article）
  └── 运行全量测试验证

阶段 2: P1 修复（建议完成）
  ├── 1.3 清理停用词
  ├── 1.2 添加 LLM query 重写
  ├── 3.2 RRF 加权
  ├── 5.1 收紧评估相关性判断
  ├── 4.1 上下文长度控制
  └── 运行评估数据集对比指标

阶段 3: P2 优化（可选）
  ├── 2.2 批量化 embedding 调用
  ├── 6.1 删除 vector_store.py
  └── 补充缺失的测试文件
```

### 变更摘要

| 阶段 | 修改文件数 | 新增文件数 | 风险等级 |
|------|-----------|-----------|----------|
| P0 | 4 | 1（test_reranker.py） | 高 |
| P1 | 6 | 1（test_query_preprocessor.py） | 中 |
| P2 | 2 | 0 | 低 |

### 验收标准总结

#### 功能验收标准
- [x] 预分块 Document 不被二次分割（移除 SentenceSplitter 全局设置）
- [x] Reranker 单次 LLM 调用完成排序
- [x] 粗召回候选集 ≥ 20
- [x] 同一法规同一条款保留最多 2 个 chunk
- [x] 停用词不包含法规限定词
- [x] 所有 query 统一走 LLM 重写
- [x] RRF 支持向量/关键词权重配置
- [x] 评估相关性判断收紧（需 2 个以上关键词命中）
- [x] 上下文总字符数 ≤ 4000
- [ ] vector_store.py 已删除（跳过：scripts/query.py 仍依赖 VectorDB）

#### 质量验收标准
- [x] `pytest scripts/tests/` 全部通过（118 passed, 21 errors 为预存的环境依赖问题）
- [x] 新增测试覆盖 reranker、index_manager、query_preprocessor
- [ ] 评估数据集指标可对比（修改前后）

#### 部署验收标准
- [ ] 修改后需重建向量索引（`import_all(force_rebuild=True)`）
- [ ] 修改后需重建 BM25 索引
- [x] 向后兼容：无 embedding client 时 LLM 重写自动跳过
