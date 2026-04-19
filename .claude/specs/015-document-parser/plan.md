# Implementation Plan: 统一文档解析器

**Branch**: `015-document-parser` | **Date**: 2026-04-17 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

创建独立的 `lib/doc_parser` 模块，统一处理知识库文档和保险产品文档的解析：

1. **知识库场景**：Markdown → TextNode 列表（供 RAG 检索）
2. **产品文档场景**：Word/PDF → AuditDocument（供审核评测）

删除废弃的飞书文档同步代码（`document_fetcher.py`）。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: python-docx>=0.8.11, pdfplumber>=0.9.0, llama-index, yaml
**Storage**: 无持久化，纯内存处理
**Testing**: pytest
**Performance Goals**: 单文档解析 < 5 秒
**Constraints**:
- 本模块是底层基础设施，不依赖业务模块（eval、audit）
- 不处理 Excel→Markdown 转换（preprocessor 职责）
- 不构建索引（builder 职责）

## Constitution Check

- [x] **Library-First**: 复用 python-docx、pdfplumber、llama-index，不重新造轮子
- [x] **测试优先**: 每个 User Story 都有对应测试计划
- [x] **简单优先**: 选择结构感知分块而非语义分块，因已有明确边界
- [x] **显式优于隐式**: 动态路由基于显式的文件扩展名，无魔法行为
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: 每个 User Story 可独立测试和交付

## Project Structure

```
scripts/lib/doc_parser/
├── __init__.py           # 顶层导出
├── models.py             # 共用数据模型
├── kb/
│   ├── __init__.py       # 导出 parse_knowledge_base
│   ├── parser.py         # 编排器
│   └── md_parser.py      # Markdown 解析器
└── pd/
    ├── __init__.py       # 导出 parse_product_document
    ├── parser.py         # 编排器
    ├── docx_parser.py    # Word 解析器
    ├── pdf_parser.py     # PDF 解析器
    ├── section_detector.py
    └── data/
        └── keywords.json

scripts/tests/lib/doc_parser/
├── conftest.py
├── test_models.py
├── kb/
│   └── test_md_parser.py
└── pd/
    ├── test_docx_parser.py
    ├── test_pdf_parser.py
    └── test_section_detector.py
```

---

## Phase 1: Infrastructure (P1) ✅

→ 对应 spec.md 所有 User Stories 的基础设施

**Step 1.1: 数据模型**

文件: `scripts/lib/doc_parser/models.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析数据模型"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any


class SectionType(str, Enum):
    """内容类型枚举"""
    CLAUSE = "clause"
    PREMIUM_TABLE = "premium_table"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"


@dataclass
class DocumentMeta:
    """文档级元数据（内部结构化表示）
    
    从 YAML frontmatter 解析而来，提供类型安全的访问接口。
    对外输出通过 to_chunk_metadata() 转换为 Dict，保证与现有检索系统兼容。
    """
    collection: str
    category: str              # 从 collection 提取
    law_name: str              # = regulation
    issuing_authority: str = ""
    doc_number: str = ""
    insurance_type: str = ""
    extra: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_frontmatter(cls, frontmatter: dict) -> 'DocumentMeta':
        """从 YAML frontmatter 构建"""
        collection = str(frontmatter.get('collection', ''))
        category = collection.split('_', 1)[1] if '_' in collection else collection
        
        return cls(
            collection=collection,
            category=category,
            law_name=str(frontmatter.get('regulation', '')),
            issuing_authority=cls._first_non_empty(frontmatter.get('发文机关', [])),
            doc_number=cls._first_non_empty(frontmatter.get('文号', [])),
            insurance_type=str(frontmatter.get('险种类型', '')),
            extra={
                '备注': cls._first_non_empty(frontmatter.get('备注', [])),
            }
        )
    
    def to_chunk_metadata(self, article_number: str, source_file: str) -> Dict[str, Any]:
        """转换为 TextNode.metadata 格式
        
        输出字段与现有 ChecklistChunker 完全一致，保证向量存储和检索兼容。
        """
        metadata: Dict[str, Any] = {
            'law_name': self.law_name,
            'article_number': article_number,
            'category': self.category,
            'source_file': source_file,
            'hierarchy_path': f"{self.category} > {self.law_name} > {article_number}",
        }
        if self.issuing_authority:
            metadata['issuing_authority'] = self.issuing_authority
        if self.doc_number:
            metadata['doc_number'] = self.doc_number
        if self.insurance_type:
            metadata['险种类型'] = self.insurance_type
        metadata.update({k: v for k, v in self.extra.items() if v})
        return metadata
    
    @staticmethod
    def _first_non_empty(values: list) -> str:
        for v in values:
            if v and str(v).strip():
                return str(v).strip()
        return ''


@dataclass(frozen=True)
class Clause:
    """条款"""
    number: str       # 条款编号，如 "1.2.3"
    title: str        # 条款标题
    text: str         # 条款正文
    section_type: str = "clause"


@dataclass
class PremiumTable:
    """费率表"""
    raw_text: str              # 原始文本
    data: List[List[str]]      # 结构化数据（二维表格）
    remark: str = ""           # 备注
    section_type: str = "premium_table"


@dataclass
class DocumentSection:
    """通用文档章节"""
    title: str        # 章节标题
    content: str      # 章节内容
    section_type: str # 内容类型：notice, health_disclosure, exclusion, rider


@dataclass
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .docx, .pdf

    clauses: List[Clause] = field(default_factory=list)
    premium_tables: List[PremiumTable] = field(default_factory=list)
    notices: List[DocumentSection] = field(default_factory=list)
    health_disclosures: List[DocumentSection] = field(default_factory=list)
    exclusions: List[DocumentSection] = field(default_factory=list)
    rider_clauses: List[Clause] = field(default_factory=list)

    parse_time: datetime = field(default_factory=datetime.now)
    warnings: List[str] = field(default_factory=list)


class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
```

