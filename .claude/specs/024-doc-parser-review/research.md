# Doc Parser 模块审查与改进 - 技术调研报告

生成时间: 2026-04-24 10:30:00
源规格: .claude/specs/024-doc-parser-review/spec.md

## 执行摘要

对 actuary-sleuth 的 doc_parser 模块进行了深入的代码审查。模块整体架构清晰，分为 pd（产品文档）和 kb（知识库）两个子模块。**主要发现**：PDF 解析器存在多栏混排、页眉页脚污染、无边框表格识别失败等问题；没有扫描件 OCR 支持；表格存储格式非 Markdown；术语标准化功能缺失。**技术选型建议**：采用 pdfplumber 坐标信息实现版面分析；表格分类器先用规则后考虑 ML；引入 MinerU 处理无边框表格。**风险**：MinerU 需要单独部署，引入成本较高。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 PDF 版面分析 | `pd/pdf_parser.py` | ❌ 需新增 — 当前仅按行提取文本 |
| FR-002 页眉页脚过滤 | `pd/pdf_parser.py` | ❌ 需新增 — 无过滤机制 |
| FR-003 扫描件预处理 | 无 | ❌ 需新增 — 无 OCR 支持 |
| FR-004 水印去除 | 无 | ❌ 需新增 — 无此功能 |
| FR-005 表格分类器 | `pd/pdf_parser.py:_extract_premium_tables` | ⚠️ 需修改 — 依赖 pdfplumber find_tables()，仅识别有边框表格 |
| FR-006 无边框表格解析 | 无 | ❌ 需新增 — find_tables() 对无边框表格无效 |
| FR-007 表格 Markdown 存储 | `models.py:PremiumTable` | ⚠️ 需修改 — 当前使用 raw_text + data 二维数组 |
| FR-008 Chunk 元数据 | `kb/md_parser.py`, `models.py` | ✅ 已有 — md_parser 有完善元数据；pd 模块仅部分支持 |
| FR-009 同义词词典 | 无 | ❌ 需新增 |
| FR-010 术语标准化 | 无 | ❌ 需新增 |
| FR-011 数字日期格式统一 | 无 | ❌ 需新增 |

### 1.2 可复用组件

- `SectionDetector` (`pd/section_detector.py`): 内容类型检测器，支持条款编号识别、费率表检测、特殊章节识别
- `MdParser` (`kb/md_parser.py`): Markdown 分块器，支持多策略层级识别、递归切分、语义完整性检查、智能 overlap
- `DocumentMeta` (`models.py`): 文档元数据模型，支持 YAML frontmatter 解析、元数据转换
- `Clause` / `PremiumTable` / `DocumentSection` (`models.py`): 数据模型，frozen dataclass 设计
- `separate_title_and_text` (`pd/utils.py`): 条款标题和正文分离

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `pd/pdf_parser.py` | 修改 | 添加版面分析、页眉页脚过滤、多栏处理 |
| `pd/layout_analyzer.py` | 新增 | 版面分析：多栏检测、区域分类 |
| `pd/header_footer_filter.py` | 新增 | 页眉页脚识别和过滤 |
| `pd/table_classifier.py` | 新增 | 表格类型分类器 |
| `pd/table_parser.py` | 新增 | 无边框表格解析（调用 MinerU） |
| `models.py` | 修改 | PremiumTable 添加 to_markdown() 方法 |
| `common/term_normalizer.py` | 新增 | 术语标准化处理 |
| `common/data/synonyms.json` | 新增 | 保险领域同义词词典 |

---

## 二、技术选型研究

### 2.1 PDF 版面分析方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| pdfplumber 坐标分析 | 轻量、无额外依赖、速度快 | 仅支持简单版面、无深度学习 | 简单多栏、页眉页脚识别 | ✅ 优先 |
| layoutparser | 精确、支持复杂版面 | 重依赖、需模型、速度慢 | 复杂报纸杂志版面 | ⏳ 备选 |
| unstructured.io | 功能全面、API 友好 | 云服务依赖或本地部署复杂 | 企业级文档处理 | ❌ 过重 |

**推荐策略**: 先用 pdfplumber 坐标信息实现基础版面分析，满足大多数保险文档场景。对于极少数复杂版面，记录 warning 提示人工处理。

### 2.2 表格分类方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 规则判断（边框线检测） | 简单、快速、无依赖 | 可能误判 | 边框清晰的表格 | ✅ 优先 |
| CNN 图像分类 | 准确、可处理模糊边框 | 需训练数据、推理开销 | 混合表格类型 | ⏳ 备选 |
| 大模型判断 | 无需训练、泛化强 | 成本高、延迟大 | 少量复杂 case | ❌ 成本过高 |

