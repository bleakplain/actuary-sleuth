# RAG Retrieval 质量改进 + jina-reranker-v3 集成方案

生成时间: 2026-04-03
分析范围: `scripts/lib/rag_engine/` retrieval 管线 + 精排模块

---

## 一、Retrieval 管线问题修复

基于对 retrieval 全链路的深度代码审查，发现以下问题按严重程度排列。

---

### 问题 1.1: [P1] LLM 重写覆盖归一化结果

- **文件**: `scripts/lib/rag_engine/query_preprocessor.py:62-67`
- **严重程度**: ⚠️ P1
- **影响**: 归一化术语替换效果被丢弃，query 中的口语化表达可能未被标准化

##### 当前代码
```python
# query_preprocessor.py:62-67
def preprocess(self, query: str) -> PreprocessedQuery:
    normalized = self._normalize(query)       # "退保" → "解除保险合同"
    rewritten = self._rewrite_with_llm(query) # 用原始 query 重写！
    if rewritten and rewritten != normalized:
        normalized = rewritten                 # 重写结果覆盖归一化
    expanded = self._expand(normalized)
    ...
```

##### 问题分析
LLM 重写用的是**原始 query**（而非归一化后的），但重写结果直接覆盖了归一化结果。例如用户输入"退保有什么规定"：
1. `_normalize` → "解除保险合同有什么规定"（术语标准化）
2. `_rewrite_with_llm` 用原始"退保有什么规定"重写 → 可能输出"关于退保的规定"
3. 归一化结果被覆盖，"解除保险合同"变回"退保"

##### 修复方案
用归一化后的文本送给 LLM 重写，确保 LLM 在标准化术语基础上改写。

##### 代码变更
```python
# query_preprocessor.py:62-67 — 替换 preprocess 方法
def preprocess(self, query: str) -> PreprocessedQuery:
    normalized = self._normalize(query)

    rewritten = self._rewrite_with_llm(normalized)  # 改用 normalized
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
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/query_preprocessor.py` |

##### 验收标准
- [ ] LLM 重写接收归一化后的 query 而非原始 query
- [ ] 术语归一化结果在 LLM 重写前已生效
- [ ] `_SIMPLE_QUERY_THRESHOLD` 仍按原始 query 长度判断（短 query 跳过重写）

---

### 问题 1.2: [P1] Reranker 使用原始 query 而非预处理后的 query

- **文件**: `scripts/lib/rag_engine/rag_engine.py:350`
- **严重程度**: ⚠️ P1
- **影响**: reranker 的排序判断与检索使用的 query 不一致，尤其是 LLM 重写后差异更大

##### 当前代码
```python
# rag_engine.py:322-351
def _hybrid_search(self, query_text, top_k, filters):
    config = self.config.hybrid_config
    ...
    results = hybrid_search(
        index=index,
        bm25_index=self._bm25_index,
        query_text=query_text,  # ← 传给 hybrid_search 内部做预处理
        ...
    )

    if self._reranker:
        results = self._reranker.rerank(query_text, results, top_k=top_k)  # ← 用原始 query！
```

##### 问题分析
`hybrid_search()` 内部通过 `QueryPreprocessor` 将 query 预处理后再检索，但 reranker 收到的仍是用户原始输入。当 LLM 重写改动了 query 时，reranker 的排序依据与实际检索不匹配。

##### 修复方案
将 `_hybrid_search` 中的预处理结果向上传递，reranker 使用预处理后的 query。

##### 代码变更

**文件 1: `scripts/lib/rag_engine/retrieval.py`** — hybrid_search 返回 preprocessed query

