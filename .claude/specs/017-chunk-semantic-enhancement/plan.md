# Implementation Plan: Chunk 语义增强

**Branch**: `017-chunk-semantic-enhancement` | **Date**: 2026-04-22 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

实现文档解析的 chunk 语义增强，主要包括：1) Markdown 表格完整性保护；2) PDF 跨页表格合并；3) 超大表格表头补充。基于现有 `MdParser` 和 `PdfParser` 架构增量增强，无新增依赖，保持接口兼容。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: pdfplumber (已有), python-docx (已有), llama-index-core (已有)
**Storage**: 无新增存储需求
**Testing**: pytest
**Performance Goals**: 单文档解析性能不下降超过 20%
**Constraints**: 必须兼容现有 MdParser 接口，不引入重量级依赖

## Constitution Check

- [x] **Library-First**: 复用 pdfplumber 的 `find_tables()` 和 `extract()`，复用现有 `MdParser` 的递归分块框架
- [x] **测试优先**: 每个 User Story 规划了对应的测试文件和测试用例
- [x] **简单优先**: 选择正则匹配而非 AST 解析，选择启发式规则而非 ML 模型
- [x] **显式优于隐式**: 表格边界通过明确的位置标记，跨页检测使用多条件判断
- [x] **可追溯性**: 每个 Phase 明确回溯到 spec.md 的 User Story
- [x] **独立可测试**: 每个 User Story 可独立开发和测试

## Project Structure

### Documentation

```text
.claude/specs/017-chunk-semantic-enhancement/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/doc_parser/
├── models.py                    # 修改: PremiumTable 增加 header 字段
├── kb/
│   ├── md_parser.py             # 修改: 增加表格识别与保护
│   └── table_utils.py           # 新增: Markdown 表格解析工具
└── pd/
    ├── pdf_parser.py            # 修改: 增加跨页表格合并
    └── table_merger.py          # 新增: PDF 跨页表格合并器

scripts/tests/lib/doc_parser/
├── kb/
│   └── test_table_utils.py      # 新增: 表格解析测试
└── pd/
    └── test_table_merger.py     # 新增: 跨页合并测试
```

## Implementation Phases

---

### Phase 1: 数据模型增强

#### 需求回溯

→ 支撑 FR-003 (表头补充) 和所有表格相关 User Story

#### 实现步骤

1. **修改 PremiumTable 数据模型**
   - 文件: `scripts/lib/doc_parser/models.py`
   - 在 `PremiumTable` 中增加 `header` 字段

```python
@dataclass(frozen=True)
class PremiumTable:
    """费率表"""
    raw_text: str              # 原始文本
    data: List[List[str]]      # 结构化数据（二维表格）
    header: List[str] = field(default_factory=list)  # 新增: 表头行
    remark: str = ""           # 备注
    section_type: str = "premium_table"
```

2. **新增 MarkdownTable 数据结构**
   - 文件: `scripts/lib/doc_parser/models.py`
   - 用于 Markdown 表格解析结果的内部表示

```python
@dataclass(frozen=True)
class MarkdownTable:
    """Markdown 表格结构"""
    header: List[str]           # 表头
    rows: List[List[str]]       # 数据行
    raw_text: str               # 原始文本
    start_pos: int              # 文档中起始位置
    end_pos: int                # 文档中结束位置
```

---

### Phase 2: Core - User Story 1 (P1) Markdown 表格完整性保护

#### 需求回溯

→ 对应 spec.md User Story 1: 表格完整性保护
→ 对应 FR-001: 系统 MUST 识别 Markdown 表格语法

#### 实现步骤

