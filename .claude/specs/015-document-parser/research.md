# 统一文档解析器 - 技术调研报告

生成时间: 2026-04-17
源规格: .claude/specs/015-document-parser/spec.md

## 执行摘要

创建独立的 `lib/doc_parser` 模块，统一处理知识库文档和保险产品文档的解析，与知识库构建流程解耦。

**模块定位**：
- **输入**：已格式化的文档文件（Markdown、Word、PDF）
- **输出**：结构化数据（TextNode 列表 或 AuditDocument）
- **不负责**：Excel→Markdown 转换（preprocessor）、索引构建（builder）

---

## 一、系统边界

### 1.1 知识库创建完整流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        知识库创建流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 1: Excel → Markdown                                               │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐     │
│  │ Excel 文件  │ ──→ │ preprocessor.py  │ ──→ │ Markdown 文件    │     │
│  │ (.xlsx)     │     │ (Excel→MD 转换)  │     │ (references/)    │     │
│  └─────────────┘     └──────────────────┘     └──────────────────┘     │
│                                    ↑                                    │
│                         【不属于 doc_parser】                            │
│                                                                         │
│  Step 2: Markdown → TextNode (分块)                                     │
│  ┌──────────────────┐     ┌──────────────────┐     ┌─────────────┐     │
│  │ Markdown 文件    │ ──→ │ doc_parser       │ ──→ │ TextNode    │     │
│  │ (references/)    │     │ (本模块)         │     │ (chunks)    │     │
│  └──────────────────┘     └──────────────────┘     └─────────────┘     │
│                                    ↑                                    │
│                         【doc_parser 职责】                             │
│                                                                         │
│  Step 3: TextNode → 索引                                                │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐     │
│  │ TextNode    │ ──→ │ builder.py       │ ──→ │ LanceDB + BM25   │     │
│  │ (chunks)    │     │ (索引构建)       │     │ 索引             │     │
│  └─────────────┘     └──────────────────┘     └──────────────────┘     │
│                                    ↑                                    │
│                         【不属于 doc_parser】                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 保险产品解析流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        保险产品解析流程                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐     │
│  │ 产品文档    │ ──→ │ doc_parser       │ ──→ │ AuditDocument    │     │
│  │ (.docx/.pdf)│     │ (本模块)         │     │ (结构化数据)     │     │
│  └─────────────┘     └──────────────────┘     └──────────────────┘     │
│                                                                         │
│  输出供审核评测模块使用：                                                │
│  - clauses: 条款列表                                                    │
│  - premium_tables: 费率表列表                                           │
│  - notices: 投保须知                                                    │
│  - health_disclosures: 健康告知                                         │
│  - exclusions: 责任免除                                                 │
│  - rider_clauses: 附加险条款                                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 职责划分

| 阶段 | 模块 | 职责 | 属于 doc_parser |
|------|------|------|----------------|
| 预处理 | `rag_engine/preprocessor.py` | Excel → Markdown 转换 | ❌ |
| **解析** | **`doc_parser/`** | **文档 → 结构化数据** | ✅ |
| 构建 | `rag_engine/builder.py` | TextNode → 向量索引 + BM25 | ❌ |
| 管理 | `rag_engine/kb_manager.py` | 版本管理、路径映射 | ❌ |

---

## 二、模块设计

### 2.1 目录结构

```
scripts/lib/doc_parser/
├── __init__.py           # 公共接口导出
├── models.py             # 数据模型定义
├── parser.py             # 编排器 + 基类定义
├── md_parser.py          # Markdown 解析器
├── docx_parser.py        # Word (.docx) 解析器
├── pdf_parser.py         # PDF 解析器
├── section_detector.py   # 内容类型检测
└── data/
    └── keywords.json     # 内容类型关键词配置
```

### 2.2 层次架构

```
┌─────────────────────────────────────────────────────────────┐
│              顶层编排层 (parser.py)                          │
├─────────────────────────────────────────────────────────────┤
│  职责:                                                      │
│  - 根据文件扩展名动态选择解析器                               │
│  - 统一错误处理                                              │
│  - 验证文件存在性                                            │
│                                                             │
│  接口:                                                      │
│  - parse_knowledge_base(file_path) → List[TextNode]        │
│  - parse_product_document(file_path) → AuditDocument       │
└─────────────────────────────────────────────────────────────┘
                              ↓ 调度
┌─────────────────────────────────────────────────────────────┐
│              解析器层 (xxx_parser.py)                        │
├─────────────────────────────────────────────────────────────┤
│  职责: 单一文档格式解析                                      │
│                                                             │
│  解析器:                                                    │
│  - MdParser: .md → List[TextNode] (知识库分块)              │
│  - DocxParser: .docx → AuditDocument (产品文档)             │
│  - PdfParser: .pdf → AuditDocument (产品文档)               │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 公共接口

```python
# lib/doc_parser/__init__.py