```python
# retrieval.py:57 — 修改返回类型
def hybrid_search(
    index,
    bm25_index,
    query_text: str,
    vector_top_k: int,
    keyword_top_k: int,
    k: int = 60,
    filters: Optional[Dict[str, Any]] = None,
    preprocessor: Optional[QueryPreprocessor] = None,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
    max_chunks_per_article: int = 3,
) -> Tuple[List[Dict[str, Any]], str]:  # 新增返回 preprocessed_query
    """混合检索（向量 + BM25 关键词，RRF 融合 + Query 预处理）"""
    if not index or not bm25_index:
        return [], query_text

    pp = preprocessor or _get_default_preprocessor()
    preprocessed = pp.preprocess(query_text)
    ...
    return reciprocal_rank_fusion(...), preprocessed.normalized
```

**文件 2: `scripts/lib/rag_engine/rag_engine.py`** — 使用预处理的 query 做 rerank

```python
# rag_engine.py:322-351 — 修改 _hybrid_search
def _hybrid_search(self, query_text, top_k, filters):
    config = self.config.hybrid_config
    index = self.index_manager.get_index()
    if not index:
        return []

    results, preprocessed_query = hybrid_search(
        index=index,
        bm25_index=self._bm25_index,
        query_text=query_text,
        vector_top_k=config.vector_top_k,
        keyword_top_k=config.keyword_top_k,
        k=config.rrf_k,
        filters=filters,
        preprocessor=self._preprocessor,
        vector_weight=config.vector_weight,
        keyword_weight=config.keyword_weight,
        max_chunks_per_article=config.max_chunks_per_article,
    )

    if self._reranker:
        results = self._reranker.rerank(preprocessed_query, results, top_k=top_k)  # 用预处理后的 query

    return results
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/retrieval.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: hybrid_search 返回 preprocessed query | 精确传递，改动小 | 修改 hybrid_search 返回类型 | ✅ |
| B: rag_engine 内部再做一次预处理 | 不改 retrieval 签名 | 重复预处理，LLM 调用两次 | ❌ |
| C: reranker 内部调用 preprocessor | 解耦 | reranker 需要依赖 preprocessor | ❌ |

##### 验收标准
- [ ] reranker 收到的 query 与向量检索使用的 query 一致
- [ ] `hybrid_search` 返回 `(results, preprocessed_query)` 元组
- [ ] 不使用 hybrid_search 的路径（纯向量检索）不受影响

---

### 问题 1.3: [P2] BM25 停用词过滤了疑问词

- **文件**: `scripts/lib/rag_engine/tokenizer.py:25`
- **严重程度**: ⚠️ P2
- **影响**: BM25 检索丢失疑问意图上下文，"如何"、"怎么" 被过滤

##### 当前代码
```python
# tokenizer.py:21-26
_BUILTIN_STOPWORDS: Set[str] = {
    '的', '了', '在', '是', ...
    '什么', '怎么', '如何', '可以', '以及', '或者', '还是',
}
```

##### 修复方案
从内置停用词中移除疑问词。疑问词对 BM25 的查询意图匹配有帮助，尤其是区分"等待期如何计算"和"等待期计算"时。

##### 代码变更
```python
# tokenizer.py:21-26 — 移除疑问词
_BUILTIN_STOPWORDS: Set[str] = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些',
    '以及', '或者', '还是',
}
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/tokenizer.py` |

##### 验收标准
- [ ] "如何"、"怎么"、"什么" 不再被过滤
- [ ] 外部 stopwords.txt 中如包含这些词，仍会被过滤（外部文件优先）
- [ ] BM25 检索保留疑问上下文

---

### 问题 1.4: [P2] 查询扩展导致 RRF 分数膨胀

- **文件**: `scripts/lib/rag_engine/retrieval.py:90-106`
- **严重程度**: ⚠️ P2
- **影响**: 同一 chunk 在多个扩展 query 中出现会累加 RRF 分数，导致排序偏差

##### 当前代码
```python
# retrieval.py:103-106
for fv in vector_futures:
    vector_nodes.extend(fv.result())  # 直接 extend，无去重