1. **创建表格解析工具模块**
   - 文件: `scripts/lib/doc_parser/kb/table_utils.py` (新增)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 表格解析工具"""
from __future__ import annotations

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass

from ..models import MarkdownTable

# Markdown 表格正则模式
# 匹配: | 表头 | 列2 |\n|---|---|\n| 数据 | 值 |
MARKDOWN_TABLE_PATTERN = re.compile(
    r'^(\|[^\n]+\|\n)'           # 表头行
    r'(\|[-:| ]+\|\n)'           # 分隔行
    r'(\|[^\n]+\|\n?)+',         # 数据行
    re.MULTILINE
)


def find_tables(text: str) -> List[MarkdownTable]:
    """识别文本中所有 Markdown 表格

    Args:
        text: Markdown 文档全文

    Returns:
        MarkdownTable 列表，按位置排序
    """
    tables: List[MarkdownTable] = []

    for match in MARKDOWN_TABLE_PATTERN.finditer(text):
        table_text = match.group(0)
        start_pos = match.start()
        end_pos = match.end()

        parsed = parse_table(table_text)
        if parsed:
            header, rows = parsed
            tables.append(MarkdownTable(
                header=header,
                rows=rows,
                raw_text=table_text,
                start_pos=start_pos,
                end_pos=end_pos,
            ))

    return tables


def parse_table(table_text: str) -> Optional[Tuple[List[str], List[List[str]]]]:
    """解析单个 Markdown 表格

    Args:
        table_text: 表格原始文本

    Returns:
        (header, rows) 或 None（解析失败时）
    """
    lines = [line.strip() for line in table_text.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        return None

    # 第一行是表头
    header = parse_table_row(lines[0])
    if not header:
        return None

    # 第二行是分隔符，跳过
    # 从第三行开始是数据行
    rows: List[List[str]] = []
    for line in lines[2:]:
        row = parse_table_row(line)
        if row:
            rows.append(row)

    return header, rows


def parse_table_row(line: str) -> List[str]:
    """解析表格行

    Args:
        line: 形如 "| 列1 | 列2 | 列3 |" 的行

    Returns:
        单元格内容列表
    """
    if not line.startswith('|') or not line.endswith('|'):
        return []

    # 移除首尾 |，按 | 分割
    cells = line[1:-1].split('|')
    return [cell.strip() for cell in cells]


def is_within_table(pos: int, tables: List[MarkdownTable]) -> bool:
    """检查位置是否在某个表格内

    Args:
        pos: 文本位置
        tables: 已识别的表格列表

    Returns:
        True 如果位置在某个表格范围内
    """
    for table in tables:
        if table.start_pos <= pos < table.end_pos:
            return True
    return False
```

2. **修改 MdParser 增加表格识别**
   - 文件: `scripts/lib/doc_parser/kb/md_parser.py`
   - 在 `parse_document()` 方法中增加表格预处理

```python
# 在 MdParser 类中增加方法

def parse_document(self, doc: Document) -> List[TextNode]:
    """解析 Document 对象，返回分块后的 TextNode 列表。"""
    source_file = doc.metadata.get('file_name', '')
    text = doc.text

    if len(text) > MAX_DOCUMENT_CHARS:
        logger.warning(
            f"文档过大 ({len(text)} chars)，截断至 {MAX_DOCUMENT_CHARS} chars: {source_file}"
        )
        text = text[:MAX_DOCUMENT_CHARS]

    frontmatter, body = self._extract_frontmatter(text)
    doc_meta = DocumentMeta.from_frontmatter(frontmatter)

    # law_name 回退策略
    if not doc_meta.law_name:
        law_name = self._extract_law_name(body)
        if law_name:
            doc_meta = replace(doc_meta, law_name=law_name)
        elif doc_meta.collection:
            doc_meta = replace(doc_meta, law_name=doc_meta.collection)
        else:
            doc_meta = replace(doc_meta, law_name='未知')

    # 新增: 识别表格
    from .table_utils import find_tables
    tables = find_tables(body)
    logger.debug(f"识别到 {len(tables)} 个表格: {source_file}")

    headings = self._identify_headings(body)

    # 修改: 传入表格信息
    chunks, _ = self._recursive_chunk(
        body, headings, doc_meta, source_file,
        tables=tables  # 新增参数
    )

    if len(chunks) > MAX_CHUNKS:
        logger.warning(
            f"分块数过多 ({len(chunks)})，仅保留前 {MAX_CHUNKS} 个: {source_file}"
        )
        chunks = chunks[:MAX_CHUNKS]

    self._link_chunks(chunks)

    return self._chunks_to_nodes(chunks)
```

3. **修改 _recursive_chunk 支持表格保护**
   - 文件: `scripts/lib/doc_parser/kb/md_parser.py`
   - 跳过表格区域，单独处理表格为 chunk

```python
def _recursive_chunk(
    self,
    body: str,
    headings: List[Heading],
    doc_meta: DocumentMeta,
    source_file: str,
    parent_path: str = "",
    parent_chunk_id: Optional[int] = None,
    level: int = 1,
    chunk_id_counter: Optional[List[int]] = None,
    tables: Optional[List] = None,  # 新增参数
) -> Tuple[List[Chunk], List[int]]:
    """递归切分文档

    新增表格保护逻辑：跳过表格区域，单独处理表格为 chunk
    """
    if chunk_id_counter is None:
        chunk_id_counter = [0]

    if tables is None:
        tables = []

    chunks: List[Chunk] = []
    current_level_chunk_ids: List[int] = []

    # 新增: 先处理表格 chunk
    for table in tables:
        chunk_id = chunk_id_counter[0]
        chunk_id_counter[0] += 1

        table_chunk = Chunk(
            content=table.raw_text,
            section_path=parent_path if parent_path else "表格",
            metadata=self._build_metadata(
                doc_meta, source_file,
                parent_path if parent_path else "表格",
                level, ""
            ),
            chunk_id=chunk_id,
            parent_chunk_id=parent_chunk_id,
            level=level,
        )
        # 新增表格相关元数据
        table_chunk.metadata['content_type'] = 'table'
        table_chunk.metadata['table_headers'] = table.header
        table_chunk.metadata['table_row_count'] = len(table.rows)
        chunks.append(table_chunk)
        current_level_chunk_ids.append(chunk_id)

    # 原有逻辑处理非表格内容（跳过表格区域）
    # ... 在遍历 body 时，使用 is_within_table() 检查并跳过表格区域

    return chunks, current_level_chunk_ids
```

4. **编写表格解析测试**
   - 文件: `scripts/tests/lib/doc_parser/kb/test_table_utils.py` (新增)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 表格解析测试"""
