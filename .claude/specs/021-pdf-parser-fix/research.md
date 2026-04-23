# PDF Parser Fix - 技术调研报告

生成时间: 2026-04-23 14:30:00
源规格: .claude/specs/021-pdf-parser-fix/spec.md

## 执行摘要

PDF 解析器存在严重的结构性缺陷：条款提取仅依赖表格，但保险产品 PDF 文档中条款内容实际分布在页面文本流中，而非表格结构。这导致 PDF 解析结果仅为 DOCX 的 1/10（7 条 vs 60 条）。核心修复策略是参照 DOCX 解析器的设计，从文本流中识别条款编号模式，重构条款提取逻辑。同时发现 `keywords.json` 配置文件缺失，需补充。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 标题层级识别 | `pdf_parser.py` | ❌ 仅从表格提取，无法识别文本流中的层级 |
| FR-002 条款文本提取 | `pdf_parser.py` | ❌ 仅提取表格行，丢失文本内容 |
| FR-003 表格解析 | `pdf_parser.py` | ⚠️ 表格识别正常，但内容不完整 |
| FR-004 接口兼容 | `parser.py`, `models.py` | ✅ 接口已统一 |
| FR-005 扫描版 PDF | 无 | ❌ 未实现 |
| FR-006 加密 PDF 提示 | `pdf_parser.py` | ❌ 未实现 |
| FR-007 PaddleOCR | 无 | ❌ 未实现 |

### 1.2 可复用组件

- `Clause`: 条款数据模型，可复用
- `PremiumTable`: 费率表数据模型，可复用
- `AuditDocument`: 文档输出结构，可复用
- `SectionDetector`: 章节检测器，可复用条款编号正则
- `separate_title_and_text()`: 标题/正文分离工具，可复用
- `parse_product_document()`: 编排器接口，可复用

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/doc_parser/pd/pdf_parser.py` | 重构 | 改为从文本流提取条款 |
| `scripts/lib/doc_parser/pd/data/keywords.json` | 新增 | Section 检测关键词配置 |
| `scripts/lib/doc_parser/pd/ocr_handler.py` | 新增 | 扫描版 PDF OCR 处理器 |
| `scripts/tests/lib/doc_parser/pd/test_pdf_parser.py` | 增强 | 真实文档测试 |

---

## 二、问题根因分析

### 2.1 真实文档解析对比

**DOCX 解析结果** (`《人保健康互联网重大疾病保险（A款）》条款V5.docx`):
```
条款数量: 60
示例条款:
  编号=1, 标题=被保险人范围
  编号=1.1, 标题=被保险人范围 凡投保时出生满28天...
  编号=2, 标题=保险责任及责任免除
  编号=2.1, 标题=保险期间 本合同保险期间为1年。
  编号=2.3.1, 标题=等待期设置
```

**PDF 解析结果** (`《人保健康互联网团体意外伤害保险（2025版）》条款.pdf`):
```
条款数量: 7
示例条款:
  编号=1, 标题=投保范围
  编号=2, 标题=保险责任及责任免除
  编号=3, 标题=合同效力
```

### 2.2 结构差异分析

**DOCX 文件结构**:
- 条款以表格形式存储
- 一个表格包含 163 行，每行对应一个条款
- 表格列: `[编号, 内容]`
- `DocxParser._extract_clauses()` 遍历表格所有行，正确提取

**PDF 文件结构** (pdfplumber 解析):
- `find_tables()` 仅识别到标题行表格
- 表格内容: `[['1', '投保范围']]` — 只有标题，无正文
- **实际条款内容在页面文本流中**:
  ```
  1 投保范围
  1.1 投保范围
  投保人可将团体7.1成员作为被保险人...
  2 保险责任及责任免除
  2.1 保险期间
  本合同的保险期间由投保人与本公司...
  2.3.1 基本部分
  意外伤害保险金 本合同保险责任...
  ```

### 2.3 PdfParser 核心问题

**当前实现** (`pdf_parser.py:79-106`):
```python
def _extract_clauses_from_tables(self, tables, ...):
    for table in tables:
        rows = table.extract()
        for row in rows:
            if self.detector.is_clause_table(row[0]):
                # 只处理表格中的行，无法获取文本流中的条款
                clauses.append(Clause(...))
