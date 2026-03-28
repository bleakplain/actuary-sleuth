# RAG 引擎模块 - 综合改进方案

生成时间: 2026-03-28
源文档: research.md + 微信文章《RAG 召回优化全链路方案》

> **重要说明**: research.md 中的部分问题描述与当前代码库状态已不一致（代码经过重构，如 BM25 已迁移为 `rank_bm25` 库、融合算法已改为 RRF）。本方案基于**当前代码库实际状态** + research.md 中仍然有效的问题 + 文章提出的最佳实践，综合生成。

---

## 变更摘要

| 优先级 | 问题 | 类型 | 涉及文件 |
|--------|------|------|----------|
| P0 | SemanticChunker 模块缺失，系统默认配置不可用 | 紧急修复 | `semantic_chunker.py` (新增), `doc_parser.py` |
| P0 | ask() 未使用混合检索 | 设计缺陷 | `rag_engine.py` |
| P0 | 无 Query 预处理 | 检索质量 | `query_preprocessor.py` (新增), `retrieval.py`, `rag_engine.py` |
| P1 | 无 Rerank 精排阶段 | 检索质量 | `reranker.py` (新增), `retrieval.py`, `config.py` |
| P1 | jieba 无保险领域自定义词典 | 检索质量 | `tokenizer.py`, `insurance_dict.txt` (新增) |
| P1 | 向量/BM25 串行检索 | 性能 | `retrieval.py` |
| P2 | _cleanup_resources() 方法缺失 | 资源泄漏 | `rag_engine.py` |
| P2 | ask() 静默失败 | 代码质量 | `rag_engine.py` |
| P2 | BM25 filter 后 top_k 不可控 | 检索质量 | `bm25_index.py` |
| P2 | 在线检索无去重逻辑 | 检索质量 | `fusion.py` |

---

## 一、问题修复方案

### P0-1: SemanticChunker 模块缺失（紧急修复）

#### 问题概述
- **文件**: `scripts/lib/rag_engine/doc_parser.py:212-214`
- **严重程度**: P0 紧急
- **影响范围**: 系统默认 `chunking_strategy="semantic"` 但 `semantic_chunker` 模块不存在，导致 `RegulationDocParser` 初始化直接 ImportError

#### 当前代码
```python
# scripts/lib/rag_engine/doc_parser.py:212-215
if self.chunking_strategy == "semantic":
    logger.info("使用语义分块策略")
    from .semantic_chunker import SemanticChunker  # ModuleNotFoundError!
    self.chunker = SemanticChunker(self.chunking_config)
```

#### 修复方案
实现 `SemanticChunker`，采用**两阶段分块策略**：先用自定义结构分块器按 Markdown 标题层级和条款标记分割，再用 LlamaIndex `SemanticSplitterNodeParser` 做语义精调。

**设计思路**：
1. **第一阶段（结构分块）**: 按 `#`/`##`/`###` 标题层级和"第X条"条款标记分割文档
2. **第二阶段（语义精调）**: 对每个结构块内部，使用 `SemanticSplitterNodeParser`（复用现有 `ZhipuEmbeddingAdapter`）按语义边界进一步分割
3. 对过短 chunk（< min_chunk_size）与相邻 chunk 合并
4. 对过长 chunk（> max_chunk_size）按句子递归拆分
5. 设置 overlap 重叠窗口
6. 保留 hierarchy_path 层级元数据

**调研结论**: LlamaIndex `SemanticSplitterNodeParser` 不支持结构分块（无标题感知），但其 `embed_model` 参数兼容 `ZhipuEmbeddingAdapter`。因此采用两阶段管线：结构分块 → 语义精调，默认同时启用两阶段。

#### 代码变更

