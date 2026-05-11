# 合规审查 source 准确性修复 - 实现方案

源规格: .claude/specs/032-compliance-source-accuracy/research.md
生成时间: 2026-05-11

---

## Technical Context

- LLM: glm-4-flash via Zhipu API
- RAG: LanceDB v4, 329 条法规，每条有全局唯一 UUID `id` 字段
- `(law_name, article_number)` 组合全局唯一（329 条零重复）
- DB 存储: `compliance_reports.result_json` 为 opaque JSON，无 source_id 列

## 系统流程

```
1. load_audit_regulations(category)
   RAG → search_by_metadata → AuditRegulationItem(chunk_id, law_name, article_number, ...)

2. build_audit_context(regulations)
   AuditRegulationItem[] → 拼接法规上下文字符串，每条用 【{law_name}-{article_number}】 标识

3. LLM 调用
   prompt(文档 + 法规上下文) → LLM → JSON(items[], 每个 item 含 source_ref)

4. 解析
   source_ref → 精确匹配 AuditRegulationItem（ref == f"{law_name}-{article_number}"）→ 取 chunk_id

5. 输出
   AuditResultItem(chunk_id, ...) + AuditRegulationItem(chunk_id, ...) → API JSON (regulations) → 前端 regulationMap[chunk_id]
```

## 核心设计

**`chunk_id`（RAG UUID）贯穿全链路。`source_ref` 是 LLM 输出中引用法规的标识，解析时用它精确匹配到 AuditRegulationItem，取 chunk_id 写入 AuditResultItem。source_ref 不出现在 API 和前端。**

---

## Phase 1: RAG 层补齐 chunk_id

**文件**: `scripts/lib/rag_engine/rag_engine.py:532`

```python
results.append({
    'id': row.get('id', ''),
    'law_name': meta.get('law_name', ''),
    ...
})
```

---

## Phase 2: 数据模型

### 2a. AuditRegulationItem（原 AuditSource）

```python
@dataclass(frozen=True)
class AuditRegulationItem:
    chunk_id: str       # RAG UUID
    law_name: str
    article_number: str
    content: str
    source_type: str    # "category" | "general" | "negative_list"
    doc_number: str = ""
    issuing_authority: str = ""
    effective_date: str = ""
```

### 2b. AuditResultItem（原 AuditItem）

`source_id: Optional[int]` → `chunk_id: Optional[str]`

### 2c. load_audit_regulations（原 load_audit_sources）

```python
regulations.append(AuditRegulationItem(
    chunk_id=r.get("id", ""),
    law_name=r.get("law_name", ""),
    article_number=_extract_real_article_number(r.get("content", ""), r.get("article_number", "")),
    content=r.get("content", ""),
    ...
))
```

### 2d. 新增 _extract_real_article_number

保险法 content 以"第十三条　..."开头，提取实际法条号；其他法规保持"第X项"。

```python
def _extract_real_article_number(content: str, fallback: str) -> str:
    match = re.match(r'第([一二三四五六七八九十百零]+)条', content)
    return f"第{match.group(1)}条" if match else fallback
```

---

## Phase 3: LLM 交互层

### 3a. build_audit_context（原 format_context_for_llm）

用 `【{law_name}-{article_number}】` 标识每条法规。这个标识就是 source_ref 的值。

```python
def build_audit_context(regulations: List[AuditRegulationItem]) -> str:
    if not regulations:
        return ""
    parts = []
    for r in regulations:
        header = f"【{r.law_name}-{r.article_number}】"
        if r.doc_number:
            header += f"（{r.doc_number}）"
        if r.issuing_authority:
            header += f"\n发布机关：{r.issuing_authority}"
        if r.effective_date:
            header += f"\n生效日期：{r.effective_date}"
        parts.append(f"{header}\n{r.content}")
    return "\n\n".join(parts)
```

### 3b. prompts.py

法规检查 prompt: `"source_id": <数字>` → `"source_ref": "<对应上面【法规名-条目号】>"`

负面清单 prompt: `rule_id` → `source_ref`，rules_text 格式同步改为 `【法规名-条号】`

---

## Phase 4: 解析层

### 4a. _match_regulation_by_ref（原 _match_source_by_ref）

精确匹配：

```python
def _match_regulation_by_ref(ref: str, regulations: List[AuditRegulationItem]) -> Optional[AuditRegulationItem]:
    """精确匹配 source_ref → AuditRegulationItem"""
    for r in regulations:
        if ref == f"{r.law_name}-{r.article_number}":
            return r
    return None
```

### 4b. run_compliance_check

```python
def run_compliance_check(prompt: str, regulations: Optional[List[AuditRegulationItem]] = None) -> Dict:
    ...
    items = result.get("items", [])
    for item in items:
        if not item.get("clause_number"):
            item["clause_number"] = "未知"
        ref = item.pop("source_ref", "")
        matched = _match_regulation_by_ref(ref, regulations) if ref and regulations else None
        item["chunk_id"] = matched.chunk_id if matched else None
        if not matched and ref:
            logger.warning(f"source_ref 匹配失败: {ref}")
        item["check_type"] = "regulation"
        item["source_type"] = "regulation"
    return result
```

### 4c. check_negative_list + _parse_violation_response

regulations 构造改为 `chunk_id=doc.get("id", "")`。

`_parse_violation_response` 中删除 `rule_id` 索引，改用 source_ref 匹配：

```python
ref = v.pop("source_ref", "")
matched = _match_regulation_by_ref(ref, regulations) if ref and regulations else None
items.append(AuditResultItem(
    ...
    chunk_id=matched.chunk_id if matched else None,
    ...
))
```