for fk in keyword_futures:
    keyword_nodes.extend(_to_node_with_scores(fk.result()))
```

##### 修复方案
在 `fusion.py` 中添加 `num_queries` 参数，对来自扩展 query 的结果应用衰减权重（除以总 query 数量）。

##### 代码变更

**文件 1: `scripts/lib/rag_engine/retrieval.py`** — 传递 num_queries

```python
# retrieval.py:108-112 — 修改返回调用
total_queries = 1 + (len(preprocessed.expanded) - 1 if preprocessed.did_expand else 0)
return reciprocal_rank_fusion(
    vector_nodes, keyword_nodes, k=k,
    vector_weight=vector_weight, keyword_weight=keyword_weight,
    max_chunks_per_article=max_chunks_per_article,
    num_queries=total_queries,
), preprocessed.normalized
```

**文件 2: `scripts/lib/rag_engine/fusion.py`** — 添加衰减权重

```python
# fusion.py:19-26 — 修改函数签名
def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
    max_chunks_per_article: int = 3,
    num_queries: int = 1,
) -> List[Dict[str, Any]]:
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

    # ... 后续不变
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/retrieval.py` |
| 修改 | `scripts/lib/rag_engine/fusion.py` |

##### 验收标准
- [ ] 不启用查询扩展时，RRF 分数与之前一致
- [ ] 启用查询扩展时，分数有衰减，不会不成比例膨胀
- [ ] `num_queries` 有默认值 1，向后兼容

---

### 问题 1.5: [P2] Reranker 内容截断可能丢失关键信息

- **文件**: `scripts/lib/rag_engine/reranker.py:78`
- **严重程度**: ⚠️ P2
- **影响**: 法规条款的"但书"（例外条款）通常在后半部分，800 字符截断可能丢失

##### 当前代码
```python
# reranker.py:78
truncated = content[:800] if len(content) > 800 else content
```

##### 修复方案
将截断长度提升到 1500 字符，并从 settings.json 的 `rerank.content_max_chars` 读取（可配置）。截断时添加 `[内容已截断]` 标记。

##### 代码变更
```python
# reranker.py:78 — 修改截断逻辑
max_chars = self._config.content_max_chars
truncated = content[:max_chars] if len(content) > max_chars else content
if len(content) > max_chars:
    truncated += '\n[内容已截断]'
```

##### 涉及文件
| 操作 | 文件路径 |
|------|---------|
| 修改 | `scripts/lib/rag_engine/reranker.py` |

##### 验收标准
- [ ] 截断长度可通过配置调整
- [ ] 截断时附加 `[内容已截断]` 标记

---

## 二、集成 jina-reranker-v3 本地精排模型

### 背景

当前精排使用 LLM（GLM-4-flash）做 batch ranking，存在以下问题：
- 每次调用消耗 API token，成本高
- 内容截断导致长条款信息丢失
- 通用 LLM 对排序任务不如专用 reranker 模型

已下载 jina-reranker-v3 GGUF 及依赖到 `/mnt/d/work/models/`：
- `jina-reranker-v3-Q4_K_M.gguf` (379MB)
- `projector.safetensors` (3MB)
- `rerank.py` (GGUFReranker 实现，已修复 llama-tokenize 路径和编码问题)
- `hanxiao-llama.cpp/build/bin/` (llama-embedding + llama-tokenize)

目标：集成 jina-reranker-v3 作为可选精排方案，通过 settings.json 配置切换，支持与现有 LLM Reranker 的 A/B test。

---

### 2.1 settings.json 新增配置

在 `llm` 中新增 `rerank` 场景（复用现有 provider 模式），新增 `rerank` 顶层配置节：

```json
{
  "llm": {
    "rerank": { "provider": "llm", "model": "glm-4-flash" }
  },
  "rerank": {
    "enabled": true,
    "top_k": 5,
    "max_candidates": 20,
    "content_max_chars": 800,
    "jina": {
      "model_path": "/mnt/d/work/models/jina-reranker-v3-Q4_K_M.gguf",
      "projector_path": "/mnt/d/work/models/projector.safetensors",
      "llama_embedding_path": "/mnt/d/work/models/hanxiao-llama.cpp/build/bin/llama-embedding"
    }
  }
}
```

- `llm.rerank.provider`: `"llm"`（当前方案）或 `"jina_local"`（本地 jina-reranker-v3）
- `rerank` 节点：精排通用参数
- `rerank.jina`：jina-reranker-v3 专用路径

---

### 2.2 修改 `scripts/lib/config.py`

新增 `RerankerConfig` 配置类，`LLMConfig._SCENES` 新增 `'rerank'`。

```python
# config.py — 新增 RerankerConfig
class RerankerConfig:
    """精排配置"""
    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('rerank', {})

    @property
    def enabled(self) -> bool:
        return self._config.get('enabled', True)

    @property
    def top_k(self) -> int:
        return self._config.get('top_k', 5)

    @property
    def max_candidates(self) -> int:
        return self._config.get('max_candidates', 20)

    @property
    def content_max_chars(self) -> int:
        return self._config.get('content_max_chars', 800)

    @property
    def jina(self) -> Dict[str, str]:
        return self._config.get('jina', {})