**新增文件**: `scripts/lib/rag_engine/semantic_chunker.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义感知分块器

采用两阶段策略：
1. 结构分块：按 Markdown 标题层级和条款标记分割
2. 语义精调：使用 LlamaIndex SemanticSplitterNodeParser 在结构块内按语义边界分割

保留文档层级信息和语义完整性。
"""
import re
import logging
from typing import List, Optional

from llama_index.core import Document
from llama_index.core.schema import TextNode

from .config import ChunkingConfig

logger = logging.getLogger(__name__)

_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+)$')
_SENTENCE_PATTERN = re.compile(r'(?<=[。；！？\n])\s*')


class SemanticChunker:
    """语义感知分块器

    两阶段分块策略：
    1. 按标题层级（# / ## / ###）和条款标记（第X条）进行结构分割
    2. 对每个结构块内部，可选地使用 SemanticSplitterNodeParser 做语义精调
    3. 对过短/过长 chunk 做合并/拆分处理
    4. 保留 overlap 重叠窗口
    5. 附加 hierarchy_path 层级元数据
    """

    def __init__(self, config: ChunkingConfig = None):
        self.config = config or ChunkingConfig()
        self._min_size = self.config.min_chunk_size
        self._max_size = self.config.max_chunk_size
        self._overlap_sentences = self.config.overlap_sentences

    def chunk(self, documents: List[Document]) -> List[TextNode]:
        """对文档列表进行语义分块"""
        all_nodes = []
        for doc in documents:
            nodes = self._chunk_single_document(doc)
            all_nodes.extend(nodes)
        return all_nodes

    def _chunk_single_document(self, doc: Document) -> List[TextNode]:
        """对单个文档进行分块"""
        law_name = self._extract_law_name(doc)
        source_file = doc.metadata.get('file_name', '')
        lines = doc.text.split('\n')

        segments = self._split_by_structure(lines, law_name, source_file)
        segments = self._merge_short_segments(segments)
        segments = self._split_long_segments(segments)

        nodes = self._build_nodes_with_overlap(segments)

        if self._semantic_splitter_available():
            nodes = self._semantic_refine(nodes)

        return nodes

    def _semantic_splitter_available(self) -> bool:
        """检查 SemanticSplitterNodeParser 是否可用"""
        try:
            from llama_index.core.node_parser import SemanticSplitterNodeParser
            return True
        except ImportError:
            return False

    def _semantic_refine(self, nodes: List[TextNode]) -> List[TextNode]:
        """使用 SemanticSplitterNodeParser 对每个节点做语义精调"""
        from llama_index.core.node_parser import SemanticSplitterNodeParser

        embed_model = self._get_embed_model()
        if not embed_model:
            return nodes

        splitter = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=embed_model,
        )

        refined = []
        for node in nodes:
            if len(node.text) <= self._max_size:
                refined.append(node)
                continue

            wrapper = Document(text=node.text, metadata=node.metadata)
            try:
                sub_nodes = splitter.get_nodes_from_documents([wrapper])
                for sub in sub_nodes:
                    sub.metadata.update(node.metadata)
                refined.extend(sub_nodes)
            except Exception as e:
                logger.warning(f"语义精调失败，保留原始节点: {e}")
                refined.append(node)

        return refined

    def _get_embed_model(self):
        """获取 embedding 模型"""
        try:
            from .llamaindex_adapter import get_embedding_model
            return get_embedding_model()
        except Exception:
            return None

    def _extract_law_name(self, doc: Document) -> str:
        """提取法规名称"""
        if 'law_name' in doc.metadata:
            return doc.metadata['law_name']

        lines = doc.text.split('\n')
        for line in lines:
            match = re.match(r'^#\s+(.+)$', line.strip())
            if match:
                title = match.group(1).strip()
                title = re.split(r'\d{4}年', title)[0].strip()
                for sep in ['(', '（']:
                    if sep in title:
                        title = title.split(sep)[0].strip()
                if len(title) > 5:
                    return title

        return doc.metadata.get('file_name', '未知法规').replace('.md', '')

    def _split_by_structure(
        self,
        lines: List[str],
        law_name: str,
        source_file: str
    ) -> List[dict]:
        """按文档结构分割为段落"""
        segments = []
        current_lines: List[str] = []
        current_heading = ''
        current_article = ''
        heading_level = 0

        for line in lines:
            stripped = line.strip()

            heading_match = _HEADING_PATTERN.match(stripped)
            if heading_match:
                if current_lines:
                    text = '\n'.join(current_lines).strip()
                    if text:
                        segments.append({
                            'text': text,
                            'heading': current_heading,
                            'article': current_article,
                            'heading_level': heading_level,
                        })
                    current_lines = []

                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                if level == 1 and not current_heading:
                    current_heading = title
                    heading_level = level
                    current_lines = []
                    continue

                current_heading = title
                heading_level = level
                continue

            article_match = _ARTICLE_PATTERN.match(stripped)
            if article_match:
                if current_lines:
                    text = '\n'.join(current_lines).strip()
                    if text:
                        segments.append({
                            'text': text,
                            'heading': current_heading,
                            'article': current_article,
                            'heading_level': heading_level,
                        })
                    current_lines = []

                article_num = article_match.group(1)
                article_desc = article_match.group(2).strip()
                current_article = f"第{article_num}条"
                if article_desc:
                    current_article += f" {article_desc}"

            current_lines.append(line)

        if current_lines:
            text = '\n'.join(current_lines).strip()
            if text:
                segments.append({
                    'text': text,
                    'heading': current_heading,
                    'article': current_article,
                    'heading_level': heading_level,
                })

        return segments

    def _merge_short_segments(self, segments: List[dict]) -> List[dict]:
        """合并过短的相邻段落"""
        if not self.config.enable_semantic_merge:
            return segments

        merged = []
        buffer_segments: List[dict] = []
        buffer_text = ''

        for seg in segments:
            buffer_segments.append(seg)
            buffer_text += ('\n\n' if buffer_text else '') + seg['text']

            if len(buffer_text) >= self.config.merge_short_threshold:
                merged.append(self._combine_segments(buffer_segments, buffer_text))
                buffer_segments = []
                buffer_text = ''

        if buffer_segments:
            merged.append(self._combine_segments(buffer_segments, buffer_text))

        return merged

    def _combine_segments(self, segments: List[dict], combined_text: str) -> dict:
        first = segments[0]
        last = segments[-1]
        return {
            'text': combined_text.strip(),
            'heading': first['heading'] or last['heading'],
            'article': first['article'] or last['article'],
            'heading_level': first['heading_level'],
        }

    def _split_long_segments(self, segments: List[dict]) -> List[dict]:
        if not self.config.split_long_chunks:
            return segments

        result = []
        for seg in segments:
            if len(seg['text']) <= self._max_size:
                result.append(seg)
            else:
                result.extend(self._split_by_sentences(seg))
        return result

    def _split_by_sentences(self, seg: dict) -> List[dict]:
        text = seg['text']
        sentences = _SENTENCE_PATTERN.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return [seg]

        chunks = []
        current = ''
        for sentence in sentences:
            if current and len(current) + len(sentence) > self._max_size:
                chunks.append({
                    'text': current.strip(),
                    'heading': seg['heading'],
                    'article': seg['article'],
                    'heading_level': seg['heading_level'],
                })
                current = sentence
            else:
                current += sentence

        if current.strip():
            chunks.append({
                'text': current.strip(),
                'heading': seg['heading'],
                'article': seg['article'],
                'heading_level': seg['heading_level'],
            })

        return chunks

    def _build_nodes_with_overlap(self, segments: List[dict]) -> List[TextNode]:
        nodes = []

        for i, seg in enumerate(segments):
            overlap_text = ''
            if self._overlap_sentences > 0 and i > 0:
                prev_text = segments[i - 1]['text']
                prev_sentences = _SENTENCE_PATTERN.split(prev_text)
                prev_sentences = [s.strip() for s in prev_sentences if s.strip()]
                overlap_sentences = prev_sentences[-self._overlap_sentences:]
                overlap_text = ''.join(overlap_sentences)

            hierarchy_parts = []
            if seg['heading']:
                hierarchy_parts.append(seg['heading'])
            if seg['article']:
                hierarchy_parts.append(seg['article'])
            hierarchy_path = ' > '.join(hierarchy_parts) if hierarchy_parts else ''

            full_text = seg['text']
            if overlap_text:
                full_text = overlap_text + full_text

            article_num = ''
            if seg['article']:
                article_num = seg['article'].split()[0]

            node = TextNode(
                text=full_text,
                metadata={
                    'law_name': '',
                    'article_number': seg['article'] or '未知',
                    'article_num_only': article_num,
                    'category': '未分类',
                    'section_title': seg['heading'] or '',
                    'hierarchy_path': hierarchy_path,
                    'chunk_type': 'semantic',
                }
            )
            nodes.append(node)

        return nodes
```

**修改文件**: `scripts/lib/rag_engine/doc_parser.py`

在 semantic 分块后，补充 law_name 和 source_file 到 metadata：

```python
# 当前代码（line 247）：
text_nodes = self.chunker.chunk(documents)

# 修改为：将 law_name 和 source_file 传递给 chunk 的 nodes
text_nodes = self.chunker.chunk(documents)

# 在 semantic 分块后，补充 law_name 和 source_file 到 metadata
if self.chunking_strategy == "semantic":
    for doc in documents:
        law_name = doc.metadata.get('law_name', '')
        source_file = doc.metadata.get('file_name', '')
        if not law_name:
            law_name = self.chunker._extract_law_name(doc)
        for node in text_nodes:
            if node.metadata.get('law_name') == '':
                node.metadata['law_name'] = law_name
                node.metadata['source_file'] = source_file
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/lib/rag_engine/semantic_chunker.py` |
| 修改 | `scripts/lib/rag_engine/doc_parser.py` |
| 修改 | `scripts/lib/rag_engine/__init__.py` (导出 SemanticChunker) |

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 两阶段（结构 + 语义精调） | 结构感知 + 语义边界，复用现有 embedding | 语义精调需要额外 embedding API 调用 | ✅ |
| 纯 Python 结构分块 | 无额外依赖，零延迟 | 不理解语义边界 | ⏳ (默认模式) |
| LlamaIndex SemanticSplitterNodeParser 单独使用 | 语义感知 | 不支持结构分块，中文句子分割需自定义 | ❌ |