**推荐策略**: 先用 pdfplumber 的 table.bbox 判断是否有边框线。如果 bbox 边界清晰且有边框线，调用 camelot/pdfplumber 提取；否则标记为无边框表格，调用 MinerU。

### 2.3 无边框表格解析方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| MinerU (Table Transformer) | 准确率高、专为此设计 | 需单独部署、推理慢 (300ms/页) | 无边框表格 | ✅ 推荐 |
| Camelot lattice | 快速 (80ms/页) | 仅支持有边框表格 | 有边框表格 | ✅ 并用 |
| pdfplumber find_tables | 快速、内置 | 仅支持有边框表格 | 简单有边框表格 | ✅ 当前方案 |
| PaddleOCR Table | 准确、支持中文 | 需 PaddlePaddle 环境 | OCR 场景 | ⏳ 可选 |

**推荐策略**:
1. 用 pdfplumber/camelot 处理有边框表格（快速）
2. 对无边框表格调用 MinerU（准确但慢）
3. 通过分类器判断表格类型，避免全量使用 MinerU

### 2.4 表格存储格式对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| Markdown 表格 | LLM 理解好、人工可读 | 大表格分割麻烦 | 向量库存储 | ✅ 推荐 |
| JSON | 结构化、程序处理方便 | LLM 理解不稳定 | API 返回 | ❌ 不推荐 |
| 自然语言描述 | LLM 处理最稳定 | 丢失结构、冗长 | 简单表格 | ❌ 不推荐 |

**推荐策略**: 为 PremiumTable 添加 `to_markdown()` 方法，返回 Markdown 格式字符串。大表格分割时每个子 Chunk 携带表头。

### 2.5 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| pdfplumber | 已有 | PDF 文本提取、表格检测 | ✅ |
| python-docx | 已有 | Word 文档解析 | ✅ |
| camelot-py[cv] | 需新增 | 表格提取（有边框） | ⚠️ 需要 OpenCV |
| MinerU | 需新增 | 无边框表格解析 | ⚠️ 需单独部署 |
| layoutparser | 可选 | 复杂版面分析 | ⚠️ 重依赖 |

---

## 三、数据流分析

### 3.1 现有数据流

```
PDF 文件 → pdfplumber.open()
         → pages 遍历
         → page.extract_text() (按行提取，无版面分析)
         → 条款识别 (_extract_clauses)
         → 表格提取 (_extract_premium_tables, find_tables)
         → AuditDocument (clauses, premium_tables, ...)
```

```
DOCX 文件 → Document(file_path)
          → tables 提取条款
          → paragraphs 提取章节
          → SectionDetector 识别类型
          → AuditDocument
```

```
Markdown 文件 → MdParser.parse_document()
              → YAML frontmatter 提取
              → 多策略标题识别
              → 递归切分
              → 元数据挂载
              → List[TextNode]
```

### 3.2 新增/变更的数据流

```
新增 PDF 版面分析:
PDF 文件 → pdfplumber.open()
         → pages 遍历
         → LayoutAnalyzer.analyze(page)  ← 新增
           - 检测多栏结构
           - 识别页眉页脚区域
           - 按逻辑顺序重组文本
         → HeaderFooterFilter.filter(text, regions)  ← 新增
         → 正常提取流程...

新增表格分类和解析:
pages → TableClassifier.classify(page, tables)  ← 新增
      - 判断有边框/无边框
      → 有边框: pdfplumber/camelot 提取
      → 无边框: MinerU 解析  ← 新增
      → to_markdown() 格式化  ← 新增
      → PremiumTable

新增术语标准化:
Chunk 文本 → TermNormalizer.normalize(text, synonym_dict)  ← 新增
           → 标准化后的文本
```

### 3.3 关键数据结构

