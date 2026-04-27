# 保险产品合规检查 - 技术调研报告

生成时间: 2026-04-23 17:30:00
源规格: .claude/specs/022-compliance-check/spec.md

## 执行摘要

1. **现有基础完备**：合规检查 API、文档解析、RAG 检索、前端页面均已实现，核心功能可复用
2. **分步操作已实现**：前端 `CompliancePage.tsx` 已支持"上传→解析→确认→检查"流程，后端 `parse-file` 和 `check/document` 接口分离
3. **法条溯源已支持**：检查结果包含 `source`（引用格式 `[来源X]`）和 `source_excerpt`（原文摘录），前端可点击查看详情
4. **待完善项**：报告导出（PDF/Word）、报告对比、测试验证流程
5. **风险评估**：LLM 输出格式不稳定、法规检索结果质量依赖 RAG 索引

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 分步操作 | `api/routers/compliance.py:parse-file`, `CompliancePage.tsx:DocumentReviewPanel` | **已实现** |
| FR-002 法条溯源 | `compliance.py:_COMPLIANCE_PROMPT_*`, `CompliancePage.tsx:SourceDrawer` | **已实现** |
| FR-003 报告管理 | `api/database.py:compliance_reports`, `CompliancePage.tsx` history tab | **部分实现**（缺少导出/对比） |
| FR-004 文档解析 | `lib/doc_parser/pd/parser.py:parse_product_document` | **已实现** |
| FR-005 RAG 检索 | `lib/rag_engine/rag_engine.py:search`, `ask` | **已实现** |
| FR-006 无结果处理 | `compliance.py:_run_compliance_check` | **需增强**（当前仅返回空 items） |
| FR-007 测试验证 | `scripts/web/e2e/compliance.spec.ts` | **部分实现**（仅有 E2E 测试） |

### 1.2 可复用组件

**后端**：
- `RAGEngine.search(query, top_k=10)` — 法规检索，返回 `List[Dict]` 包含 `law_name`, `article_number`, `content`, `score` 等
- `RAGEngine.ask(question)` — 问答模式，返回答案 + 引用来源
- `parse_product_document(file_path)` — 产品文档解析，返回 `AuditDocument`
- `_build_context(search_results)` — 构建法规上下文字符串
- `_run_compliance_check(engine, prompt)` — 执行 LLM 合规检查

**前端**：
- `DocumentReviewPanel` — 文档审查面板，支持上传/解析/确认流程
- `SourceDrawer` — 法条来源详情抽屉
- `complianceApi` — API 客户端

**数据模型**：
- `AuditDocument`, `Clause`, `PremiumTable`, `DocumentSection` — 文档解析结果
- `ComplianceReport`, `ComplianceItem`, `ComplianceResult` — 检查报告结构
- `Source`, `Citation` — 法条引用结构

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `api/routers/compliance.py` | 修改 | 增强法规无结果处理、支持报告对比 API |
| `api/schemas/compliance.py` | 新增 | 添加 `ReportCompareRequest`, `ReportCompareResponse` |
| `api/database.py` | 修改 | 添加报告对比查询函数 |
| `lib/reporting/` | 新增 | 报告导出模块（PDF/Word 生成） |
| `scripts/web/src/pages/CompliancePage.tsx` | 修改 | 添加报告导出/对比 UI |
| `scripts/web/src/api/compliance.ts` | 修改 | 添加导出/对比 API 调用 |
| `scripts/tests/compliance/` | 新增 | 合规检查测试验证流程 |

---

## 二、技术选型研究

### 2.1 报告导出方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 选择 |
|------|------|------|---------|------|
| python-docx 生成 Word | 项目已有依赖、格式灵活 | 需手动排版 | Word 导出 | ✅ |
| reportlab 生成 PDF | 专业 PDF 库、中文支持好 | 学习曲线陡、需新增依赖 | PDF 导出 | ❌ |
| WeasyPrint HTML→PDF | 简单、前端模板复用 | 依赖系统字体、渲染慢 | 快速实现 | ✅ |
| jsPDF 前端生成 | 无需后端、离线可用 | 中文字体配置复杂 | 前端导出 | ❌ |

**推荐方案**：后端使用 `WeasyPrint`（HTML→PDF）和 `python-docx`（Word），复用前端报告样式。