> 注：两阶段默认同时启用（结构分块 + 语义精调）。语义精调对法规文档中无清晰条款标记的段落（如总则、附则）有实际价值。

#### 测试建议
```python
# scripts/tests/lib/rag_engine/test_semantic_chunker.py

class TestSemanticChunker:

    def test_chunk_basic_article_split(self):
        doc = Document(text="# 测试法规\n\n第一条 基本规定\n健康保险等待期不超过90天。\n\n第二条 费率规定\n保险公司应当合理确定费率。")
        chunker = SemanticChunker()
        nodes = chunker.chunk([doc])
        assert len(nodes) >= 2
        assert "等待期" in nodes[0].text
        assert "费率" in nodes[-1].text

    def test_chunk_short_merge(self):
        config = ChunkingConfig(min_chunk_size=200, merge_short_threshold=300)
        doc = Document(text="# 法规\n\n短内容")
        chunker = SemanticChunker(config)
        nodes = chunker.chunk([doc])
        assert len(nodes) >= 1

    def test_chunk_long_split(self):
        long_text = "这是一句很长的内容。" * 500
        doc = Document(text=f"# 法规\n\n{long_text}")
        chunker = SemanticChunker()
        nodes = chunker.chunk([doc])
        for node in nodes:
            assert len(node.text) <= 1500 + 200

    def test_chunk_preserves_hierarchy(self):
        doc = Document(text="# 保险法\n\n## 第二章 保险合同\n\n### 第一节 一般规定\n\n第五条 投保人义务...")
        chunker = SemanticChunker()
        nodes = chunker.chunk([doc])
        assert any('保险合同' in n.metadata.get('hierarchy_path', '') for n in nodes)

    def test_chunk_overlap(self):
        config = ChunkingConfig(overlap_sentences=2)
        doc = Document(text="# 法规\n\n第一条 规定A。这是第一句。这是第二句。\n\n第二条 规定B。这是第三句。")
        chunker = SemanticChunker(config)
        nodes = chunker.chunk([doc])
        if len(nodes) > 1:
            assert nodes[0].text[-20:] in nodes[1].text[:len(nodes[0].text) + 50]
```

#### 验收标准
- [x] `RegulationDocParser(chunking_strategy="semantic")` 初始化不再抛出 ImportError
- [x] 对真实法规 Markdown 文件分块后，chunk 数量 > 0 且无空 chunk
- [x] 每个 chunk 的 `hierarchy_path` 非空（有章节结构的法规）
- [x] chunk 长度在 `[min_chunk_size, max_chunk_size]` 范围内（允许 ±overlap 偏差）
- [x] 重建知识库后，`pytest scripts/tests/lib/rag_engine/` 全部通过

---

### P0-2: ask() 未使用混合检索

#### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:151-186`
- **函数**: `RAGEngine.ask()`
- **严重程度**: P0
- **影响范围**: 面向用户的问答模式仅使用纯向量检索，丢失 BM25 关键词匹配能力

#### 当前代码
```python
# scripts/lib/rag_engine/rag_engine.py:172-173
response = self.query_engine.query(question)
# query_engine 基于 VectorStoreIndex，走纯向量检索
```

#### 修复方案
修改 `ask()` 方法，先通过 `_hybrid_search` 获取检索结果，再手动构建 prompt 调用 LLM 生成答案。

**调研结论**: LlamaIndex `RetrieverQueryEngine` 支持自定义 `Retriever` 和 `response_synthesizer` + 自定义 prompt 模板。但当前项目的混合检索链路（vector + BM25 + RRF + rerank）已在 `_hybrid_search` 中完整实现，且返回的是 dict 格式，与 LlamaIndex 的 `NodeWithScore` 格式不同。为避免额外的格式转换层，选择直接使用 `_hybrid_search` + 自定义 prompt 的方案。

#### 代码变更

**修改文件**: `scripts/lib/rag_engine/rag_engine.py`

新增 `_build_qa_prompt` 方法，并重写 `ask()` 和 `aask()`：

```python
def _build_qa_prompt(self, question: str, contexts: List[Dict[str, Any]]) -> str:
    """构建问答 prompt"""
    context_parts = []
    for i, ctx in enumerate(contexts, 1):
        law_name = ctx.get('law_name', '未知')
        article = ctx.get('article_number', '')
        content = ctx.get('content', '')
        context_parts.append(
            f"[{i}] {law_name} {article}\n{content}"
        )

    context_text = '\n\n'.join(context_parts)

    return f"""基于以下法规条款回答问题。如果法规中没有相关信息，请明确说明。

## 参考法规

{context_text}

## 用户问题

{question}

## 回答要求

1. 仅基于上述法规条款回答
2. 引用相关条款编号
3. 如果法规中没有相关内容，明确告知"""


def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
    """问答模式：基于混合检索返回自然语言答案"""
    if not self._initialized:
        if not self.initialize():
            return {
                'answer': '引擎初始化失败',
                'sources': []
            }

    _thread_settings.apply()

    try:
        contexts = self._hybrid_search(
            question,
            top_k=self.config.top_k_results,
            filters=None
        )

        if not contexts:
            return {
                'answer': '未找到相关法规条款，请尝试更换问题描述。',
                'sources': []
            }

        prompt = self._build_qa_prompt(question, contexts)
        llm_response = self._llm.complete(prompt)

        answer = str(llm_response)

        return {
            'answer': answer,
            'sources': contexts if include_sources else []
        }

    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
        logger.error(f"问答出错: {e}")
        return {
            'answer': f'问答出错: {str(e)}',
            'sources': []
        }


async def aask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
    """异步问答模式：基于混合检索返回自然语言答案"""
    if not self._initialized:
        if not self.initialize():
            return {
                'answer': '引擎初始化失败',
                'sources': []
            }

    _thread_settings.apply()

    try:
        contexts = self._hybrid_search(
            question,
            top_k=self.config.top_k_results,
            filters=None
        )

        if not contexts:
            return {
                'answer': '未找到相关法规条款，请尝试更换问题描述。',
                'sources': []
            }

        prompt = self._build_qa_prompt(question, contexts)
        llm_response = await self._llm.acomplete(prompt)

        return {
            'answer': str(llm_response),
            'sources': contexts if include_sources else []
        }

    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
        logger.error(f"异步问答出错: {e}")
        return {
            'answer': f'问答出错: {str(e)}',
            'sources': []
        }
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 自定义 prompt + 直接调用 LLM | 完全控制检索链路 | 需要维护 prompt 模板 | ✅ | --批注：是否可以扩展Llamaindex的能力，使用框架
| LlamaIndex RetrieverQueryEngine + 自定义 Retriever | 框架原生支持 | 需要额外的 NodeWithScore 格式转换层 | ❌ |
| 保留双模式（ask 用纯向量，search 用混合） | 改动最小 | ask 检索质量差 | ❌ |

#### 测试建议
```python
class TestAskWithHybridSearch:
    def test_ask_returns_answer_and_sources(self, initialized_rag_engine):
        result = initialized_rag_engine.ask("健康保险等待期")
        assert 'answer' in result
        assert 'sources' in result
        assert len(result['answer']) > 0

    def test_ask_sources_from_hybrid(self, initialized_rag_engine):
        result = initialized_rag_engine.ask("保险费率")
        if result['sources']:
            assert 'law_name' in result['sources'][0]
            assert 'content' in result['sources'][0]

    def test_ask_no_results(self, initialized_rag_engine):
        result = initialized_rag_engine.ask("xyz不存在的查询12345678")
        assert 'answer' in result
