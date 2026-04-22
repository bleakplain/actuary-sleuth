# Chunk 语义增强 - 技术调研报告

生成时间: 2026-04-22
源规格: .claude/specs/017-chunk-semantic-enhancement/spec.md

## 执行摘要

通过对 doc_parser 模块的深入分析，发现：1) Markdown 解析器缺少表格识别能力，表格会被常规分块逻辑切碎；2) PDF 解析器逐页提取表格，无跨页合并逻辑；3) 数据模型中 PremiumTable 未分离存储表头信息。建议在现有架构基础上增量增强，无需大规模重构。主要风险是跨页表格检测的准确性，需设计合理的启发式规则。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 Markdown 表格识别 | `kb/md_parser.py` | **需增强** - 无表格识别逻辑 |
| FR-002 PDF 跨页表格合并 | `pd/pdf_parser.py` | **需新增** - 逐页处理，无合并 |
| FR-003 表头补充 | `models.py::PremiumTable` | **需增强** - 无表头分离存储 |
| FR-004 句子完整性 | `kb/md_parser.py::_chunk_by_sentence` | **已有** - 需验证边界检测 |
| FR-005 层级结构保留 | `kb/md_parser.py::_identify_headings` | **已有** - 多策略标题识别 |
| FR-006 接口兼容 | `kb/md_parser.py::parse_document` | **已有** - 保持接口不变 |

### 1.2 可复用组件

- `MdParser._identify_headings()` (L164-241): 多策略标题识别，支持 Markdown、中文条款、数字层级
- `MdParser._should_merge()` (L563-586): 语义完整性检测，检测冒号结尾、列表项编号、转折词
- `MdParser._chunk_by_sentence()` (L428-478): 句子边界切分，支持智能 overlap
- `SectionDetector.is_premium_table()` (L94-96): PDF 表格类型识别
- `PremiumTable` (models.py:94-99): 表格数据结构，可扩展添加表头字段

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `kb/md_parser.py` | 修改 | 增加 Markdown 表格识别与保护逻辑 |
| `pd/pdf_parser.py` | 修改 | 增加跨页表格检测与合并逻辑 |
| `models.py` | 修改 | PremiumTable 增加 header 字段 |
| `kb/table_utils.py` | 新增 | Markdown 表格解析工具函数 |
| `pd/table_merger.py` | 新增 | PDF 跨页表格合并器 |

---

## 二、技术选型研究

### 2.1 Markdown 表格识别方案

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 正则匹配 `\|.*\|` | 简单、无依赖、速度快 | 无法处理复杂嵌套 | 标准 Markdown 表格 | ✅ 推荐 |
| markdown-it-py 解析 | 完整 AST、处理复杂情况 | 增加依赖、学习成本 | 复杂 Markdown 文档 | ❌ 过度设计 |
| HTML 转换后解析 | 可处理混合格式 | 重量级、可能改变语义 | HTML 混合内容 | ❌ 不适用 |

**选择理由**: 项目假设明确"Markdown 表格使用标准 `|...|` 语法"，正则匹配足够满足需求。

### 2.2 PDF 跨页表格合并方案

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 列头相似度匹配 | 简单、准确率高 | 需假设表格有表头 | 有表头的费率表 | ✅ 推荐 |
| 行内容连续性检测 | 不依赖表头 | 误合并风险高 | 无表头表格 | ❌ 风险高 |
| 页面底部/顶部位置检测 | 利用 PDF 结构 | 依赖 pdfplumber 特性 | 所有表格 | ✅ 辅助判断 |

**选择理由**: 保险产品费率表通常有明确表头，列头相似度匹配是最可靠的方法。

### 2.3 表格分块策略

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| 表格整体作为一个 chunk | 语义完整、实现简单 | 超大表格可能超出限制 | 小/中型表格 | ✅ 默认策略 |
| 按行分块 + 表头重复 | 支持超大表格 | 实现复杂 | 超大表格（如费率表） | ✅ 可选策略 |
| 按 N 行固定切分 | 实现简单 | 可能切断语义 | 不推荐 | ❌ |

**选择理由**: 分层策略——默认整体，超大表格按行分块并重复表头。

### 2.4 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| pdfplumber | 已有 | PDF 表格提取 | 无新增依赖 |
| python-docx | 已有 | Word 表格提取 | 无新增依赖 |
| 无新增依赖 | - | - | 符合约束 |

---

## 三、数据流分析