import pytest
from lib.doc_parser.kb.table_utils import (
    find_tables,
    parse_table,
    parse_table_row,
    is_within_table,
)


class TestParseTableRow:
    """测试表格行解析"""

    def test_simple_row(self):
        assert parse_table_row("| a | b | c |") == ["a", "b", "c"]

    def test_row_with_spaces(self):
        assert parse_table_row("|  列1  |  列2  |") == ["列1", "列2"]

    def test_invalid_row_no_pipe(self):
        assert parse_table_row("a | b | c") == []


class TestParseTable:
    """测试表格解析"""

    def test_simple_table(self):
        table_text = "| 列1 | 列2 |\n|---|---|\n| a | b |\n| c | d |"
        result = parse_table(table_text)
        assert result is not None
        header, rows = result
        assert header == ["列1", "列2"]
        assert rows == [["a", "b"], ["c", "d"]]

    def test_table_with_alignment(self):
        table_text = "| 列1 | 列2 |\n|:---|---:|\n| a | b |"
        result = parse_table(table_text)
        assert result is not None
        header, rows = result
        assert header == ["列1", "列2"]


class TestFindTables:
    """测试表格识别"""

    def test_find_single_table(self):
        text = """
# 标题

这是一段文字。

| 列1 | 列2 |
|---|---|
| a | b |

另一段文字。
"""
        tables = find_tables(text)
        assert len(tables) == 1
        assert tables[0].header == ["列1", "列2"]

    def test_find_multiple_tables(self):
        text = """
| 表1 | 列2 |
|---|---|
| a | b |

中间文字

| 表2 | 列2 |
|---|---|
| c | d |
"""
        tables = find_tables(text)
        assert len(tables) == 2

    def test_no_table(self):
        text = "这是一段普通文字，没有表格。"
        tables = find_tables(text)
        assert len(tables) == 0


