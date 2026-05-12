# Implementation Plan: 合规审核准确性提升

**Branch**: `033-compliance-audit-accuracy` | **Date**: 2026-05-12 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

用户在审核报告时发现两个核心问题：(1) 条款检查项不完整，(2) 检查项引用的法规条文与实际检查内容不对应。深度代码审计识别出 18 个问题（5 高 / 10 中 / 3 低）。

本方案按优先级分三个阶段修复：
- **Phase 1 (P0)**: 修复直接影响审查准确性的 3 个问题 — 分批丢弃首条款前文本、source_ref 失败保留编造 requirement、prompt 未约束 R 编号范围
- **Phase 2 (P1)**: 修复影响报告质量的 4 个问题 — 负面清单法规隐藏、batch 失败丢弃结果、不完整 items 过滤、LLM max_tokens 截断
- **Phase 3 (P2)**: 修复需要较大改动的 5 个问题 — HTML 解析器、backfill 语义校验、DOCX 段落条款提取、条款覆盖率不全、分类采样窗口

## Technical Context

**Language/Version**: Python 3.x + TypeScript (React)
**Primary Dependencies**: FastAPI, Pydantic, python-docx, ZhipuAI SDK
**Storage**: SQLite (reports), LanceDB (regulations)
**Testing**: pytest + React Testing Library
**Constraints**: 不得修改知识库数据；改动限于现有模块；不能引入新依赖（Phase 3 除外）

## Constitution Check

- [x] Library-First: 所有修复复用现有模块（re、json、logging），Phase 3 HTML 解析引入 htmldocx 库
- [x] 测试优先: 每个 Phase 包含单元测试更新
- [x] 简单优先: P0/P1 修复均为小改动（1-10 行），P2 才涉及较大重构
- [x] 显式优于隐式: 将隐式的 `if not item.get("requirement")` 守卫改为显式覆盖逻辑
- [x] 可追溯性: 每个 Phase 回溯到 spec.md 的 User Story
- [x] 独立可测试: 每个 Phase 独立可验证

## Project Structure

### Documentation

```text
.claude/specs/033-compliance-audit-accuracy/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/compliance/
├── checker.py       # Phase 1, 2, 3 核心修改
├── prompts.py       # Phase 1 prompt 修改
scripts/lib/common/
├── html_converter.py # Phase 3 HTML 解析器重写
scripts/api/routers/
├── compliance.py    # Phase 2 路由修改
scripts/lib/llm/
├── zhipu.py         # Phase 2 max_tokens 调整
scripts/tests/compliance/
├── test_checker.py  # 测试更新
```

## Implementation Phases

### Phase 1: Core Accuracy Fixes (P0) — US1 + US2

#### 需求回溯

→ 对应 spec.md User Story 1 (SC-001 条款覆盖率 ≥ 80%)
→ 对应 spec.md User Story 2 (SC-003 source_ref 匹配率 ≥ 95%)

#### 实现步骤

##### Step 1: 修复 `_split_by_clauses` 丢弃首条款前文本 (H1)

**文件**: `scripts/lib/compliance/checker.py:354`

**当前代码**:
```python
current_start = clause_positions[0]
```

**修复后**:
```python
current_start = 0
```

首条款前的文本（产品概述、保险责任等）不再被丢弃，作为第一个 batch 的开头部分。

##### Step 2: 修复 source_ref 匹配失败时保留 LLM 编造 requirement (H2)

**文件**: `scripts/lib/compliance/checker.py:328-335`

**当前代码**:
```python
else:
    item["chunk_id"] = None
    if ref:
        logger.warning(f"source_ref 匹配失败: {ref}")
    if not item.get("requirement"):
        item["requirement"] = "法规来源待确认"
    if not item.get("source_excerpt"):
        item["source_excerpt"] = ""
```

