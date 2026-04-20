# 架构重构方案：统一文档解析到 kb 模块

## 一、当前问题

### 1.1 职责分散

```
当前结构：
rag_engine/
├── preprocessor.py      # Excel → Markdown (kb 预处理)
├── chunker.py           # Markdown → TextNode (kb 解析) [将被删除]
├── builder.py           # TextNode → 索引 (kb 构建)
└── ...

doc_parser/
├── kb/                  # Markdown → TextNode (与 chunker.py 重复)
└── pd/                  # Word/PDF → AuditDocument (产品文档)
```

### 1.2 命名混淆

- `preprocessor.py` 在 `rag_engine/` 下，但实际是文档格式转换
- `query_preprocessor.py` 也是预处理，但处理的是查询而非文档
- 两者的"预处理"含义不同，造成混淆

## 二、重构方案

### 2.1 新结构

```
doc_parser/
├── __init__.py           # 统一入口
├── models.py             # 数据模型
├── kb/                   # 知识库文档处理 (完整流程)
│   ├── __init__.py
│   ├── parser.py         # 编排器: parse_knowledge_base()
│   ├── md_parser.py      # Markdown → TextNode
│   └── converter/        # Excel → Markdown (原 preprocessor)
│       ├── __init__.py
│       ├── excel_to_md.py
│       └── llm_extractor.py
└── pd/                   # 产品文档解析
    ├── __init__.py
    ├── parser.py
    ├── docx_parser.py
    ├── pdf_parser.py
    ├── section_detector.py
    ├── utils.py
    └── data/keywords.json
```

### 2.2 职责边界

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    doc_parser (文档解析层)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  kb/ (知识库文档)                                                        │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  converter/           # Step 1: 格式转换                           │ │
│  │    Excel → Markdown   # 输出结构化 .md 文件                        │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  md_parser.py         # Step 2: 内容解析                           │ │
│  │    Markdown → TextNode # 输出向量索引的输入                        │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│                       List[TextNode]                                    │
│                                                                         │
│  pd/ (产品文档)                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  docx_parser.py       # Word 解析                                  │ │
│  │  pdf_parser.py        # PDF 解析                                   │ │
│  │    Word/PDF → AuditDocument                                        │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                              ↓                                          │
│                       AuditDocument                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    rag_engine (检索引擎层)                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  输入: List[TextNode] (来自 doc_parser/kb)                              │
│  输出: 向量索引 + BM25 索引 + 检索结果                                   │
│                                                                         │
│  builder.py: TextNode → LanceDB + BM25                                  │
│  retrieval.py: query → 混合检索 → 融合 → 重排序                         │
│  rag_engine.py: 完整 RAG 问答                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `doc_parser/kb/converter/` | Excel→Markdown 转换 | Excel 检查清单 | Markdown 文件 |
| `doc_parser/kb/md_parser.py` | Markdown 解析分块 | Markdown 文件 | List[TextNode] |
| `doc_parser/pd/` | 产品文档解析 | Word/PDF | AuditDocument |
| `rag_engine/builder.py` | 索引构建 | List[TextNode] | LanceDB + BM25 |
| `rag_engine/retrieval.py` | 检索 | query | 检索结果 |

### 2.4 命名澄清

| 原名称 | 新位置 | 说明 |
|--------|--------|------|
| `rag_engine/preprocessor.py` | `doc_parser/kb/converter/` | Excel→Markdown 转换器 |
| `rag_engine/query_preprocessor.py` | 保持不变 | 查询预处理器 |
| `rag_engine/chunker.py` | 删除 | 由 `doc_parser/kb/md_parser.py` 替代 |

## 三、公共接口

### 3.1 doc_parser 顶层接口

```python
# lib/doc_parser/__init__.py

# 数据模型
from .models import (
    Clause, PremiumTable, DocumentSection,
    AuditDocument, DocumentParseError, SectionType, DocumentMeta,
)

# kb 场景接口
from .kb import parse_knowledge_base

# pd 场景接口
from .pd import parse_product_document

__all__ = [
    # 数据模型
    'Clause', 'PremiumTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType', 'DocumentMeta',
    # kb 接口
    'parse_knowledge_base',
    # pd 接口
    'parse_product_document',
]
```

**注意**：`MdParser` 是内部实现，顶层不导出。`convert_excel_to_markdown` 在 `kb` 子模块公开。

### 3.2 kb 子模块接口

```python
# lib/doc_parser/kb/__init__.py

# 解析接口
from .parser import parse_knowledge_base
from .md_parser import MdParser

# 转换接口 (原 preprocessor)
from .converter import convert_excel_to_markdown

__all__ = [
    'parse_knowledge_base', 'MdParser',
    'convert_excel_to_markdown',
]
```

## 四、迁移影响

### 4.1 需要修改的文件

| 文件 | 修改内容 | 状态 |
|------|---------|------|
| `rag_engine/builder.py` | 改用 `doc_parser.kb.MdParser` | ✅ 已完成 |
| `rag_engine/__init__.py` | 移除 `preprocessor` 导出 | ✅ 无需修改（未导出） |
| `rag_engine/sample_synthesizer.py` | 更新 import 路径 | ✅ 已完成 |
| 测试文件 | 更新 import 路径 | ✅ 已完成 |

### 4.2 需要删除的文件

| 文件 | 原因 | 状态 |
|------|------|------|
| `rag_engine/chunker.py` | 由 `doc_parser/kb/md_parser.py` 替代 | ✅ 已删除 |
| `rag_engine/preprocessor.py` | 迁移到 `doc_parser/kb/converter/` | ✅ 已删除 |

### 4.3 已新增的文件

| 文件 | 内容 | 状态 |
|------|------|------|
| `doc_parser/kb/converter/__init__.py` | 导出 convert_excel_to_markdown | ✅ |
| `doc_parser/kb/converter/excel_to_md.py` | 原 preprocessor 核心逻辑（含 LLM 提取） | ✅ |

**注**：`llm_extractor.py` 未拆分，LLM 提取逻辑保留在 `excel_to_md.py` 中，保持单文件简洁。

## 五、向后兼容

### 5.1 兼容性保证

```python
# rag_engine/builder.py 中的迁移
# 改造前
from .chunker import ChecklistChunker
self.chunker = ChecklistChunker()

# 改造后
from lib.doc_parser.kb import MdParser
self.chunker = MdParser()  # 接口完全兼容
```

### 5.2 弃用警告

```python
# rag_engine/__init__.py
import warnings

def __getattr__(name):
    if name == 'preprocessor':
        warnings.warn(
            "rag_engine.preprocessor 已迁移到 doc_parser.kb.converter",
            DeprecationWarning,
            stacklevel=2
        )
        from lib.doc_parser.kb import converter
        return converter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```