### 3.1 现有数据流

```
Markdown 文件 → MdParser.parse_document() → List[TextNode]
     ↓
Document → _extract_frontmatter() → DocumentMeta
        → _identify_headings() → List[Heading]
        → _recursive_chunk() → List[Chunk]
        → _chunks_to_nodes() → List[TextNode]
```

```
PDF 文件 → PdfParser.parse() → AuditDocument
     ↓
逐页处理 → page.find_tables() → 提取表格
         → 提取条款/费率表
         → 合并到 AuditDocument
```

### 3.2 新增/变更的数据流

```
Markdown 表格保护 (新增):
Markdown 文件 → 预处理: 识别表格位置 → 标记表格边界
             → _recursive_chunk() → 跳过表格区域
             → 表格作为独立 chunk 输出
```

```
PDF 跨页表格合并 (新增):
PDF 文件 → 逐页提取表格 → 收集所有表格
        → 跨页检测: 列头相似度 + 位置判断
        → 合并连续表格
        → 补充缺失表头
        → 输出 PremiumTable
```

### 3.3 关键数据结构

```python
# 需要修改: PremiumTable 增加表头字段
@dataclass(frozen=True)
class PremiumTable:
    raw_text: str
    data: List[List[str]]
    header: List[str] = field(default_factory=list)  # 新增: 表头行
    remark: str = ""

# 新增: Markdown 表格结构
@dataclass(frozen=True)
class MarkdownTable:
    header: List[str]           # 表头
    rows: List[List[str]]       # 数据行
    raw_text: str               # 原始文本
    start_pos: int              # 文档中起始位置
    end_pos: int                # 文档中结束位置

# 新增: 表格 chunk 元数据
# 在 Chunk.metadata 中增加:
{
    'content_type': 'table',           # 标识为表格类型
    'table_headers': ['列1', '列2'],   # 表头信息
    'table_row_count': 10,             # 行数
}
```

---

## 四、关键技术问题

### 4.1 Markdown 表格识别

**问题**: 如何准确识别 Markdown 表格边界，避免误识别？

**解决方案**:
```python
# 表格识别正则模式
TABLE_PATTERN = re.compile(
    r'^(\|[^\n]+\|\n)'           # 表头行
    r'(\|[-:| ]+\|\n)'           # 分隔行
    r'(\|[^\n]+\|\n?)+',         # 数据行
    re.MULTILINE
)

# 识别流程:
# 1. 用正则匹配所有表格
# 2. 记录表格的 (start, end) 位置
# 3. 在 _recursive_chunk() 中跳过这些区域
# 4. 单独处理每个表格为一个 chunk
```

**验证点**:
- [ ] 表格前后有普通文本时边界是否正确
- [ ] 连续多个表格是否被正确分离
- [ ] 表格内包含 `|` 字符时是否处理正确

### 4.2 PDF 跨页表格检测

**问题**: 如何判断两个表格是否应该合并？

**解决方案** - 多条件启发式判断:
```python
def should_merge_tables(table1, table2, page1_num, page2_num) -> bool:
    # 条件1: 必须是相邻页
    if page2_num != page1_num + 1:
        return False

    # 条件2: 列数相同
    if len(table1.header) != len(table2.header):
        return False

    # 条件3: 列头相似度 >= 0.8 (或 table2 无表头)
    if table2.header and not _headers_similar(table1.header, table2.header, threshold=0.8):
        return False

    # 条件4: table1 在页面底部，table2 在页面顶部
    # (利用 pdfplumber 的 bbox 信息)

    return True

def _headers_similar(h1, h2, threshold=0.8) -> bool:
    """计算列头相似度"""
    matches = sum(1 for a, b in zip(h1, h2) if a.strip() == b.strip())
    return matches / len(h1) >= threshold
```

**验证点**:
- [ ] 费率表跨 2 页场景
- [ ] 费率表跨 3+ 页场景
- [ ] 页面中间有多个表格的混淆场景
- [ ] 第二页表格无表头的场景

### 4.3 超大表格分块

**问题**: 表格超过 max_chunk_chars 时如何处理？