**修复后**:
```python
else:
    item["chunk_id"] = None
    if ref:
        logger.warning(f"source_ref 匹配失败: {ref}")
        item["requirement"] = f"法规来源待确认（引用 {ref} 未匹配）"
    else:
        item["requirement"] = "法规来源待确认"
    item["source_excerpt"] = ""
```

关键变化：移除 `if not item.get("requirement")` 守卫。LLM 总是输出 requirement，原守卫永远为 False，导致 LLM 编造内容被保留。修复后，匹配失败时始终覆盖为明确的"待确认"文本，`source_excerpt` 清空避免展示不相关内容。

##### Step 3: prompt 约束 R 编号有效范围 (M3)

**文件**: `scripts/lib/compliance/prompts.py:34`

**当前代码**:
```python
2. source_ref 必须是上面法规的编号（如 R1、R5、R12），引用与该条款最相关的法规
```

**修复后**:
```python
2. source_ref 必须是上面法规的编号，范围为 R1 到 R{regulation_count}，引用与该条款最相关的法规
```

显式告知 LLM 有效范围，减少超出范围的 source_ref 输出。

##### Step 4: 更新测试

**文件**: `scripts/tests/compliance/test_checker.py`

新增/更新测试用例：
- `_split_by_clauses` 首条款前有文本时，文本被包含在第一个 batch
- `run_compliance_check` source_ref 匹配失败时，requirement 被覆盖为"法规来源待确认"
- source_ref 为空时，requirement 为"法规来源待确认"
- source_ref 有效时，requirement 为法规内容（行为不变）

---

### Phase 2: Report Quality Fixes (P1) — US1 + US2

#### 需求回溯

→ 对应 spec.md User Story 1 (FR-001 条款覆盖)
→ 对应 spec.md User Story 2 (FR-005 不确定项标注)

#### 实现步骤

##### Step 1: 无违规时也展示负面清单法规 (M2)

**文件**: `scripts/api/routers/compliance.py:74-76`

**当前代码**:
```python
if negative_items:
    result["items"].extend([item.__dict__ for item in negative_items])
    result["regulation_sources"]["负面清单"] = [r.law_name for r in negative_regulations]
```

**修复后**:
```python
if negative_items:
    result["items"].extend([item.__dict__ for item in negative_items])
if negative_regulations:
    result["regulation_sources"]["负面清单"] = [r.law_name for r in negative_regulations]
```

负面清单法规来源始终展示，无论是否有违规项。

##### Step 2: batch 失败时保留已收集结果 (M5)

**文件**: `scripts/lib/compliance/checker.py:392-395`

**当前代码**:
```python
batch_result = run_compliance_check(prompt, regulations=regulations)
if "error" in batch_result:
    return batch_result
all_items.extend(batch_result.get("items", []))
```

**修复后**:
```python
batch_result = run_compliance_check(prompt, regulations=regulations)
if "error" in batch_result:
    logger.warning(f"分批检查 {i + 1}/{len(batches)} 失败: {batch_result['error']}")
    partial_error = True
    continue
all_items.extend(batch_result.get("items", []))
```

在 `batch_compliance_check` 开头增加 `partial_error = False`，返回时在结果中标注：
```python
result = {"summary": {...}, "items": all_items}
if partial_error:
    result["partial_error"] = True
return result
```

路由层检查 `result.get("partial_error")` 时记录警告但不 raise HTTPException，已收集的结果正常返回。

##### Step 3: 过滤不完整 items (M7)

**文件**: `scripts/lib/compliance/checker.py:318` 之后

在 `items = result.get("items", [])` 之后，过滤 status 无效的 items：

```python
items = result.get("items", [])
valid_statuses = {"compliant", "non_compliant", "attention"}
items = [item for item in items if item.get("status") in valid_statuses]
result["items"] = items
```

JSON 修复产生的不完整 items（status 为空或非法值）被过滤，避免 summary 统计丢失。

##### Step 4: 增加 LLM max_tokens 配置 (M4)

**文件**: `scripts/lib/llm/zhipu.py:139`