# 数据模型
from .models import (
    Clause,
    PremiumTable,
    DocumentSection,
    AuditDocument,
    DocumentParseError,
    SectionType,
)

# 基类
from .parser import KnowledgeBaseParser, ProductDocumentParser

# 便捷接口 (推荐使用)
from .parser import parse_knowledge_base, parse_product_document

# 解析器类 (供高级用户直接使用)
from .md_parser import MdParser
from .docx_parser import DocxParser
from .pdf_parser import PdfParser

__all__ = [
    # 数据模型
    'Clause', 'PremiumTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType',
    # 基类
    'KnowledgeBaseParser', 'ProductDocumentParser',
    # 解析器类
    'MdParser', 'DocxParser', 'PdfParser',
    # 便捷接口
    'parse_knowledge_base', 'parse_product_document',
]
```

---

## 三、数据模型

### 3.1 AuditDocument（审核文档）

```python
@dataclass
class AuditDocument:
    """保险产品审核文档"""
    file_name: str
    file_type: str  # .docx, .pdf

    # 按类型分组的内容
    clauses: List[Clause]              # 条款
    premium_tables: List[PremiumTable] # 费率表
    notices: List[DocumentSection]     # 投保须知
    health_disclosures: List[DocumentSection]  # 健康告知
    exclusions: List[DocumentSection]  # 责任免除
    rider_clauses: List[Clause]        # 附加险条款

    # 元数据
    parse_time: datetime
    warnings: List[str]  # 解析警告（非致命问题）
```

### 3.2 Clause（条款）

```python
@dataclass(frozen=True)
class Clause:
    """条款"""
    number: str       # 条款编号，如 "1.2.3"
    title: str        # 条款标题
    text: str         # 条款正文
    section_type: str = "clause"
```

### 3.3 PremiumTable（费率表）

```python
@dataclass
class PremiumTable:
    """费率表"""
    raw_text: str              # 原始文本
    data: List[List[str]]      # 结构化数据（二维表格）
    remark: str = ""           # 备注
    section_type: str = "premium_table"
```

### 3.4 DocumentSection（文档章节）

```python
@dataclass
class DocumentSection:
    """通用文档章节"""
    title: str        # 章节标题
    content: str      # 章节内容
    section_type: str # 内容类型：notice, health_disclosure, exclusion, rider
```

### 3.5 SectionType（内容类型枚举）

```python
class SectionType(str, Enum):
    """内容类型枚举"""
    CLAUSE = "clause"
    PREMIUM_TABLE = "premium_table"
    NOTICE = "notice"
    HEALTH_DISCLOSURE = "health_disclosure"
    EXCLUSION = "exclusion"
    RIDER = "rider"
```

### 3.6 DocumentParseError（解析错误）

```python
class DocumentParseError(Exception):
    """文档解析错误"""
    def __init__(self, message: str, file_path: str = "", detail: str = ""):
        self.file_path = file_path
        self.detail = detail
        super().__init__(f"{message}: {file_path}" if file_path else message)