```

`LLMConfig._SCENES` 修改：
```python
_SCENES = ('qa', 'audit', 'eval', 'embed', 'name_parser', 'ocr', 'rerank')
```

`Config._init_nested_configs()` 新增：
```python
self._reranker = RerankerConfig(self._config)
```

新增快捷函数：
```python
def get_rerank_llm_config() -> Dict[str, Any]:
    return get_llm_config().rerank

def get_reranker_config() -> 'RerankerConfig':
    return get_config()._reranker
```

---

### 2.3 新建 `scripts/lib/rag_engine/jina_reranker_impl.py`

从 `/mnt/d/work/models/rerank.py` 提取核心实现，封装为内部适配器（不依赖外部脚本）。

```python
#!/usr/bin/env python3
"""jina-reranker-v3 GGUF 内部实现（基于 llama.cpp）"""
import json
import logging
import os
import subprocess
import tempfile
from typing import Dict, List, Optional

import numpy as np
from safetensors import safe_open

logger = logging.getLogger(__name__)


class _MLPProjector:
    """MLP projector to project hidden states to embedding space."""

    def __init__(self, linear1_weight, linear2_weight):
        self.linear1_weight = linear1_weight
        self.linear2_weight = linear2_weight

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = x @ self.linear1_weight.T
        x = np.maximum(0, x)
        x = x @ self.linear2_weight.T
        return x


def _load_projector(projector_path: str) -> _MLPProjector:
    with safe_open(projector_path, framework="numpy") as f:
        w0 = f.get_tensor("projector.0.weight")
        w2 = f.get_tensor("projector.2.weight")
    return _MLPProjector(w0, w2)