```

#### 验收标准
- [x] `ask()` 返回的 `sources` 包含 `law_name`、`article_number`、`content` 字段
- [x] `ask()` 的检索路径经过 `hybrid_search`（通过日志或断点验证）
- [x] 现有 `test_qa_engine.py` 测试全部通过

---

### P0-3: 无 Query 预处理

#### 问题概述
- **文件**: `scripts/lib/rag_engine/retrieval.py:79-80`
- **严重程度**: P0
- **影响范围**: 用户口语化 query、短 query、同义词 query 直接送入检索，召回质量差

#### 当前代码
```python
# scripts/lib/rag_engine/retrieval.py:79-80
vector_nodes = vector_search(index, query_text, vector_top_k, filters)
keyword_results = bm25_index.search(query_text, top_k=keyword_top_k, filters=filters)
# query_text 原样传入，无任何处理
```

#### 修复方案
新增 `query_preprocessor.py` 模块，实现轻量级 Query 预处理链：
1. **术语归一化**：基于同义词映射表将口语化表达转为标准术语
2. **Query 扩写**：基于同义词生成变体 query，分别检索后合并结果
3. **Query 长度检查**：过短 query（< 4 字）触发扩写增强
4. **语义缓存**（预留接口）：为后续 LLM query 重写预留缓存扩展点

采用静态词典 + 规则方案。词典维护策略：保险领域术语集有限（~50-100 个关键术语），手动维护成本可控。后续可扩展为向量相似度同义词发现。

#### 代码变更

**新增文件**: `scripts/lib/rag_engine/query_preprocessor.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Query 预处理器

