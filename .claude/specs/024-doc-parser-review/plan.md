# Implementation Plan: Doc Parser 模块审查与改进

**Branch**: `024-doc-parser-review` | **Date**: 2026-04-24 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

改进 doc_parser 模块，解决 PDF 解析的多栏混排、页眉页脚污染、无边框表格识别失败等问题。主要工作包括：
1. PDF 版面分析（基于 pdfplumber 坐标）
2. 页眉页脚过滤
3. 表格分类器（规则优先）
4. 表格 Markdown 格式存储
5. Chunk 完整元数据挂载
6. 术语标准化（同义词词典）

MinerU 无边框表格解析作为可选能力，优先级较低（P2），可后续引入。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: pdfplumber (已有), python-docx (已有), camelot-py (新增可选)
**Storage**: SQLite (元数据), 向量库 (Chunk)
**Testing**: pytest
**Performance Goals**: PDF 解析速度不低于当前水平
**Constraints**:
- 不引入重依赖（layoutparser、MinerU 暂不引入）
- 保持现有 API 兼容性
- 遵循 CLAUDE.md 编码规范

## Constitution Check

- [x] **Library-First**: 复用 pdfplumber 的坐标信息，复用现有 SectionDetector、MdParser
- [x] **测试优先**: 每个功能模块有对应测试，使用 fixtures 构造测试样本
- [x] **简单优先**: 版面分析用坐标信息而非深度学习；表格分类用规则而非 CNN
- [x] **显式优于隐式**: 新增模块有明确接口；配置文件显式声明（synonyms.json）
- [x] **可追溯性**: 每个 Phase 回溯到 spec.md 的 User Story
- [x] **独立可测试**: 每个 User Story 可独立验证（验收场景明确）

## Project Structure

### Documentation

```text
.claude/specs/024-doc-parser-review/
├── spec.md          # 需求规格
├── research.md      # 技术调研
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/doc_parser/
├── models.py                          # 修改: PremiumTable.to_markdown()
├── pd/
│   ├── pdf_parser.py                  # 修改: 集成版面分析、页眉页脚过滤
│   ├── layout_analyzer.py             # 新增: 版面分析
│   ├── header_footer_filter.py        # 新增: 页眉页脚过滤
│   ├── table_classifier.py            # 新增: 表格分类器
│   └── data/
│       └── keywords.json              # 已有: 可扩展页眉页脚关键词
├── common/
│   ├── term_normalizer.py             # 新增: 术语标准化
│   └── data/
│       └── synonyms.json              # 新增: 同义词词典
└── tests/
    └── lib/doc_parser/
        ├── pd/
        │   ├── test_layout_analyzer.py      # 新增
        │   ├── test_header_footer_filter.py # 新增
        │   └── test_table_classifier.py     # 新增
        └── common/
            └── test_term_normalizer.py      # 新增
```

## Implementation Phases

### Phase 1: Setup

基础设施准备：数据模型扩展、依赖确认。

#### 实现步骤

1. **为 PremiumTable 添加 to_markdown() 方法**
   - 文件: `scripts/lib/doc_parser/models.py`
   - 代码示例:
   ```python
   @dataclass(frozen=True)
   class PremiumTable:
       raw_text: str
       data: List[List[str]]
       remark: str = ""
       section_type: str = "premium_table"
       page_number: Optional[int] = None
       bbox: Optional[Tuple[float, float, float, float]] = None
       table_index: Optional[int] = None

       def to_markdown(self) -> str:
           """转换为 Markdown 表格格式"""
           if not self.data:
               return ""
           lines = []
           headers = [str(cell).replace('\n', ' ') for cell in self.data[0]]
           lines.append("| " + " | ".join(headers) + " |")
           lines.append("| " + " | ".join("---" for _ in headers) + " |")
           for row in self.data[1:]:
               cells = [str(cell).replace('\n', ' ') for cell in row]
               while len(cells) < len(headers):
                   cells.append("")
               lines.append("| " + " | ".join(cells[:len(headers)]) + " |")
           if self.remark:
               lines.append(f"\n*{self.remark}*")
           return "\n".join(lines)

       def split_for_chunking(self, max_rows: int = 50) -> List['PremiumTable']:
           """将大表格分割为多个子表格，每个子表格携带表头"""
           if len(self.data) <= max_rows:
               return [self]
           result = []
           header = self.data[0]
           for i in range(1, len(self.data), max_rows - 1):
               chunk_data = [header] + self.data[i:i + max_rows - 1]
               result.append(PremiumTable(
                   raw_text="",
                   data=chunk_data,
                   remark=self.remark,
                   page_number=self.page_number,
                   bbox=self.bbox,
               ))
           return result
   ```