**Step 1.2: 顶层导出**

文件: `scripts/lib/doc_parser/__init__.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文档解析器"""
from __future__ import annotations

from .models import (
    Clause,
    PremiumTable,
    DocumentSection,
    AuditDocument,
    DocumentParseError,
    SectionType,
)
from .kb import parse_knowledge_base
from .pd import parse_product_document

__all__ = [
    'Clause', 'PremiumTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType',
    'parse_knowledge_base', 'parse_product_document',
]
```

**Step 1.3: 错误处理测试**

文件: `scripts/tests/lib/doc_parser/test_error_handling.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""错误处理测试"""
import pytest
from lib.doc_parser import parse_knowledge_base, parse_product_document, DocumentParseError


class TestErrorHandling:

    def test_file_not_found(self):
        with pytest.raises(DocumentParseError) as exc:
            parse_knowledge_base("/nonexistent/path/file.md")
        assert "文件不存在" in str(exc.value)

    def test_unsupported_format(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content")

        with pytest.raises(DocumentParseError) as exc:
            parse_knowledge_base(str(txt_file))
        assert "不支持" in str(exc.value)

    def test_doc_format_error(self, tmp_path):
        doc_file = tmp_path / "test.doc"
        doc_file.write_bytes(b"fake doc content")

        with pytest.raises(DocumentParseError) as exc:
            parse_product_document(str(doc_file))
        assert "不支持" in str(exc.value)

    def test_corrupted_docx(self, tmp_path):
        docx_file = tmp_path / "corrupt.docx"
        docx_file.write_bytes(b"not a valid docx")

        with pytest.raises(DocumentParseError) as exc:
            parse_product_document(str(docx_file))
        assert "解析失败" in str(exc.value)

    def test_empty_file(self, tmp_path):
        md_file = tmp_path / "empty.md"
        md_file.write_text("")

        nodes = parse_knowledge_base(str(md_file))
        assert nodes == []
```

---

## Phase 2: Core - User Story 1 (P1)

→ 对应 spec.md User Story 1: 知识库文档解析

**Step 2.1: kb 包导出**

文件: `scripts/lib/doc_parser/kb/__init__.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库文档解析"""
from .parser import parse_knowledge_base

__all__ = ['parse_knowledge_base']
```

**Step 2.2: kb 编排器**

文件: `scripts/lib/doc_parser/kb/parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库文档解析编排器"""
from __future__ import annotations

from pathlib import Path
from typing import List

from llama_index.core.readers import SimpleDirectoryReader
from llama_index.core.schema import TextNode

from ..models import DocumentParseError
from .md_parser import MdParser


def parse_knowledge_base(file_path: str) -> List[TextNode]:
    """解析单个知识库文档。
    
    使用 SimpleDirectoryReader 加载文件，复用其文件编码处理和错误处理能力。
    """
    path = Path(file_path)
    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    ext = path.suffix.lower()
    if ext not in MdParser.supported_extensions():
        raise DocumentParseError(
            f"不支持的知识库文档格式: {ext}",
            file_path,
            f"支持的格式: {MdParser.supported_extensions()}"
    )

    # 复用 SimpleDirectoryReader 加载文件
    reader = SimpleDirectoryReader(input_files=[file_path])
    documents = reader.load_data()
    if not documents:
        return []
    
    return MdParser().parse_document(documents[0])
```