GLM-4-Flash 输出 tokens 硬限制为 8192，无法通过参数突破。因此不改默认 max_tokens，改为在 `batch_compliance_check` 中通过分批策略控制每个 batch 的条款数量，确保单次 LLM 响应不超限。

**文件**: `scripts/lib/compliance/checker.py` — `batch_compliance_check` 函数

在单批检查路径中，计算单批文档预期条款数，如果超过 15 条则主动分割：

```python
# 在 len(document_content) <= budget 的单批路径中不变
# 在 _split_by_clauses 中增加更细粒度的分割，确保每批条款数 ≤ 15
```

具体改动在 `_split_by_clauses`：在按条款边界分割的基础上，对每个 batch 内的条款数量计数，如果单批超过 15 个条款标记则在该范围内进一步分割。

**实际改动量**：在 `_split_by_clauses` 的循环中增加条款计数器，当 `batch_clause_count > 15` 时强制切割。

##### Step 5: 更新测试

**文件**: `scripts/tests/compliance/test_checker.py`

- batch 失败时部分结果被保留
- 不完整 items（status 为空）被过滤
- 负面清单无违规时 regulation_sources 仍包含负面清单

---

### Phase 3: Deep Fixes (P2) — US1 + US2

#### 需求回溯

→ 对应 spec.md User Story 1 (FR-001 全条款覆盖)
→ 对应 spec.md User Story 2 (FR-004 不得引用不相关法规)

#### 实现步骤

##### Step 1: HTML 解析器扩展 (H3)

**文件**: `scripts/lib/common/html_converter.py`

扩展 `SimpleHTMLParser` 支持更多标签：
- `<div>`, `<section>` → 同 `<p>` 处理（开启 in_p 标志）
- `<ul>`, `<ol>` → 列表容器，列表项间插入换行
- `<li>` → 同 `<p>` 处理，闭合时添加前缀标记（如 "• "）
- `<br>` → 在 current_text 中添加换行符

**具体改动**:

`handle_starttag` 新增标签处理：
```python
elif tag in ('div', 'section', 'li'):
    self.in_p = True
    self.current_text = ""
elif tag == 'br':
    if self.in_p:
        self.current_text += '\n'
    elif self.in_cell:
        self.current_cell += '\n'
```

`handle_endtag` 新增标签处理：
```python
elif tag in ('div', 'section') and self.in_p:
    self.in_p = False
    text = self.current_text.strip()
    if text:
        self.paragraphs.append(text)
elif tag == 'li' and self.in_p:
    self.in_p = False
    text = self.current_text.strip()
    if text:
        self.paragraphs.append(f"• {text}")
elif tag in ('ul', 'ol'):
    if self.paragraphs:
        self.paragraphs.append("")
```

##### Step 2: backfill 语义相关性校验 (H4)

**文件**: `scripts/lib/compliance/checker.py:324-327`

在 matched 分支中增加简单校验：检查 item 的 param 关键词是否出现在 matched 法规内容中。如果不相关，在 requirement 前添加警告标记。

```python
if matched:
    item["chunk_id"] = matched.chunk_id
    # 将 param 按中文 2-gram 拆分，提升匹配率
    param_text = item.get("param", "").replace("、", " ").replace("：", " ")
    param_keywords = set()
    for word in param_text.split():
        if len(word) >= 2:
            param_keywords.add(word)
        if len(word) >= 4:
            for j in range(len(word) - 1):
                param_keywords.add(word[j:j+2])
    content_text = matched.content[:500]
    is_relevant = any(kw in content_text for kw in param_keywords if len(kw) >= 2)
    if is_relevant:
        item["requirement"] = f"{matched.law_name}: {matched.content[:200]}"
    else:
        item["requirement"] = f"[法规相关性待确认] {matched.law_name}: {matched.content[:200]}"
        logger.info(f"法规相关性低: param={item.get('param')}, regulation={matched.law_name}")
    item["source_excerpt"] = matched.content[:300]
```