2. **创建同义词词典数据文件**
   - 文件: `scripts/lib/common/data/synonyms.json`
   - 代码示例:
   ```json
   {
       "被保险人": ["被保人", "投保对象", "保险标的人", "受保人", "被保方"],
       "理赔申请": ["索赔申请", "报案材料", "理赔资料", "出险申请", "理赔单"],
       "保险期间": ["保障期限", "保险年期", "有效期", "承保期", "保期"],
       "免责条款": ["责任免除", "除外责任", "不赔项目", "免赔条款", "除外条款"],
       "等待期": ["观察期", "缓冲期", "等待时间", "守候期"],
       "保费": ["保险费", "年保费", "月保费", "应缴保费"],
       "保额": ["保险金额", "基本保额", "保障金额"],
       "投保人": ["投保客户", "申请人", "要保人"]
   }
   ```

---

### Phase 2: Core - User Story 1 & 2 (P1) - PDF 版面分析与页眉页脚过滤

#### 需求回溯

→ 对应 spec.md User Story 1: PDF 多栏排版正确解析
→ 对应 spec.md User Story 2: 页眉页脚过滤

#### 实现步骤

1. **创建 LayoutAnalyzer 类 - 版面分析**
   - 文件: `scripts/lib/doc_parser/pd/layout_analyzer.py`
   - 代码示例:
   ```python
   from __future__ import annotations

   import logging
   from dataclasses import dataclass
   from typing import List, Tuple, Optional

   logger = logging.getLogger(__name__)


   @dataclass(frozen=True)
   class LayoutRegion:
       """版面区域"""
       region_type: str  # "body", "left_col", "right_col", "header", "footer"
       bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
       content: str = ""
       confidence: float = 1.0


   class LayoutAnalyzer:
       """PDF 版面分析器

       基于 pdfplumber 的字符坐标信息检测多栏结构和页眉页脚区域。
       """

       def __init__(
           self,
           column_gap_threshold: float = 30.0,
           header_region_ratio: float = 0.08,
           footer_region_ratio: float = 0.08,
       ):
           self.column_gap_threshold = column_gap_threshold
           self.header_region_ratio = header_region_ratio
           self.footer_region_ratio = footer_region_ratio

       def analyze(self, page) -> Tuple[str, List[LayoutRegion]]:
           """分析页面版面结构

           Returns:
               (reordered_text, regions): 重组后的文本和区域列表
           """
           chars = page.chars
           if not chars:
               return "", []

           page_width = page.width
           page_height = page.height

           # 检测多栏结构
           columns = self._detect_columns(chars, page_width)

           if len(columns) > 1:
               # 多栏：按列重组文本
               text = self._reconstruct_multi_column(chars, columns, page_height)
               regions = [
                   LayoutRegion(
                       region_type="left_col",
                       bbox=(0, 0, columns[0]['x1'], page_height),
                   ),
                   LayoutRegion(
                       region_type="right_col",
                       bbox=(columns[1]['x0'], 0, page_width, page_height),
                   ),
               ]
           else:
               # 单栏：正常提取
               text = page.extract_text() or ""
               regions = [LayoutRegion(
                   region_type="body",
                   bbox=(0, 0, page_width, page_height),
               )]

           return text, regions

       def _detect_columns(self, chars: List[dict], page_width: float) -> List[dict]:
           """检测多栏结构

           通过统计字符 x 坐标分布，寻找中间空白区域（栏间分隔）。
           """
           if not chars:
               return []

           # 统计每个 x 位置的字符密度
           x_positions = [c['x0'] for c in chars]
           min_x = min(x_positions)
           max_x = max(x_positions)

           # 将页面分为 20 个区间
           num_bins = 20
           bin_width = (max_x - min_x) / num_bins
           bins = [0] * num_bins

           for x in x_positions:
               bin_idx = int((x - min_x) / bin_width)
               bin_idx = min(bin_idx, num_bins - 1)
               bins[bin_idx] += 1

           # 寻找中间的空白区间（字符密度 < 平均密度的 10%）
           avg_density = sum(bins) / num_bins
           threshold = avg_density * 0.1

           gaps = []
           for i in range(1, num_bins - 1):
               if bins[i] < threshold and bins[i-1] >= threshold and bins[i+1] >= threshold:
                   gap_center = min_x + (i + 0.5) * bin_width
                   # 只考虑页面中间 30%-70% 区域的空白
                   if 0.3 * page_width < gap_center < 0.7 * page_width:
                       gaps.append(gap_center)

           if len(gaps) == 1:
               # 检测到双栏
               gap = gaps[0]
               return [
                   {'x0': min_x, 'x1': gap - self.column_gap_threshold},
                   {'x0': gap + self.column_gap_threshold, 'x1': max_x},
               ]

           return [{'x0': min_x, 'x1': max_x}]

       def _reconstruct_multi_column(
           self,
           chars: List[dict],
           columns: List[dict],
           page_height: float,
       ) -> str:
           """按多栏逻辑顺序重组文本"""
           left_chars = [c for c in chars if c['x0'] < columns[1]['x0']]
           right_chars = [c for c in chars if c['x0'] >= columns[1]['x0']]

           left_text = self._chars_to_text(left_chars)
           right_text = self._chars_to_text(right_chars)

           return left_text + "\n\n" + right_text

       def _chars_to_text(self, chars: List[dict]) -> str:
           """将字符列表转换为文本"""
           if not chars:
               return ""

           # 按 y 坐标分行，再按 x 坐标排序
           lines = {}
           y_tolerance = 3.0
           for c in chars:
               y_key = round(c['top'] / y_tolerance) * y_tolerance
               if y_key not in lines:
                   lines[y_key] = []
               lines[y_key].append(c)

           sorted_lines = []
           for y in sorted(lines.keys(), reverse=True):
               line_chars = sorted(lines[y], key=lambda c: c['x0'])
               line_text = ''.join(c['text'] for c in line_chars)
               sorted_lines.append(line_text)

           return '\n'.join(sorted_lines)
   ```