**Step 2.3: Markdown 解析器**

文件: `scripts/lib/doc_parser/kb/md_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 文档解析器"""
from __future__ import annotations

import re
import logging
from typing import List, Dict

import yaml
from llama_index.core import Document
from llama_index.core.schema import TextNode

from ..models import DocumentMeta

logger = logging.getLogger(__name__)

_ITEM_HEADING = re.compile(r'^##\s*第(\d+)项\s*$', re.MULTILINE)
_BLOCKQUOTE_META = re.compile(r'^>\s*\*\*元数据\*\*\s*:\s*(.+)$', re.MULTILINE)
_KV_PAIR = re.compile(r'(\S+?)=([^|]+)')
_MAX_CHUNK_CHARS = 3000
_SENTENCE_SPLIT = re.compile(r'(?<=[。；！？\n])\s*')


class MdParser:
    """Markdown 解析器

    解析 preprocessor.py 生成的结构化 Markdown 文件：
    - YAML frontmatter → DocumentMeta
    - ## 第N项 → 分块边界
    - > **元数据** blockquote → 条款级元数据
    """

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.md', '.markdown']

    def parse_document(self, doc: Document) -> List[TextNode]:
        """解析 Document 对象，返回分块后的 TextNode 列表。"""
        source_file = doc.metadata.get('file_name', '')
        text = doc.text

        frontmatter, body = self._extract_frontmatter(text)
        meta = DocumentMeta.from_frontmatter(frontmatter)
        
        # 如果 regulation 为空，从 body 标题提取
        if not meta.law_name:
            law_name = self._extract_law_name(body)
            if law_name:
                from dataclasses import replace
                meta = replace(meta, law_name=law_name)
        
        items = self._split_by_items(body)
        return self._build_nodes(items, meta, source_file)

    @staticmethod
    def _extract_frontmatter(text: str) -> tuple:
        if not text.startswith('---'):
            return {}, text

        parts = text.split('---', 2)
        if len(parts) < 3:
            return {}, text

        yaml_str = parts[1].strip()
        body = parts[2].strip()

        try:
            data = yaml.safe_load(yaml_str)
            return data if isinstance(data, dict) else {}, body
        except yaml.YAMLError:
            logger.warning("YAML frontmatter 解析失败")
            return {}, body

    @staticmethod
    def _extract_law_name(body: str) -> str:
        """从 body 标题提取法规名称"""
        for line in body.split('\n'):
            m = re.match(r'^#\s+(.+)$', line.strip())
            if m:
                return m.group(1).strip()
        return ''

    @staticmethod
    def _split_by_items(body: str) -> List[dict]:
        matches = list(_ITEM_HEADING.finditer(body))
        if not matches:
            return []

        items = []
        for i, match in enumerate(matches):
            item_num = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            section = body[start:end].strip()

            chunk_meta: Dict[str, str] = {}
            meta_match = _BLOCKQUOTE_META.search(section)
            if meta_match:
                meta_str = meta_match.group(1)
                for kv in _KV_PAIR.finditer(meta_str):
                    chunk_meta[kv.group(1).strip()] = kv.group(2).strip()
                section = _BLOCKQUOTE_META.sub('', section).strip()

            section = re.sub(r'^\s+', '', section, count=1) if section else section

            items.append({
                'item_number': item_num,
                'content': section,
                'chunk_meta': chunk_meta,
            })

        return items

    def _build_nodes(
        self,
        items: List[dict],
        meta: DocumentMeta,
        source_file: str,
    ) -> List[TextNode]:
        nodes: List[TextNode] = []
        for item in items:
            content = item['content']
            if len(content) < 20:
                continue

            article_number = f"第{item['item_number']}项"
            metadata = meta.to_chunk_metadata(article_number, source_file)

            # 合并 chunk 级元数据
            for key, value in item['chunk_meta'].items():
                metadata[key] = value

            if len(content) > _MAX_CHUNK_CHARS:
                sub_nodes = self._split_long_chunk(content, metadata)
                nodes.extend(sub_nodes)
            else:
                nodes.append(TextNode(text=content, metadata=metadata))

        return nodes

    @staticmethod
    def _split_long_chunk(text: str, metadata: Dict[str, any]) -> List[TextNode]:
        sentences = _SENTENCE_SPLIT.split(text)
        current = ''
        nodes: List[TextNode] = []

        for sent in sentences:
            if len(current) + len(sent) > _MAX_CHUNK_CHARS and current:
                nodes.append(TextNode(text=current.strip(), metadata=metadata))
                current = sent
            else:
                current += sent

        if current.strip():
            nodes.append(TextNode(text=current.strip(), metadata=metadata))

        return nodes
```