```

---

## 四、解析器实现

### 4.1 编排器 (parser.py)

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List
from llama_index.core.schema import TextNode
from .models import AuditDocument, DocumentParseError


# ========== 基类定义 ==========

class KnowledgeBaseParser(ABC):
    """知识库文档解析器基类"""

    @abstractmethod
    def parse(self, file_path: str) -> List[TextNode]:
        """解析文档，返回分块后的文本节点"""
        pass

    @staticmethod
    @abstractmethod
    def supported_extensions() -> List[str]:
        """返回支持的文件扩展名"""
        pass


class ProductDocumentParser(ABC):
    """产品文档解析器基类"""

    @abstractmethod
    def parse(self, file_path: str) -> AuditDocument:
        """解析文档，返回结构化审核文档"""
        pass

    @staticmethod
    @abstractmethod
    def supported_extensions() -> List[str]:
        """返回支持的文件扩展名"""
        pass


# ========== 解析器注册表 ==========

_KB_PARSERS: dict = {}        # 知识库场景: ext -> parser
_PRODUCT_PARSERS: dict = {}   # 产品文档场景: ext -> parser


def _register(parser_cls, scenario: str):
    """注册解析器到对应场景"""
    for ext in parser_cls.supported_extensions():
        if scenario == 'knowledge_base':
            _KB_PARSERS[ext] = parser_cls()
        elif scenario == 'product_document':
            _PRODUCT_PARSERS[ext] = parser_cls()


# ========== 公共接口 ==========

def parse_knowledge_base(file_path: str) -> List[TextNode]:
    """
    解析知识库文档

    根据文件扩展名自动选择解析器，输出 TextNode 列表供 RAG 检索。

    Args:
        file_path: 文档文件路径 (.md 等)

    Returns:
        List[TextNode]: 分块后的文本节点

    Raises:
        DocumentParseError: 文件不存在、格式不支持、解析失败
    """
    path = Path(file_path)

    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    ext = path.suffix.lower()
    parser = _KB_PARSERS.get(ext)

    if not parser:
        raise DocumentParseError(
            f"不支持的知识库文档格式: {ext}",
            file_path,
            f"支持的格式: {list(_KB_PARSERS.keys())}"
        )

    return parser.parse(file_path)


def parse_product_document(file_path: str) -> AuditDocument:
    """
    解析保险产品文档

    根据文件扩展名自动选择解析器，输出结构化审核文档。

    Args:
        file_path: 文档文件路径 (.docx, .pdf 等)

    Returns:
        AuditDocument: 结构化审核文档

    Raises:
        DocumentParseError: 文件不存在、格式不支持、解析失败
    """
    path = Path(file_path)

    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    ext = path.suffix.lower()
    parser = _PRODUCT_PARSERS.get(ext)

    if not parser:
        raise DocumentParseError(
            f"不支持的产品文档格式: {ext}",
            file_path,
            f"支持的格式: {list(_PRODUCT_PARSERS.keys())}"
        )

    return parser.parse(file_path)


# ========== 自动注册 ==========

def _auto_register():
    from .md_parser import MdParser
    from .docx_parser import DocxParser
    from .pdf_parser import PdfParser

    _register(MdParser, 'knowledge_base')
    _register(DocxParser, 'product_document')
    _register(PdfParser, 'product_document')

_auto_register()
```

### 4.2 MdParser (知识库 Markdown 解析)

```python
# lib/doc_parser/md_parser.py

from typing import List
from llama_index.core.schema import TextNode
from .parser import KnowledgeBaseParser


class MdParser(KnowledgeBaseParser):
    """Markdown 解析器 (知识库场景)

    解析 preprocessor.py 生成的结构化 Markdown 文件：
    - YAML frontmatter → 文件级元数据
    - ## 第N项 → 分块边界
    - > **元数据** blockquote → 条款级元数据
    """

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.md', '.markdown']

    def parse(self, file_path: str) -> List[TextNode]:
        """解析 Markdown 文件，返回分块后的文本节点"""
        # 实现逻辑：
        # 1. 读取文件内容
        # 2. 提取 YAML frontmatter
        # 3. 按 ## 第N项 切分
        # 4. 提取 blockquote 元数据
        # 5. 构建 TextNode 列表
        ...
```

### 4.3 DocxParser (Word 解析)

```python
# lib/doc_parser/docx_parser.py

from .parser import ProductDocumentParser
from .models import Clause, PremiumTable, AuditDocument, DocumentSection


class DocxParser(ProductDocumentParser):
    """Word (.docx) 文档解析器"""

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.docx']

    def parse(self, file_path: str) -> AuditDocument:
        """解析 Word 文档"""
        from docx import Document

        doc = Document(file_path)
        clauses = self._extract_clauses(doc.tables)
        premium_tables = self._extract_premium_tables(doc.tables)
        sections = self._extract_sections(doc.tables, doc.paragraphs)

        return AuditDocument(
            file_name=Path(file_path).name,
            file_type='.docx',
            clauses=clauses,
            premium_tables=premium_tables,
            **sections,
        )
```

### 4.4 PdfParser (PDF 解析)