2. **创建 HeaderFooterFilter 类 - 页眉页脚过滤**
   - 文件: `scripts/lib/doc_parser/pd/header_footer_filter.py`
   - 代码示例:
   ```python
   from __future__ import annotations

   import logging
   import re
   from dataclasses import dataclass
   from typing import List, Tuple

   logger = logging.getLogger(__name__)


   @dataclass(frozen=True)
   class FilterConfig:
       """过滤配置"""
       header_patterns: Tuple[str, ...] = (
           "内部资料", "严禁外传", "仅供内部使用", "保密",
       )
       footer_patterns: Tuple[str, ...] = (
           r"第\s*\d+\s*页", r"Page\s*\d+", r"共\s*\d+\s*页",
           r"\d+\s*/\s*\d+",
       )
       header_max_length: int = 60
       footer_max_length: int = 40


   class HeaderFooterFilter:
       """页眉页脚过滤器"""

       def __init__(
           self,
           config: FilterConfig = None,
           header_region_ratio: float = 0.08,
           footer_region_ratio: float = 0.08,
       ):
           self.config = config or FilterConfig()
           self.header_region_ratio = header_region_ratio
           self.footer_region_ratio = footer_region_ratio

       def filter(self, page) -> str:
           """过滤页眉页脚，返回清洁文本"""
           text = page.extract_text() or ""
           lines = text.split('\n')
           page_height = page.height

           if not lines:
               return ""

           # 获取每行的 y 坐标
           line_positions = self._get_line_positions(page)

           filtered_lines = []
           for i, line in enumerate(lines):
               stripped = line.strip()
               if not stripped:
                   continue

               y_pos = line_positions[i] if i < len(line_positions) else page_height / 2

               # 检查是否为页眉（顶部区域）
               if y_pos > page_height * (1 - self.header_region_ratio):
                   if self._is_header(stripped):
                       logger.debug(f"过滤页眉: {stripped[:30]}")
                       continue

               # 检查是否为页脚（底部区域）
               if y_pos < page_height * self.footer_region_ratio:
                   if self._is_footer(stripped):
                       logger.debug(f"过滤页脚: {stripped[:30]}")
                       continue

               filtered_lines.append(stripped)

           return '\n'.join(filtered_lines)

       def _get_line_positions(self, page) -> List[float]:
           """获取每行的 y 坐标（从 chars 中提取）"""
           chars = page.chars
           if not chars:
               return []

           # 按 y 坐标分组
           lines_by_y = {}
           y_tolerance = 3.0
           for c in chars:
               y_key = round(c['top'] / y_tolerance) * y_tolerance
               if y_key not in lines_by_y:
                   lines_by_y[y_key] = []
               lines_by_y[y_key].append(c['text'])

           return sorted(lines_by_y.keys(), reverse=True)

       def _is_header(self, line: str) -> bool:
           """检测是否为页眉"""
           if len(line) > self.config.header_max_length:
               return False
           for pattern in self.config.header_patterns:
               if pattern in line:
                   return True
           return False

       def _is_footer(self, line: str) -> bool:
           """检测是否为页脚"""
           if len(line) > self.config.footer_max_length:
               return False
           for pattern in self.config.footer_patterns:
               if re.search(pattern, line, re.IGNORECASE):
                   return True
           return False
   ```