**Step 2.4: 测试 fixtures**

文件: `scripts/tests/lib/doc_parser/conftest.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档解析器测试 fixtures"""
import pytest
from pathlib import Path
from typing import List, Tuple

from docx import Document


@pytest.fixture
def sample_docx_with_clauses(tmp_path: Path):
    """创建包含条款的 Word 文档 fixture"""
    def _create(docx_path: Path, clauses: List[Tuple[str, str, str]]) -> None:
        doc = Document()
        table = doc.add_table(rows=len(clauses) + 1, cols=2)
        table.rows[0].cells[0].text = "条款编号"
        table.rows[0].cells[1].text = "条款内容"
        for i, (number, title, text) in enumerate(clauses, 1):
            table.rows[i].cells[0].text = number
            table.rows[i].cells[1].text = f"{title}\n{text}"
        doc.save(str(docx_path))
    return _create


@pytest.fixture
def sample_docx_with_premium(tmp_path: Path):
    """创建包含费率表的 Word 文档 fixture"""
    def _create(docx_path: Path) -> None:
        doc = Document()
        table = doc.add_table(rows=4, cols=3)
        table.rows[0].cells[0].text = "年龄"
        table.rows[0].cells[1].text = "性别"
        table.rows[0].cells[2].text = "费率"
        for i, (age, gender, rate) in enumerate([
            ("18", "男", "100"),
            ("19", "男", "105"),
            ("20", "男", "110"),
        ], 1):
            table.rows[i].cells[0].text = age
            table.rows[i].cells[1].text = gender
            table.rows[i].cells[2].text = rate
        doc.save(str(docx_path))
    return _create


@pytest.fixture
def sample_docx_with_company_info(tmp_path: Path):
    """创建包含公司信息表格的 Word 文档 fixture"""
    def _create(docx_path: Path) -> None:
        doc = Document()
        table = doc.add_table(rows=3, cols=2)
        table.rows[0].cells[0].text = "公司名称"
        table.rows[0].cells[1].text = "XX保险公司"
        table.rows[1].cells[0].text = "地址"
        table.rows[1].cells[1].text = "北京市朝阳区..."
        table.rows[2].cells[0].text = "客服电话"
        table.rows[2].cells[1].text = "400-XXX-XXXX"
        doc.save(str(docx_path))
    return _create


@pytest.fixture
def sample_pdf_with_clauses(tmp_path: Path):
    """创建包含条款的 PDF 文档 fixture。集成测试建议使用真实文件。"""
    def _create(pdf_path: Path) -> None:
        import reportlab.lib.pagesizes as pagesizes
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(pdf_path), pagesize=pagesizes.A4)
        c.drawString(100, 700, "条款编号    条款内容")
        c.drawString(100, 680, "1           保险责任")
        c.save()
    return _create
```

**Step 2.5: Markdown 解析测试**

文件: `scripts/tests/lib/doc_parser/kb/test_md_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 解析器测试"""
import pytest
from lib.doc_parser.kb import parse_knowledge_base
from lib.doc_parser.kb.md_parser import MdParser


class TestMdParser:

    def test_supported_extensions(self):
        assert '.md' in MdParser.supported_extensions()
        assert '.markdown' in MdParser.supported_extensions()

    def test_extract_frontmatter(self, tmp_path):
        md_content = """---
regulation: 健康保险管理办法
collection: 03_健康保险管理办法
发文机关: ["中国银保监会"]
文号: ["银保监发〔2019〕102号"]
---
# 健康保险管理办法

## 第1项
条款内容...
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(md_content, encoding='utf-8')

        nodes = parse_knowledge_base(str(md_file))
        assert len(nodes) == 1
        assert nodes[0].metadata['law_name'] == '健康保险管理办法'
        assert nodes[0].metadata['doc_number'] == '银保监发〔2019〕102号'

    def test_split_by_items(self, tmp_path):
        md_content = """---
regulation: 测试法规
---
# 测试法规

## 第1项
第一项内容

## 第2项
第二项内容

## 第3项
第三项内容
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(md_content, encoding='utf-8')

        nodes = parse_knowledge_base(str(md_file))
        assert len(nodes) == 3
        assert nodes[0].metadata['article_number'] == '第1项'
        assert nodes[1].metadata['article_number'] == '第2项'
        assert nodes[2].metadata['article_number'] == '第3项'

    def test_blockquote_metadata(self, tmp_path):
        md_content = """---
regulation: 测试法规
---
# 测试法规

## 第1项
> **元数据**: 险种类型=医疗险 | 保险期限=短期

条款内容...
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(md_content, encoding='utf-8')

        nodes = parse_knowledge_base(str(md_file))
        assert len(nodes) == 1
        assert nodes[0].metadata['险种类型'] == '医疗险'
        assert nodes[0].metadata['保险期限'] == '短期'

    def test_long_chunk_split(self, tmp_path):
        long_content = "这是一句话。" * 1000
        md_content = f"""---
regulation: 测试法规
---
# 测试法规

## 第1项
{long_content}
"""
        md_file = tmp_path / "test.md"
        md_file.write_text(md_content, encoding='utf-8')

        nodes = parse_knowledge_base(str(md_file))
        assert len(nodes) > 1
        for node in nodes:
            assert len(node.text) <= 3000
```