class GGUFReranker:
    """GGUF-based jina-reranker-v3 implementation."""

    def __init__(
        self,
        model_path: str,
        projector_path: str,
        llama_embedding_path: str,
    ):
        self._model_path = model_path
        self._llama_embedding_path = llama_embedding_path
        self._llama_tokenize_path = os.path.join(
            os.path.dirname(llama_embedding_path), 'llama-tokenize'
        )
        self._projector = _load_projector(projector_path)
        self._doc_embed_token_id = 151670
        self._query_embed_token_id = 151671

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """Rerank documents by relevance to query.

        Returns:
            List of {'index': int, 'relevance_score': float} sorted by score desc.
        """
        prompt = self._format_prompt(query, documents)
        embeddings = self._get_hidden_states(prompt)
        tokens = self._tokenize(prompt)

        tokens_array = np.array(tokens)
        query_positions = np.where(tokens_array == self._query_embed_token_id)[0]
        doc_positions = np.where(tokens_array == self._doc_embed_token_id)[0]

        if len(query_positions) == 0 or len(doc_positions) == 0:
            logger.warning("Special tokens not found, returning original order")
            return [
                {'index': i, 'relevance_score': 1.0 / (i + 1)}
                for i in range(len(documents))
            ]

        query_hidden = embeddings[query_positions[0]:query_positions[0] + 1]
        doc_hidden = embeddings[doc_positions]

        query_embeds = self._projector(query_hidden)
        doc_embeds = self._projector(doc_hidden)

        dot_product = np.sum(doc_embeds * query_embeds, axis=-1)
        doc_norm = np.sqrt(np.sum(doc_embeds * doc_embeds, axis=-1))
        query_norm = np.sqrt(np.sum(query_embeds * query_embeds, axis=-1))
        scores = dot_product / (doc_norm * query_norm)

        results = [
            {'index': idx, 'relevance_score': float(score)}
            for idx, score in enumerate(scores)
        ]
        results.sort(key=lambda x: x['relevance_score'], reverse=True)

        if top_n is not None:
            results = results[:top_n]
        return results

    def _format_prompt(self, query: str, docs: List[str]) -> str:
        prefix = (
            "<|im_start|>system\n"
            "You are a search relevance expert who can determine a ranking "
            "of the passages based on how relevant they are to the query.\n"
            "<|im_end|>\n<|im_start|>user\n"
        )
        suffix = "<|im_end|>\n<|im_start|>assistant\n"

        doc_prompts = [
            f'<passage id="{i}">\n{doc}<|embed_token|>\n</passage>'
            for i, doc in enumerate(docs)
        ]
        body = (
            f"Rank the passages based on their relevance to query: {query}\n"
            + "\n".join(doc_prompts) + "\n"
            + f"<query>\n{query}<|rerank_token|>\n</query>"
        )
        return prefix + body + suffix

    def _get_hidden_states(self, prompt: str) -> np.ndarray:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(prompt)
            prompt_file = f.name
        try:
            result = subprocess.run(
                [
                    self._llama_embedding_path,
                    '-m', self._model_path,
                    '-f', prompt_file,
                    '--pooling', 'none',
                    '--embd-separator', '<#JINA_SEP#>',
                    '--embd-normalize', '-1',
                    '--embd-output-format', 'json',
                    '--ubatch-size', '512',
                    '--ctx-size', '8192',
                    '-ngl', '99',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            output = json.loads(result.stdout)
            return np.array([item['embedding'] for item in output['data']])
        finally:
            os.unlink(prompt_file)

    def _tokenize(self, prompt: str) -> List[int]:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(prompt)
            prompt_file = f.name
        try:
            result = subprocess.run(
                [self._llama_tokenize_path, '-m', self._model_path, '-f', prompt_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            tokens = []
            for line in result.stdout.decode('utf-8', errors='replace').strip().split('\n'):
                if '->' in line:
                    token_id = int(line.split('->')[0].strip())
                    tokens.append(token_id)
            return tokens
        finally:
            os.unlink(prompt_file)
```

---

### 2.4 修改 `scripts/lib/rag_engine/reranker.py` — 核心变更

将 jina-reranker-v3 逻辑融合进现有 reranker.py，保持单一文件。

#### RerankConfig 扩展

```python
# reranker.py — 替换 RerankConfig
from dataclasses import dataclass, field

@dataclass(frozen=True)
class RerankConfig:
    enabled: bool = True
    top_k: int = 5
    max_candidates: int = 20
    provider: str = "llm"  # "llm" | "jina_local"
    content_max_chars: int = 800
    jina_config: Dict[str, str] = field(default_factory=dict)
```

#### 新增 JinaLocalReranker 类

```python
# reranker.py — 新增类
class JinaLocalReranker:
    """基于 jina-reranker-v3 GGUF 的本地精排器"""

    def __init__(self, config: RerankConfig):
        self._config = config
        self._reranker = None

    def _ensure_loaded(self) -> None:
        if self._reranker is not None:
            return
        from .jina_reranker_impl import GGUFReranker
        jina_cfg = self._config.jina_config
        self._reranker = GGUFReranker(
            model_path=jina_cfg['model_path'],
            projector_path=jina_cfg['projector_path'],
            llama_embedding_path=jina_cfg['llama_embedding_path'],
        )
        logger.info("jina-reranker-v3 模型已加载")

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self._config.enabled or not candidates:
            return candidates[:top_k] if top_k else candidates

        self._ensure_loaded()
        top_k = top_k or self._config.top_k
        candidates = candidates[:self._config.max_candidates]

        try:
            documents = [c.get('content', '') for c in candidates]
            results = self._reranker.rerank(query, documents, top_n=top_k)

            output: List[Dict[str, Any]] = []
            for r in results:
                candidate = dict(candidates[r['index']])
                candidate['rerank_score'] = r['relevance_score']
                candidate['reranked'] = True
                output.append(candidate)
            return output
        except Exception as e:
            logger.warning(f"jina-reranker-v3 精排失败: {e}, 回退到原始顺序")
            fallback = [dict(candidates[i]) for i in range(min(top_k, len(candidates)))]
            for r in fallback:
                r['reranked'] = False
            return fallback
```

#### 新增 create_reranker 工厂函数

```python
# reranker.py — 新增工厂函数
def create_reranker(
    llm_client: Optional[Any],
    config: RerankConfig,
) -> 'LLMReranker | JinaLocalReranker':
    """根据配置创建精排器"""
    if config.provider == "jina_local":
        return JinaLocalReranker(config)
    return LLMReranker(llm_client, config)
```

**设计理由**：reranker 创建是 reranker 模块的内部职责，不是 `lib/llm/factory` 的职责。`lib/llm/factory` 创建的是 `BaseLLMClient`（文本生成/嵌入），而 jina-reranker 是独立的精排模型，不继承 `BaseLLMClient`。与现有模式一致：`rag_engine/` 内部模块自己管理自己的组件创建。

---

### 2.5 修改 `scripts/lib/rag_engine/rag_engine.py`

`_setup_llm()` 中使用 `create_reranker()` 创建 reranker。

```python
# rag_engine.py — 修改 _setup_llm
def _setup_llm(self):
    if not self._llm_client:
        self._llm_client = LLMClientFactory.create_qa_llm()

    self._llm = ClientLLMAdapter(self._llm_client)
    self._embed_model = LLMClientFactory.create_embed_llm()

    from lib.config import get_reranker_config
    reranker_cfg = get_reranker_config()
    rerank_config = RerankConfig(
        enabled=reranker_cfg.enabled,
        top_k=reranker_cfg.top_k,
        max_candidates=reranker_cfg.max_candidates,
        provider=self.config.hybrid_config.rerank_provider,
        content_max_chars=reranker_cfg.content_max_chars,
        jina_config=reranker_cfg.jina,
    )
    self._reranker = create_reranker(self._llm_client, rerank_config)
    self._preprocessor = QueryPreprocessor(llm_client=self._llm_client)
```

---

### 2.6 修改 `scripts/lib/rag_engine/config.py`

`HybridQueryConfig` 新增 `rerank_provider` 字段：

```python
# config.py:9-18 — HybridQueryConfig 扩展
@dataclass
class HybridQueryConfig:
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    enable_rerank: bool = True
    rerank_top_k: int = 5
    rerank_provider: str = "llm"  # 新增: "llm" | "jina_local"
    max_chunks_per_article: int = 3
```

---

### 2.7 修改 `scripts/lib/rag_engine/__init__.py`

导出新增类和函数：

```python
from .reranker import LLMReranker, RerankConfig, JinaLocalReranker, create_reranker
```

`__all__` 新增 `'JinaLocalReranker'` 和 `'create_reranker'`。

---

### 2.8 新增测试 `scripts/tests/lib/rag_engine/test_jina_reranker.py`

```python
class TestJinaLocalReranker:
    def test_rerank_returns_ranked_results(self):
        """jina reranker 返回按相关性排序的结果"""

    def test_rerank_empty_candidates(self):
        """空候选返回空列表"""

    def test_rerank_disabled_returns_original(self):
        """禁用时返回原始候选"""

    def test_rerank_failure_fallback(self):
        """模型调用失败时回退到原始顺序"""

    def test_lazy_loading(self):
        """首次 rerank 时才加载模型"""

    def test_output_format_matches_llm_reranker(self):
        """输出包含 rerank_score 和 reranked 字段"""


class TestCreateReranker:
    def test_create_llm_reranker(self):
        """provider='llm' 返回 LLMReranker"""

    def test_create_jina_local_reranker(self):
        """provider='jina_local' 返回 JinaLocalReranker"""
```

---

## 三、涉及文件总览

| 操作 | 文件路径 | 章节 | 说明 |
|------|---------|------|------|
| 修改 | `scripts/config/settings.json` | 2.1 | 新增 rerank 配置 |
| 修改 | `scripts/lib/config.py` | 2.2 | 新增 RerankerConfig |
| 修改 | `scripts/lib/rag_engine/query_preprocessor.py` | 1.1 | LLM 重写用 normalized query |
| 修改 | `scripts/lib/rag_engine/retrieval.py` | 1.2, 1.4 | 返回 preprocessed query + num_queries |
| 修改 | `scripts/lib/rag_engine/fusion.py` | 1.4 | 扩展衰减权重 |
| 修改 | `scripts/lib/rag_engine/tokenizer.py` | 1.3 | 移除疑问词停用 |
| 修改 | `scripts/lib/rag_engine/reranker.py` | 1.5, 2.4 | 扩展 RerankConfig + JinaLocalReranker + 工厂 |
| 修改 | `scripts/lib/rag_engine/config.py` | 2.6 | HybridQueryConfig 新增 rerank_provider |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` | 1.2, 2.5 | 用 preprocessed query + create_reranker |
| 修改 | `scripts/lib/rag_engine/__init__.py` | 2.7 | 导出 |
| 新建 | `scripts/lib/rag_engine/jina_reranker_impl.py` | 2.3 | GGUFReranker 内部实现 |
| 新建 | `scripts/tests/lib/rag_engine/test_jina_reranker.py` | 2.8 | jina reranker 测试 |

---

## 四、验收标准总结

### 功能验收
- [ ] LLM 重写使用归一化后的 query
- [ ] reranker 使用预处理后的 query 而非原始 query
- [ ] BM25 检索保留疑问词
- [ ] 查询扩展分数有衰减机制
- [ ] Reranker 截断长度可通过配置调整
- [ ] `provider="jina_local"` 时使用 jina-reranker-v3
- [ ] `provider="llm"` 时行为与当前完全一致
- [ ] jina-reranker-v3 延迟加载，不影响启动时间
- [ ] JinaLocalReranker 输出格式与 LLMReranker 一致

### 质量验收
- [ ] `pytest scripts/tests/lib/rag_engine/` 全部通过
- [ ] `mypy scripts/lib/rag_engine/` 无类型错误

### 兼容性验收
- [ ] `hybrid_search()` 签名向后兼容（`num_queries` 有默认值）
- [ ] 不修改 settings.json 时行为完全不变
- [ ] `RerankConfig` 新字段有默认值，现有代码无需修改即可运行

### A/B Test 验证
- [ ] 切换 `llm.rerank.provider` 后同一 query 可得到不同排序结果
- [ ] jina-reranker-v3 排序结果更准确（通过人工评估确认）