3. **修改 PdfParser 集成版面分析和过滤**
   - 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
   - 修改 `_extract_clauses` 和 `_extract_special_sections` 方法
   - 代码示例:
   ```python
   # 在 __init__ 中添加
   from .layout_analyzer import LayoutAnalyzer
   from .header_footer_filter import HeaderFooterFilter

   def __init__(self, section_detector: Optional[SectionDetector] = None):
       self.detector = section_detector or SectionDetector()
       self.layout_analyzer = LayoutAnalyzer()
       self.header_footer_filter = HeaderFooterFilter()

   # 修改 _extract_clauses
   def _extract_clauses(self, pages: List, warnings: List[str]) -> List[Clause]:
       clauses_dict: Dict[str, Clause] = {}
       pending_number: Optional[str] = None
       pending_title: Optional[str] = None
       pending_content: List[str] = []
       pending_page: int = 1

       for page_idx, page in enumerate(pages):
           # 版面分析
           reordered_text, regions = self.layout_analyzer.analyze(page)

           # 页眉页脚过滤
           clean_text = self.header_footer_filter.filter(page)

           # 如果版面分析改变了文本，使用重组后的文本
           if reordered_text and len(reordered_text) > len(clean_text) * 0.8:
               text = reordered_text
           else:
               text = clean_text

           lines = text.split('\n')
           # ... 后续处理不变
   ```

4. **编写测试**
   - 文件: `scripts/tests/lib/doc_parser/pd/test_layout_analyzer.py`
   - 文件: `scripts/tests/lib/doc_parser/pd/test_header_footer_filter.py`

---

### Phase 3: Core - User Story 4 & 5 (P1) - 表格分类器与 Markdown 存储

#### 需求回溯

→ 对应 spec.md User Story 4: 无边框表格智能解析
→ 对应 spec.md User Story 5: 表格存储格式标准化

#### 实现步骤