class TestIsWithinTable:
    """测试位置判断"""

    def test_position_in_table(self):
        table_text = "| a | b |\n|---|---|\n| c | d |"
        tables = find_tables(table_text)
        assert len(tables) == 1
        assert is_within_table(0, tables) is True
        assert is_within_table(5, tables) is True
        assert is_within_table(100, tables) is False
```

---

### Phase 3: Core - User Story 2 (P1) PDF 跨页表格合并

#### 需求回溯

→ 对应 spec.md User Story 2: 跨页表格合并
→ 对应 FR-002: 系统 MUST 识别 PDF 中的表格结构

#### 实现步骤

1. **创建跨页表格合并器**
   - 文件: `scripts/lib/doc_parser/pd/table_merger.py` (新增)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 跨页表格合并器"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 合并判断阈值
HEADER_SIMILARITY_THRESHOLD = 0.8
SAME_TABLE_MAX_GAP_PAGES = 1


@dataclass
class ExtractedTable:
    """从 PDF 提取的表格信息"""
    page_num: int
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    header: List[str]
    rows: List[List[str]]
    raw_data: List[List[str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.header) if self.header else 0


class TableMerger:
    """PDF 跨页表格合并器"""

    def __init__(self, header_similarity_threshold: float = HEADER_SIMILARITY_THRESHOLD):
        self.header_similarity_threshold = header_similarity_threshold

    def merge_tables(self, tables: List[ExtractedTable]) -> List[ExtractedTable]:
        """合并跨页表格

        Args:
            tables: 按页面顺序提取的表格列表

        Returns:
            合并后的表格列表
        """
        if not tables:
            return []

        # 按 page_num 排序
        sorted_tables = sorted(tables, key=lambda t: t.page_num)

        merged: List[ExtractedTable] = []
        current: Optional[ExtractedTable] = None

        for table in sorted_tables:
            if current is None:
                current = table
                continue

            if self._should_merge(current, table):
                current = self._do_merge(current, table)
            else:
                merged.append(current)
                current = table

        if current:
            merged.append(current)

        return merged

    def _should_merge(self, table1: ExtractedTable, table2: ExtractedTable) -> bool:
        """判断两个表格是否应该合并

        合并条件:
        1. 页码相邻
        2. 列数相同
        3. 表头相似度 >= 阈值（或 table2 无表头）
        """
        # 条件1: 页码相邻
        if table2.page_num - table1.page_num > SAME_TABLE_MAX_GAP_PAGES:
            return False

        # 条件2: 列数相同
        if table1.column_count != table2.column_count:
            return False

        # 条件3: 表头相似度
        if not table2.header or all(not cell.strip() for cell in table2.header):
            # table2 无表头，可能是跨页表格的延续
            return True

        similarity = self._calculate_header_similarity(table1.header, table2.header)
        return similarity >= self.header_similarity_threshold

    def _calculate_header_similarity(self, h1: List[str], h2: List[str]) -> float:
        """计算表头相似度"""
        if not h1 or not h2 or len(h1) != len(h2):
            return 0.0

        matches = sum(
            1 for a, b in zip(h1, h2)
            if a.strip() == b.strip()
        )
        return matches / len(h1)

    def _do_merge(self, table1: ExtractedTable, table2: ExtractedTable) -> ExtractedTable:
        """合并两个表格"""
        # 使用 table1 的表头（table2 可能无表头或表头相同）
        merged_header = table1.header

        # 合并数据行
        merged_rows = table1.rows + table2.rows
        merged_raw_data = table1.raw_data + table2.raw_data

        # 使用 table1 的页面和位置信息
        return ExtractedTable(
            page_num=table1.page_num,
            bbox=table1.bbox,
            header=merged_header,
            rows=merged_rows,
            raw_data=merged_raw_data,
        )


def extract_table_with_header(raw_data: List[List[str]]) -> ExtractedTable:
    """从原始表格数据提取表头和数据行

    Args:
        raw_data: pdfplumber 提取的原始数据

    Returns:
        ExtractedTable 对象
    """
    if not raw_data:
        return ExtractedTable(
            page_num=0,
            bbox=(0, 0, 0, 0),
            header=[],
            rows=[],
            raw_data=[],
        )

    # 第一行作为表头
    header = [str(cell or '').strip() for cell in raw_data[0]]
    rows = [[str(cell or '').strip() for cell in row] for row in raw_data[1:]]

    return ExtractedTable(
        page_num=0,  # 由调用方设置
        bbox=(0, 0, 0, 0),  # 由调用方设置
        header=header,
        rows=rows,
        raw_data=raw_data,
    )
```