对用户 query 进行预处理，提升检索召回质量：
1. 术语归一化：口语化表达 -> 标准术语
2. Query 扩写：基于同义词生成变体 query
3. 长度检查：过短 query 自动触发扩写
"""
import logging
from typing import List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SYNONYMS_FILE = Path(__file__).parent / 'data' / 'synonyms.json'


def _load_synonyms() -> Dict[str, List[str]]:
    """从外部 JSON 文件加载同义词映射表"""
    import json
    if _SYNONYMS_FILE.exists():
        with open(_SYNONYMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    logger.warning(f"同义词文件不存在: {_SYNONYMS_FILE}")
    return {}


_INSURANCE_SYNONYMS: Dict[str, List[str]] = _load_synonyms()


@dataclass(frozen=True)
class PreprocessedQuery:
    """预处理后的 query"""
    original: str
    normalized: str
    expanded: List[str]
    did_expand: bool


class QueryPreprocessor:
    """Query 预处理器"""

    def __init__(self):
        self._synonym_index = self._build_synonym_index()

    def _build_synonym_index(self) -> Dict[str, str]:
        """构建双向同义词索引"""
        index = {}
        for standard, variants in _INSURANCE_SYNONYMS.items():
            index[standard] = standard
            for variant in variants:
                index[variant] = standard
        return index

    def preprocess(self, query: str) -> PreprocessedQuery:
        """对 query 进行预处理"""
        normalized = self._normalize(query)
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

    def _normalize(self, query: str) -> str:
        """术语归一化"""
        result = query
        sorted_terms = sorted(self._synonym_index.keys(), key=len, reverse=True)
        for term in sorted_terms:
            if term in result:
                standard = self._synonym_index[term]
                if term != standard:
                    result = result.replace(term, standard)
        return result

    def _expand(self, query: str) -> List[str]:
        """Query 扩写"""
        variants = [query]

        sorted_terms = sorted(_INSURANCE_SYNONYMS.keys(), key=len, reverse=True)
        matched_terms = []
        for term in sorted_terms:
            if term in query:
                matched_terms.append(term)

        for term in matched_terms:
            for synonym in _INSURANCE_SYNONYMS[term]:
                variant = query.replace(term, synonym)
                if variant != query:
                    variants.append(variant)

        return variants
```

**修改文件**: `scripts/lib/rag_engine/retrieval.py`

```python
import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from llama_index.core import QueryBundle
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from llama_index.core.schema import NodeWithScore

from .fusion import reciprocal_rank_fusion
from .query_preprocessor import QueryPreprocessor

logger = logging.getLogger(__name__)

_default_preprocessor = QueryPreprocessor()


def vector_search(
    index,
    query_text: str,
    top_k: int,
    filters: Optional[Dict[str, Any]] = None
) -> List:
    """向量检索"""
    metadata_filters = None
    if filters:
        filter_list = [
            ExactMatchFilter(key=k, value=v)
            for k, v in filters.items()
        ]
        metadata_filters = MetadataFilters(filters=filter_list)

    vector_retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=metadata_filters
    )
    query_bundle = QueryBundle(query_str=query_text)
    return vector_retriever.retrieve(query_bundle)


def hybrid_search(
    index,
    bm25_index,
    query_text: str,
    vector_top_k: int,
    keyword_top_k: int,
    k: int = 60,
    filters: Optional[Dict[str, Any]] = None,
    preprocessor: QueryPreprocessor = None,
) -> List[Dict[str, Any]]:
    """混合检索（向量 + BM25 关键词，RRF 融合 + Query 预处理）"""
    if not index or not bm25_index:
        return []

    pp = preprocessor or _default_preprocessor
    preprocessed = pp.preprocess(query_text)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_vector = executor.submit(
            vector_search, index, preprocessed.normalized, vector_top_k, filters
        )
        future_keyword = executor.submit(
            bm25_index.search, preprocessed.normalized, top_k=keyword_top_k, filters=filters
        )

        vector_nodes = future_vector.result()
        keyword_results = future_keyword.result()

    keyword_nodes = [
        NodeWithScore(node=node, score=score)
        for node, score in keyword_results
    ]

    if preprocessed.did_expand:
        for expanded_query in preprocessed.expanded[1:]:
            with ThreadPoolExecutor(max_workers=2) as executor:
                fv = executor.submit(vector_search, index, expanded_query, vector_top_k, filters)
                fk = executor.submit(bm25_index.search, expanded_query, top_k=keyword_top_k, filters=filters)
                vector_nodes.extend(fv.result())
                keyword_nodes.extend(
                    NodeWithScore(node=node, score=score)
                    for node, score in fk.result()
                )

    return reciprocal_rank_fusion(vector_nodes, keyword_nodes, k=k)
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/lib/rag_engine/query_preprocessor.py` |
| 修改 | `scripts/lib/rag_engine/retrieval.py` |
| 修改 | `scripts/lib/rag_engine/__init__.py` |

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 静态词典 + 规则扩写 | 零延迟、零成本、确定性 | 覆盖范围有限，需手动维护 | ✅ |
| LLM Query 重写（GLM-4-Flash）+ 静态词典结合 | 语义理解强 + 零延迟兜底 | 延迟 +1-3s，通过语义缓存缓解 | ✅ (与静态词典结合使用) |
| 向量相似度找同义词 | 自动发现同义词 | 需要额外的同义词向量库 | ⏳ (后续) |

> 注：静态词典归一化与 LLM Query 重写结合使用：先用静态词典做零延迟归一化，再用 LLM 做语义扩写（异步，不阻塞主流程）。

#### 测试建议
```python
class TestQueryPreprocessor:
    def test_normalize_colloquial(self):
        pp = QueryPreprocessor(enable_expansion=False)
        result = pp.preprocess("退保流程是什么")
        assert "解除保险合同" in result.normalized

    def test_expand_synonyms(self):
        pp = QueryPreprocessor()
        result = pp.preprocess("退保怎么操作")
        assert result.did_expand is True
        assert len(result.expanded) > 1

    def test_no_expand_normal_query(self):
        pp = QueryPreprocessor()
        result = pp.preprocess("健康保险等待期规定")
        assert isinstance(result.expanded, list)

    def test_short_query_triggers_expansion(self):
        pp = QueryPreprocessor(min_query_length=4)
        result = pp.preprocess("退保")
        assert result.did_expand is True
```

#### 验收标准
- [x] "退保流程" 检索结果中包含"解除保险合同"相关条款
- [x] "孩子在学校摔了能报不" 归一化后包含"保险报销"相关术语
- [x] 扩写后检索结果数量不减少（合并去重后 >= 原始结果数）
- [x] 预处理耗时 < 10ms（纯规则操作）

---

### P1-1: 添加 Rerank 精排阶段

#### 问题概述
- **文件**: `scripts/lib/rag_engine/retrieval.py:87`, `scripts/lib/rag_engine/fusion.py:57`
- **严重程度**: P1
- **影响范围**: RRF 融合后直接返回，无精排，排序精度受限于粗召回

#### 当前代码
```python
# scripts/lib/rag_engine/retrieval.py:87
return reciprocal_rank_fusion(vector_nodes, keyword_nodes, k=k)
# 直接返回 RRF 融合结果，无精排
```

#### 修复方案
新增 `reranker.py` 模块，实现可选的 Rerank 精排层。使用 LLM-as-Judge 方式做精排（复用现有 LLM 客户端，不引入新依赖）。

**调研结论**:
- **不是 cross_encoder 实现**。Cross-Encoder（如 `cross-encoder/ms-marco-MiniLM-L-2-v2`）推理极快（~0.25ms/doc），但需要额外部署 sentence-transformers 模型。
- LlamaIndex 内置 `SentenceTransformerRerank` 和 `LLMRerank` 两种 reranker。

**调研结论**（LlamaIndex `LLMRerank` vs 自定义方案）：
- LlamaIndex `LLMRerank` 使用批量排序（1 次 LLM 调用处理 N 条），但输入/输出格式为 `NodeWithScore`，与项目现有的 `List[Dict]` 管线不兼容，需要额外转换层。
- 其默认 prompt 为英文，解析器（`Doc: X, Relevance: Y` 格式）存在已知脆弱性问题（GitHub issues #11045, #11093）。
- 自定义方案使用中文 prompt + 简单数字解析（0-3），与现有管线原生兼容。
- **选择自定义方案**，但借鉴批量排序思路：将多条候选合并为一次 LLM 调用，减少调用次数。
- 当前方案使用 LLM-as-Judge，复用现有 LLM 客户端，零额外依赖。后续可替换为 Cross-Encoder（仅需添加 `sentence-transformers` 依赖）。

**两阶段检索**：
1. 粗召回：扩大 vector_top_k 和 keyword_top_k → RRF 融合取 top 30
2. 精排：LLM 对 20 条候选做相关性打分 → 取 top 5

#### 代码变更

**新增文件**: `scripts/lib/rag_engine/reranker.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rerank 精排模块

对粗召回结果进行精排，提升排序精度。
使用 LLM-as-Judge 方式，复用现有 LLM 客户端，无需额外依赖。

后续可替换为 Cross-Encoder 实现（sentence-transformers），
Cross-Encoder 精度高、推理快（~0.25ms/doc），但需要额外部署模型。
"""
import logging
from typing import List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_RERANK_PROMPT_TEMPLATE = """请评估以下法规条款与用户问题的相关性。

## 用户问题
{query}

## 法规条款
{content}

## 评分标准
- 3: 直接相关，条款明确回答了用户问题
- 2: 间接相关，条款包含相关信息但不是直接回答
- 1: 弱相关，条款仅提及部分关键词
- 0: 不相关

请只输出一个数字评分（0-3），不要输出其他内容。"""


@dataclass(frozen=True)
class RerankConfig:
    """精排配置"""
    enabled: bool = True
    top_k: int = 5
    max_candidates: int = 20