1. **创建 TableClassifier 类 - 表格类型分类**
   - 文件: `scripts/lib/doc_parser/pd/table_classifier.py`
   - 代码示例:
   ```python
   from __future__ import annotations

   import logging
   from dataclasses import dataclass
   from typing import List, Tuple, Optional

   logger = logging.getLogger(__name__)


   @dataclass(frozen=True)
   class TableClassification:
       """表格分类结果"""
       table_type: str  # "bordered", "borderless", "unknown"
       confidence: float
       bbox: Tuple[float, float, float, float]


   class TableClassifier:
       """表格类型分类器

       基于边框线检测判断表格类型。
       """

       def __init__(self, border_threshold: float = 0.5):
           self.border_threshold = border_threshold

       def classify(self, table) -> TableClassification:
           """分类表格类型"""
           bbox = getattr(table, 'bbox', (0, 0, 0, 0))

           # 检查是否有明确的边框
           # pdfplumber 的 table 对象有 edges 属性
           edges = getattr(table, 'edges', None)

           if edges is not None:
               # 统计边框线数量
               edge_count = len(edges) if isinstance(edges, list) else 0
               if edge_count >= 8:  # 至少有 8 条边框线（4 外框 + 4 内部）
                   return TableClassification(
                       table_type="bordered",
                       confidence=0.9,
                       bbox=bbox,
                   )

           # 检查 bbox 是否清晰
           if bbox and (bbox[2] - bbox[0]) > 0 and (bbox[3] - bbox[1]) > 0:
               # 有明确的边界框，可能是隐藏边框的表格
               return TableClassification(
                   table_type="bordered",
                   confidence=0.7,
                   bbox=bbox,
               )

           return TableClassification(
               table_type="unknown",
               confidence=0.5,
               bbox=bbox,
           )

       def has_borders(self, table) -> bool:
           """判断是否有边框"""
           result = self.classify(table)
           return result.table_type == "bordered" and result.confidence >= self.border_threshold
   ```

2. **修改 PdfParser 使用 TableClassifier**
   - 文件: `scripts/lib/doc_parser/pd/pdf_parser.py`
   - 修改 `_extract_premium_tables` 方法
   - 代码示例:
   ```python
   from .table_classifier import TableClassifier

   def __init__(self, section_detector: Optional[SectionDetector] = None):
       self.detector = section_detector or SectionDetector()
       self.layout_analyzer = LayoutAnalyzer()
       self.header_footer_filter = HeaderFooterFilter()
       self.table_classifier = TableClassifier()

   def _extract_premium_tables(self, pages: List, warnings: List[str]) -> List[PremiumTable]:
       premium_tables: List[PremiumTable] = []

       for page_idx, page in enumerate(pages):
           tables = page.find_tables()

           for table_idx, table in enumerate(tables):
               # 分类表格类型
               classification = self.table_classifier.classify(table)

               rows = table.extract()
               if not rows:
                   continue

               header = [str(cell or '').strip() for cell in rows[0]]
               if self.detector.is_premium_table(header):
                   raw_text = '\n'.join(
                       '\t'.join(str(cell or '') for cell in row)
                       for row in rows
                   )
                   data = [[str(cell or '') for cell in row] for row in rows]
                   bbox = getattr(table, 'bbox', None)

                   premium_tables.append(PremiumTable(
                       raw_text=raw_text,
                       data=data,
                       page_number=page_idx + 1,
                       bbox=bbox,
                       table_index=table_idx,
                   ))

                   # 记录表格类型信息
                   if classification.table_type == "borderless":
                       warnings.append(
                           f"Page {page_idx + 1} table {table_idx} 可能是无边框表格"
                       )

       return premium_tables
   ```

3. **编写测试**
   - 文件: `scripts/tests/lib/doc_parser/pd/test_table_classifier.py`

---

### Phase 4: Core - User Story 6 (P1) - Chunk 元数据挂载

#### 需求回溯

→ 对应 spec.md User Story 6: Chunk 元数据挂载

#### 实现步骤