```python
# 新增: 版面区域
@dataclass(frozen=True)
class LayoutRegion:
    region_type: str  # "title", "body", "left_col", "right_col", "header", "footer"
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    content: str
    confidence: float = 1.0

# 新增: 表格分类结果
@dataclass(frozen=True)
class TableClassification:
    table_type: str  # "bordered", "borderless", "unknown"
    confidence: float
    bbox: Tuple[float, float, float, float]

# 修改: PremiumTable 添加 Markdown 支持
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
        # 表头
        lines.append("| " + " | ".join(str(cell) for cell in self.data[0]) + " |")
        # 分隔行
        lines.append("| " + " | ".join("---" for _ in self.data[0]) + " |")
        # 数据行
        for row in self.data[1:]:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
        return "\n".join(lines)

# 新增: 同义词词典结构
# 存储在 common/data/synonyms.json
{
    "被保险人": ["被保人", "投保对象", "保险标的人", "受保人"],
    "理赔申请": ["索赔申请", "报案材料", "理赔资料"],
    "保险期间": ["保障期限", "保险年期", "有效期", "承保期"],
    ...
}
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] pdfplumber 的 char 坐标信息能否准确判断多栏结构？验证方式：准备 10 个双栏 PDF 样本，统计判断准确率
- [ ] 页眉页脚的位置规律是否稳定？验证方式：分析 50 个保险 PDF 的页眉页脚位置分布
- [ ] MinerU 对中文保险表格的支持程度？验证方式：准备 20 个无边框表格样本，测试解析准确率
- [ ] 大表格分割后携带表头，LLM 能否正确理解上下文？验证方式：构造测试用例，让 LLM 回答跨 Chunk 问题

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| MinerU 部署复杂，团队不熟悉 | 高 | 高 | 先用规则方案，积累数据后再引入 |
| pdfplumber 版面分析不准确 | 中 | 中 | 添加 fallback：记录 warning，保留原始文本 |
| 无边框表格分类器误判 | 中 | 高 | 保守策略：不确定时调用 MinerU |
| 术语标准化误替换 | 低 | 中 | 同义词词典需要人工审核；特殊上下文不替换 |
| 页眉页脚过滤误删正文 | 中 | 高 | 设置高阈值；低置信度时保留原文 |

---

## 五、现有代码问题详解

### 5.1 PDF 多栏排版问题 (pdf_parser.py:82-109)

**问题代码**:
```python
def _extract_clauses(self, pages: List, warnings: List[str]) -> List[Clause]:
    for page_idx, page in enumerate(pages):
        text = page.extract_text() or ''  # 按行提取，不区分左右栏
        lines = text.split('\n')
        for line in lines:
            # ... 直接处理每行
```

**问题分析**:
- `page.extract_text()` 返回的是按阅读顺序（从上到下、从左到右）提取的文本
- 对于双栏排版，会先提取左栏第一行，再提取右栏第一行，导致左右内容混在一起
- 影响：条款编号和内容错位，语义混乱

**改进方案**:
```python
def _extract_clauses_with_layout(self, page) -> str:
    """按版面逻辑顺序提取文本"""
    chars = page.chars  # 获取每个字符的坐标

    # 按行分组
    lines = self._group_chars_by_y(chars)

    # 检测多栏结构
    columns = self._detect_columns(lines)

    if len(columns) > 1:
        # 多栏：按列重组
        return self._reconstruct_multi_column(columns)
    else:
        # 单栏：正常提取
        return page.extract_text()

def _detect_columns(self, lines: List) -> List[List]:
    """检测多栏结构"""
    # 统计 x 坐标分布，寻找分隔点
    all_x = []
    for line in lines:
        for char in line:
            all_x.append(char['x0'])

    # K-means 聚类或简单的中点分割
    # ...
```

### 5.2 页眉页脚污染问题 (pdf_parser.py:244-259)

**问题代码**:
```python
def _extract_special_sections(self, pages: List, warnings: List[str]) -> Dict[str, List[Any]]:
    for page in pages:
        text = page.extract_text() or ''  # 包含页眉页脚
        lines = text.split('\n')
        for line in lines:
            stripped = line.strip()
            # ... 直接处理，未过滤页眉页脚
```

**问题分析**:
- 每页的页眉（如"XX保险公司 内部资料"）和页脚（如"第 1 页/共 10 页"）都会混入文本
- 这些重复的无意义文本会进入 Chunk，影响向量检索

**改进方案**:
```python
def _filter_header_footer(self, page) -> str:
    """过滤页眉页脚"""
    text = page.extract_text() or ''
    lines = text.split('\n')

    # 获取页面尺寸
    page_height = page.height

    filtered_lines = []
    for line in lines:
        # 获取行的 y 坐标（需要从 chars 中获取）
        y_pos = self._get_line_y_position(page, line)

        # 页眉区域（顶部 5%）
        if y_pos > page_height * 0.95:
            if self._is_header_pattern(line):
                continue

        # 页脚区域（底部 5%）
        if y_pos < page_height * 0.05:
            if self._is_footer_pattern(line):
                continue

        filtered_lines.append(line)

    return '\n'.join(filtered_lines)