### 2.2 报告对比方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 字段级 diff | 精确、可视化差异 | 实现简单 | ✅ |
| 文本相似度 | 自动化程度高 | 语义差异难捕捉 | ❌ |

**实现思路**：对比两个报告的 `items` 列表，按 `param` 匹配，标注新增/删除/状态变更。

### 2.3 测试验证方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 真实产品文档 + 人工标注 | 贴近实际场景 | 标注成本高 | ✅ 主 |
| 合成测试数据 | 成本低、可控 | 可能偏离实际 | ✅ 辅 |
| 回归测试 | 自动化、持续 | 需先建立基准 | ✅ 辅 |

**测试流程**：
1. 准备测试集：`/mnt/d/work/actuary-assets/products/` 下的真实产品文档
2. 执行自动检查：调用 `check/document` API
3. 对比人工结果：一致性统计、差异分析
4. 生成验证报告：记录准确率、问题分布

### 2.4 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| weasyprint | 60.x | PDF 导出 | 需安装系统依赖 (pango, cairo) |
| python-docx | 已有 | Word 导出 | 无问题 |
| jinja2 | 已有 | 报告模板 | 无问题 |

---

## 三、数据流分析

### 3.1 现有数据流

```
用户上传文档
    ↓
POST /api/compliance/parse-file
    ↓ parse_product_document()
AuditDocument (clauses, premium_tables, ...)
    ↓ 用户确认
POST /api/compliance/check/document
    ↓ RAGEngine.search() → _build_context()
    ↓ LLM 生成检查结果
ComplianceReport (result.items with source/source_excerpt)
    ↓ save_compliance_report()
SQLite (compliance_reports 表)
```

### 3.2 新增/变更的数据流

**报告导出**：
```
GET /api/compliance/reports/{id}/export?format=pdf|docx
    ↓ 查询报告 + sources
    ↓ 渲染模板 (jinja2)
    ↓ WeasyPrint / python-docx
文件下载
```

**报告对比**：
```
POST /api/compliance/reports/compare
    ↓ 查询两个报告
    ↓ diff items by param
    ↓ 标注变更类型 (added/removed/changed)
ReportCompareResponse
```

**测试验证**：
```
测试集 (产品文档 + 人工结果)
    ↓ 批量执行 check/document
    ↓ 对比自动结果 vs 人工结果
    ↓ 计算一致性指标
验证报告 (accuracy, confusion_matrix)
```

### 3.3 关键数据结构

**报告对比结果**：
```python
@dataclass
class ReportDiff:
    added_items: List[CheckItem]       # 新增问题
    removed_items: List[CheckItem]     # 已修复问题
    changed_items: List[ChangedItem]   # 状态变更

@dataclass
class ChangedItem:
    param: str
    old_status: str
    new_status: str
    old_value: str
    new_value: str
```

**测试验证结果**：
```python
@dataclass
class ValidationReport:
    total_samples: int
    accuracy: float                    # 一致性比例
    by_status: Dict[str, float]        # 分状态准确率
    mismatches: List[MismatchDetail]   # 差异详情

@dataclass
class MismatchDetail:
    sample_id: str
    auto_result: CheckItem
    human_result: CheckItem
    diff_description: str
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [x] 文档解析准确率 >= 90% — 已在 015-document-parser spec 中定义，待验证
- [ ] RAG 检索召回率 — 需用真实产品条款验证法规检索覆盖率
- [ ] LLM 输出格式稳定性 — 需测试多次调用结果一致性
- [x] 法条引用格式 `[来源X]` — 已实现，前端可解析

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| LLM 输出 JSON 解析失败 | 中 | 高 | 已有 fallback：返回原始输出供人工审查 |
| 法规检索无结果 | 中 | 中 | 标注为 `attention`，提示用户检查知识库 |
| 文档解析失败 | 低 | 高 | 前端阻止检查，显示解析错误 |
| 报告导出中文乱码 | 低 | 中 | WeasyPrint 配置中文字体 |
| 测试验证数据不足 | 中 | 低 | 先用少量样本验证流程，逐步扩充 |

---

## 五、现有实现细节

### 5.1 合规检查 Prompt 模板

**产品参数检查**（`compliance.py:24-61`）：
```
你是一位保险法规合规专家。请根据以下产品参数和相关法规条款，逐项检查该产品是否符合法规要求。