1. **扩展 AuditDocument 添加 Chunk 生成方法**
   - 文件: `scripts/lib/doc_parser/models.py`
   - 代码示例:
   ```python
   from datetime import datetime
   from typing import Dict, Any, Optional

   @dataclass(frozen=True)
   class ChunkMetadata:
       """Chunk 元数据"""
       doc_id: str
       doc_name: str
       doc_type: str
       section_path: str
       section_level: int
       chunk_index: int
       char_count: int
       is_key_clause: bool
       has_table: bool
       prev_chunk_id: Optional[str]
       next_chunk_id: Optional[str]
       parse_confidence: float
       update_time: str

       def to_dict(self) -> Dict[str, Any]:
           return {
               'doc_id': self.doc_id,
               'doc_name': self.doc_name,
               'doc_type': self.doc_type,
               'section_path': self.section_path,
               'section_level': self.section_level,
               'chunk_index': self.chunk_index,
               'char_count': self.char_count,
               'is_key_clause': self.is_key_clause,
               'has_table': self.has_table,
               'prev_chunk_id': self.prev_chunk_id,
               'next_chunk_id': self.next_chunk_id,
               'parse_confidence': self.parse_confidence,
               'update_time': self.update_time,
           }


   @dataclass(frozen=True)
   class AuditDocument:
       # ... 现有字段 ...

       def get_chunk_metadata(
           self,
           section_path: str,
           chunk_index: int,
           is_key_clause: bool = False,
           has_table: bool = False,
           prev_chunk_id: Optional[str] = None,
           next_chunk_id: Optional[str] = None,
       ) -> ChunkMetadata:
           """生成 Chunk 元数据"""
           doc_id = self.file_name.replace('.', '_')
           doc_type = "insurance_contract" if self.file_type in ['.pdf', '.docx'] else "unknown"

           char_count = sum(
               len(c.text) for c in self.clauses
           ) + sum(
               len(pt.raw_text) for pt in self.premium_tables
           )

           return ChunkMetadata(
               doc_id=doc_id,
               doc_name=self.file_name,
               doc_type=doc_type,
               section_path=section_path,
               section_level=section_path.count('>') + 1,
               chunk_index=chunk_index,
               char_count=char_count,
               is_key_clause=is_key_clause,
               has_table=has_table,
               prev_chunk_id=prev_chunk_id,
               next_chunk_id=next_chunk_id,
               parse_confidence=0.95,  # PDF 解析默认高置信度
               update_time=self.parse_time.isoformat(),
           )
   ```

2. **为 Clause 和 PremiumTable 添加元数据支持**
   - 文件: `scripts/lib/doc_parser/models.py`
   - 添加 `doc_id`、`section_path` 等可选字段

---

### Phase 5: Enhancement - User Story 7 (P2) - 术语标准化

#### 需求回溯

→ 对应 spec.md User Story 7: 术语标准化处理

#### 实现步骤

1. **创建 TermNormalizer 类 - 术语标准化**
   - 文件: `scripts/lib/common/term_normalizer.py`
   - 代码示例:
   ```python
   from __future__ import annotations

   import json
   import logging
   import re
   from pathlib import Path
   from typing import Dict, List, Set

   logger = logging.getLogger(__name__)


   class TermNormalizer:
       """保险术语标准化器"""

       def __init__(self, synonyms_path: Optional[str] = None):
           if synonyms_path:
               config_path = Path(synonyms_path)
           else:
               config_path = Path(__file__).parent / 'data' / 'synonyms.json'

           self.synonym_to_standard: Dict[str, str] = {}
           self.standard_terms: Set[str] = set()

           try:
               with open(config_path, 'r', encoding='utf-8') as f:
                   synonyms_dict: Dict[str, List[str]] = json.load(f)

               for standard, synonyms in synonyms_dict.items():
                   self.standard_terms.add(standard)
                   for syn in synonyms:
                       self.synonym_to_standard[syn] = standard

           except FileNotFoundError:
               logger.warning(f"同义词词典不存在: {config_path}")
           except json.JSONDecodeError as e:
               logger.error(f"同义词词典解析失败: {e}")

       def normalize(self, text: str) -> str:
           """将文本中的同义词替换为标准术语"""
           if not text:
               return text

           result = text
           for syn, standard in sorted(
               self.synonym_to_standard.items(),
               key=lambda x: len(x[0]),
               reverse=True  # 先替换长词
           ):
               if syn in result:
                   result = result.replace(syn, standard)

           return result

       def normalize_query(self, query: str) -> str:
           """标准化用户查询"""
           return self.normalize(query)

       def normalize_chunk(self, chunk_text: str) -> str:
           """标准化 Chunk 文本"""
           return self.normalize(chunk_text)

       def get_standard_term(self, term: str) -> str:
           """获取标准术语"""
           if term in self.standard_terms:
               return term
           return self.synonym_to_standard.get(term, term)
   ```