```

**问题**:
1. 仅从表格提取条款，表格只包含标题行
2. `_extract_sections_from_page()` 处理文本，但逻辑是按章节类型（告知、免责等）分类，不是按条款结构
3. 没有识别文本流中的条款编号模式（1.1, 2.3.1 等）

### 2.4 配置文件缺失

**错误日志**:
```
关键词配置文件不存在: /.../doc_parser/pd/data/keywords.json，section 检测功能将不可用
```

**影响**:
- `SectionDetector` 无法识别告知事项、健康告知、责任免除等特殊章节
- `_extract_sections_from_page()` 功能失效

---

## 三、技术选型研究

### 3.1 条款提取方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| A: 纯表格提取（当前） | 简单 | PDF 表格不完整 | 仅适用于表格结构化的 PDF | ❌ |
| B: 纯文本流提取 | 覆盖完整 | 需处理复杂布局 | 适用于保险条款 PDF | ✅ |
| C: 表格+文本混合 | 兼顾两者 | 逻辑复杂 | 适用于混合结构 | ⚠️ 备选 |

**推荐方案 B**：参照 DOCX 解析器从文本流提取条款，同时保留表格提取作为补充。

### 3.2 条款编号识别策略

**文本流中的编号模式**:
```
1          → 一级标题
1.1        → 二级标题
1.1.1      → 三级标题
2.3.1      → 三级标题
第一条     → 中文格式
（一）     → 括号格式
```

**现有正则** (`section_detector.py:36-41`):
```python
CLAUSE_NUMBER_PATTERNS = [
    re.compile(r'^(\d+(?:\.\d+)*)\s*$'),  # 1, 1.2, 1.2.3
    re.compile(r'^第([' + _CN_NUM_CHARS_EXT + r']+)条\s*$'),  # 第一条
    ...
]
```

**扩展策略**:
1. 识别行首的 `编号 + 空格 + 标题` 模式
2. 提取标题后的正文直到下一个编号出现
3. 合并跨行的正文内容

### 3.3 OCR 方案选型

| 方案 | 优点 | 缺点 | 部署 |
|------|------|------|------|
| PaddleOCR | 中文识别率高 | 依赖较重 | 本地 ollama |
| Tesseract | 轻量 | 中文效果一般 | apt/brew |
| pdf2image + OCR | 通用 | 性能开销 | pip |

**推荐**: PaddleOCR（用户已指定本地 ollama 部署）

---

## 四、数据流分析

### 4.1 现有数据流

```
PDF 文件
    ↓ pdfplumber.open()
页面对象
    ├→ find_tables() → 表格 → 条款（不完整）
    └→ extract_text() → 文本 → 章节（未识别条款）
    ↓
AuditDocument（缺失大量条款）
```

### 4.2 新增/变更的数据流

```
PDF 文件
    ↓ pdfplumber.open()
页面对象
    ├→ 检查是否扫描版（图片型）
    │   └→ 是 → OCR 处理 → 文本
    └→ extract_text() → 原始文本
    ↓
条款提取器（新增）
    ├→ 识别条款编号行
    ├→ 提取标题和正文
    └→ 合并跨页条款
    ↓
AuditDocument（完整条款）
```

### 4.3 关键数据结构

```python
# 条款提取中间结果
@dataclass
class RawClause:
    number: str           # "1.2.3"
    title: str            # "保险期间"
    content_lines: List[str]  # 正文行列表
    page_number: int
    start_line: int       # 在页面中的起始行