---

## Phase 3: Core - User Story 2 & 3 (P1)

→ 对应 spec.md User Story 2: 保险产品条款解析
→ 对应 spec.md User Story 3: 多内容类型解析

**Step 3.1: pd 包导出**

文件: `scripts/lib/doc_parser/pd/__init__.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析"""
from .parser import parse_product_document

__all__ = ['parse_product_document']
```

**Step 3.2: pd 编排器**

文件: `scripts/lib/doc_parser/pd/parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析编排器"""
from __future__ import annotations

from pathlib import Path

from ..models import AuditDocument, DocumentParseError
from .docx_parser import DocxParser
from .pdf_parser import PdfParser


def parse_product_document(file_path: str) -> AuditDocument:
    """解析保险产品文档，根据文件扩展名自动选择解析器。"""
    path = Path(file_path)
    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    ext = path.suffix.lower()
    if ext in DocxParser.supported_extensions():
        return DocxParser().parse(file_path)
    if ext in PdfParser.supported_extensions():
        return PdfParser().parse(file_path)

    raise DocumentParseError(
        f"不支持的产品文档格式: {ext}",
        file_path,
        f"支持的格式: {DocxParser.supported_extensions() + PdfParser.supported_extensions()}"
    )
```

**Step 3.3: 内容类型检测器**

文件: `scripts/lib/doc_parser/pd/section_detector.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容类型检测器"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Set

from ..models import SectionType


class SectionDetector:
    """内容类型检测器

    关键词通过 data/keywords.json 配置，可替换为其他领域的配置。
    """

    CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s*$')

    def __init__(self, keywords_path: Optional[str] = None):
        if keywords_path:
            config_path = Path(keywords_path)
        else:
            config_path = Path(__file__).parent / 'data' / 'keywords.json'

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.section_keywords: dict = config['section_keywords']
        self.premium_table_keywords: Set[str] = set(config['premium_table_keywords'])
        self.non_clause_table_keywords: Set[str] = set(config['non_clause_table_keywords'])

        self._priority = [
            SectionType.HEALTH_DISCLOSURE,
            SectionType.EXCLUSION,
            SectionType.NOTICE,
            SectionType.RIDER,
        ]

    def detect_section_type(self, title: str) -> Optional[SectionType]:
        for section_type in self._priority:
            keywords = self.section_keywords.get(section_type.value, [])
            for kw in keywords:
                if kw in title:
                    return section_type
        return None

    def is_clause_table(self, first_col: str) -> bool:
        return bool(self.CLAUSE_NUMBER_PATTERN.match(first_col.strip()))

    def is_premium_table(self, header_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in header_row)
        return any(kw in text for kw in self.premium_table_keywords)

    def is_non_clause_table(self, first_row: List[str]) -> bool:
        text = ' '.join(str(cell) for cell in first_row)
        return any(kw in text for kw in self.non_clause_table_keywords)
```

**Step 3.4: 关键词配置**

文件: `scripts/lib/doc_parser/pd/data/keywords.json`

```json
{
  "section_keywords": {
    "notice": ["投保须知", "投保说明", "重要提示"],
    "health_disclosure": ["健康告知", "健康声明", "告知事项"],
    "exclusion": ["责任免除", "免责条款", "除外责任"],
    "rider": ["附加险", "附加条款", "附加合同"]
  },
  "premium_table_keywords": ["年龄", "费率", "保费", "周岁", "性别", "缴费", "保额"],
  "non_clause_table_keywords": ["公司", "地址", "电话", "邮编", "客服", "网址", "资质"]
}
```

