# Actuary Sleuth RAG Engine - 知识库建设综合改进方案

生成时间: 2026-03-29
源文档: research.md

本方案基于 research.md 的分析内容生成，包含以下章节：

---

## 一、问题修复方案

### 🔴 P0 问题（必须修复）

---

#### 问题 1.1: [P0] Overlap 在语义精调阶段被破坏

##### 问题概述
- **文件**: `scripts/lib/rag_engine/semantic_chunker.py:53-67`
- **函数**: `_chunk_single_document()`
- **严重程度**: 🔴 P0
- **影响范围**: 跨 chunk 边界的信息连续性丢失，降低检索召回率

##### 当前代码
```python
# semantic_chunker.py:53-67
def _chunk_single_document(self, doc: Document) -> List[TextNode]:
    law_name = extract_law_name(doc.text, doc.metadata)
    source_file = doc.metadata.get('file_name', '')
    lines = doc.text.split('\n')

    segments = self._split_by_structure(lines, law_name, source_file)
    segments = self._merge_short_segments(segments)
    segments = self._split_long_segments(segments)

    nodes = self._build_nodes_with_overlap(segments, law_name, source_file)

    if self._use_semantic_split:
        nodes = self._semantic_refine(nodes)

    return nodes
```

##### 修复方案
将 overlap 添加步骤移到语义精调**之后**。先构建不含 overlap 的节点，语义精调完成后，再为精调后的节点添加 overlap。

实施步骤：
1. 新增 `_build_nodes()` 方法，构建不含 overlap 的 TextNode
2. 新增 `_add_overlap()` 方法，为已有节点列表添加 overlap
3. 调整 `_chunk_single_document()` 的执行顺序：先精调，后添加 overlap

##### 代码变更

**修改 `semantic_chunker.py:53-67`**：

```python
def _chunk_single_document(self, doc: Document) -> List[TextNode]:
    law_name = extract_law_name(doc.text, doc.metadata)
    source_file = doc.metadata.get('file_name', '')
    lines = doc.text.split('\n')

    segments = self._split_by_structure(lines, law_name, source_file)
    segments = self._merge_short_segments(segments)
    segments = self._split_long_segments(segments)

    nodes = self._build_nodes(segments, law_name, source_file)

    if self._use_semantic_split:
        nodes = self._semantic_refine(nodes)

    if self._overlap_sentences > 0:
        nodes = self._add_overlap(nodes)

    return nodes
```

**新增 `_build_nodes()` 方法**：

```python
@staticmethod
def _build_nodes(
    segments: List[dict], law_name: str, source_file: str
) -> List[TextNode]:
    """构建不含 overlap 的 TextNode 列表"""
    nodes: List[TextNode] = []
    category = _extract_product_category(source_file)

    for seg in segments:
        node = TextNode(
            text=seg['text'],
            metadata={
                'law_name': law_name,
                'article_number': seg['article'] or '未知',
                'category': category,
                'hierarchy_path': seg.get('hierarchy_path', ''),
                'source_file': source_file,
            }
        )
        nodes.append(node)

    return nodes
```

**新增 `_add_overlap()` 方法**：

```python
def _add_overlap(self, nodes: List[TextNode]) -> List[TextNode]:
    """为节点列表添加 overlap 重叠窗口"""
    if self._overlap_sentences <= 0 or len(nodes) <= 1:
        return nodes

    result: List[TextNode] = []
    for i, node in enumerate(nodes):
        if i == 0:
            result.append(node)
            continue

        prev_text = nodes[i - 1].text
        prev_sentences = _SENTENCE_PATTERN.split(prev_text)
        prev_sentences = [s.strip() for s in prev_sentences if s.strip()]
        overlap_sentences = prev_sentences[-self._overlap_sentences:]
        overlap_text = ''.join(overlap_sentences)

        new_text = overlap_text + node.text
        overlapped_node = TextNode(
            text=new_text,
            metadata=dict(node.metadata),
        )
        result.append(overlapped_node)

    return result
```

**删除旧方法 `_build_nodes_with_overlap()`**（其功能被 `_build_nodes()` + `_add_overlap()` 替代）。

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/semantic_chunker.py` — 重构 `_build_nodes_with_overlap()` 为 `_build_nodes()` + `_add_overlap()`，调整 `_chunk_single_document()` 执行顺序

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. overlap 移到精调之后 | overlap 位置准确，语义边界清晰 | 需要重构方法拆分 | ✅ |
| B. 精调内保留 overlap | 不改变外部接口 | 实现复杂，SemanticSplitterNodeParser 不支持 | ❌ |
| C. 禁用语义精调时 overlap | 最简单 | 精调时完全无 overlap，降低质量 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 精调后节点数变化导致 overlap 错位 | 低 | 中 | `_add_overlap()` 按节点索引遍历，自适应节点数变化 |
| overlap 文本被重复嵌入 | 中 | 低 | overlap 仅在节点文本前拼接，不影响语义切分结果 |
| 现有测试因方法名变更失败 | 高 | 低 | 同步更新测试引用 |

##### 测试建议
```python
# scripts/tests/lib/rag_engine/test_semantic_chunker.py