2. **修改 PdfParser 使用合并器**
   - 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
   - 修改 `parse()` 方法，增加跨页合并逻辑

```python
# 在 PdfParser 类中修改

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
    sections_data: Dict[str, List[Any]] = {
        'notices': [],
        'health_disclosures': [],
        'exclusions': [],
        'rider_clauses': [],
    }

    # 新增: 收集所有页面提取的表格
    from .table_merger import TableMerger, ExtractedTable, extract_table_with_header
    all_tables: List[ExtractedTable] = []

    try:
        for page_num, page in enumerate(pdf.pages):
            tables = page.find_tables()

            # 提取表格信息
            for table in tables:
                rows = table.extract()
                if not rows:
                    continue

                extracted = extract_table_with_header(rows)
                extracted.page_num = page_num
                extracted.bbox = table.bbox
                all_tables.append(extracted)

        # 新增: 合并跨页表格
        merger = TableMerger()
        merged_tables = merger.merge_tables(all_tables)
        logger.info(f"表格合并: {len(all_tables)} -> {len(merged_tables)}")

        # 处理合并后的表格
        for table in merged_tables:
            if self.detector.is_premium_table(table.header):
                raw_text = '\n'.join('\t'.join(row) for row in table.raw_data)
                premium_tables.append(PremiumTable(
                    raw_text=raw_text,
                    data=table.raw_data,
                    header=table.header,  # 新增: 表头
                ))
            elif self._is_clause_table(table):
                for row in table.rows:
                    if row and row[0] and self.detector.is_clause_table(row[0]):
                        number = row[0]
                        title, text = separate_title_and_text(row[1] if len(row) > 1 else '')
                        clauses.append(Clause(number=number, title=title, text=text))

        # 原有的文本段落提取逻辑
        for page in pdf.pages:
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
        notices=sections_data['notices'],
        health_disclosures=sections_data['health_disclosures'],
        exclusions=sections_data['exclusions'],
        rider_clauses=sections_data['rider_clauses'],
        parse_time=datetime.now(),
        warnings=warnings,
    )

def _is_clause_table(self, table: ExtractedTable) -> bool:
    """判断是否为条款表格"""
    # 检查第一列是否为条款编号格式
    for row in table.rows[:3]:  # 检查前3行
        if row and row[0] and self.detector.is_clause_table(row[0]):
            return True
    return False
```