**Step 3.5: Word 解析器**

文件: `scripts/lib/doc_parser/pd/docx_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 文档解析器"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from docx import Document
from docx.table import Table

from ..models import Clause, PremiumTable, AuditDocument, DocumentSection, DocumentParseError
from .section_detector import SectionDetector

logger = logging.getLogger(__name__)


class DocxParser:
    """Word (.docx) 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.docx']

    def parse(self, file_path: str) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)

        try:
            doc = Document(file_path)
        except Exception as e:
            raise DocumentParseError("Word 文件解析失败", file_path, str(e))

        warnings: List[str] = []

        clauses = self._extract_clauses(doc.tables, warnings)
        premium_tables = self._extract_premium_tables(doc.tables, warnings)
        sections = self._extract_sections(doc.tables, doc.paragraphs, warnings)

        return AuditDocument(
            file_name=path.name,
            file_type='.docx',
            clauses=clauses,
            premium_tables=premium_tables,
            **sections,
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses(self, tables: List[Table], warnings: List[str]) -> List[Clause]:
        clauses = []

        for table in tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                continue

            if self.detector.is_non_clause_table(rows[0]):
                continue

            for row in rows:
                if not row or not row[0]:
                    continue

                if self.detector.is_clause_table(row[0]):
                    number = row[0].strip()
                    title, text = self._separate_title_and_text(row[1] if len(row) > 1 else '')
                    clauses.append(Clause(number=number, title=title, text=text))

        return clauses

    def _extract_premium_tables(self, tables: List[Table], warnings: List[str]) -> List[PremiumTable]:
        premium_tables = []

        for table in tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                continue

            if self.detector.is_premium_table(rows[0]):
                raw_text = '\n'.join('\t'.join(row) for row in rows)
                data = rows
                premium_tables.append(PremiumTable(raw_text=raw_text, data=data))

        return premium_tables

    def _extract_sections(
        self,
        tables: List[Table],
        paragraphs: List,
        warnings: List[str],
    ) -> dict:
        result = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        current_type = None
        current_content: List[str] = []

        for para in paragraphs:
            text = para.text.strip()
            if not text:
                continue

            detected = self.detector.detect_section_type(text)
            if detected:
                if current_type and current_content:
                    self._add_section(result, current_type, '', '\n'.join(current_content))
                current_type = detected
                current_content = []
            else:
                if current_type:
                    current_content.append(text)

        if current_type and current_content:
            self._add_section(result, current_type, '', '\n'.join(current_content))

        return result

    def _add_section(self, result: dict, section_type, title: str, content: str) -> None:
        section = DocumentSection(title=title, content=content, section_type=section_type.value)

        if section_type.value == 'notice':
            result['notices'].append(section)
        elif section_type.value == 'health_disclosure':
            result['health_disclosures'].append(section)
        elif section_type.value == 'exclusion':
            result['exclusions'].append(section)
        elif section_type.value == 'rider':
            result['rider_clauses'].append(section)

    @staticmethod
    def _separate_title_and_text(content: str) -> Tuple[str, str]:
        if not content:
            return '', ''

        content = content.strip()

        if '\n' in content:
            lines = content.split('\n', 1)
            return lines[0].strip(), lines[1].strip() if len(lines) > 1 else ''

        sentences = []
        current = ''
        for char in content:
            current += char
            if char in '。！？':
                sentences.append(current.strip())
                current = ''

        if current:
            sentences.append(current.strip())

        if len(sentences) >= 2 and len(sentences[0]) <= 30:
            return sentences[0], ''.join(sentences[1:])

        return content, ''
```

**Step 3.6: PDF 解析器**