**解决方案** - 可配置策略:
```python
class TableChunkStrategy(Enum):
    WHOLE = "whole"           # 整体作为一个 chunk，允许超出限制
    ROW_BASED = "row_based"   # 按行分块，每块重复表头

# 默认策略: WHOLE
# 当 table.rows > TABLE_ROW_THRESHOLD 时，使用 ROW_BASED

def chunk_large_table(table: PremiumTable, max_chars: int) -> List[str]:
    """按行分块，每块包含表头"""
    header_text = "| " + " | ".join(table.header) + " |"
    separator = "|" + "|".join(["---"] * len(table.header)) + "|"

    chunks = []
    current_rows = []

    for row in table.data[1:]:  # 跳过表头行
        row_text = "| " + " | ".join(row) + " |"
        if len("\n".join([header_text, separator] + current_rows + [row_text])) > max_chars:
            if current_rows:
                chunks.append("\n".join([header_text, separator] + current_rows))
            current_rows = [row_text]
        else:
            current_rows.append(row_text)

    if current_rows:
        chunks.append("\n".join([header_text, separator] + current_rows))

    return chunks
```

**验证点**:
- [ ] 100+ 行费率表的分块结果
- [ ] 分块后检索结果是否包含表头

### 4.4 需要验证的技术假设

- [ ] **假设**: pdfplumber 的 `find_tables()` 返回顺序与页面顺序一致 → 验证方式：打印调试
- [ ] **假设**: Markdown 表格不会嵌套在其他块元素中 → 验证方式：检查现有法规文档
- [ ] **假设**: 跨页表格的第二页通常无表头 → 验证方式：检查保险产品 PDF 样本

---

## 五、潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 跨页表格误合并 | 中 | 高 | 设置高阈值(0.8) + 多条件判断 + 可回退日志 |
| 正则误识别表格 | 低 | 中 | 严格匹配表头+分隔行+数据行结构 |
| 性能下降 | 低 | 低 | 表格识别在预处理阶段一次完成 |
| 现有测试失败 | 低 | 高 | 增量修改 + 兼容性测试 |

---

## 六、参考实现

### 6.1 Markdown 表格识别

- [Python markdown 库的表格扩展](https://python-markdown.github.io/extensions/tables/) - 标准表格语法参考
- [marko 表格解析器](https://github.com/frostming/marko/blob/main/marko/parse.py) - 轻量级实现参考

### 6.2 PDF 跨页表格

- [tabula-py 跨页表格处理](https://github.com/chezou/tabula-py) - Java 实现参考
- [camelot 跨页检测逻辑](https://github.com/camelot-dev/camelot) - 启发式规则参考

### 6.3 表格分块最佳实践

- 参考文章《字节面试官懵了：你的 Chunk 切分就是无脑按 500 字一刀切？》- 表格完整性保护
- 参考文章《阿里面试官怒了：RAG 你 chunk 还在用固定 512》- 跨页表格处理

---

## 七、改动影响评估

### 7.1 兼容性影响

| 组件 | 影响程度 | 说明 |
|------|---------|------|
| MdParser 公开接口 | 无影响 | parse_document() 签名不变 |
| 现有测试用例 | 低影响 | 需验证输出 chunk 数量可能变化 |
| 向量索引重建 | 可能需要 | 表格 chunk 内容变化 |

### 7.2 性能影响

| 操作 | 影响 | 说明 |
|------|------|------|
| Markdown 解析 | +5-10% | 新增表格识别步骤 |
| PDF 解析 | +10-15% | 新增跨页检测逻辑 |
| 向量索引大小 | 可能增大 | 表格作为独立 chunk |

---

## 八、总结

### 8.1 主要发现

1. **Markdown 表格**: 当前 `md_parser.py` 无表格识别，表格会被 `_recursive_chunk()` 按段落切分
2. **PDF 跨页表格**: `pdf_parser.py` 逐页独立处理，无跨页合并逻辑
3. **表头信息**: `PremiumTable` 有 data 字段但未分离表头，需要增强
4. **可复用基础**: 现有的递归分块、句子边界检测、层级识别等机制设计良好，可在此基础上扩展

### 8.2 关键风险

- 跨页表格检测的准确性依赖启发式规则，需要实际数据验证
- 表格整体作为 chunk 可能超出 max_chunk_chars 限制

### 8.3 下一步行动

1. 实现 Markdown 表格识别（FR-001）- 预计 1 天
2. 实现 PDF 跨页表格合并（FR-002）- 预计 2 天
3. 增强 PremiumTable 表头存储（FR-003）- 预计 0.5 天
4. 编写单元测试和集成测试 - 预计 1 天
5. 性能测试和优化 - 预计 0.5 天

**总预计工作量**: 5 天
