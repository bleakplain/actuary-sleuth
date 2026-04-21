# 统一文档解析器 - 代码实现深度研究报告

生成时间: 2026-04-19
分析范围: scripts/lib/doc_parser/ 全模块
源规格: .claude/specs/015-document-parser/spec.md

---

## 执行摘要

重构后的 `doc_parser` 模块统一处理知识库文档和产品文档，职责边界清晰：

```
doc_parser/
├── kb/                   # 知识库文档处理 (完整流程)
│   ├── converter/        # Excel → Markdown
│   └── md_parser.py      # Markdown → TextNode
└── pd/                   # 产品文档解析
    └── ...               # Word/PDF → AuditDocument
```

**输出作为 rag_engine 的输入**，检索引擎仅负责索引构建和查询。

---

## 一、架构设计

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    doc_parser (文档解析层)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  kb/ (知识库文档)                                                        │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  converter/                    # Step 1: 格式转换                  │ │
│  │    convert_excel_to_markdown() # Excel → Markdown                 │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  md_parser.py                  # Step 2: 内容解析                  │ │
│  │    MdParser.chunk()            # Markdown → TextNode              │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│                       List[TextNode] ──────────────────────┐            │
│                                                            │            │
│  pd/ (产品文档)                                            │            │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  docx_parser.py                # Word 解析                        │ │
│  │  pdf_parser.py                 # PDF 解析                         │ │
│  │    parse_product_document()    # Word/PDF → AuditDocument         │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│                       AuditDocument                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                               │
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    rag_engine (检索引擎层)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  输入: List[TextNode] (来自 doc_parser/kb)                              │
│  职责: 索引构建、混合检索、重排序                                         │
│                                                                         │
│  builder.py:    TextNode → LanceDB + BM25                               │
│  retrieval.py:  query → 混合检索 → RRF 融合                             │
│  rag_engine.py: 完整 RAG 问答                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 职责划分

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `doc_parser/kb/converter/` | Excel→Markdown 转换 | Excel 检查清单 | Markdown 文件 |
| `doc_parser/kb/md_parser.py` | Markdown 解析分块 | Markdown 文件 | List[TextNode] |
| `doc_parser/pd/` | 产品文档解析 | Word/PDF | AuditDocument |
| `rag_engine/builder.py` | 索引构建 | List[TextNode] | LanceDB + BM25 |
| `rag_engine/retrieval.py` | 检索 | query | 检索结果 |

---

## 二、kb 模块详解

### 2.1 converter/ (Excel → Markdown)

**原位置**: `rag_engine/preprocessor.py`
**新位置**: `doc_parser/kb/converter/`

**核心功能**：
- 解析 Excel 检查清单结构
- 调用 LLM 提取法规元数据（发文机关、文号）
- 生成结构化 Markdown 文件
- OCR 处理内嵌表格图片

**公共接口**：
```python
def convert_excel_to_markdown(
    excel_path: str,
    output_dir: str,
    skip_ocr: bool = False,
) -> Path:
    """Excel 检查清单 → Markdown 知识库"""
```

### 2.2 md_parser.py (Markdown → TextNode)

**核心功能**：
- YAML frontmatter 解析
- `## 第N项` 分块边界识别
- blockquote 元数据提取
- 超长 chunk 按句子拆分

**公共接口**：
```python
class MdParser:
    def chunk(self, documents: List[Document]) -> List[TextNode]:
        """批量分块，兼容 ChecklistChunker 接口"""
    
    def parse_document(self, doc: Document) -> List[TextNode]:
        """解析单个文档"""
```

### 2.3 元数据字段

| 字段 | 来源 | 说明 |
|------|------|------|
| law_name | regulation / H1 / collection / "未知" | 法规名称 (四级回退) |
| article_number | `第{N}项` | 条款编号 |
| category | collection 去序号 | 分类 |
| source_file | 文件名 | 来源 |
| hierarchy_path | `category > law_name > article_number` | 层级路径 |
| doc_number | frontmatter.文号 | 发文字号 |
| issuing_authority | frontmatter.发文机关 | 发文机关 |
| 动态字段 | blockquote `key=value` | 险种类型等 |

---

## 三、pd 模块详解

### 3.1 解析流程

```
Word/PDF 文件
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  1. 遍历表格                                        │
│     - 条款表: 首列匹配条款编号 (1, 1.1, 2.3.2)      │
│     - 费率表: 表头包含 "年龄/费率/保费" 等           │
│     - 过滤非条款表: 公司/地址/电话...               │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  2. 遍历段落/文本                                   │
│     - 检测章节类型: 投保须知/健康告知/责任免除/附加险│
│     - 按关键词匹配识别                              │
└─────────────────────────────────────────────────────┘
    │
    ▼
AuditDocument
```

### 3.2 输出结构

```python
@dataclass
class AuditDocument:
    file_name: str
    file_type: str  # .docx, .pdf
    clauses: List[Clause]
    premium_tables: List[PremiumTable]
    notices: List[DocumentSection]
    health_disclosures: List[DocumentSection]
    exclusions: List[DocumentSection]
    rider_clauses: List[Clause]
    parse_time: datetime
    warnings: List[str]
```

---

## 四、当前状态

### 4.1 已完成

| 组件 | 状态 | 说明 |
|------|------|------|
| `doc_parser/models.py` | ✅ | 数据模型定义 |
| `doc_parser/kb/md_parser.py` | ✅ | Markdown 解析器 |
| `doc_parser/kb/parser.py` | ✅ | kb 编排器 |
| `doc_parser/kb/converter/` | ✅ | Excel → Markdown 转换（已迁移） |
| `doc_parser/pd/` | ✅ | 产品文档解析 |
| `doc_parser/pd/data/keywords.json` | ✅ | 关键词配置 |

### 4.2 引用更新

| 文件 | 修改内容 | 状态 |
|------|---------|------|
| `rag_engine/sample_synthesizer.py` | 改用 `lib.doc_parser.kb.converter.excel_to_md.extract_json_array` | ✅ |

### 4.3 待删除

| 文件 | 原因 | 状态 |
|------|------|------|
| `rag_engine/chunker.py` | 由 `doc_parser/kb/md_parser.py` 替代 | 待删除 |
| `rag_engine/preprocessor.py` | 已迁移到 `doc_parser/kb/converter/` | 待删除 |

---

## 五、测试验证

### 5.1 kb 模块测试

| 测试文件 | 覆盖场景 |
|---------|---------|
| `test_md_parser.py` | frontmatter、分块、元数据、超长拆分、接口兼容 |

### 5.2 功能等价性

**MdParser 与 ChecklistChunker 完全等价**：
- 正则表达式完全相同
- 分块边界识别逻辑相同
- 元数据字段和优先级相同
- 四级回退逻辑相同 (regulation → H1 → collection → "未知")
- 超长 chunk 拆分逻辑相同
- chunk() 接口兼容

---

## 六、下一步行动

1. **更新 rag_engine/builder.py** — 改用 `doc_parser.kb.MdParser`
2. **删除旧代码** — 删除 `rag_engine/chunker.py` 和 `rag_engine/preprocessor.py`
3. **运行测试** — 确保所有测试通过