2. **编写测试**
   - 文件: `scripts/tests/lib/common/test_term_normalizer.py`

---

### Phase 6: Enhancement - User Story 3 (P2) - 扫描件 OCR（可选）

#### 需求回溯

→ 对应 spec.md User Story 3: 扫描件 OCR 质量优化

#### 实现步骤

**此功能标记为可选**，当前版本暂不实现。原因：
- 现有代码已有 OCR 能力（通过 LLM）
- 图像预处理和水印去除需要额外依赖（OpenCV、PIL）
- U-Net 模型训练成本高

**未来实现方向**：
1. 图像清晰度检测（拉普拉斯方差）
2. 低分辨率预处理（CLAHE、双边滤波）
3. 水印检测和去除（可选，需模型）

---

---

### Phase 7: Integration Test - 真实文档验证

使用 `/Users/plain/work/actuary-assets/products/` 目录下的真实保险产品文档进行集成测试验证。

#### 测试文档清单

| 文档类型 | 文件名 | 预期验证点 |
|---------|--------|-----------|
| PDF | 《人保健康附加互联网恶性肿瘤特定药品费用医疗保险》条款.pdf | PDF 解析、条款提取、表格识别 |
| PDF | 《人保健康互联网手术医疗意外保险》保险条款.pdf | PDF 解析、条款提取 |
| PDF | 《人保健康互联网团体意外伤害保险（2025版）》条款.pdf | PDF 解析、多栏检测、页眉页脚过滤 |
| DOCX | 《人保健康城市定制型团体医疗保险（A款）》产品条款.docx | Word 解析、条款提取 |
| DOCX | 《人保健康附加团体终身重度恶性肿瘤疾病保险》条款.docx | Word 解析、表格提取 |

#### 实现步骤