文件: `scripts/lib/doc_parser/pd/pdf_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 文档解析器"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

import pdfplumber

from ..models import Clause, PremiumTable, AuditDocument, DocumentSection, DocumentParseError
from .section_detector import SectionDetector

logger = logging.getLogger(__name__)


class PdfParser:
    """PDF 文档解析器"""

    def __init__(self, section_detector: Optional[SectionDetector] = None):
        self.detector = section_detector or SectionDetector()

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.pdf']

    def parse(self, file_path: str) -> AuditDocument:
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError("文件不存在", file_path)

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as e:
            raise DocumentParseError("PDF 文件解析失败", file_path, str(e))

        warnings: List[str] = []
        clauses: List[Clause] = []
        premium_tables: List[PremiumTable] = []
        sections_data = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        try:
            for page in pdf.pages:
                page_clauses = self._extract_clauses_from_page(page, warnings)
                clauses.extend(page_clauses)

                page_premium = self._extract_premium_tables_from_page(page, warnings)
                premium_tables.extend(page_premium)

                page_sections = self._extract_sections_from_page(page, warnings)
                for key, items in page_sections.items():
                    sections_data[key].extend(items)
        finally:
            pdf.close()

        return AuditDocument(
            file_name=path.name,
            file_type='.pdf',
            clauses=clauses,
            premium_tables=premium_tables,
            **sections_data,
            parse_time=datetime.now(),
            warnings=warnings,
        )

    def _extract_clauses_from_page(self, page, warnings: List[str]) -> List[Clause]:
        clauses = []

        tables = page.find_tables()
        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            for row in rows:
                if not row or not row[0]:
                    continue

                first_cell = str(row[0]).strip() if row[0] else ''
                if self.detector.is_clause_table(first_cell):
                    number = first_cell
                    content = str(row[1]).strip() if len(row) > 1 and row[1] else ''
                    title, text = self._separate_title_and_text(content)
                    clauses.append(Clause(number=number, title=title, text=text))

        return clauses

    def _extract_premium_tables_from_page(self, page, warnings: List[str]) -> List[PremiumTable]:
        premium_tables = []

        tables = page.find_tables()
        for table in tables:
            rows = table.extract()
            if not rows:
                continue

            header = [str(cell).strip() for cell in rows[0]] if rows else []
            if self.detector.is_premium_table(header):
                raw_text = '\n'.join('\t'.join(str(cell) for cell in row) for row in rows)
                data = [[str(cell) for cell in row] for row in rows]
                premium_tables.append(PremiumTable(raw_text=raw_text, data=data))

        return premium_tables

    def _extract_sections_from_page(self, page, warnings: List[str]) -> dict:
        result = {
            'notices': [],
            'health_disclosures': [],
            'exclusions': [],
            'rider_clauses': [],
        }

        text = page.extract_text() or ''
        lines = text.split('\n')

        current_type = None
        current_content: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            detected = self.detector.detect_section_type(line)
            if detected:
                if current_type and current_content:
                    self._add_section(result, current_type, '', '\n'.join(current_content))
                current_type = detected
                current_content = []
            else:
                if current_type:
                    current_content.append(line)

        if current_type and current_content:
            self._add_section(result, current_type, '', '\n'.join(current_content))

        return result

    def _add_section(self, result: dict, section_type, title: str, content: str) -> None:
        section = DocumentSection(title=title, content=content, section_type=section_type.value)

        if section_type.value == 'notice':
            result['notices'].append(section)
        elif section_type.value == 'health_disclosure':
            result['health_disclosures'].append(section)
        elif section_type.value == 'exclusion':
            result['exclusions'].append(section)
        elif section_type.value == 'rider':
            result['rider_clauses'].append(section)

    @staticmethod
    def _separate_title_and_text(content: str) -> Tuple[str, str]:
        if not content:
            return '', ''

        content = content.strip()

        if '\n' in content:
            lines = content.split('\n', 1)
            return lines[0].strip(), lines[1].strip() if len(lines) > 1 else ''

        sentences = []
        current = ''
        for char in content:
            current += char
            if char in '。！？':
                sentences.append(current.strip())
                current = ''

        if current:
            sentences.append(current.strip())

        if len(sentences) >= 2 and len(sentences[0]) <= 30:
            return sentences[0], ''.join(sentences[1:])

        return content, ''
```

**Step 3.7: Word/PDF 解析测试**

文件: `scripts/tests/lib/doc_parser/pd/test_docx_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 解析器测试"""
import pytest
from lib.doc_parser import parse_product_document
from lib.doc_parser.pd.docx_parser import DocxParser


class TestDocxParser:

    def test_supported_extensions(self):
        assert '.docx' in DocxParser.supported_extensions()

    def test_extract_clauses(self, tmp_path, sample_docx_with_clauses):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_clauses(docx_file, [
            ("1", "保险责任", "我们承担以下保险责任..."),
            ("2", "责任免除", "因下列情形导致..."),
        ])

        doc = parse_product_document(str(docx_file))
        assert len(doc.clauses) == 2
        assert doc.clauses[0].number == "1"
        assert doc.clauses[0].title == "保险责任"

    def test_extract_premium_tables(self, tmp_path, sample_docx_with_premium):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_premium(docx_file)

        doc = parse_product_document(str(docx_file))
        assert len(doc.premium_tables) >= 1

    def test_non_clause_table_filtered(self, tmp_path, sample_docx_with_company_info):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_company_info(docx_file)

        doc = parse_product_document(str(docx_file))
        assert all(c.number not in ['', '公司'] for c in doc.clauses)
```