```python
# lib/doc_parser/pdf_parser.py

from .parser import ProductDocumentParser
from .models import Clause, PremiumTable, AuditDocument


class PdfParser(ProductDocumentParser):
    """PDF 文档解析器"""

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.pdf']

    def parse(self, file_path: str) -> AuditDocument:
        """解析 PDF 文档"""
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            clauses = self._extract_clauses(pdf)
            premium_tables = self._extract_premium_tables(pdf)
            sections = self._extract_sections(pdf)

        return AuditDocument(
            file_name=Path(file_path).name,
            file_type='.pdf',
            clauses=clauses,
            premium_tables=premium_tables,
            **sections,
        )
```

---

## 五、关键技术细节

### 5.1 条款编号识别

**格式**：阿拉伯数字层级编号（1, 1.1, 2.3.2），不是中文"第X条"

```python
CLAUSE_NUMBER_PATTERN = re.compile(r'^(\d+(?:\.\d+)*)\s*$')
```

### 5.2 内容位置（DOCX）

- 条款内容主要在**表格**中
- 段落多为空（8-15 个空段落），主内容在 2-3 个表格

### 5.3 标题/正文分离

约 41% 的条款标题和正文混在同一单元格，分离策略（按优先级）：

1. 如果有换行符，第一行为标题
2. 如果有句号且第一句<=30字，第一句为标题
3. 否则全部作为标题

### 5.4 内容类型检测

**关键词检测规则**：

```python
SECTION_KEYWORDS = {
    'notice': ['投保须知', '投保说明', '重要提示'],
    'health_disclosure': ['健康告知', '健康声明', '告知事项'],
    'exclusion': ['责任免除', '免责条款', '除外责任'],
    'rider': ['附加险', '附加条款', '附加合同'],
}

PREMIUM_TABLE_KEYWORDS = {'年龄', '费率', '保费', '周岁', '性别', '缴费', '保额'}
```

**检测优先级**：health_disclosure > exclusion > notice > rider

### 5.5 非条款表格过滤

```python
NON_CLAUSE_TABLE_KEYWORDS = {'公司', '地址', '电话', '邮编', '客服', '网址', '资质'}
```

---

## 六、RAG 文档解析最佳实践

### 6.1 行业主流方案对比

| 方案 | 优势 | 劣势 | 适用场景 |
|------|------|------|---------|
| **Unstructured.io** | 支持 30+ 格式、云端托管、VLM 增强 | 依赖外部服务、hi_res 模式慢 20 倍 | 大规模通用文档处理 |
| **LlamaParse** | 复杂布局支持、表格还原好 | 付费服务、延迟高 | 高质量 PDF 解析 |
| **pdfplumber** | 纯 Python、表格提取强、可视化调试 | 不支持扫描件 PDF | 机器生成的 PDF |
| **python-docx** | 纯 Python、API 简洁 | 不支持 .doc 格式 | Word 文档 |
| **自研方案** | 完全可控、无外部依赖 | 需自行处理边界情况 | 特定领域文档 |

**选型结论**：保险产品文档主要是机器生成的 Word/PDF，选择 `python-docx` + `pdfplumber` 组合，满足需求且无外部依赖。

### 6.2 分块策略最佳实践

#### LlamaIndex 推荐的分块方式

| 策略 | 描述 | 适用场景 |
|------|------|---------|
| **SemanticSplitter** | 基于语义相似度切分，相邻句子相似度低于阈值时断开 | 长文档、主题切换明显 |
| **SentenceSplitter** | 按句子边界切分，支持重叠窗口 | 通用场景 |
| **MarkdownNodeParser** | 按 Markdown 标题层级切分 | Markdown 文档 |
| **HierarchicalNodeParser** | 多层级结构，父节点包含完整上下文 | 需要上下文的检索 |
| **CodeSplitter** | 按代码语义单元（函数、类）切分 | 代码文档 |

**语义分块原理**（Greg Kamradt 方案）：

```python
from llama_index.core.node_parser import SemanticSplitterNodeParser

splitter = SemanticSplitterNodeParser(
    buffer_size=1,  # 句子分组大小
    breakpoint_percentile_threshold=95,  # 相似度阈值
    embed_model=embed_model
)
```

- 计算相邻句子的 embedding 相似度
- 相似度低于百分位阈值时，作为断点
- 适合长文档，避免在主题中间切断

#### 我们的选择