## 产品信息
- 产品名称：{product_name}
- 险种类型：{category}
- 产品参数：{params_json}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{
    "summary": {"compliant": N, "non_compliant": M, "attention": K},
    "items": [
        {
            "param": "参数名称",
            "value": "产品实际值",
            "requirement": "法规要求，引用法规原文关键句",
            "status": "compliant|non_compliant|attention",
            "source": "[来源X]",
            "source_excerpt": "从来源法规中直接摘录的原文片段",
            "suggestion": "修改建议，仅不合规时填写"
        }
    ]
}
```

**条款文档审查**（`compliance.py:63-102`）：
- 类似结构，增加 `extracted_params` 字段
- 先提取条款关键参数，再逐项检查

### 5.2 法规上下文构建

**`_build_context()` 函数**（`compliance.py:106-123`）：
```python
def _build_context(search_results: list) -> str:
    parts = []
    for i, r in enumerate(search_results):
        law_name = r.get('law_name', '')
        article = r.get('article_number', '')
        content = r.get('content', '')
        authority = r.get('issuing_authority', '')
        doc_number = r.get('doc_number', '')
        effective = r.get('effective_date', '')
        header = f"[来源{i+1}] 【{law_name}】{article}"
        if doc_number:
            header += f"（{doc_number}）"
        if authority:
            header += f"\n发布机关：{authority}"
        if effective:
            header += f"\n生效日期：{effective}"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)
```

**输出格式**：
```
[来源1] 【健康保险管理办法】第三条（银保监会令2019年第3号）
发布机关：中国银行保险监督管理委员会
生效日期：2019-12-01
健康保险产品条款应当明确约定等待期...
```

### 5.3 前端分步操作实现

**`DocumentReviewPanel` 组件**（`CompliancePage.tsx:119-327`）：
- 左侧：原文展示（DocumentViewer 或 TextArea）
- 右侧：解析结果（Collapse 折叠面板）
- 操作：上传文件 → 解析 → 确认并检查

**关键状态**：
```typescript
const [parsedDocument, setParsedDocument] = useState<ParsedDocument | null>(null);
const [uploadedFile, setUploadedFile] = useState<File | null>(null);
const [checkingResult, setCheckingResult] = useState<ComplianceReport | null>(null);
```

**流程**：
1. `handleFileUpload` → 调用 `parseFile` API → 设置 `parsedDocument`
2. 用户查看解析结果
3. `handleConfirmReview` → 调用 `checkDocument` API → 设置 `checkingResult`

### 5.4 法条溯源展示

**`SourceDrawer` 组件**（`CompliancePage.tsx:26-117`）：
- 点击检查项的 `[来源X]` 标签触发
- 展示法规详情：名称、条款、文号、机关、生效日期
- 高亮引用原文片段
- 显示法规全文

---

## 六、测试覆盖分析

### 6.1 现有测试

| 测试文件 | 类型 | 覆盖内容 |
|---------|------|---------|
| `scripts/web/src/api/compliance.test.ts` | 单元测试 | API 调用 mock 测试 |
| `scripts/web/e2e/compliance.spec.ts` | E2E 测试 | 产品参数检查、文档审查、历史列表 |

### 6.2 测试建议

**后端测试**（新增）：
- `test_compliance_check.py` — 检查结果格式验证
- `test_report_export.py` — 导出功能测试
- `test_report_compare.py` — 对比功能测试

**集成测试**（新增）：
- `test_validation_flow.py` — 测试验证流程
- 使用 `scripts/tests/fixtures/` 下的测试文档

**测试数据准备**：
```
scripts/tests/fixtures/compliance/
├── sample_product_1.pdf        # 测试产品文档
├── sample_product_1.json       # 人工标注结果
├── sample_product_2.docx
├── sample_product_2.json
└── ...
```

---

## 七、参考实现

- [python-docx 文档](https://python-docx.readthedocs.io/) — Word 文档生成
- [WeasyPrint 文档](https://doc.courtbouillon.org/weasyprint/) — HTML 转 PDF
- [Ant Design Table](https://ant.design/components/table) — 前端表格组件
- [现有 CompliancePage](scripts/web/src/pages/CompliancePage.tsx) — 前端实现参考
