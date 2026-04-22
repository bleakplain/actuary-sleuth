# 产品文档解析结果审核页面 - 技术调研报告

生成时间: 2026-04-22
源规格: .claude/specs/020-doc-parser-review-page/spec.md

## 执行摘要

调研发现 `doc_parser` 模块当前未存储位置信息（页码、坐标），这是实现原文高亮定位的核心阻碍。建议扩展数据模型添加位置字段。知识库审核页面的左右分栏交互模式可直接复用，定位算法（去空白匹配+反算行号）已验证可行。审核状态管理可复用 `eval_samples` 表的模式。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 展示解析结果 | `scripts/lib/doc_parser/models.py` | 已有 AuditDocument 数据模型 |
| FR-002 原文定位高亮 | `scripts/lib/doc_parser/pd/*.py` | **缺失位置信息** |
| FR-003 复用知识库审核页面 | `scripts/web/src/pages/KnowledgePage.tsx` | 可复用分块验证 Modal |
| FR-004 审核流程集成 | `scripts/api/routers/eval.py` | 可复用 review 状态模式 |
| FR-005 审核状态标记 | `scripts/api/database.py` | eval_samples 有 review_status 字段 |

### 1.2 可复用组件

**后端**：
- `AuditDocument` (models.py:111-125): 解析结果数据模型，可直接用于 API 响应
- `Clause` (models.py:85-91): 条款模型，需扩展位置字段
- `PremiumTable` (models.py:94-99): 费率表模型
- `SectionDetector` (section_detector.py:29-101): 章节类型检测器

**前端**：
- `KnowledgePage.tsx` 分块验证 Modal (527-719行): 左右分栏布局、定位算法、高亮渲染
- `locateInSource()` (194-234行): 文本定位算法，去空白匹配+反算行号
- 高亮渲染 useEffect (66-99行): CSS `.kb-highlight` 类 + `scrollIntoView`
- `EvalPage.tsx` SampleDrawer (64-200行): 审核抽屉交互模式

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/doc_parser/models.py` | 修改 | Clause/PremiumTable 添加位置字段 |
| `scripts/lib/doc_parser/pd/docx_parser.py` | 修改 | 提取表格在文档中的位置 |
| `scripts/lib/doc_parser/pd/pdf_parser.py` | 修改 | 提取表格在 PDF 中的页码和 bbox |
| `scripts/api/routers/` | 新增 | 产品文档解析结果 API |
| `scripts/web/src/pages/` | 新增 | 产品文档审核页面 |

---

## 二、技术选型研究

### 2.1 位置信息存储方案

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| A. 文本匹配定位 | 无需修改解析器 | 长文档定位不准，无法处理重复文本 | 知识库 MD 文档 | ✅ 知识库 |
| B. 段落索引 | 改动小 | PDF 难以精确对应 | Word 文档 | ⚠️ 部分 |
| C. 页码+BBox | 精确定位 | 需大改解析器 | PDF 文档 | ✅ 推荐 |

**推荐方案**: 采用**混合策略**
- Word: 存储段落索引 + 表格索引
- PDF: 存储页码 + pdfplumber 提供的 bbox

### 2.2 数据模型扩展

```python
# models.py 扩展方案
@dataclass(frozen=True)
class Clause:
    number: str
    title: str
    text: str
    section_type: str = "clause"
    # 新增位置字段
    page_number: Optional[int] = None      # PDF 页码（从1开始）
    bbox: Optional[Tuple[float, float, float, float]] = None  # PDF 坐标 (x0, y0, x1, y1)
    table_index: Optional[int] = None      # 表格索引（Word）
    paragraph_index: Optional[int] = None  # 段落索引（Word）

@dataclass(frozen=True)
class PremiumTable:
    raw_text: str
    data: List[List[str]]
    remark: str = ""
    section_type: str = "premium_table"
    # 新增位置字段
    page_number: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    table_index: Optional[int] = None