| 场景 | 策略 | 理由 |
|------|------|------|
| **知识库 Markdown** | 结构感知分块（按 `## 第N项`） | 已有约定好的结构边界 |
| **保险产品 Word/PDF** | 表格感知分块（按条款编号） | 条款是独立语义单元 |

**不采用语义分块的原因**：
1. 保险产品文档有明确的条款编号边界，无需语义推断
2. 语义分块依赖 embedding 模型，增加解析延迟
3. 条款粒度已经是最小审核单元

### 6.3 表格提取策略

#### Unstructured.io 表格处理

```
处理策略：
- fast: 不提取表格，仅提取文本（快 20 倍）
- hi_res: 完整表格提取，支持 VLM 增强
- ocr_only: 多栏文档，无提取文本时使用
```

#### pdfplumber 表格提取

```python
import pdfplumber

with pdfplumber.open("doc.pdf") as pdf:
    for page in pdf.pages:
        # 查找表格
        tables = page.find_tables()
        for table in tables:
            # 获取表格数据
            data = table.extract()
            # 获取边界框
            bbox = table.bbox
```

**表格检测策略**：

| 策略 | 描述 | 适用场景 |
|------|------|---------|
| `lines` | 基于图形线条检测 | 标准表格 |
| `text` | 基于文字对齐推断 | 无边框表格 |
| `explicit` | 用户自定义边界 | 复杂布局 |

#### 我们的实现要点

```python
# 条款表格检测
def is_clause_table(cells: List[str]) -> bool:
    """判断是否为条款表格"""
    # 第一列包含条款编号（1, 1.1, 2.3.2）
    first_col = cells[0] if cells else ""
    return bool(CLAUSE_NUMBER_PATTERN.match(first_col.strip()))

# 费率表检测
def is_premium_table(header_row: List[str]) -> bool:
    """判断是否为费率表"""
    text = " ".join(str(c) for c in header_row)
    return any(kw in text for kw in PREMIUM_TABLE_KEYWORDS)

# 非条款表格过滤
def is_non_clause_table(first_row: List[str]) -> bool:
    """过滤公司信息等非条款表格"""
    text = " ".join(str(c) for c in first_row)
    return any(kw in text for kw in NON_CLAUSE_TABLE_KEYWORDS)
```

### 6.4 元数据继承最佳实践

LlamaIndex 推荐：**父节点元数据自动继承到子节点**

```python
# 元数据继承示例
parent_metadata = {
    "law_name": "健康保险管理办法",
    "doc_number": "银保监发〔2019〕102号",
    "issuing_authority": "中国银保监会",
}

# 子节点自动继承
child_node = TextNode(
    text="条款内容...",
    metadata={
        **parent_metadata,  # 继承父节点元数据
        "article_number": "第3条",  # 子节点特有元数据
    }
)
```

**我们的实现**：

```python
# 从 frontmatter 提取文件级元数据
file_metadata = {
    "law_name": frontmatter.get("regulation"),
    "category": frontmatter.get("collection"),
    "doc_number": frontmatter.get("文号"),
    "issuing_authority": frontmatter.get("发文机关"),
}

# 每个 chunk 继承文件级元数据
for item in items:
    node = TextNode(
        text=item["content"],
        metadata={
            **file_metadata,  # 继承
            "article_number": f"第{item['item_number']}项",
            "hierarchy_path": f"{category} > {law_name} > 第{item['item_number']}项",
        }
    )
```