3. **编写跨页合并测试**
   - 文件: `scripts/tests/lib/doc_parser/pd/test_table_merger.py` (新增)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 跨页表格合并测试"""
import pytest
from lib.doc_parser.pd.table_merger import (
    TableMerger,
    ExtractedTable,
    extract_table_with_header,
)


class TestExtractTableWithHeader:
    """测试表格提取"""

    def test_extract_header_and_rows(self):
        raw_data = [
            ["列1", "列2", "列3"],
            ["a", "b", "c"],
            ["d", "e", "f"],
        ]
        table = extract_table_with_header(raw_data)
        assert table.header == ["列1", "列2", "列3"]
        assert len(table.rows) == 2
        assert table.rows[0] == ["a", "b", "c"]


class TestTableMerger:
    """测试表格合并"""

    def test_no_merge_different_pages(self):
        """非相邻页不合并"""
        merger = TableMerger()
        tables = [
            ExtractedTable(page_num=1, bbox=(0, 0, 100, 100), header=["A", "B"], rows=[["1", "2"]], raw_data=[["A", "B"], ["1", "2"]]),
            ExtractedTable(page_num=3, bbox=(0, 0, 100, 100), header=["A", "B"], rows=[["3", "4"]], raw_data=[["A", "B"], ["3", "4"]]),
        ]
        merged = merger.merge_tables(tables)
        assert len(merged) == 2

    def test_merge_adjacent_pages_same_header(self):
        """相邻页相同表头合并"""
        merger = TableMerger()
        tables = [
            ExtractedTable(page_num=1, bbox=(0, 0, 100, 100), header=["列1", "列2"], rows=[["a", "b"]], raw_data=[["列1", "列2"], ["a", "b"]]),
            ExtractedTable(page_num=2, bbox=(0, 0, 100, 100), header=["列1", "列2"], rows=[["c", "d"]], raw_data=[["列1", "列2"], ["c", "d"]]),
        ]
        merged = merger.merge_tables(tables)
        assert len(merged) == 1
        assert len(merged[0].rows) == 2

    def test_merge_with_empty_header(self):
        """第二页无表头时合并"""
        merger = TableMerger()
        tables = [
            ExtractedTable(page_num=1, bbox=(0, 0, 100, 100), header=["列1", "列2"], rows=[["a", "b"]], raw_data=[["列1", "列2"], ["a", "b"]]),
            ExtractedTable(page_num=2, bbox=(0, 0, 100, 100), header=["", ""], rows=[["c", "d"]], raw_data=[["", ""], ["c", "d"]]),
        ]
        merged = merger.merge_tables(tables)
        assert len(merged) == 1
        assert merged[0].header == ["列1", "列2"]

    def test_no_merge_different_columns(self):
        """列数不同不合并"""
        merger = TableMerger()
        tables = [
            ExtractedTable(page_num=1, bbox=(0, 0, 100, 100), header=["A", "B"], rows=[["1", "2"]], raw_data=[["A", "B"], ["1", "2"]]),
            ExtractedTable(page_num=2, bbox=(0, 0, 100, 100), header=["A", "B", "C"], rows=[["3", "4", "5"]], raw_data=[["A", "B", "C"], ["3", "4", "5"]]),
        ]
        merged = merger.merge_tables(tables)
        assert len(merged) == 2
```

---

### Phase 4: Enhancement - User Story 3 (P2) 超大表格表头补充

#### 需求回溯

→ 对应 spec.md User Story 3: 超大表格 Header 补充
→ 对应 FR-003: 系统 MUST 为跨页/分块表格补充表头信息

#### 实现步骤

1. **在 md_parser 中增加超大表格分块逻辑**
   - 文件: `scripts/lib/doc_parser/kb/md_parser.py`
   - 新增表格分块策略配置和实现

```python
# 在 md_parser.py 开头增加配置
TABLE_ROW_THRESHOLD = 50  # 超过此行数的表格按行分块


class MdParser:
    def __init__(
        self,
        max_chunk_chars: int = 3000,
        chunk_overlap_chars: int = 150,
        min_chunk_chars: int = 20,
        chunk_config: Optional[Any] = None,
        table_row_threshold: int = TABLE_ROW_THRESHOLD,  # 新增
    ):
        # ... 原有初始化 ...
        self.table_row_threshold = table_row_threshold

    def _chunk_table(self, table) -> List[str]:
        """将大表格分块，每块包含表头

        Args:
            table: MarkdownTable 对象

        Returns:
            分块后的文本列表
        """
        if len(table.rows) <= self.table_row_threshold:
            # 小表格整体返回
            return [table.raw_text]

        # 大表格按行分块
        header_line = "| " + " | ".join(table.header) + " |"
        separator = "|" + "|".join(["---"] * len(table.header)) + "|"

        chunks: List[str] = []
        current_rows: List[str] = []
        current_len = len(header_line) + len(separator) + 2

        for row in table.rows:
            row_line = "| " + " | ".join(row) + " |"
            if current_len + len(row_line) > self.max_chunk_chars and current_rows:
                # 输出当前块
                chunks.append("\n".join([header_line, separator] + current_rows))
                current_rows = [row_line]
                current_len = len(header_line) + len(separator) + len(row_line) + 2
            else:
                current_rows.append(row_line)
                current_len += len(row_line) + 1

        if current_rows:
            chunks.append("\n".join([header_line, separator] + current_rows))

        return chunks
```

2. **修改 _recursive_chunk 使用表格分块**
   - 文件: `scripts/lib/doc_parser/kb/md_parser.py`
   - 调用 `_chunk_table()` 处理大表格

```python
# 在 _recursive_chunk 中修改表格处理部分
def _recursive_chunk(self, body, headings, doc_meta, source_file, ...):
    # ...

    # 处理表格 chunk
    for table in tables:
        table_chunks = self._chunk_table(table)  # 使用新方法

        for chunk_text in table_chunks:
            chunk_id = chunk_id_counter[0]
            chunk_id_counter[0] += 1

            table_chunk = Chunk(
                content=chunk_text,
                section_path=parent_path if parent_path else "表格",
                metadata=self._build_metadata(...),
                chunk_id=chunk_id,
                parent_chunk_id=parent_chunk_id,
                level=level,
            )
            table_chunk.metadata['content_type'] = 'table'
            table_chunk.metadata['table_headers'] = table.header
            chunks.append(table_chunk)
```

---

### Phase 5: Enhancement - User Story 4 & 5 (P2/P3) 验证与增强

#### 需求回溯

→ 对应 spec.md User Story 4: 语义感知段落切分
→ 对应 spec.md User Story 5: 层级结构保留
→ 对应 FR-004, FR-005

#### 实现步骤

这两个 User Story 在现有代码中已有基础实现，主要是验证和增强：

1. **验证句子边界切分** - 运行现有测试确认 `_chunk_by_sentence()` 正确工作
2. **验证层级结构保留** - 运行现有测试确认 `_identify_headings()` 正确工作
3. **增强列表完整性检测** - 扩展 `_should_merge()` 检测更多列表模式

```python
# 增强 _should_merge 检测更多列表模式
def _should_merge(self, chunk1: str, chunk2: str) -> bool:
    """检测两个chunk是否应该合并"""
    text1 = chunk1.strip()
    text2 = chunk2.strip()

    # 场景1: 冒号结尾
    if text1.endswith((':', '：', ';', '；')):
        return True

    # 场景2: 列表项编号开头
    if re.match(r'^[（(]\d+[）)]|^[①②③④⑤]|^[a-zA-Z]\.|^\d+\.', text2):
        return True

    # 场景3: 转折词开头
    if text2.startswith(('但', '然而', '除外', '不包括', '另有规定', '但是')):
        return True

    # 场景4: 延续性词汇开头 (新增)
    if text2.startswith(('其中', '包括', '即', '例如', '如下', '如下：')):
        return True

    return False
```

---

### Phase 6: 集成测试与验收

#### 需求回溯

→ 对应 spec.md Success Criteria

#### 实现步骤

1. **编写集成测试**
   - 文件: `scripts/tests/lib/doc_parser/test_integration.py` (新增)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chunk 语义增强集成测试"""