1. **创建集成测试脚本**
   - 文件: `scripts/tests/lib/doc_parser/test_integration_real_docs.py`
   - 代码示例:
   ```python
   import pytest
   from pathlib import Path
   from lib.doc_parser import parse_product_document

   # 真实文档目录
   PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")


   @pytest.fixture
   def real_pdf_files():
       """真实 PDF 文件列表"""
       return list(PRODUCTS_DIR.glob("*.pdf"))


   @pytest.fixture
   def real_docx_files():
       """真实 DOCX 文件列表"""
       return list(PRODUCTS_DIR.glob("*.docx"))


   class TestRealDocuments:
       """真实文档集成测试"""

       def test_parse_real_pdfs(self, real_pdf_files):
           """测试解析真实 PDF 文件"""
           for pdf_path in real_pdf_files:
               doc = parse_product_document(str(pdf_path))
               assert doc.file_type == '.pdf'
               assert doc.file_name == pdf_path.name
               # 至少提取到一些内容
               total_content = (
                   len(doc.clauses) +
                   len(doc.premium_tables) +
                   len(doc.notices) +
                   len(doc.exclusions)
               )
               assert total_content > 0, f"{pdf_path.name} 未提取到任何内容"
               # 记录解析结果
               print(f"\n{pdf_path.name}:")
               print(f"  条款: {len(doc.clauses)}")
               print(f"  费率表: {len(doc.premium_tables)}")
               print(f"  告知事项: {len(doc.notices)}")
               print(f"  责任免除: {len(doc.exclusions)}")
               print(f"  Warnings: {len(doc.warnings)}")

       def test_parse_real_docx_files(self, real_docx_files):
           """测试解析真实 DOCX 文件"""
               for docx_path in real_docx_files:
                   doc = parse_product_document(str(docx_path))
                   assert doc.file_type == '.docx'
                   assert doc.file_name == docx_path.name
                   total_content = (
                       len(doc.clauses) +
                       len(doc.premium_tables)
                   )
                   assert total_content > 0, f"{docx_path.name} 未提取到任何内容"

       def test_premium_table_markdown(self, real_pdf_files):
           """测试费率表 Markdown 输出"""
           for pdf_path in real_pdf_files:
               doc = parse_product_document(str(pdf_path))
               for table in doc.premium_tables:
                   md = table.to_markdown()
                   assert md.startswith("|"), "Markdown 表格应以 | 开头"
                   assert "---" in md, "Markdown 表格应包含分隔行"

       def test_no_header_footer_in_content(self, real_pdf_files):
           """验证页眉页脚被过滤"""
           header_patterns = ["内部资料", "严禁外传"]
           footer_patterns = ["第", "页"]

           for pdf_path in real_pdf_files:
               doc = parse_product_document(str(pdf_path))
               all_text = "\n".join(c.text for c in doc.clauses)

               # 检查是否存在明显的页眉页脚污染
               for pattern in header_patterns:
                   count = all_text.count(pattern)
                   if count > 3:  # 允许少量出现（可能是正文内容）
                       doc.warnings.append(f"可能的页眉残留: '{pattern}' 出现 {count} 次")

               for pattern in footer_patterns:
                   # 页脚格式通常是 "第 X 页"，检查是否有连续出现
                   import re
                   matches = re.findall(r'第\s*\d+\s*页', all_text)
                   if len(matches) > 3:
                       doc.warnings.append(f"可能的页脚残留: '第 X 页' 出现 {len(matches)} 次")
   ```

2. **运行集成测试**
   ```bash
   pytest scripts/tests/lib/doc_parser/test_integration_real_docs.py -v
   ```

3. **分析测试结果，记录问题**
   - 统计各文档的解析成功率
   - 记录 warnings 列表
   - 识别需要人工处理的边界情况

#### 验收标准

- 所有 PDF 文件解析成功（无异常）
- 所有 DOCX 文件解析成功（无异常）
- 条款提取数量 > 0
- 费率表 Markdown 格式正确
- 页眉页脚过滤效果可验证（warnings 可追溯）

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | 所有方案均选择最简实现：版面分析用坐标而非 ML，表格分类用规则而非 CNN，MinerU 暂不引入 | - |

---

## Appendix

### 执行顺序建议

```
Phase 1 (Setup) ─┬─> Phase 2 (版面分析+页眉页脚)
                 │
                 └─> Phase 3 (表格分类+Markdown)

Phase 4 (元数据) ─> 依赖 Phase 2, 3 完成

Phase 5 (术语标准化) ─> 独立，可并行

Phase 6 (OCR) ─> 可选，优先级低

Phase 7 (集成测试) ─> 所有 Phase 完成后执行
```

推荐执行顺序：
1. Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 7
2. Phase 6 可后续单独迭代

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 PDF 多栏排版 | 双栏 PDF 解析后左右栏分离 | test_layout_analyzer.py |
| US2 页眉页脚过滤 | 过滤后无"内部资料"、"第X页"等 | test_header_footer_filter.py |
| US4 表格分类 | 正确区分有边框/无边框表格 | test_table_classifier.py |
| US5 Markdown 存储 | PremiumTable.to_markdown() 输出正确格式 | test_pdf_parser.py |
| US6 元数据挂载 | Chunk 携带完整元数据 | test_pdf_parser.py |
| US7 术语标准化 | "被保人" → "被保险人" | test_term_normalizer.py |
| US3 OCR 优化 | 可选，暂不测试 | - |
| 集成测试 | 真实文档解析成功率 > 95% | test_integration_real_docs.py |