### 4d. 路由层（compliance.py）

删除重新编号逻辑（`reg_count`、`renumbered_neg_sources`、`renumbered_neg_items`），直接合并。

`result["sources"]` → `result["regulations"]`，`regulation_sources` dict 保持不变。

删除重新编号块后，`AuditRegulationItem` 和 `AuditResultItem` 的 import 变为死代码，一并删除。

调用改为 `run_compliance_check(prompt, regulations=regulations)`。

---

## Phase 5: API + 前端

### 5a. schemas/compliance.py

- `AuditSourceOut` → `AuditRegulationItemResponse`，`source_id` → `chunk_id`
- `AuditItemOut` → `AuditResultItemResponse`，`source_id` → `chunk_id`
- `ComplianceResultOut` → `ComplianceReportDataResponse`，`sources` → `regulations`
- `ComplianceReportOut` → `ComplianceReportResponse`

### 5b. types/index.ts

- `AuditSource` → `AuditRegulationItem`，`source_id: number` → `chunk_id: string`
- `ComplianceItem` → `AuditResultItem`，`source_id: number | null` → `chunk_id: string | null`
- `ComplianceResult.sources` → `ComplianceResult.regulations`

### 5c. CompliancePage.tsx

API JSON key 统一重命名：`sources` → `regulations`。

```typescript
// regulationMap 按 chunk_id 查找
const regulationMap: Record<string, AuditRegulationItem> = {};
for (const r of (docResult.regulations || [])) {
    regulationMap[r.chunk_id] = r;
}

// 表格渲染
if (!record.chunk_id) return <span>{stripped}</span>;
const reg = regulationMap[record.chunk_id];

// 点击事件
const handleRegulationClick = (chunkId: string) => {
    const regulation = regulationMap[chunkId];
    if (regulation) {
        setSelectedRegulation(regulation);
        setRegulationDrawerVisible(true);
    }
};
```

---

## Phase 6: 测试

### 删除
- `test_source_id_validation`
- `TestLoadAuditSources` → `TestLoadAuditRegulations`
- `TestFormatContextForLlm` → `TestBuildAuditContext`
- `TestCheckNegativeList` → 保持名称

### 修改
- 所有 `AuditSource(...)` → `AuditRegulationItem(...)`
- 所有 `AuditItem(...)` → `AuditResultItem(...)`
- `TestBuildAuditContext` — `[来源1]` → `【法规名-条号】`
- `TestCheckNegativeList` — mock fixtures 加 `id` 字段，`rule_id` → `source_ref`
- e2e 测试 — 无需改动（不检查 source_id/chunk_id）

### 新增
- `TestMatchRegulationByRef` — 精确匹配、无匹配、空 ref
- `TestExtractRealArticleNumber` — 中文数字提取、无匹配回退、空内容

---

## 清理清单

| 删除/重命名 | 文件 |
|-------------|------|
| `AuditSource` → `AuditRegulationItem` | checker.py, __init__.py, compliance.py, types |
| `AuditItem` → `AuditResultItem` | checker.py, __init__.py, compliance.py, types |
| `AuditSourceOut` → `AuditRegulationItemResponse` | schemas/compliance.py, compliance.py |
| `AuditItemOut` → `AuditResultItemResponse` | schemas/compliance.py, compliance.py |
| `ComplianceResultOut` → `ComplianceReportDataResponse` | schemas/compliance.py, compliance.py |
| `ComplianceReportOut` → `ComplianceReportResponse` | schemas/compliance.py, compliance.py |
| `load_audit_sources` → `load_audit_regulations` | checker.py, __init__.py, compliance.py |
| `format_context_for_llm` → `build_audit_context` | checker.py, __init__.py, compliance.py |
| `_match_source_by_ref` → `_match_regulation_by_ref` | checker.py |
| `source_id` 字段（4个模型） | checker.py, schemas/compliance.py, types/index.ts |
| `sources` → `regulations`（API key） | schemas/compliance.py, types/index.ts, compliance.py, CompliancePage.tsx |
| `num_sources` 参数及范围校验 | checker.py |
| 负面清单 `rule_id` 索引逻辑 | checker.py |
| 负面清单重新编号逻辑 | compliance.py |
| `AuditRegulationItem`/`AuditResultItem` 死代码 import | compliance.py |
| `[来源{s.source_id}]` 格式 | checker.py |
| `test_source_id_validation` | test_checker.py |
| 前端 `sourceMap` → `regulationMap` | CompliancePage.tsx |
| 前端 `sourceDrawerVisible`/`selectedSource`/`setSelectedSource` 状态变量 | CompliancePage.tsx |
| 前端 `handleSourceClick` → `handleRegulationClick` | CompliancePage.tsx |

## 涉及文件

| 文件 | 改动 |
|------|------|
| `rag_engine.py` | 返回 id 字段 |
| `checker.py` | 数据模型重命名 + 法条号提取 + context 格式 + ref 匹配 |
| `__init__.py` | 导出重命名 |
| `prompts.py` | source_ref 替代 source_id/rule_id |
| `schemas/compliance.py` | 模型重命名 + source_id → chunk_id |
| `compliance.py` | 删除重新编号，参数适配，import 清理 |
| `types/index.ts` | 类型重命名 + chunk_id |
| `CompliancePage.tsx` | 类型引用 + regulationMap |
| `test_checker.py` | 全面适配 |
| `test_negative_list.py` | fixtures 加 id，rule_id → source_ref |