import pytest
from pathlib import Path
from lib.doc_parser.kb.md_parser import MdParser
from llama_index.core import Document


class TestMarkdownTableProtection:
    """User Story 1 验收测试"""

    def test_table_not_fragmented(self):
        """表格不被切碎"""
        md_text = """
# 测试文档

| 列1 | 列2 | 列3 |
|-----|-----|-----|
| a   | b   | c   |
| d   | e   | f   |
| g   | h   | i   |

其他内容。
"""
        parser = MdParser(max_chunk_chars=100)
        doc = Document(text=md_text, metadata={'file_name': 'test.md'})
        nodes = parser.parse_document(doc)

        # 验证表格在一个 chunk 中
        table_nodes = [n for n in nodes if n.metadata.get('content_type') == 'table']
        assert len(table_nodes) == 1
        assert '列1' in table_nodes[0].text
        assert 'g' in table_nodes[0].text

    def test_multiple_tables_separate(self):
        """多个表格独立成块"""
        md_text = """
| 表1 | 列2 |
|-----|-----|
| a   | b   |

| 表2 | 列2 |
|-----|-----|
| c   | d   |
"""
        parser = MdParser()
        doc = Document(text=md_text, metadata={'file_name': 'test.md'})
        nodes = parser.parse_document(doc)

        table_nodes = [n for n in nodes if n.metadata.get('content_type') == 'table']
        assert len(table_nodes) == 2