def _is_header_pattern(self, line: str) -> bool:
    """检测页眉特征"""
    patterns = ['内部资料', '严禁外传', '保险公司']
    return any(p in line for p in patterns) and len(line) < 50

def _is_footer_pattern(self, line: str) -> bool:
    """检测页脚特征"""
    import re
    return bool(re.match(r'第\s*\d+\s*页', line)) or \
           bool(re.match(r'Page\s*\d+', line, re.I))
```

### 5.3 无边框表格识别失败 (pdf_parser.py:202-228)

**问题代码**:
```python
def _extract_premium_tables(self, pages: List, warnings: List[str]) -> List[PremiumTable]:
    for page_idx, page in enumerate(pages):
        tables = page.find_tables()  # 仅识别有边框的表格
        for table_idx, table in enumerate(tables):
            rows = table.extract()
            # ...
```

**问题分析**:
- `pdfplumber.find_tables()` 依赖边框线检测表格
- 对于靠空格对齐的无边框表格，返回空列表
- 导致大量费率表无法提取

**改进方案**:
```python
def _extract_premium_tables(self, pages: List, warnings: List[str]) -> List[PremiumTable]:
    tables_result = []

    for page_idx, page in enumerate(pages):
        # 先尝试有边框表格
        bordered_tables = page.find_tables()

        for table in bordered_tables:
            rows = table.extract()
            if rows and self.detector.is_premium_table(rows[0]):
                tables_result.append(self._create_premium_table(rows, page_idx, table.bbox))

        # 检测无边框表格区域
        borderless_regions = self._detect_borderless_table_regions(page)

        for region in borderless_regions:
            # 调用 MinerU 解析
            try:
                md_table = self._parse_with_mineru(page, region)
                rows = self._parse_markdown_table(md_table)
                if rows and self.detector.is_premium_table(rows[0]):
                    tables_result.append(PremiumTable(
                        raw_text=md_table,
                        data=rows,
                        page_number=page_idx + 1,
                        bbox=region,
                    ))
            except Exception as e:
                warnings.append(f"无边框表格解析失败 (page {page_idx + 1}): {e}")

    return tables_result
```

### 5.4 表格非 Markdown 格式存储 (models.py:96-105)

**问题代码**:
```python
@dataclass(frozen=True)
class PremiumTable:
    raw_text: str              # 制表符分隔的文本
    data: List[List[str]]      # 二维数组
    remark: str = ""
    # ... 无 to_markdown 方法
```

**问题分析**:
- 向量库存储时直接使用 raw_text（制表符分隔）
- LLM 对 Markdown 表格理解更好
- 缺少格式转换能力

**改进方案**:
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
        headers = [str(cell) for cell in self.data[0]]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in self.data[1:]:
            cells = [str(cell).replace('\n', ' ') for cell in row]
            # 补齐列数
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
                raw_text="",  # 可按需生成
                data=chunk_data,
                remark=self.remark,
                page_number=self.page_number,
                bbox=self.bbox,
            ))
        return result
```

### 5.5 元数据不完整 (pdf_parser.py, models.py)

**问题分析**:
- `Clause` 和 `PremiumTable` 有 `page_number` 和 `bbox`，但缺少：
  - `doc_id` / `doc_name`
  - `section_path`（章节路径）
  - `chunk_index`
  - `is_key_clause`
  - `prev_chunk_id` / `next_chunk_id`
  - `parse_confidence`
  - `update_time`
- `AuditDocument` 没有为 Chunk 提供元数据生成方法

**对比 md_parser.py**:
```python
# md_parser.py 有完善的元数据生成
def _build_metadata(self, doc_meta, source_file, section_path, level, heading_text):
    metadata = doc_meta.to_chunk_metadata(section_path, source_file)
    metadata['section_path'] = section_path
    metadata['content_type'] = 'text'
    metadata['level'] = level
    # ...
```

**改进方案**:
为 `AuditDocument` 添加 Chunk 生成方法，复用 `md_parser` 的元数据逻辑。

---

## 六、参考实现

- [pdfplumber 文档](https://github.com/jsvine/pdfplumber) — 坐标信息获取、表格检测
- [MinerU](https://github.com/opendatalab/MinerU) — 无边框表格解析
- [layoutparser](https://github.com/Layout-Parser/layout-parser) — 深度学习版面分析
- [Camelot](https://github.com/camelot-dev/camelot) — 表格提取
- [unstructured.io](https://github.com/Unstructured-IO/unstructured) — 文档解析工具集