文件: `scripts/tests/lib/doc_parser/pd/test_pdf_parser.py`

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 解析器测试"""
import pytest
from lib.doc_parser import parse_product_document
from lib.doc_parser.pd.pdf_parser import PdfParser


class TestPdfParser:

    def test_supported_extensions(self):
        assert '.pdf' in PdfParser.supported_extensions()

    def test_extract_clauses_from_pdf(self, tmp_path, sample_pdf_with_clauses):
        pdf_file = tmp_path / "test.pdf"
        sample_pdf_with_clauses(pdf_file)

        doc = parse_product_document(str(pdf_file))
        assert len(doc.clauses) >= 1

    def test_pdf_output_matches_docx(self, tmp_path, sample_docx_with_clauses, sample_pdf_with_clauses):
        docx_file = tmp_path / "test.docx"
        pdf_file = tmp_path / "test.pdf"

        sample_docx_with_clauses(docx_file, [("1", "保险责任", "内容...")])
        sample_pdf_with_clauses(pdf_file)

        docx_result = parse_product_document(str(docx_file))
        pdf_result = parse_product_document(str(pdf_file))

        assert len(docx_result.clauses) == len(pdf_result.clauses)
```

---

## Phase 4: Enhancement - User Story 4 (P2)

→ 对应 spec.md User Story 4: 飞书文档同步代码删除

**Step 4.1: 删除废弃文件**

- 删除: `scripts/lib/common/document_fetcher.py`
- 删除: `scripts/tests/lib/common/test_document_fetcher.py`（如存在）

**Step 4.2: 清理引用**

```bash
grep -r "document_fetcher" scripts/  # 移除所有 import
```

---

## Phase 5: Integration

集成到现有知识库构建流程。

**Step 5.1: 修改 KnowledgeBuilder**

文件: `scripts/lib/rag_engine/builder.py`

仅替换 chunker，保持 parse() 和 chunk() 接口不变：

```python
from lib.doc_parser.kb.md_parser import MdParser

class KnowledgeBuilder:
    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        self.chunker = MdParser()  # 替换为 MdParser
        self.index_manager = VectorIndexManager(self.config)
        self._embedding_setup_done = False

    # parse() 保持不变
    def parse(self, file_pattern: str = "**/*.md") -> List:
        regulations_dir = Path(self.config.regulations_dir)
        if not regulations_dir.exists():
            logger.error(f"目录不存在: {regulations_dir}")
            return []

        from llama_index.core.readers import SimpleDirectoryReader
        md_files = sorted(regulations_dir.glob(file_pattern))
        if not md_files:
            logger.error(f"未找到匹配 {file_pattern} 的文件")
            return []

        reader = SimpleDirectoryReader(input_files=[str(f) for f in md_files])
        documents = reader.load_data()
        logger.info(f"从 {regulations_dir} 加载了 {len(documents)} 个文档")
        return documents

    # chunk() 接口不变，内部调用 MdParser
    def chunk(self, documents: List) -> List[TextNode]:
        all_nodes: List[TextNode] = []
        for doc in documents:
            nodes = self.chunker.parse_document(doc)
            all_nodes.extend(nodes)
        return all_nodes

    # build() 保持不变
```

**Step 5.2: 删除旧代码**

- 删除: `scripts/lib/rag_engine/chunker.py`
- 更新: `scripts/lib/rag_engine/__init__.py` 移除 `ChecklistChunker` 导出

---

## Appendix

### 执行顺序

```
Phase 1 (Infrastructure)
    ↓
Phase 2 (Markdown 解析) ─────┐
    ↓                        │
Phase 3 (Word/PDF 解析) ─────┼─→ 可并行
    ↓                        │
Phase 4 (删除废弃代码) ───────┘
    ↓
Phase 5 (集成)
```

### 验收标准

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1: 知识库文档解析 | frontmatter 提取、`## 第N项` 分块、向后兼容 | test_md_parser.py |
| US2: 保险产品条款解析 | 条款编号识别、标题/正文分离、费率表提取 | test_docx_parser.py, test_pdf_parser.py |
| US3: 多内容类型解析 | 6 种内容类型正确识别 | test_section_detector.py |
| US4: 飞书代码删除 | 文件已删除、引用已清理 | grep 验证 |
| US5: 解析错误处理 | 明确异常类型和消息 | test_error_handling.py |

### 依赖安装

```bash
pip install python-docx>=0.8.11 pdfplumber>=0.9.0
```