关键词匹配策略：
- 先按空格和中文标点拆分 param
- 对长度 ≥ 4 的词，额外提取所有 2-gram（如"保险金额及给付比例" → "保险"、"险金"、"金额"、"额及"、"及给"、"给付"、"付比"、"比例"）
- 对长度 2-3 的词直接使用（如"等待期"、"免赔额"）
- 检查关键词是否出现在法规内容前 500 字中
- 误报可接受（宁可多标记），漏报风险低（保险法规内容通常包含相关术语）

##### Step 3: 扩展条款覆盖率计算 (M1)

**文件**: `scripts/lib/compliance/checker.py:61-62` 和 `scripts/api/routers/compliance.py:86-95`

**checker.py** — 新增 `extract_section_numbers`，内部调用 `extract_clause_numbers` 避免重复：

```python
def extract_section_numbers(document_content: str) -> Dict[str, Any]:
    clauses = extract_clause_numbers(document_content)
    return {
        "clauses": clauses,
        "has_notices": bool(re.search(r'【投保须知】', document_content)),
        "has_health": bool(re.search(r'【健康告知】', document_content)),
        "has_exclusions": bool(re.search(r'【责任免除】', document_content)),
        "has_tables": bool(re.search(r'【数据表 \d+】', document_content)),
    }
```

`extract_clause_numbers` 保持不变（仍被 `compliance.py` 直接调用用于 clause_set 计算）。

**compliance.py** — 使用新的 section 信息丰富 clause_coverage：
```python
section_info = extract_section_numbers(req.document_content)
doc_clause_set = set(section_info["clauses"])
# checked_clause_set 逻辑不变（仍基于 clause_number 交集）
result["clause_coverage"] = {
    "total": len(doc_clause_set),
    "checked": len(checked_clause_set & doc_clause_set),
    "unchecked": list(doc_clause_set - checked_clause_set),
    "has_notices": section_info["has_notices"],
    "has_health": section_info["has_health"],
    "has_exclusions": section_info["has_exclusions"],
    "has_tables": section_info["has_tables"],
}
```

**前端** — `scripts/web/src/types/index.ts`：

`ComplianceResult.clause_coverage` 类型更新：
```typescript
clause_coverage: {
  total: number;
  checked: number;
  unchecked: string[];
  has_notices?: boolean;
  has_health?: boolean;
  has_exclusions?: boolean;
  has_tables?: boolean;
} | null;
```

`CompliancePage.tsx` — 在遗漏条款提示下方展示非条款区块信息：
```tsx
{docResult.clause_coverage && (
  docResult.clause_coverage.has_notices ||
  docResult.clause_coverage.has_exclusions
) && (
  <div style={{ marginTop: 8, color: '#666', fontSize: 12 }}>
    文档还包含：
    {docResult.clause_coverage.has_notices && <Tag>投保须知</Tag>}
    {docResult.clause_coverage.has_health && <Tag>健康告知</Tag>}
    {docResult.clause_coverage.has_exclusions && <Tag>责任免除</Tag>}
    {docResult.clause_coverage.has_tables && <Tag>数据表</Tag>}
    等区块已纳入审查范围
  </div>
)}
```

新增 `import { Tag } from 'antd'`（如尚未导入）。

##### Step 4: 增大分类采样窗口 (M8)

**文件**: `scripts/lib/compliance/checker.py:242, 256`

```python
# 当前
classify_product(product_name, document_content[:1000])
document_content[:2000]

# 修复后
classify_product(product_name, document_content[:5000])
document_content[:5000]
```

##### Step 5: DOCX 段落条款提取 (H5)

**文件**: `scripts/lib/doc_parser/pd/docx_parser.py`

修改 `parse` 方法，增加段落条款提取备选路径：