# 最终输出（复用现有）
Clause(number, title, text, ...)
```

---

## 五、关键技术问题

### 5.1 需要验证的技术假设

- [ ] pdfplumber 对所有保险 PDF 都能正确提取文本 — 验证：用 3 种不同格式 PDF 测试
- [ ] 条款编号正则覆盖所有格式 — 验证：提取所有匹配行，人工检查
- [ ] 跨页条款合并逻辑正确 — 验证：检查最后一个条款是否被截断
- [ ] PaddleOCR ollama 接口可用 — 验证：调用测试

### 5.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 文本布局复杂导致误识别 | 高 | 高 | 多格式测试，增加边界条件处理 |
| 扫描版 PDF OCR 质量差 | 中 | 中 | 识别率阈值，低质量提示人工 |
| 性能问题（大文件） | 低 | 中 | 分页处理，进度回调 |
| 配置文件格式错误 | 低 | 低 | 加载异常捕获，使用默认值 |

---

## 六、代码位置索引

| 功能 | 文件 | 行号 | 说明 |
|------|------|------|------|
| PdfParser 入口 | `pdf_parser.py` | 30-77 | parse() 方法 |
| 条款提取（缺陷） | `pdf_parser.py` | 79-106 | _extract_clauses_from_tables() |
| 文本处理 | `pdf_parser.py` | 131-163 | _extract_sections_from_page() |
| 条款编号正则 | `section_detector.py` | 36-41 | CLAUSE_NUMBER_PATTERNS |
| 章节检测 | `section_detector.py` | 71-77 | detect_section_type() |
| 数据模型 | `models.py` | 85-94 | Clause 类 |
| 编排器 | `parser.py` | 13-29 | parse_product_document() |
| 测试 fixture | `conftest.py` | 71-81 | sample_pdf_with_clauses |

---

## 七、修复方案建议

### 7.1 核心修改：条款提取重构

**新方法 `_extract_clauses_from_text()`**:
```python
def _extract_clauses_from_text(self, pages: List) -> List[Clause]:
    clauses = []
    pending_clause = None

    for page_idx, page in enumerate(pages):
        text = page.extract_text() or ''
        lines = text.split('\n')

        for line in lines:
            # 检查是否为新条款编号行
            match = self._match_clause_header(line)
            if match:
                # 保存上一个条款
                if pending_clause:
                    clauses.append(self._finalize_clause(pending_clause))
                # 开始新条款
                pending_clause = RawClause(
                    number=match.group(1),
                    title=match.group(2).strip(),
                    content_lines=[],
                    page_number=page_idx + 1,
                )
            elif pending_clause:
                # 追加到当前条款正文
                pending_clause.content_lines.append(line.strip())

    # 保存最后一个条款
    if pending_clause:
        clauses.append(self._finalize_clause(pending_clause))

    return clauses

def _match_clause_header(self, line: str) -> Optional[Match]:
    """匹配 '编号 标题' 格式的条款头"""
    # 匹配: "1.2 保险期间" 或 "2.3.1 等待期设置"
    pattern = r'^(\d+(?:\.\d+)*)\s+(.+)$'
    return re.match(pattern, line.strip())
```

### 7.2 补充配置文件

**`data/keywords.json`**:
```json
{
  "section_keywords": {
    "notice": ["阅读指引", "重要提示", "告知事项"],
    "health_disclosure": ["健康告知", "如实告知", "健康说明"],
    "exclusion": ["责任免除", "免责条款", "不承担责任"],
    "rider": ["附加险", "附加条款"]
  },
  "premium_table_keywords": ["费率", "保险费", "保费"],
  "non_clause_table_keywords": ["公司名称", "客服电话", "地址"]
}
```

### 7.3 OCR 处理器

**`ocr_handler.py`** (新增):
```python
class OcrHandler:
    """扫描版 PDF OCR 处理"""

    def is_scanned_pdf(self, page) -> bool:
        """检测是否为扫描版（无文字层）"""
        text = page.extract_text() or ''
        return len(text.strip()) < 100

    def ocr_page(self, page_image) -> str:
        """调用 PaddleOCR 识别图片"""
        # TODO: 调用本地 ollama OCR 接口
        pass
```

---

## 八、参考实现

- [pdfplumber 文档](https://github.com/jsvine/pdfplumber) — PDF 解析库
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — OCR 引擎
- [python-docx](https://python-docx.readthedocs.io/) — DOCX 解析参考

---

## 九、下一步行动

1. **创建 keywords.json 配置文件**
2. **重构 PdfParser 条款提取逻辑**：从文本流提取
3. **实现 OCR 处理器**：检测扫描版 PDF，调用 PaddleOCR
4. **编写集成测试**：使用真实 PDF 文档验证
5. **对比验证**：PDF 与 DOCX 解析结果一致性