class TestLargeTableHeaderSupplement:
    """User Story 3 验收测试"""

    def test_large_table_has_header_in_each_chunk(self):
        """超大表格每个分块都有表头"""
        # 构造超过 threshold 的表格
        rows = ["| " + " | ".join([f"val{i}_{j}" for j in range(5)]) + " |" for i in range(60)]
        table_text = "| 列1 | 列2 | 列3 | 列4 | 列5 |\n" + \
                     "|-----|-----|-----|-----|-----|\n" + \
                     "\n".join(rows)

        parser = MdParser(max_chunk_chars=500, table_row_threshold=20)
        doc = Document(text=table_text, metadata={'file_name': 'test.md'})
        nodes = parser.parse_document(doc)

        # 验证每个 chunk 都包含表头
        table_nodes = [n for n in nodes if n.metadata.get('content_type') == 'table']
        assert len(table_nodes) > 1  # 应该被分块
        for node in table_nodes:
            assert '列1' in node.text  # 每个块都有表头
```

2. **运行完整测试套件**
```bash
pytest scripts/tests/lib/doc_parser/ -v
```

3. **性能测试**
```bash
python -c "
import time
from lib.doc_parser.kb.md_parser import MdParser
from llama_index.core import Document

# 构造大文档
text = '# 标题\n\n' + '\n\n'.join([f'段落 {i} 的内容...' * 50 for i in range(100)])
text += '\n\n| 列1 | 列2 |\n|---|---|\n' + '\n'.join([f'| a{i} | b{i} |' for i in range(50)])

doc = Document(text=text, metadata={'file_name': 'perf.md'})

start = time.time()
parser = MdParser()
nodes = parser.parse_document(doc)
elapsed = time.time() - start

print(f'解析 {len(text)} 字符，生成 {len(nodes)} 个 chunk，耗时 {elapsed:.2f}s')
"
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | - | - |

本方案完全符合简单优先原则，使用正则匹配而非 AST 解析，使用启发式规则而非 ML 模型。

---

## Appendix

### 执行顺序建议

```
Phase 1 (数据模型) → Phase 2 (Markdown 表格) → Phase 3 (PDF 跨页) → Phase 4 (超大表格) → Phase 5 (验证增强) → Phase 6 (集成测试)
```

**依赖关系**:
- Phase 1 是所有后续 Phase 的基础
- Phase 2、3 可并行开发
- Phase 4 依赖 Phase 2 的表格分块框架
- Phase 6 需等待所有功能完成

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US-1 表格完整性 | 表格不被切碎 | `test_table_not_fragmented` |
| US-2 跨页合并 | 相邻页相同表头表格合并 | `test_merge_adjacent_pages_same_header` |
| US-3 表头补充 | 超大表格每块含表头 | `test_large_table_has_header_in_each_chunk` |
| US-4 句子完整性 | 切分点在句子边界 | 现有 `_chunk_by_sentence` 测试 |
| US-5 层级保留 | metadata 含完整层级路径 | 现有 `_identify_headings` 测试 |

### 预计工作量

| Phase | 工作量 | 说明 |
|-------|--------|------|
| Phase 1 | 0.5 天 | 数据模型修改 |
| Phase 2 | 1.5 天 | Markdown 表格识别与测试 |
| Phase 3 | 2 天 | PDF 跨页合并与测试 |
| Phase 4 | 0.5 天 | 超大表格分块 |
| Phase 5 | 0.5 天 | 验证与增强 |
| Phase 6 | 1 天 | 集成测试与验收 |
| **总计** | **6 天** | - |