```

### 2.3 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| pdfplumber | 已有 | PDF 解析，提供 bbox | ✅ |
| python-docx | 已有 | Word 解析 | ✅ |
| react-pdf | 新增 | 前端 PDF 预览 | 需评估 |

---

## 三、数据流分析

### 3.1 现有数据流

```
产品文档 → DocxParser/PdfParser.parse() → AuditDocument → [未持久化]
```

**关键问题**: 当前 `AuditDocument` 仅在内存中使用，未持久化存储。

### 3.2 新增/变更的数据流

```
新增:
产品文档 → DocxParser/PdfParser.parse() → AuditDocument (含位置信息)
         → 存储到数据库/文件 → API 暴露 → 前端展示

变更:
审核页面 → 调用 API 获取解析结果 + 原文预览 → 对照验证 → 提交审核状态
```

### 3.3 关键数据结构

```python
# 审核状态数据结构（复用 eval_samples 模式）
@dataclass(frozen=True)
class ParseReviewStatus:
    document_id: str
    review_status: str  # pending, approved, rejected
    reviewer: Optional[str]
    reviewed_at: Optional[datetime]
    review_comment: Optional[str]
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] pdfplumber bbox 坐标能否与前端 PDF 渲染器对应？
- [ ] Word 文档段落索引在不同打开方式下是否稳定？
- [ ] 大型 PDF（100+ 页）的前端渲染性能？

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| PDF 位置信息不准确 | 中 | 高 | 增加文本匹配作为 fallback |
| 原文预览性能问题 | 中 | 中 | 分页加载、虚拟滚动 |
| Word 文档格式多样 | 高 | 中 | 提供原文下载作为备选 |

---

## 五、参考实现

### 5.1 知识库审核页面定位算法

```tsx
// KnowledgePage.tsx:194-234
const locateInSource = useCallback((text: string) => {
  const lines = sourceContent.split('\n');
  const flatSource = sourceContent.replace(/\s+/g, '');
  const snippet = text.replace(/\s+/g, '').slice(0, 80);
  const pos = flatSource.indexOf(snippet);
  if (pos < 0) return;

  // 反算对应的源码行号
  let charCount = 0, startLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const lineLen = lines[i].replace(/\s+/g, '').length;
    if (charCount + lineLen > pos) { startLine = i; break; }
    charCount += lineLen;
  }
  // ...向上找标题行，向下找结束行
  setHighlightLines({ start: headerLine, end: endLine });
}, [sourceContent]);
```

### 5.2 审核状态 API

```python
# eval.py:553-565
@router.patch("/dataset/samples/{sample_id}/review")
async def review_sample(sample_id: str, request: ReviewRequest):
    # 更新 review_status, reviewer, reviewed_at, review_comment
    return await update_sample_review(sample_id, request)
```

### 5.3 分块验证 Modal 布局

```tsx
// KnowledgePage.tsx:634-665 (桌面端)
<div style={{ display: 'flex', height: '100%' }}>
  <div style={{ width: '45%', height: '100%', borderRight: '...' }}>
    {/* 原文预览 */}
    <ReactMarkdown>{sourceContent}</ReactMarkdown>
  </div>
  <div style={{ width: '55%', height: '100%' }}>
    {/* 提取条款列表 */}
    <Table onRow={(record) => ({
      onClick: () => { setSelectedChunk(record); locateInSource(record.text); }
    })} />
  </div>
</div>
```

---

## 六、实现建议

### 6.1 阶段一：最小可行版本

1. 复用知识库审核页面布局
2. 采用文本匹配定位（先支持已转 MD 的文档）
3. 新增解析结果存储和 API

### 6.2 阶段二：精确位置支持

1. 扩展 Clause/PremiumTable 添加位置字段
2. 修改解析器提取位置信息
3. 前端支持 PDF 预览 + bbox 高亮

### 6.3 阶段三：审核闭环

1. 审核状态持久化
2. 审核历史记录
3. 错误修正反馈机制