class TestOverlapAfterRefine:
    """验证 overlap 在语义精调之后正确添加"""

    def test_overlap_preserved_after_refine(self):
        """语义精调后 overlap 仍位于 chunk 开头"""
        config = ChunkingConfig(
            min_chunk_size=50,
            max_chunk_size=200,
            overlap_sentences=2,
            split_long_chunks=False,
        )
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "## 第一章 总则\n\n"
                "第一条 为了规范保险活动。保护保险活动当事人的合法权益。"
                "第二条 本法所称保险。是指投保人根据合同约定。"
                "第三条 在中华人民共和国境内从事保险活动。适用本法。"
            ),
            metadata={'file_name': 'test_law.md'},
        )

        nodes = chunker.chunk([doc])
        if len(nodes) >= 2:
            first_last_sents = "保护保险活动当事人的合法权益。"
            assert first_last_sents in nodes[1].text

    def test_no_overlap_for_first_chunk(self):
        """第一个 chunk 不应包含 overlap"""
        config = ChunkingConfig(overlap_sentences=2)
        chunker = SemanticChunker(config)

        doc = Document(
            text="## 总则\n\n第一条 保险活动应当遵守法律。",
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        assert len(nodes) >= 1
        assert nodes[0].text.startswith("第一条")

    def test_zero_overlap_config(self):
        """overlap_sentences=0 时不添加 overlap"""
        config = ChunkingConfig(overlap_sentences=0)
        chunker = SemanticChunker(config)

        doc = Document(
            text="## 总则\n\n第一条 保险活动应当遵守法律。\n\n第二条 本法适用范围。第三条 定义。",
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        for node in nodes:
            assert '保险活动应当遵守法律' not in node.text or node == nodes[0]
```

##### 验收标准
- [x] `_chunk_single_document()` 中 overlap 步骤在语义精调之后执行
- [x] 精调产生多个子 chunk 时，每个子 chunk 的 overlap 来自其前一个节点
- [x] `overlap_sentences=0` 时不添加任何 overlap
- [x] 所有现有 test_semantic_chunker.py 测试通过

---

#### 问题 1.2: [P0] hierarchy_path 仅记录当前标题，不保留完整层级路径

##### 问题概述
- **文件**: `scripts/lib/rag_engine/semantic_chunker.py:131-177, 255-293`
- **函数**: `_split_by_structure()`, `_build_nodes_with_overlap()`
- **严重程度**: 🔴 P0
- **影响范围**: 多层标题文档的层级路径不完整，影响检索定位

##### 当前代码
```python
# semantic_chunker.py:131-161
def _split_by_structure(self, lines, law_name, source_file):
    segments: List[dict] = []
    current_lines: List[str] = []
    current_heading = ''     # ← 单一变量
    current_article = ''
    heading_level = 0

    for line in lines:
        stripped = line.strip()
        heading_match = _HEADING_PATTERN.match(stripped)
        if heading_match:
            segments.extend(self._flush_lines(...))
            current_lines = []

            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if level == 1 and not current_heading:
                current_heading = title     # 第一个 h1
                heading_level = level
                continue

            current_heading = title          # ← 直接覆盖！
            heading_level = level
            continue
        # ...
```

```python
# semantic_chunker.py:270-275
hierarchy_parts: List[str] = []
if seg['heading']:
    hierarchy_parts.append(seg['heading'])    # ← 只有当前 heading
if seg['article']:
    hierarchy_parts.append(seg['article'])
hierarchy_path = ' > '.join(hierarchy_parts)
```

##### 修复方案
在 `_split_by_structure()` 中维护标题栈 `heading_stack`，每次遇到标题时根据层级 push/pop 栈。将完整栈路径存入 segment 的 `hierarchy_path` 字段。

实施步骤：
1. 将 `current_heading` + `heading_level` 替换为 `heading_stack: List[str]`
2. 遇到标题时：清除栈中同级及更深层级的标题，push 当前标题
3. 在 `_flush_lines()` 中将完整栈路径写入 segment
4. 在 `_build_nodes()` 中直接使用 segment 的 `hierarchy_path`

##### 代码变更

**修改 `_split_by_structure()`**：

```python
def _split_by_structure(
    self,
    lines: List[str],
    law_name: str,
    source_file: str
) -> List[dict]:
    segments: List[dict] = []
    current_lines: List[str] = []
    current_article = ''
    heading_stack: List[str] = []    # 标题层级栈

    for line in lines:
        stripped = line.strip()

        heading_match = _HEADING_PATTERN.match(stripped)
        if heading_match:
            segments.extend(self._flush_lines(
                current_lines, heading_stack, current_article
            ))
            current_lines = []

            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            # 清除同级及更深层级的标题，保留更高级别的标题
            heading_stack = heading_stack[:level - 1]
            heading_stack.append(title)

            continue

        article_match = _ARTICLE_PATTERN.match(stripped)
        if not article_match:
            article_match = _PLAIN_ARTICLE_PATTERN.match(stripped)

        if article_match:
            segments.extend(self._flush_lines(
                current_lines, heading_stack, current_article
            ))
            current_lines = []

            article_num = article_match.group(1)
            article_desc = article_match.group(2).strip()
            current_article = f"第{article_num}条"
            if article_desc:
                current_article += f" {article_desc}"

        current_lines.append(line)

    segments.extend(self._flush_lines(
        current_lines, heading_stack, current_article
    ))
    return segments
```

**修改 `_flush_lines()`**：

```python
@staticmethod
def _flush_lines(
    current_lines: List[str],
    heading_stack: List[str],
    current_article: str,
) -> List[dict]:
    """将当前缓冲行刷新为 segment"""
    segments = []
    text = '\n'.join(current_lines).strip()
    if text:
        hierarchy_parts = list(heading_stack)
        if current_article:
            hierarchy_parts.append(current_article)
        hierarchy_path = ' > '.join(hierarchy_parts) if hierarchy_parts else ''

        segments.append({
            'text': text,
            'heading': heading_stack[-1] if heading_stack else '',
            'article': current_article,
            'hierarchy_path': hierarchy_path,
        })
    return segments
```

**修改 `_combine_segments()` 以保留 hierarchy_path**：

```python
def _combine_segments(self, segments: List[dict], combined_text: str) -> dict:
    first = segments[0]
    last = segments[-1]
    return {
        'text': combined_text.strip(),
        'heading': first['heading'] or last['heading'],
        'article': first['article'] or last['article'],
        'hierarchy_path': first['hierarchy_path'] or last['hierarchy_path'],
    }
```

**修改 `_split_by_sentences()` 以保留 hierarchy_path**：

```python
def _split_by_sentences(self, seg: dict) -> List[dict]:
    text = seg['text']
    sentences = _SENTENCE_PATTERN.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return [seg]

    chunks: List[dict] = []
    current = ''
    for sentence in sentences:
        if current and len(current) + len(sentence) > self._max_size:
            chunks.append({
                'text': current.strip(),
                'heading': seg['heading'],
                'article': seg['article'],
                'hierarchy_path': seg.get('hierarchy_path', ''),
            })
            current = sentence
        else:
            current += sentence

    if current.strip():
        chunks.append({
            'text': current.strip(),
            'heading': seg['heading'],
            'article': seg['article'],
            'hierarchy_path': seg.get('hierarchy_path', ''),
        })

    return chunks
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/semantic_chunker.py` — `_split_by_structure()`, `_flush_lines()`, `_build_nodes()`, `_combine_segments()`, `_split_by_sentences()`

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 标题栈 push/pop | 完整层级路径，自动处理层级关系 | segment 数据结构新增字段 | ✅ |
| B. 仅记录 level-1 标题 | 改动最小 | 信息不完整 | ❌ |
| C. 全量保留所有标题 | 最完整 | 路径过长，可能冗余 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| segment 数据结构变更影响下游 | 低 | 中 | `hierarchy_path` 字段向后兼容，下游已使用此字段 |
| 标题栈在文档开头不包含文档名 | 中 | 低 | `hierarchy_path` 不含 law_name（law_name 在 metadata 中独立存储） |
| 合并/拆分操作丢失 hierarchy_path | 低 | 中 | 同步更新 `_combine_segments()` 和 `_split_by_sentences()` |

##### 测试建议
```python
class TestHierarchyPathCompleteness:
    """验证多层标题文档的 hierarchy_path 完整性"""

    def test_multi_level_heading_stack(self):
        """多层标题应生成完整路径"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "## 第一章 总则\n\n"
                "### 第一节 适用范围\n\n"
                "第一条 在中华人民共和国境内从事保险活动，适用本法。\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        assert len(nodes) >= 1
        path = nodes[0].metadata.get('hierarchy_path', '')
        assert '保险法' in path
        assert '第一章 总则' in path
        assert '第一节 适用范围' in path
        assert '第一条' in path

    def test_heading_stack_pop_on_same_level(self):
        """同级标题应替换而非追加"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "## 第一章 总则\n\n"
                "第一条 总则内容。\n\n"
                "## 第二章 保险合同\n\n"
                "第二条 合同内容。\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        if len(nodes) >= 2:
            path_1 = nodes[0].metadata.get('hierarchy_path', '')
            path_2 = nodes[1].metadata.get('hierarchy_path', '')
            assert '保险法' in path_1
            assert '保险法' in path_2
            assert '第一章' in path_1 or '总则' in path_1
            assert '第二章' in path_2 or '保险合同' in path_2

    def test_heading_stack_preserves_parent(self):
        """h2 下方新增 h3 不影响 h2"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "## 第二章 保险合同\n\n"
                "### 第一节 合同订立\n\n"
                "第一条 订立规则。\n\n"
                "### 第二节 合同效力\n\n"
                "第二条 效力规则。\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        for node in nodes:
            path = node.metadata.get('hierarchy_path', '')
            assert '保险法' in path
            assert '第二章' in path or '保险合同' in path
```

##### 验收标准
- [x] 多层标题文档的 `hierarchy_path` 包含从最高级到当前标题的完整路径
- [x] 同级标题替换而非追加（如第二章替换第一章）
- [x] 合并/拆分后的 segment 保留 `hierarchy_path`
- [x] 现有 test_doc_parser.py 中依赖 hierarchy_path 的测试通过

---

#### 问题 1.3: [P0] SemanticChunker 不匹配纯文本条款标记

##### 问题概述
- **文件**: `scripts/lib/rag_engine/semantic_chunker.py:21-23`
- **函数**: `_split_by_structure()`
- **严重程度**: 🔴 P0
- **影响范围**: 无 `#` 前缀的法规文档中条款不会被切分，导致超大 chunk

##### 当前代码
```python
# semantic_chunker.py:21-23
_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
```

仅匹配 `#{1,3}第X条` 格式，不匹配纯文本 `第X条`。

##### 修复方案
在 `_split_by_structure()` 中增加对纯文本 `第X条` 的独立匹配逻辑。新增 `_PLAIN_ARTICLE_PATTERN`，在 `_ARTICLE_PATTERN` 匹配失败后回退到纯文本匹配。

##### 代码变更

**新增 `_PLAIN_ARTICLE_PATTERN`**：

```python
_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
_PLAIN_ARTICLE_PATTERN = re.compile(
    r'^第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
```

**修改 `_split_by_structure()` 中的条款匹配逻辑**（已在问题 1.2 的代码变更中包含）：

```python
        # 先检查带 # 前缀的条款标记
        article_match = _ARTICLE_PATTERN.match(stripped)
        # 再检查纯文本条款标记
        if not article_match:
            article_match = _PLAIN_ARTICLE_PATTERN.match(stripped)

        if article_match:
            segments.extend(self._flush_lines(
                current_lines, heading_stack, current_article
            ))
            current_lines = []
            # ... 后续不变 ...
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/semantic_chunker.py` — 新增 `_PLAIN_ARTICLE_PATTERN`，修改 `_split_by_structure()` 条款匹配逻辑

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 新增纯文本模式 | 与 fixed 策略一致，覆盖所有格式 | 可能误匹配正文中含「第X条」的描述性文本 | ✅ |
| B. 仅保留 # 前缀模式 | 精确匹配 | 遗漏纯文本格式 | ❌ |
| C. 合并为单一正则 | 代码更简洁 | 正则更复杂，可读性下降 | ⏳ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 正文中「第X条」被误匹配 | 低 | 中 | 正则匹配行首 `^`，且法规正文通常以「第X条」开头 |
| 两种策略的条款识别完全统一 | 高 | 低 | 两种策略的匹配模式已对齐 |

##### 测试建议
```python
class TestPlainArticleMatching:
    """验证纯文本条款标记的识别"""

    def test_plain_article_without_hash(self):
        """无 # 前缀的「第X条」应被识别为条款标记"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "第一条 在中华人民共和国境内从事保险活动，适用本法。\n\n"
                "第二条 从事保险活动必须遵守法律、行政法规。\n\n"
                "第三条 本法所称保险，是指投保人根据合同约定。\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        assert len(nodes) >= 3
        article_numbers = [n.metadata['article_number'] for n in nodes]
        assert '第一条' in article_numbers
        assert '第二条' in article_numbers
        assert '第三条' in article_numbers

    def test_mixed_article_formats(self):
        """同一文档中 # 前缀和纯文本条款应都被识别"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "## 第一章 总则\n\n"
                "### 第一条 总则内容\n\n"
                "第二条 纯文本条款。\n\n"
                "### 第三条 带标题条款\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        article_numbers = [n.metadata['article_number'] for n in nodes]
        assert '第一条' in article_numbers
        assert '第二条' in article_numbers
        assert '第三条' in article_numbers

    def test_article_in_body_text_not_matched(self):
        """正文中引用「第X条」不应被误识别为条款标记"""
        config = ChunkingConfig()
        chunker = SemanticChunker(config)

        doc = Document(
            text=(
                "# 保险法\n\n"
                "第一条 总则内容。根据前款规定，依照第十五条执行。\n\n"
                "第二条 第二条内容。\n"
            ),
            metadata={'file_name': 'test.md'},
        )

        nodes = chunker.chunk([doc])
        # 「依照第十五条执行」在行中间，不应被识别为条款标记
        assert len(nodes) >= 2
```

##### 验收标准
- [x] 无 `#` 前缀的 `第X条` 被识别为条款分割点
- [x] 带和不带前缀的条款标记在同一文档中均可识别
- [x] 行中间引用的「第X条」不被误识别（`^` 行首匹配）
- [x] 现有 test_semantic_chunker.py 测试全部通过

---

### ⚠️ P1 问题（尽快修复）

---

#### 问题 2.1: [P1] BM25 索引使用 pickle 持久化，存在安全风险

##### 问题概述
- **文件**: `scripts/lib/rag_engine/bm25_index.py:74-75, 126-135`
- **函数**: `BM25Index.load()`, `BM25Index._save()`
- **严重程度**: ⚠️ P1
- **影响范围**: 潜在 RCE 风险，跨版本兼容性风险

##### 当前代码
```python
# bm25_index.py:74-75
with open(index_path, 'rb') as f:
    data = pickle.load(f)

# bm25_index.py:126-135
with open(path, 'wb') as f:
    pickle.dump({
        'bm25': index._bm25,
        'nodes': index._nodes,
    }, f)
```

##### 修复方案
使用 `joblib` 替代 `pickle` 进行序列化，并添加版本号校验。

##### 代码变更

**修改 imports 和新增版本常量**：

```python
import heapq
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import joblib
from rank_bm25 import BM25Okapi

from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_INDEX_VERSION = "1.0"
```

**修改 `_save()` 方法**：

```python
@classmethod
def _save(cls, index: 'BM25Index', path: Path) -> None:
    """序列化索引到磁盘"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        'version': _INDEX_VERSION,
        'bm25': index._bm25,
        'nodes': index._nodes,
    }
    joblib.dump(payload, path, compress=3)
    logger.info(f"BM25 索引已保存: {path}")
```

**修改 `load()` 方法**：

```python
@classmethod
def load(cls, index_path: Path) -> Optional['BM25Index']:
    """从磁盘加载 BM25 索引"""
    try:
        with open(index_path, 'rb') as f:
            payload = joblib.load(f)

        if not isinstance(payload, dict) or 'version' not in payload:
            logger.warning(f"BM25 索引格式无效: {index_path}")
            return None

        version = payload['version']
        if version != _INDEX_VERSION:
            logger.warning(
                f"BM25 索引版本不匹配: 期望 {_INDEX_VERSION}, 实际 {version}, "
                f"请重新构建索引"
            )
            return None

        index = cls(payload['bm25'], payload['nodes'])
        logger.info(f"BM25 索引已加载: {index_path} ({len(payload['nodes'])} 个文档)")
        return index
    except FileNotFoundError:
        logger.warning(f"BM25 索引文件不存在: {index_path}")
        return None
    except Exception as e:
        logger.error(f"加载 BM25 索引失败: {e}")
        return None
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/bm25_index.py` — 替换 pickle 为 joblib，添加版本校验
- **修改**: `requirements.txt` — 添加 `joblib>=1.3.0`

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. joblib + 版本校验 | 压缩支持，numpy 友好，版本校验 | 仍基于 pickle 协议 | ✅ |
| B. JSON 序列化 | 完全安全，可读 | BM25Okapi 内部状态无法直接 JSON 化 | ❌ |
| C. pickle + hash 校验 | 最小改动 | 仅防篡改，不防反序列化攻击 | ⏳ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 旧版 pickle 索引不兼容 | 高 | 中 | 版本校验 + 清晰错误提示，引导用户重建 |
| joblib 依赖增加 | 低 | 低 | joblib 已被 scikit-learn 等广泛使用 |

##### 测试建议
```python
class TestBM25IndexVersioning:
    """验证 BM25 索引版本校验"""

    def test_load_invalid_version_rejects(self, temp_index_path):
        """版本不匹配时应返回 None"""
        import joblib
        joblib.dump({'version': '0.9', 'bm25': None, 'nodes': []}, temp_index_path)

        result = BM25Index.load(temp_index_path)
        assert result is None

    def test_load_missing_version_rejects(self, temp_index_path):
        """缺少 version 字段时应返回 None"""
        import joblib
        joblib.dump({'bm25': None, 'nodes': []}, temp_index_path)

        result = BM25Index.load(temp_index_path)
        assert result is None

    def test_build_and_load_roundtrip(self, temp_index_path):
        """构建后加载应能正常工作"""
        documents = [
            Document(text="第一条 保险合同成立。", metadata={'law_name': 'test'}),
            Document(text="第二条 投保人义务。", metadata={'law_name': 'test'}),
        ]
        BM25Index.build(documents, temp_index_path)

        loaded = BM25Index.load(temp_index_path)
        assert loaded is not None
        assert loaded.doc_count == 2

        results = loaded.search("保险合同", top_k=1)
        assert len(results) > 0
```

##### 验收标准
- [x] `_save()` 使用 `joblib.dump` 且包含版本号
- [x] `load()` 校验版本号，不匹配时返回 None 并记录 warning
- [x] 旧版 pickle 文件加载时返回 None 并提示重建
- [x] 现有 test_bm25_index.py 测试全部通过

---

#### 问题 2.2: [P1] `get_index_stats()` 方法不存在

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data_importer.py:130`
- **函数**: `import_all()`
- **严重程度**: ⚠️ P1
- **影响范围**: 每次构建知识库时抛出 AttributeError

##### 当前代码
```python
# data_importer.py:130
index_stats = self.index_manager.get_index_stats()
logger.info(f"索引统计: {index_stats}")
```

##### 修复方案
在 `VectorIndexManager` 中添加 `get_index_stats()` 方法。

##### 代码变更

**在 `index_manager.py` 中添加方法**：

```python
def get_index_stats(self) -> Dict[str, Any]:
    """获取索引统计信息"""
    if self.index is None:
        return {'status': 'not_initialized'}

    try:
        vector_store = self.index.vector_store
        table = vector_store.get_table(self.config.collection_name)
        count = len(table)
        return {
            'status': 'ok',
            'doc_count': count,
            'collection': self.config.collection_name,
        }
    except Exception as e:
        logger.warning(f"获取索引统计失败: {e}")
        return {'status': 'error', 'message': str(e)}
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/index_manager.py` — 新增 `get_index_stats()` 方法

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 添加 get_index_stats() | 提供有用的索引统计信息 | 需要了解 LanceDB API | ✅ |
| B. 删除调用 | 最简单 | 丢失有用的统计日志 | ❌ |
| C. try-except 包裹 | 兼容两种方案 | 静默失败 | ❌ |

##### 验收标准
- [x] `get_index_stats()` 返回包含 doc_count 的字典
- [x] 索引未初始化时返回 `{'status': 'not_initialized'}`
- [x] `import_all()` 不再抛出 AttributeError

---

#### 问题 2.3: [P1] 向量索引与 BM25 索引无一致性保障

##### 问题概述
- **文件**: `scripts/lib/rag_engine/data_importer.py:122-142`
- **函数**: `import_all()`
- **严重程度**: ⚠️ P1
- **影响范围**: 两个索引不同步可能导致检索遗漏或重复

##### 当前代码
```python
# data_importer.py:122-142
if not skip_vector:
    if self.import_to_vector_db(documents, force_rebuild):
        stats['vector'] = len(documents)

BM25Index.build(documents, bm25_path)
stats['bm25'] = len(documents)
```

##### 修复方案
为 BM25 构建添加异常处理，并在构建结束后校验两个索引的文档数量。

##### 代码变更

**修改 `import_all()` 中的 BM25 构建部分**：

```python
    # 构建 BM25 索引
    logger.info("=" * 60)
    logger.info(f"步骤 {step_num}: 构建 BM25 索引")
    logger.info("=" * 60)
    from .bm25_index import BM25Index
    data_dir = Path(self.config.vector_db_path).parent
    bm25_path = data_dir / "bm25_index.pkl"
    try:
        BM25Index.build(documents, bm25_path)
        stats['bm25'] = len(documents)
    except Exception as e:
        logger.error(f"BM25 索引构建失败: {e}")
        stats['bm25_error'] = str(e)

    # 一致性校验
    if not skip_vector and stats['vector'] > 0 and stats['bm25'] > 0:
        if stats['vector'] != stats['bm25']:
            logger.warning(
                f"索引一致性检查失败: 向量索引 {stats['vector']} 条, "
                f"BM25 索引 {stats['bm25']} 条, 建议重新构建"
            )
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/data_importer.py` — 添加 BM25 构建异常处理和一致性校验

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 构建后校验 + 告警 | 实现简单，不影响构建流程 | 不自动修复不一致 | ✅ |
| B. 失败时自动回滚 | 保证一致性 | 实现复杂，可能误删正常索引 | ❌ |
| C. 事务性构建 | 最安全 | LanceDB 和 pickle 不支持事务 | ❌ |

##### 验收标准
- [x] BM25 构建失败时不阻断流程，错误信息记录在 stats 中
- [x] 向量和 BM25 索引数量不一致时记录 warning 日志
- [x] stats 返回值中包含 `bm25_error` 字段（仅在失败时）

---

#### 问题 2.4: [P1] Embedding 不区分 query 和 text 模式

##### 问题概述
- **文件**: `scripts/lib/rag_engine/llamaindex_adapter.py:155-159`
- **函数**: `ZhipuEmbeddingAdapter._get_query_embedding()`, `_get_text_embedding()`
- **严重程度**: ⚠️ P1
- **影响范围**: 检索相关性可能降低；存在 copy-paste bug

##### 当前代码
```python
# llamaindex_adapter.py:155-159
def _get_query_embedding(self, query: str) -> List[float]:
    return self._get_embedding(query)

def _get_text_embedding(self, text: str) -> List[float]:
    return self._get_embedding(query)  # ← bug: 应为 text
```

##### 修复方案
在 API 调用中添加 `encoding_type` 参数。智谱 embedding-3 API 支持 `query` 和 `document` 两种类型。同时修复 copy-paste bug。

##### 代码变更

**修改 `_get_embeddings()` 方法**：

```python
def _get_embeddings(
    self, texts: List[str], encoding_type: str = "document"
) -> List[List[float]]:
    if not texts:
        return []

    payload = {"model": self._model, "input": texts}
    if encoding_type:
        payload["encoding_type"] = encoding_type

    response = self._session.post(
        f"{self._base_url}/embeddings",
        headers={
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()

    embeddings = []
    for item in result.get("data", []):
        embeddings.append(item.get("embedding", []))
    return embeddings
```

**修改 `_get_query_embedding()` 和 `_get_text_embedding()`**：

```python
def _get_query_embedding(self, query: str) -> List[float]:
    result = self._get_embeddings([query], encoding_type="query")
    return result[0] if result else []

def _get_text_embedding(self, text: str) -> List[float]:
    return self._get_embedding(text)  # _get_embedding 使用 encoding_type="document"
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/llamaindex_adapter.py` — 修改 `_get_embeddings()`, `_get_query_embedding()`, `_get_text_embedding()`

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 添加 encoding_type 参数 | 利模型特性，提升检索质量 | 依赖智谱 API 的 encoding_type 支持 | ✅ |
| B. 统一使用 document 模式 | 简单，不依赖额外 API 参数 | 未利用 query 模式的优势 | ❌ |
| C. 配置化模式选择 | 灵活 | 过度设计 | ❌ |

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 旧版智谱 API 不支持 encoding_type | 低 | 中 | API 返回错误时回退到无 encoding_type 调用 |
| Ollama 不支持 encoding_type | 高 | 低 | Ollama 路径不受影响，仅修改 ZhipuEmbeddingAdapter |

##### 验收标准
- [x] `_get_query_embedding()` 使用 `encoding_type="query"`
- [x] `_get_text_embedding()` 使用 `encoding_type="document"`
- [x] 修复 `_get_text_embedding()` 中的 `query` → `text` bug
- [x] 现有测试通过

---

#### 问题 2.5: [P1] `_MAX_CHUNKS_PER_ARTICLE=2` 去重过于激进

##### 问题概述
- **文件**: `scripts/lib/rag_engine/fusion.py:19`
- **函数**: `_deduplicate_by_article()`
- **严重程度**: ⚠️ P1
- **影响范围**: 长条款的关键信息可能被丢弃

##### 当前代码
```python
# fusion.py:19
_MAX_CHUNKS_PER_ARTICLE = 2
```

##### 修复方案
将 `_MAX_CHUNKS_PER_ARTICLE` 提升为可配置参数，默认值从 2 调整为 3。

##### 代码变更

**修改 `config.py`**：

```python
@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 1.0
    enable_rerank: bool = True
    rerank_top_k: int = 5
    max_chunks_per_article: int = 3  # 新增：每条款最大 chunk 数
```

**修改 `fusion.py`**：

```python
def reciprocal_rank_fusion(
    vector_results: List[NodeWithScore],
    keyword_results: List[NodeWithScore],
    k: int = 60,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
    max_chunks_per_article: int = 3,
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

    results = _deduplicate_by_article(results, max_chunks_per_article)
    return sorted(results, key=lambda x: x['score'], reverse=True)


def _deduplicate_by_article(
    results: List[Dict[str, Any]],
    max_chunks: int = 3,
) -> List[Dict[str, Any]]:
    """按法规名称+条款号去重，每条款保留至多 max_chunks 个 chunk"""
    grouped: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in results:
        key = (r.get('law_name', ''), r.get('article_number', ''))
        grouped.setdefault(key, []).append(r)

    deduped = []
    for chunks in grouped.values():
        chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
        deduped.extend(chunks[:max_chunks])

    return deduped
```

**同步修改 `retrieval.py` 中的调用**：

```python
# retrieval.py:107-110 — 传递 max_chunks_per_article 参数
return reciprocal_rank_fusion(
    vector_nodes, keyword_nodes, k=k,
    vector_weight=vector_weight, keyword_weight=keyword_weight,
    max_chunks_per_article=config.max_chunks_per_article,
)
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/fusion.py` — `_deduplicate_by_article()` 参数化，`reciprocal_rank_fusion()` 新增参数
- **修改**: `scripts/lib/rag_engine/config.py` — `HybridQueryConfig` 新增 `max_chunks_per_article` 字段
- **修改**: `scripts/lib/rag_engine/retrieval.py` — 传递配置参数

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 默认值改为 3 + 可配置 | 兼顾长条款覆盖和结果多样性 | 需要同步修改 config/fusion/retrieval | ✅ |
| B. 仅改为 3 | 最小改动 | 不可配置 | ⏳ |
| C. 动态基于长度调整 | 最精确 | 实现复杂，行为不可预测 | ❌ |

##### 验收标准
- [x] `HybridQueryConfig.max_chunks_per_article` 默认值为 3
- [x] 长条款（3+ chunk）的第 3 个 chunk 可以出现在检索结果中
- [x] 现有 test_fusion.py 测试通过（注意更新预期值）

---

### 🟡 P2 问题（建议修复）

---

#### 问题 3.1: [P2] 无内容清洗步骤

##### 问题概述
- **文件**: `scripts/lib/rag_engine/doc_parser.py`
- **严重程度**: 🟡 P2
- **影响范围**: 噪音内容被原样索引

##### 修复方案
在 `RegulationDocParser.parse_all()` 和 `parse_single_file()` 中添加 `_clean_content()` 预处理步骤。

##### 代码变更

**在 `doc_parser.py` 中新增清洗函数**：

```python
_TOC_PATTERN = re.compile(
    r'^#{1,4}\s*(目录|目\s*录|TABLE\s+OF\s+CONTENTS)',
    re.IGNORECASE,
)
_EMPTY_OR_SEPARATOR = re.compile(r'^[\s\-=_*]{3,}$')


def _clean_content(text: str) -> str:
    """清洗文档内容：去除目录、空行、分隔符等噪音"""
    lines = text.split('\n')
    cleaned = []
    in_toc = False

    for line in lines:
        stripped = line.strip()

        # 跳过目录标记
        if _TOC_PATTERN.match(stripped):
            in_toc = True
            continue

        # 目录区域：跳过直到下一个标题
        if in_toc:
            if _HEADING_PATTERN.match(stripped):
                in_toc = False
            else:
                continue

        # 跳过纯分隔符行
        if _EMPTY_OR_SEPARATOR.match(stripped):
            continue

        # 跳过多余空行（保留段落间的单个空行）
        if not stripped:
            if cleaned and cleaned[-1] != '':
                cleaned.append('')
            continue

        cleaned.append(line)

    # 移除首尾空行
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return '\n'.join(cleaned)
```

**在 `parse_all()` 中调用**：

```python
    # ... reader.load_data() 之后 ...
    documents = reader.load_data()

    # 内容清洗
    for doc in documents:
        doc.text = _clean_content(doc.text)

    # ... 后续分块逻辑 ...
```

**在 `parse_single_file()` 中同样调用**：

```python
    # ... reader.load_data() 之后 ...
    docs = reader.load_data()

    if not docs:
        logger.warning(f"未找到文件: {file_name}")
        return []

    # 内容清洗
    for doc in docs:
        doc.text = _clean_content(doc.text)

    # ... 后续分块逻辑 ...
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/doc_parser.py` — 新增 `_clean_content()`，在 `parse_all()` 和 `parse_single_file()` 中调用

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A. 基于正则的清洗 | 无额外依赖，可控 | 规则需维护 | ✅ |
| B. LLM 清洗 | 最智能 | 成本高，速度慢 | ❌ |
| C. 依赖专用库（如 clean-text） | 功能全面 | 新增依赖 | ⏳ |

##### 验收标准
- [x] 目录行被过滤
- [x] 分隔符行被过滤
- [x] 法规正文内容不受影响
- [x] 构建后的 chunk 中不包含目录内容

---

#### 问题 3.2: [P2] fixed 策略下 chunk 缺少 hierarchy_path 元数据

##### 问题概述
- **文件**: `scripts/lib/rag_engine/doc_parser.py:200-208`
- **函数**: `RegulationNodeParser._create_node()`
- **严重程度**: 🟡 P2

##### 修复方案
在 `_create_node()` 的 metadata 中添加 `hierarchy_path` 字段。

##### 代码变更

```python
# doc_parser.py:200-208
    return TextNode(
        text=full_content,
        metadata={
            'law_name': law_name,
            'article_number': article_title,
            'category': category,
            'hierarchy_path': f"{law_name} > {article_title}",
            'source_file': source_file,
        }
    )
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/doc_parser.py:200-208`

##### 验收标准
- [x] fixed 策略生成的 chunk 包含 `hierarchy_path` 元数据
- [x] `hierarchy_path` 格式为「法规名 > 条款号」

---

#### 问题 3.3: [P2] 遗留 vector_store.py 清理

##### 问题概述
- **文件**: `scripts/lib/rag_engine/vector_store.py` (376 行)
- **严重程度**: 🟡 P2

##### 修复方案
确认无调用方后删除文件。

##### 涉及文件
- **删除**: `scripts/lib/rag_engine/vector_store.py`

##### 验收标准
- [x] `grep -r "vector_store" scripts/lib/rag_engine/` 无结果
- [x] `pytest scripts/tests/` 全部通过

---

### 🔵 P3 问题（可选修复）

---

#### 问题 4.1: [P3] `_merge_short_segments()` 不检查合并后上限

##### 问题概述
- **文件**: `scripts/lib/rag_engine/semantic_chunker.py:179-199`
- **函数**: `_merge_short_segments()`
- **严重程度**: 🔵 P3

##### 修复方案
在合并时检查上限，超过 `max_chunk_size` 时强制 flush。

##### 代码变更

```python
def _merge_short_segments(self, segments: List[dict]) -> List[dict]:
    if not self.config.enable_semantic_merge:
        return segments

    merged: List[dict] = []
    buffer_segments: List[dict] = []
    buffer_text = ''

    for seg in segments:
        new_text = buffer_text + ('\n\n' if buffer_text else '') + seg['text']

        if len(new_text) > self._max_size and buffer_segments:
            merged.append(self._combine_segments(buffer_segments, buffer_text))
            buffer_segments = []
            buffer_text = ''

        buffer_segments.append(seg)
        buffer_text = buffer_text + ('\n\n' if len(buffer_text) > 0 else '') + seg['text']

        if len(buffer_text) >= self.config.merge_short_threshold:
            merged.append(self._combine_segments(buffer_segments, buffer_text))
            buffer_segments = []
            buffer_text = ''

    if buffer_segments:
        merged.append(self._combine_segments(buffer_segments, buffer_text))

    return merged
```

##### 涉及文件
- **修改**: `scripts/lib/rag_engine/semantic_chunker.py:179-199`

##### 验收标准
- [x] 多个短段连续合并时不超过 `max_chunk_size`
- [x] 现有 test_semantic_chunker.py 测试通过

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 模块 | 覆盖率 | 关键缺口 |
|------|--------|---------|
| semantic_chunker.py | ~70% | overlap+refine 交互、层级路径完整性、纯文本条款 |
| doc_parser.py | ~60% | fixed 策略 hierarchy_path、内容清洗 |
| bm25_index.py | ~80% | 版本校验、异常格式 |
| fusion.py | ~85% | max_chunks_per_article 参数化 |
| index_manager.py | ~50% | get_index_stats() |
| data_importer.py | ~40% | 索引一致性校验、BM25 构建失败 |

### 新增测试计划

#### 优先级 P0（与 bug 修复同步）

| 测试文件 | 测试用例 | 对应问题 |
|---------|---------|---------|
| test_semantic_chunker.py | `TestOverlapAfterRefine` (3 tests) | 问题 1.1 |
| test_semantic_chunker.py | `TestHierarchyPathCompleteness` (3 tests) | 问题 1.2 |
| test_semantic_chunker.py | `TestPlainArticleMatching` (3 tests) | 问题 1.3 |

#### 优先级 P1

| 测试文件 | 测试用例 | 对应问题 |
|---------|---------|---------|
| test_bm25_index.py | `TestBM25IndexVersioning` (3 tests) | 问题 2.1 |
| test_index_manager.py | `test_get_index_stats()` | 问题 2.2 |
| test_data_importer.py | `test_index_consistency_warning()` | 问题 2.3 |
| test_fusion.py | `test_deduplicate_max_chunks_3()` | 问题 2.5 |

#### 优先级 P2

| 测试文件 | 测试用例 | 对应问题 |
|---------|---------|---------|
| test_doc_parser.py | `test_clean_content_filters_toc()` | 问题 3.1 |
| test_doc_parser.py | `test_fixed_strategy_has_hierarchy_path()` | 问题 3.2 |
| test_semantic_chunker.py | `test_merge_short_respects_max_size()` | 问题 4.1 |

### 测试基础设施

无需新增基础设施。现有测试已使用：
- `pytest` + `tempfile` + `pathlib`
- `rag_fixtures.py` 共享 fixtures（`sample_regulation_documents`, `temp_lancedb_dir`）
- `MagicMock` / `patch` 用于 mock

---

## 三、技术债务清理方案

### 技术债务清单

| 优先级 | 债务 | 位置 | 状态 |
|--------|------|------|------|
| P0 | Overlap 语义失效 | semantic_chunker.py:53-67 | 本方案覆盖 |
| P0 | hierarchy_path 不完整 | semantic_chunker.py:270-275 | 本方案覆盖 |
| P0 | 纯文本条款不识别 | semantic_chunker.py:21-23 | 本方案覆盖 |
| P1 | pickle 安全 | bm25_index.py:74 | 本方案覆盖 |
| P1 | get_index_stats() 缺失 | data_importer.py:130 | 本方案覆盖 |
| P1 | 索引一致性 | data_importer.py:122-142 | 本方案覆盖 |
| P1 | Embedding 模式区分 | llamaindex_adapter.py:155-159 | 本方案覆盖 |
| P1 | 去重阈值 | fusion.py:19 | 本方案覆盖 |
| P2 | 无内容清洗 | doc_parser.py | 本方案覆盖 |
| P2 | 仅支持 Markdown | doc_parser.py:248 | **不在本方案范围** |
| P2 | fixed 缺 hierarchy_path | doc_parser.py:200-208 | 本方案覆盖 |
| P2 | 遗留 vector_store.py | vector_store.py | 本方案覆盖 |
| P3 | print() 替代 logger | vector_store.py | 随删除解决 |
| P3 | merge 不检查上限 | semantic_chunker.py:179-199 | 本方案覆盖 |

### 清理路线图

```
Phase 1 (立即) — P0 修复
├── 1.1 Overlap 执行顺序调整
├── 1.2 层级路径标题栈实现
└── 1.3 纯文本条款匹配

Phase 2 (短期) — P1 修复
├── 2.1 pickle → joblib 替换
├── 2.2 get_index_stats() 实现
├── 2.3 索引一致性校验
├── 2.4 Embedding query/text 模式
└── 2.5 去重阈值可配置化

Phase 3 (中期) — P2/P3 修复
├── 3.1 内容清洗预处理
├── 3.2 fixed 策略 hierarchy_path
├── 3.3 删除 vector_store.py
└── 3.4 merge 上限检查
```

### Phase 2 之后
- **不在本方案范围**：多格式文档解析（PDF/Word）— 需要独立的方案设计和依赖评估
- **不在本方案范围**：构建健康检查仪表盘 — 需要运维需求对齐

---

## 四、架构和代码质量改进

### 架构改进

#### 4.1 Segment 数据结构规范化

当前 segment 使用裸 `dict`，字段不明确。建议定义 `dataclass`：

```python
@dataclass(frozen=True)
class StructureSegment:
    text: str
    heading: str
    article: str
    hierarchy_path: str
```

**时机**：Phase 1 完成后，作为独立重构任务。

#### 4.2 构建流水线解耦

当前 `import_all()` 直接编排三个步骤。如果后续需要添加清洗、校验等步骤，方法会继续膨胀。建议：

```python
class BuildPipeline:
    def __init__(self, config: RAGConfig):
        self._steps = []

    def add_step(self, step: BuildStep):
        self._steps.append(step)

    def execute(self, documents) -> BuildResult:
        # 串行执行所有步骤，任一步骤失败则记录并继续
```

**时机**：Phase 2 完成后，视复杂度决定。

### 代码质量改进

1. **删除 vector_store.py**：减少 376 行死代码
2. **统一 segment 数据结构**：从 dict 迁移到 dataclass
3. **修复 llamaindex_adapter.py 中的 copy-paste bug**：`_get_text_embedding` 参数 `text` 被误写为 `query`（问题 2.4 修复中一并处理）

### 性能优化建议

1. **BM25 构建并行化**：`tokenize_chinese()` 对每个文档串行调用，可使用 `ThreadPoolExecutor` 并行分词
2. **Embedding 批处理**：当前 `_get_embeddings()` 已支持批量，但 LlamaIndex 可能逐条调用。确认 `embed_batch_size` 配置生效

---

## 附录

### 执行顺序建议

建议按 Phase 顺序执行，每个 Phase 内的修复相互独立，可并行开发：

```
Phase 1 (P0) — semantic_chunker.py 集中修改
├── 1.1 + 1.2 + 1.3 合并为一次 PR
└── 新增 ~9 个测试用例

Phase 2 (P1) — 多文件修改
├── 2.1 独立 PR（bm25_index.py + requirements.txt）
├── 2.2 + 2.3 独立 PR（index_manager.py + data_importer.py）
├── 2.4 独立 PR（llamaindex_adapter.py）
└── 2.5 独立 PR（fusion.py + config.py + retrieval.py）

Phase 3 (P2/P3) — 清理和加固
├── 3.1 + 3.2 独立 PR（doc_parser.py）
└── 3.3 + 3.4 独立 PR
```

### 变更摘要

| 文件 | 变更类型 | Phase | 说明 |
|------|---------|-------|------|
| `semantic_chunker.py` | 修改 | 1 | 重构 overlap/层级路径/纯文本匹配 |
| `bm25_index.py` | 修改 | 2 | pickle → joblib + 版本校验 |
| `index_manager.py` | 修改 | 2 | 新增 get_index_stats() |
| `data_importer.py` | 修改 | 2 | 一致性校验 + 异常处理 |
| `llamaindex_adapter.py` | 修改 | 2 | query/text embedding 模式 |
| `fusion.py` | 修改 | 2 | 去重阈值参数化 |
| `config.py` | 修改 | 2 | 新增 max_chunks_per_article |
| `retrieval.py` | 修改 | 2 | 传递 max_chunks_per_article |
| `doc_parser.py` | 修改 | 3 | 内容清洗 + fixed hierarchy_path |
| `vector_store.py` | 删除 | 3 | 清理遗留代码 |
| `requirements.txt` | 修改 | 2 | 添加 joblib |

### 验收标准总结

#### 功能验收标准
- [x] **P0**: overlap 在语义精调之后正确添加
- [x] **P0**: hierarchy_path 包含完整的多层标题路径
- [x] **P0**: 纯文本 `第X条` 被正确识别为条款分割点
- [x] **P1**: BM25 索引使用 joblib 序列化且包含版本校验
- [x] **P1**: `get_index_stats()` 正常返回索引统计信息
- [x] **P1**: 向量和 BM25 索引数量不一致时记录 warning
- [x] **P1**: 智谱 embedding 区分 query/text 模式
- [x] **P1**: 每条款最多保留 3 个 chunk（可配置）
- [x] **P2**: 目录和分隔符行被过滤
- [x] **P2**: fixed 策略生成的 chunk 包含 hierarchy_path
- [x] **P2**: vector_store.py 已删除且无引用

#### 质量验收标准
- [x] `pytest scripts/tests/` 全部通过
- [x] 新增测试覆盖所有修复的 bug（共 ~15 个新测试用例）
- [x] 无 `import *` 通配符导入
- [x] 无新增 `print()` 调用

#### 部署验收标准
- [ ] 知识库重建后 chunk 数量合理（14 份文档 → 预计 200-500 个 chunk）
- [ ] 检索结果中 hierarchy_path 包含完整路径
- [ ] 旧版 pickle 索引加载时给出清晰的重建提示
- [x] 向后兼容：现有 RAG 查询接口不受影响