```python
def parse(self, file_path: str) -> AuditDocument:
    path = Path(file_path)
    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    try:
        doc = Document(file_path)
    except Exception as e:
        raise DocumentParseError("Word 文件解析失败", file_path, str(e))

    warnings: List[str] = []

    clauses = self._extract_clauses_from_tables(doc.tables, warnings)
    if len(clauses) < 5:
        para_clauses = self._extract_clauses_from_paragraphs(doc.paragraphs, warnings)
        if len(para_clauses) > len(clauses):
            clauses = para_clauses
    tables = self._extract_tables(doc.tables, warnings)
    sections = self._extract_sections(doc.paragraphs, warnings)

    return AuditDocument(
        file_name=path.name,
        file_type='.docx',
        clauses=clauses,
        tables=tables,
        notices=sections['notices'],
        health_disclosures=sections['health_disclosures'],
        exclusions=sections['exclusions'],
        rider_clauses=sections['rider_clauses'],
        parse_time=datetime.now(),
        warnings=warnings,
    )
```

新增 `_extract_clauses_from_paragraphs` 方法，复用 PDF 解析器的正则匹配逻辑：

```python
def _extract_clauses_from_paragraphs(self, paragraphs: List, warnings: List[str]) -> List[Clause]:
    """从段落文本中提取条款，当表格提取结果不足时使用。"""
    clauses: List[Clause] = []
    for para in paragraphs:
        text = para.text.strip()
        if not text:
            continue
        match = re.match(r'^(\d+\.\d+(?:\.\d+)*)\s+(.+)$', text)
        if match:
            number = match.group(1)
            rest = match.group(2).strip()
            title, content = split_title_and_content(rest)
            clauses.append(Clause(number=number, title=title, text=content))
    if clauses:
        warnings.append(f"从段落提取了 {len(clauses)} 条条款（表格提取不足）")
    return clauses
```

条件：仅当从表格提取的条款 < 5 条时启用。如果段落提取数量更多则使用段落结果，否则保留表格结果。已导入的 `split_title_and_content` 从 `.utils` 复用，`re` 已在文件顶部导入。

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| Phase 3 H4 语义校验 | 关键词匹配可能误报 | 不做校验（风险：27.8% 错误匹配被掩盖）→ 排除：用户明确反馈法规不一致 |
| Phase 3 H5 DOCX 段落提取 | 增加解析复杂度 | 强制用户使用 PDF → 排除：DOCX 是主要输入格式 |

## Appendix

### 执行顺序建议

```
Phase 1 (P0) → Phase 2 (P1) → Phase 3 (P2)
Phase 1 内部: Step 1, 2, 3 可并行（不同文件），Step 4 依赖 1-3
Phase 2 内部: Step 1, 2, 3 可并行，Step 4 依赖 2, 3，Step 5 依赖全部
Phase 3 内部: Step 1, 4 可并行，Step 2, 3, 5 可并行
```

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 (SC-001) | 条款覆盖率 ≥ 80% | test_checker: 分批不丢失首条款前内容 |
| US1 (FR-003) | clause_coverage 展示已检查/未检查 | test_checker: extract_section_numbers |
| US2 (SC-002) | source_ref 语义相关率 ≥ 90% | test_checker: backfill 语义校验 |
| US2 (SC-003) | source_ref 匹配率 ≥ 95% | test_checker: 失败时覆盖 requirement |
| US2 (FR-005) | 不确定项标注"法规来源待确认" | test_checker: source_ref 为空/超范围 |

### 修改文件清单

| 文件 | Phase | 修改类型 |
|------|-------|----------|
| `scripts/lib/compliance/checker.py` | 1, 2, 3 | 修改 |
| `scripts/lib/compliance/prompts.py` | 1 | 修改 |
| `scripts/api/routers/compliance.py` | 2, 3 | 修改 |
| `scripts/lib/common/html_converter.py` | 3 | 修改 |
| `scripts/lib/llm/zhipu.py` | 2 | 修改 |
| `scripts/lib/doc_parser/pd/docx_parser.py` | 3 | 修改 |
| `scripts/web/src/types/index.ts` | 3 | 修改 |
| `scripts/tests/compliance/test_checker.py` | 1, 2, 3 | 修改 |