### 6.5 多格式文档处理流水线

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    文档解析流水线                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Stage 1: 格式检测                                                      │
│  ┌─────────────┐     ┌──────────────────┐                              │
│  │ 文件路径    │ ──→ │ 扩展名识别        │                              │
│  └─────────────┘     └──────────────────┘                              │
│                              ↓                                          │
│  Stage 2: 解析器选择                                                    │
│  ┌──────────────────────────────────────────────────────────┐          │
│  │  .md/.markdown  → MdParser    → 知识库分块               │          │
│  │  .docx          → DocxParser  → 产品文档解析             │          │
│  │  .pdf           → PdfParser   → 产品文档解析             │          │
│  │  其他           → 抛出 DocumentParseError                │          │
│  └──────────────────────────────────────────────────────────┘          │
│                              ↓                                          │
│  Stage 3: 结构提取                                                      │
│  ┌──────────────────────────────────────────────────────────┐          │
│  │  知识库场景:                                              │          │
│  │    - YAML frontmatter → 文件级元数据                      │          │
│  │    - ## 第N项 → 分块边界                                  │          │
│  │    - blockquote → 条款级元数据                            │          │
│  │                                                          │          │
│  │  产品文档场景:                                            │          │
│  │    - 表格提取 → 条款/费率表                               │          │
│  │    - 章节标题 → 内容类型分类                              │          │
│  │    - 条款编号 → 层级结构                                  │          │
│  └──────────────────────────────────────────────────────────┘          │
│                              ↓                                          │
│  Stage 4: 输出构建                                                      │
│  ┌──────────────────────────────────────────────────────────┐          │
│  │  知识库场景: List[TextNode]                              │          │
│  │  产品文档场景: AuditDocument                             │          │
│  └──────────────────────────────────────────────────────────┘          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.6 关键决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 分块策略 | 结构感知（非语义分块） | 已有明确的条款边界 |
| 表格提取 | pdfplumber (lines 策略) | 机器生成 PDF，表格有边框 |
| 元数据管理 | 文件级 + 条款级双层 | 满足检索和溯源需求 |
| 错误处理 | 明确异常 + 警告列表 | 区分致命错误和可恢复问题 |
| 扩展性 | 解析器注册表模式 | 未来支持新格式只需新增解析器 |

---

## 七、依赖分析

| 依赖 | 版本 | 用途 |
|------|------|------|
| `python-docx` | >=0.8.11 | Word 解析 |
| `pdfplumber` | >=0.9.0 | PDF 解析 |
| `llama-index` | (已有) | TextNode 类型 |
| `yaml` | (已有) | frontmatter 解析 |

---

## 八、与知识库模块的集成

### 7.1 KnowledgeBuilder 改造

```python
# rag_engine/builder.py

class KnowledgeBuilder:
    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        # 移除: from .chunker import ChecklistChunker
        # 移除: self.chunker = ChecklistChunker()
        self.index_manager = VectorIndexManager(self.config)

    def chunk(self, documents: List) -> List[TextNode]:
        # 改为调用 doc_parser
        from lib.doc_parser import parse_knowledge_base
        nodes = []
        for doc in documents:
            file_path = doc.metadata.get('file_path', '')
            if file_path:
                nodes.extend(parse_knowledge_base(file_path))
        return nodes
```

### 7.2 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `rag_engine/chunker.py` | 删除 | 逻辑迁移到 `doc_parser/md_parser.py` |
| `rag_engine/builder.py` | 修改 | 改用 `parse_knowledge_base()` |
| `rag_engine/__init__.py` | 修改 | 移除 ChecklistChunker re-export |
| `tests/lib/rag_engine/test_chunker.py` | 删除 | 测试迁移到 `tests/lib/doc_parser/` |
| `common/document_fetcher.py` | 删除 | 无外部引用，安全删除 |

---

## 九、测试清单

| 测试文件 | 说明 |
|---------|------|
| `tests/lib/doc_parser/test_models.py` | 数据模型测试 |
| `tests/lib/doc_parser/test_md_parser.py` | Markdown 解析测试（含向后兼容） |
| `tests/lib/doc_parser/test_docx_parser.py` | Word 解析测试 |
| `tests/lib/doc_parser/test_pdf_parser.py` | PDF 解析测试 |
| `tests/lib/doc_parser/test_section_detector.py` | 内容类型检测测试 |

---

## 十、真实保险产品分析

基于 `/mnt/d/work/actuary-assets/products/` 目录的 24 个文件：

| 格式 | 数量 | 说明 |
|------|------|------|
| `.docx` | 11 | 可直接解析 |
| `.doc` | 9 | 需预处理转换为 `.docx` |
| `.pdf` | 3 | 可直接解析 |

**产品类型分布**：医疗险 8、重疾险 4、护理险 4、意外险 3、残疾险 2、年金险 1、附加险 1

---

## 十一、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Markdown 解析迁移破坏向后兼容 | 中 | 高 | 迁移前完整测试，迁移后对比输出 |
| 内容类型关键词检测误判 | 中 | 中 | 支持自定义关键词，记录警告 |
| `.doc` 文件无法解析 | 高 | 中 | 明确错误提示需转换为 `.docx` |
| PDF 表格跨页断裂 | 中 | 低 | 按编号去重，记录警告 |