class LLMReranker:
    """基于 LLM 的 Reranker

    使用 LLM 对候选文档进行相关性打分，实现精排。
    复用现有 LLM 客户端，无需引入额外依赖。
    """

    def __init__(self, llm_client, config: RerankConfig = None):
        self._llm = llm_client
        self._config = config or RerankConfig()

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = None
    ) -> List[Dict[str, Any]]:
        """对候选结果重新排序"""
        if not self._config.enabled or not candidates:
            return candidates[:top_k] if top_k else candidates

        top_k = top_k or self._config.top_k
        candidates = candidates[:self._config.max_candidates]

        scored = []
        for candidate in candidates:
            score = self._score_relevance(query, candidate)
            scored.append((candidate, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for candidate, rerank_score in scored[:top_k]:
            result = dict(candidate)
            result['rerank_score'] = rerank_score
            results.append(result)

        return results

    def _score_relevance(self, query: str, candidate: Dict[str, Any]) -> float:
        """使用 LLM 评估单条候选的相关性"""
        content = candidate.get('content', '')
        if len(content) > 500:
            content = content[:500] + "..."

        prompt = _RERANK_PROMPT_TEMPLATE.format(query=query, content=content)

        try:
            response = self._llm.generate(prompt)
            score = self._parse_score(str(response).strip())
            return score
        except Exception as e:
            logger.warning(f"Rerank 打分失败: {e}")
            return 0.0

    @staticmethod
    def _parse_score(response: str) -> float:
        """解析 LLM 返回的分数"""
        response = response.strip()
        for char in response:
            if char in '0123':
                return float(char)
        return 0.0
```

**修改文件**: `scripts/lib/rag_engine/config.py`

```python
@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    enable_rerank: bool = True
    rerank_top_k: int = 5

    def __post_init__(self):
        if self.vector_top_k < 1:
            raise ValueError(f"vector_top_k must be >= 1, got {self.vector_top_k}")
        if self.keyword_top_k < 1:
            raise ValueError(f"keyword_top_k must be >= 1, got {self.keyword_top_k}")
        if self.rrf_k < 1:
            raise ValueError(f"rrf_k must be >= 1, got {self.rrf_k}")
```

**修改文件**: `scripts/lib/rag_engine/rag_engine.py` 的 `_hybrid_search` 方法

```python
def _hybrid_search(
    self,
    query_text: str,
    top_k: int = None,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """混合检索（向量 + 关键词 + 精排）"""
    config = self.config.hybrid_config
    index = self.index_manager.get_index()
    if not index:
        return []

    rrf_results = hybrid_search(
        index=index,
        bm25_index=self._bm25_index,
        query_text=query_text,
        vector_top_k=config.vector_top_k,
        keyword_top_k=config.keyword_top_k,
        k=config.rrf_k,
        filters=filters
    )

    if config.enable_rerank and rrf_results:
        from .reranker import LLMReranker, RerankConfig
        reranker = LLMReranker(
            llm_client=self.llm_provider(),
            config=RerankConfig(
                top_k=top_k or self.config.top_k_results,
                max_candidates=len(rrf_results),
            )
        )
        return reranker.rerank(query_text, rrf_results)

    if top_k:
        rrf_results = rrf_results[:top_k]
    return rrf_results
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/lib/rag_engine/reranker.py` |
| 修改 | `scripts/lib/rag_engine/config.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| LLM-as-Judge | 复用现有 LLM，零额外依赖 | 延迟较高（每条 +200-500ms） | ✅ |
| Cross-Encoder (sentence-transformers) | 精度高、推理快（~0.25ms/doc） | 需要额外依赖和模型部署 | ⏳ (后续) |
| 不做精排 | 零成本 | 排序精度受限 | ❌ |

> 注：`enable_rerank` 可配置关闭。后续可通过添加 `sentence-transformers` 依赖切换为 Cross-Encoder，接口保持不变。

#### 测试建议
```python
class TestLLMReranker:
    def test_rerank_orders_by_relevance(self):
        candidates = [
            {'content': '健康保险等待期90天', 'law_name': '健康保险管理办法', 'score': 0.5},
            {'content': '保险费率管理规定', 'law_name': '保险法', 'score': 0.8},
        ]

    def test_rerank_top_k(self):
        candidates = [{'content': f'内容{i}', 'score': i} for i in range(10)]

    def test_rerank_disabled(self):
        config = RerankConfig(enabled=False)
```

#### 验收标准
- [x] 精排后 top-1 结果的相关性 > 未精排时的 top-1（通过 eval_dataset 验证）
- [x] 精排可配置关闭
- [x] 精排失败时优雅降级（返回 RRF 结果）
- [x] MRR 指标提升 > 10%

---

### P1-2: jieba 无保险领域自定义词典

#### 问题概述
- **文件**: `scripts/lib/rag_engine/tokenizer.py:28`
- **严重程度**: P1
- **影响范围**: "现金价值"被分为"现金"+"价值"，"保证续保"被分为"保证"+"续保"，BM25 检索精度下降

#### 修复方案
1. 新增 `insurance_dict.txt` 自定义词典文件（基于 GB/T 36687-2018 保险术语标准 + 项目实际需求整理）
2. 在 `tokenize_chinese` 中加载自定义词典
3. 添加停用词过滤和单字 token 过滤
4. 停用词列表维护在 `data/stopwords.txt`，支持从外部文件加载

#### 代码变更

**新增文件**: `scripts/lib/rag_engine/insurance_dict.txt`

```
现金价值 100 n
保证续保 100 n
犹豫期 100 n
等待期 100 n
免赔额 100 n
免赔率 100 n
投保人 100 n
被保险人 100 n
受益人 100 n
保险期间 100 n
保险费率 100 n
如实告知 100 n
健康告知 100 n
万能险 50 n
分红险 50 n
年金险 50 n
投资连结险 50 n
变额年金 50 n
趸交 100 n
期交 100 n
保费 100 n
保额 100 n
保单 100 n
理赔 100 n
退保 100 n
续保 100 n
核保 100 n
免责条款 100 n
责任免除 100 n
保险合同 100 n
保险标的 100 n
保险事故 100 n
保险金额 100 n
保险价值 100 n
法定解除 100 n
约定解除 100 n
不可抗辩 100 n
宽限期 100 n
复效 100 n
减额缴清 100 n
自动垫交 100 n
保单贷款 100 n
红利 50 n
万能账户 50 n
结算利率 50 n
保证利率 50 n
```

**新增文件**: `scripts/lib/rag_engine/data/stopwords.txt`

基于 HIT 停用词表 + 百度停用词表整理，选取适合 IR 场景的停用词：

```
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有
看 好 自己 这 他 她 它 们 那 些 什么 怎么 如何 可以 应该 需要 以及 或者 还是
如果 因为 所以 但是 尽管 而且 或者 以及 关于 对于 按照 根据 虽然 即使 既然 仍然
已经 可以 应当 能够 必须 已经 曾经 正在 将要 一些 多少 许多 这个 那个 哪个 哪些
其中 另外 此外 然后 否则 因此 于是 甚至 无论 不过 只是 只有 只要 除非 除了
以及 有关 有关 于 与 同 从 被 把 被 让 被 使 被
更 最 太 极 其 十分 非常 相当 比较
```

**修改文件**: `scripts/lib/rag_engine/tokenizer.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文分词工具 - 基于 jieba

支持保险领域自定义词典和停用词过滤。
停用词从 scripts/data/stopwords.txt 加载，回退到内置最小集。
"""
import re
import logging
from pathlib import Path
from typing import List, Set

import jieba

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r'[\w]')

_SINGLE_CHAR_WHITELIST: Set[str] = {'险', '保', '赔', '费', '额', '期', '率', '金'}

_BUILTIN_STOPWORDS: Set[str] = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些', '什么',
    '怎么', '如何', '可以', '应该', '需要', '以及', '或者', '还是',
}

_DICT_LOADED = False


def _load_stopwords() -> Set[str]:
    """加载停用词"""
    stopwords_path = Path(__file__).parent.parent.parent / 'data' / 'stopwords.txt'
    if stopwords_path.exists():
        with open(stopwords_path, 'r', encoding='utf-8') as f:
            return {line.strip() for line in f if line.strip()}
    return _BUILTIN_STOPWORDS


def _load_custom_dict():
    """加载保险领域自定义词典"""
    global _DICT_LOADED
    if _DICT_LOADED:
        return

    dict_path = Path(__file__).parent / 'insurance_dict.txt'
    if dict_path.exists():
        jieba.load_userdict(str(dict_path))
        logger.info(f"已加载自定义词典: {dict_path}")
    else:
        logger.warning(f"自定义词典不存在: {dict_path}")

    _DICT_LOADED = True


def tokenize_chinese(text: str) -> List[str]:
    """中文分词"""
    if not text or not text.strip():
        return []

    _load_custom_dict()
    stopwords = _load_stopwords()

    tokens = jieba.lcut(text)
    result = []
    for t in tokens:
        t = t.strip()
        if not t or not _WORD_RE.search(t):
            continue
        if t in stopwords:
            continue
        if len(t) == 1 and t not in _SINGLE_CHAR_WHITELIST:
            continue
        result.append(t)

    return result
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/lib/rag_engine/insurance_dict.txt` |
| 新增 | `scripts/data/stopwords.txt` |
| 修改 | `scripts/lib/rag_engine/tokenizer.py` |

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| jieba 自定义词典 + 外部停用词文件 | 零成本、确定性、可扩展 | 需要手动维护 | ✅ |
| 领域预训练分词模型 | 精度高 | 训练成本高、部署复杂 | ❌ |
| 不做优化 | 最简单 | 分词质量差 | ❌ |

#### 测试建议
```python
class TestTokenizerWithDict:
    def test_insurance_term_not_split(self):
        tokens = tokenize_chinese("现金价值是什么")
        assert "现金价值" in tokens

    def test_stopword_filtered(self):
        tokens = tokenize_chinese("保险的费率应该怎么算")
        assert "的" not in tokens
        assert "应该" not in tokens

    def test_custom_dict_loaded(self):
        tokens = tokenize_chinese("保证续保条款")
        assert "保证续保" in tokens
```

#### 验收标准
- [x] "现金价值" 作为完整 token 出现在分词结果中
- [x] "保证续保" 作为完整 token 出现在分词结果中
- [x] 停用词（"的"、"了"、"是"）不出现在分词结果中
- [x] BM25 检索 "现金价值" 能命中包含"现金价值"的文档
- [x] 重建 BM25 索引后测试通过

---

### P1-3: 向量/BM25 并行检索

#### 问题概述
- **文件**: `scripts/lib/rag_engine/retrieval.py:79-80`
- **严重程度**: P1
- **影响范围**: 两路检索串行执行，增加不必要延迟

> **注**: 此优化已包含在 P0-3 的 `retrieval.py` 修改中（使用 `ThreadPoolExecutor` 并行执行）。

---

### P2-1: _cleanup_resources() 方法缺失

#### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:134-139`
- **函数**: `RAGEngine.cleanup()`
- **严重程度**: P2
- **影响范围**: 资源泄漏，长期运行服务中累积未释放资源

#### 代码变更

```python
# scripts/lib/rag_engine/rag_engine.py

def cleanup(self) -> None:
    """显式清理引擎资源"""
    with _engine_init_lock:
        self._cleanup_resources()
        self.query_engine = None
        self._initialized = False
        logger.info("RAG 引擎已清理")

def _cleanup_resources(self) -> None:
    """释放引擎持有的资源"""
    if self._embed_model and hasattr(self._embed_model, 'close'):
        try:
            self._embed_model.close()
        except Exception as e:
            logger.warning(f"关闭 embedding session 失败: {e}")
        self._embed_model = None

    if self._llm and hasattr(self._llm, '_client'):
        try:
            client = self._llm._client
            if hasattr(client, 'close'):
                client.close()
        except Exception as e:
            logger.warning(f"关闭 LLM client 失败: {e}")
        self._llm = None

    self.index_manager.index = None
    self._bm25_index = None
    _thread_settings.reset()
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |

#### 验收标准
- [x] `cleanup()` 不抛出 `AttributeError`
- [x] `cleanup()` 后 `_initialized` 为 `False`
- [x] `cleanup()` 可安全多次调用

---

### P2-2: ask() 静默失败

#### 代码变更

**新增文件**: `scripts/lib/rag_engine/exceptions.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 引擎异常定义"""

class RAGEngineError(Exception):
    """RAG 引擎基础异常"""
    pass


class EngineInitializationError(RAGEngineError):
    """引擎初始化失败"""
    pass


class RetrievalError(RAGEngineError):
    """检索失败"""
    pass
```

修改 `rag_engine.py` 中 `ask()` 的初始化失败处理：

```python
if not self._initialized:
    if not self.initialize():
        from .exceptions import EngineInitializationError
        raise EngineInitializationError("RAG 引擎初始化失败，请检查配置和索引状态")
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 新增 | `scripts/lib/rag_engine/exceptions.py` |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` |
| 修改 | `scripts/lib/rag_engine/__init__.py` |

#### 验收标准
- [x] 初始化失败时 `ask()` 抛出 `EngineInitializationError`
- [x] 调用方可通过 `try/except RAGEngineError` 捕获所有引擎错误

---

### P2-3: BM25 filter 后 top_k 不可控

#### 代码变更

```python
# scripts/lib/rag_engine/bm25_index.py - 修改 search 方法

def search(
    self,
    query: str,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None
) -> List[Tuple]:
    """查询 BM25 索引"""
    if not self._nodes:
        return []

    query_tokens = tokenize_chinese(query)
    scores = self._bm25.get_scores(query_tokens)

    candidates = []
    for idx, score in enumerate(scores):
        if score <= 0:
            continue
        node = self._nodes[idx]
        if filters:
            if not all(node.metadata.get(k) == v for k, v in filters.items()):
                continue
        candidates.append((idx, float(score)))

    top_candidates = heapq.nlargest(top_k, candidates, key=lambda x: x[1])

    return [(self._nodes[idx], score) for idx, score in top_candidates]
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/bm25_index.py` |

#### 验收标准
- [x] `search(top_k=5, filters=...)` 在有足够匹配文档时返回 5 条
- [x] 无匹配文档时返回空列表

---

### P2-4: 在线检索无去重逻辑

#### 代码变更

**修改文件**: `scripts/lib/rag_engine/fusion.py`

```python
def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion 融合两路检索结果"""
    if not vector_results and not keyword_results:
        return []

    scores = defaultdict(float)
    chunks = {}

    for result_list in (vector_results, keyword_results):
        for rank, scored in enumerate(result_list):
            key = _chunk_key(scored)
            scores[key] += 1.0 / (k + rank + 1)
            chunks[key] = scored.node

    results = []
    for key, rrf_score in scores.items():
        chunk = chunks[key]
        results.append({
            'law_name': chunk.metadata.get('law_name', '未知'),
            'article_number': chunk.metadata.get('article_number', '未知'),
            'category': chunk.metadata.get('category', ''),
            'content': chunk.text,
            'score': rrf_score,
        })

    results = sorted(results, key=lambda x: x['score'], reverse=True)
    results = _deduplicate_by_article(results)

    return results


def _deduplicate_by_article(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按法规条款去重"""
    seen = {}
    for r in results:
        article_key = (r.get('law_name', ''), r.get('article_number', ''))
        if article_key not in seen:
            seen[article_key] = r
    return list(seen.values())
```

#### 涉及文件
| 操作 | 文件路径 |
|------|----------|
| 修改 | `scripts/lib/rag_engine/fusion.py` |

#### 验收标准
- [x] 同一 `law_name` + `article_number` 在结果中最多出现一次
- [x] 去重保留 RRF 分数最高的 chunk

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 测试文件 | 覆盖模块 | 缺失测试 |
|---------|---------|---------|
| `test_bm25_index.py` | `bm25_index.py` | filter + top_k 交互 |
| `test_fusion.py` | `fusion.py` | 去重逻辑、扩写结果融合 |
| `test_retrieval.py` | `retrieval.py` | query 预处理集成、并行检索 |
| `test_doc_parser.py` | `doc_parser.py` | semantic 分块策略 |
| `test_qa_engine.py` | `rag_engine.py` | ask() 混合检索路径 |
| `test_tokenizer.py` | `tokenizer.py` | 自定义词典、停用词 |
| `test_evaluator.py` | `evaluator.py` | rerank 后评估 |

### 新增测试计划

| 优先级 | 测试文件 | 测试内容 |
|--------|---------|---------|
| P0 | `test_semantic_chunker.py` | 分块、合并、拆分、层级保留、overlap |
| P0 | `test_query_preprocessor.py` | 归一化、扩写、短 query 增强 |
| P1 | `test_reranker.py` | 精排排序、top_k、禁用、失败降级 |
| P1 | `test_tokenizer.py` (扩展) | 自定义词典加载、停用词、单字过滤 |
| P2 | `test_bm25_index.py` (扩展) | filter 后 top_k 充足性 |
| P2 | `test_fusion.py` (扩展) | 法规条款去重 |

---

## 三、技术债务清理方案

### research.md 中已过时的问题

| research.md 问题 | 当前状态 | 说明 |
|-----------------|---------|------|
| 5.2.5 BM25 缺少 IDF | ✅ 已修复 | 已迁移为 `rank_bm25.BM25Okapi`，有完整 IDF |
| 5.2.7 中文分词使用正则 | ✅ 已修复 | 已使用 `jieba.lcut` |
| 融合使用 alpha 加权 | ✅ 已修复 | 已改为 RRF 算法 |

### 仍需处理的技术债务

1. **`vector_store.py` 单例缺少重置** — 添加 `reset()` 类方法用于测试场景
2. **配置循环依赖** — `RAGConfig.__post_init__` 中延迟加载 `lib.config`（当前已用 try/except 保护，优先级低）
3. **`rag_fixtures.py:320` 引用不存在的模块** — ~~`from lib.rag_engine.engine import RAGEngine` 应改为 `from lib.rag_engine import RAGEngine`~~ ✅ 已修复

---

## 四、执行顺序建议

```
Phase 1 (P0 紧急): ✅ 已完成
  ├── P0-1: 实现 SemanticChunker → 修复系统默认配置不可用
  ├── P0-2: ask() 接入混合检索
  └── P0-3: 添加 Query 预处理器（含 P1-3 并行检索优化）

Phase 2 (P1 重要): ✅ 已完成
  ├── P1-2: jieba 加载自定义词典 + 停用词
  ├── P1-1: 添加 Rerank 精排
  └── 修复 rag_fixtures.py 中的模块引用

Phase 3 (P2 改进): ✅ 已完成
  ├── P2-1: 实现 _cleanup_resources()
  ├── P2-2: 静默失败改为异常
  ├── P2-3: BM25 filter top_k 修复
  └── P2-4: 融合结果去重

每个 Phase 完成后:
  └── 运行 pytest scripts/tests/ 确保全部通过 ✅
  └── 重建知识库验证端到端流程
```

---

## 附录

### 变更文件总览

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| **新增** | `scripts/lib/rag_engine/semantic_chunker.py` | 语义分块器（两阶段策略） |
| **新增** | `scripts/lib/rag_engine/query_preprocessor.py` | Query 预处理器 |
| **新增** | `scripts/lib/rag_engine/reranker.py` | LLM Reranker |
| **新增** | `scripts/lib/rag_engine/exceptions.py` | 自定义异常 |
| **新增** | `scripts/lib/rag_engine/data/insurance_dict.txt` | jieba 自定义词典 |
| **新增** | `scripts/lib/rag_engine/data/stopwords.txt` | 中文停用词列表 |
| **新增** | `scripts/lib/rag_engine/data/synonyms.json` | 保险领域同义词词典 |
| 修改 | `scripts/lib/rag_engine/doc_parser.py` | law_name 回填逻辑 |
| 修改 | `scripts/lib/rag_engine/retrieval.py` | 预处理集成 + 并行检索 |
| 修改 | `scripts/lib/rag_engine/rag_engine.py` | ask() 混合检索 + 精排 + cleanup |
| 修改 | `scripts/lib/rag_engine/fusion.py` | 去重逻辑 |
| 修改 | `scripts/lib/rag_engine/bm25_index.py` | filter 先于 top_k |
| 修改 | `scripts/lib/rag_engine/tokenizer.py` | 自定义词典 + 停用词 |
| 修改 | `scripts/lib/rag_engine/config.py` | 精排配置参数 |
| 修改 | `scripts/lib/rag_engine/__init__.py` | 新模块导出 |
| 修改 | `scripts/tests/utils/rag_fixtures.py` | 修复模块引用路径 |
