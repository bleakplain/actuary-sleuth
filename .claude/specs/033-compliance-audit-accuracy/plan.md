# Implementation Plan: 合规审核准确性提升

**Branch**: `033-compliance-audit-accuracy` | **Date**: 2026-05-11 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

解决合规审核报告的两个核心问题：(1) 法规引用相关率仅 44.4%（目标 ≥90%），LLM 在 88 条平铺法规中无法准确选择与检查事项相关的法规；(2) 条款覆盖对长文档可能不足。

**核心改动**：为每条法规分配编号 `[R1]-[R88]`，重构 prompt 引导 LLM 逐条检查条款并用编号引用法规，后处理改为编号直接映射。

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: 无新增（复用现有 `compliance` 模块）
**Storage**: SQLite（报告存储不变）
**Testing**: pytest
**Performance Goals**: 无额外 LLM 调用，单次检查延迟不变
**Constraints**: glm-4-flash 模型能力有限，prompt 工程是主要改进手段

## Constitution Check

- [x] Library-First: 复用 `AuditRegulationItem`、`_normalize_ref()`、`load_audit_regulations()`，不引入新模块
- [x] 测试优先: Phase 3 规划了覆盖分析和匹配逻辑的单元测试
- [x] 简单优先: 编号方案是最简方案——不引入 RAG 检索、不增加 LLM 调用
- [x] 显式优于隐式: 编号 `[R1]` 是显式引用，替代隐式的法规名字符串匹配
- [x] 可追溯性: 每个 Phase 回溯到 spec.md 的 User Story
- [x] 独立可测试: 两个 User Story 可独立验证

## Project Structure

### Source Code

```
scripts/lib/compliance/
├── checker.py       # 修改：build_audit_context 加编号，run_compliance_check 改解析
├── prompts.py       # 修改：重构 prompt 模板
└── __init__.py      # 不变

scripts/api/routers/
└── compliance.py    # 修改：截断告知、传递覆盖数据

scripts/api/schemas/
└── compliance.py    # 修改：response 增加 clause_coverage 字段

scripts/tests/compliance/
├── test_checker.py  # 修改：新增编号映射、覆盖分析测试
└── test_e2e_compliance.py  # 不变
```

## Implementation Phases

### Phase 1: 编号引用机制 (US2 — 法规引用准确)

#### 需求回溯

→ spec.md User Story 2: 检查项与法规引用准确对应
→ FR-002: 系统 MUST 确保每个检查项的法规引用与检查内容语义相关
→ FR-004: 系统 MUST NOT 将不相关的法规条文作为某个检查项的法规依据

#### 实现步骤

**Step 1: 修改 `build_audit_context()` 为法规分配编号**

- 文件: `scripts/lib/compliance/checker.py:112-126`
- 改动: 函数签名不变，返回值不变，每条法规前加 `[R{i+1}]` 编号，去掉 `article_number` 中的"第N项"

```python
def build_audit_context(regulations: List[AuditRegulationItem]) -> str:
    if not regulations:
        return ""

    parts = []
    for i, r in enumerate(regulations):
        index = f"R{i + 1}"
        header = f"[{index}] {r.law_name}"
        if r.doc_number:
            header += f"（{r.doc_number}）"
        parts.append(f"{header}\n{r.content}")
    return "\n\n".join(parts)
```

关键变化：
- `【法规名-第1项】` → `[R1] 法规名`（编号替代无意义的"第N项"）
- 去掉发布机关/生效日期（减少 noise，这些信息对 LLM 选择法规无帮助）

**Step 2: 修改 `run_compliance_check()` 用编号解析**

- 文件: `scripts/lib/compliance/checker.py:279-342`
- 改动: 替换 `_build_ref_map` 字符串匹配为编号直接映射

```python
def run_compliance_check(prompt: str, regulations: Optional[List[AuditRegulationItem]] = None) -> Dict:
    try:
        llm = get_audit_llm()

        logger.info(f"Prompt length: {len(prompt)}")
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response)

        logger.info(f"LLM response length: {len(answer)}, preview: {answer[:200]}")

        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

        json_start = answer.find("{")
        json_end = answer.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            logger.warning(f"No JSON found in LLM response: {answer[:200]}")
            return {
                "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                "items": [],
                "error": "json_not_found",
                "raw_answer": answer[:1000],
            }

        json_str = answer[json_start:json_end]

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            open_brackets = json_str.count("{") - json_str.count("}")
            open_arrays = json_str.count("[") - json_str.count("]")
            json_str_fixed = json_str + "]" * open_arrays + "}" * open_brackets
            try:
                result = json.loads(json_str_fixed)
            except json.JSONDecodeError:
                logger.warning(f"JSON repair failed, returning empty result")
                return {
                    "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                    "items": [],
                    "error": "json_parse_failed",
                    "raw_answer": answer[:1000],
                }

        reg_index = {f"R{i + 1}": r for i, r in enumerate(regulations)} if regulations else {}
        items = result.get("items", [])
        for item in items:
            if not item.get("clause_number"):
                item["clause_number"] = "未知"
            ref = item.pop("source_ref", "")
            matched = reg_index.get(ref) if ref else None
            if matched:
                item["chunk_id"] = matched.chunk_id
                item["requirement"] = f"{matched.law_name}: {matched.content[:200]}"
                item["source_excerpt"] = matched.content[:300]
            else:
                item["chunk_id"] = None
                if ref:
                    logger.warning(f"source_ref 匹配失败: {ref}")
                item["requirement"] = item.get("requirement", "") or "法规来源待确认"
                item["source_excerpt"] = item.get("source_excerpt", "")
            item["check_type"] = "regulation"
            item["source_type"] = "regulation"

        return result

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0, "attention": 0}, "items": [], "error": str(e)}
```

关键变化：
- `ref_map = _build_ref_map(regulations)` → `reg_index = {f"R{i+1}": r ...}`（编号直接映射，100% 准确）
- 匹配成功时从 regulation 回填 `requirement` 和 `source_excerpt`（防止 LLM 幻觉）
- 匹配失败时标记"法规来源待确认"（FR-005）

**Step 3: 同步修改负面清单的编号引用**

- 文件: `scripts/lib/compliance/checker.py:129-195`
- 改动: `check_negative_list()` 和 `_parse_violation_response()` 也用编号替代法规名匹配

`check_negative_list` 中 `rules_text` 构建：

```python
rules_text = "\n\n".join([
    f"[R{i + 1}] {r.law_name}\n{r.content}"
    for i, r in enumerate(regulations)
])
```

`_parse_violation_response` 中匹配逻辑：

```python
reg_index = {f"R{i + 1}": r for i, r in enumerate(regulations)}
...
matched = reg_index.get(ref) if ref else None
```

**Step 4: 重构 prompt 模板**

- 文件: `scripts/lib/compliance/prompts.py`
- 改动: 完全重写 prompt，引导逐条检查 + 编号引用

```python
COMPLIANCE_PROMPT_DOCUMENT = """你是一位保险法规合规专家。请逐条审查以下保险条款文档中的每一项条款，检查是否符合相关法规要求。

## 条款文档内容
{document_content}

## 相关法规条款（共 {regulation_count} 条）
{context}

## 输出要求
请逐条检查文档中的每个条款，以 JSON 格式输出检查结果：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "clause_number": "<条款编号，如'3.2'>",
            "param": "<检查项名称，如等待期、免赔额>",
            "value": "<条款中的实际内容>",
            "requirement": "<相关法规的要求摘要>",
            "status": "<compliant|non_compliant|attention>",
            "source_ref": "<引用上面法规的编号，如 R5>",
            "suggestion": "<修改建议，合规时留空>"
        }}
    ]
}}

注意：
1. 必须检查文档中的每一项条款，不要遗漏任何条款
2. source_ref 必须是上面法规的编号（如 R1、R5、R12），引用与该条款最相关的法规
3. 选择 source_ref 时，先理解条款内容，再找到法规列表中内容最匹配的编号
4. clause_number 必须对应文档中实际的条款编号
5. 仅输出 JSON"""
```

关键变化：
- 新增 `{regulation_count}` 占位符（传入 `len(regulations)`）
- "逐条检查文档中的每一项条款，不要遗漏"（解决 US1 覆盖问题）
- `source_ref` 改用编号格式 "R5"（解决 US2 引用准确性）
- "选择 source_ref 时，先理解条款内容，再找到法规列表中内容最匹配的编号"（引导 LLM 按内容选择而非按序号猜测）
- 去掉 `source_excerpt` 输出要求（改由后端从 matched regulation 回填，防止 LLM 幻觉）

**Step 5: 修改 router 传递 regulation_count**

- 文件: `scripts/api/routers/compliance.py:63-66`
- 改动: prompt format 传入 `regulation_count`

```python
prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
    document_content=document_content,
    context=context,
    regulation_count=len(regulations),
)
```

**Step 6: 删除 `_build_ref_map()` 和 `_normalize_ref()` 的死代码**

- 文件: `scripts/lib/compliance/checker.py:198-207`
- `_normalize_ref()` 保留（负面清单可能仍需），删除 `_build_ref_map()` 中第 207 行的死代码（unreachable return）

**Checkpoint**: Phase 1 完成后，手动执行一次审核，验证：
- 法规上下文格式为 `[R1] 法规名\n内容`
- LLM 输出的 source_ref 为 "R5" 格式
- chunk_id 正确映射到对应 regulation

---

### Phase 2: 截断告知 + 覆盖分析 (US1 — 条款覆盖)

#### 需求回溯

→ spec.md User Story 1: 审核结果覆盖所有条款
→ FR-003: 系统 SHOULD 在报告中提供条款覆盖分析
→ FR-006: 系统 SHOULD 在文档截断时告知用户哪些内容未被检查

#### 实现步骤

**Step 1: 截断时记录被截断的内容范围**

- 文件: `scripts/api/routers/compliance.py:37-44`
- 改动: `_prepare_document_content()` 返回截断信息

```python
def _prepare_document_content(content: str) -> Tuple[str, Optional[str]]:
    if len(content) <= MAX_DOCUMENT_CHARS:
        return content, None
    truncated = content[:MAX_DOCUMENT_CHARS]
    last_clause = truncated.rfind("\n【条款")
    if last_clause > 0:
        used = truncated[:last_clause]
    else:
        used = truncated
        last_clause = MAX_DOCUMENT_CHARS
    omitted_preview = content[last_clause:last_clause + 200]
    return used, f"文档内容超过 {MAX_DOCUMENT_CHARS} 字符限制，以下内容未被检查: {omitted_preview}..."
```

**Step 2: 从文档中提取条款编号列表**

- 文件: `scripts/lib/compliance/checker.py`
- 新增函数 `_extract_clause_numbers(document_content) -> List[str]`

```python
def _extract_clause_numbers(document_content: str) -> List[str]:
    return re.findall(r'【条款\s+(\d+(?:\.\d+)*)】', document_content)
```

**Step 3: 计算条款覆盖并附加到结果**

- 文件: `scripts/api/routers/compliance.py:check_document()`
- 改动: 在结果中追加覆盖分析

```python
doc_clauses = _extract_clause_numbers(document_content)
checked_clauses = [item.get("clause_number", "") for item in result.get("items", [])]
checked_clauses = [c for c in checked_clauses if c != "未知"]

result["clause_coverage"] = {
    "total": len(doc_clauses),
    "checked": len(set(checked_clauses) & set(doc_clauses)),
    "unchecked": list(set(doc_clauses) - set(checked_clauses)),
}
if truncation_warning:
    result["clause_coverage"]["truncation_warning"] = truncation_warning
```

**Step 4: schema 增加字段**

- 文件: `scripts/api/schemas/compliance.py`
- 改动: `ComplianceResult` 或 response model 增加 `clause_coverage` 可选字段

**Checkpoint**: Phase 2 完成后验证：
- 短文档无截断警告
- 长文档（>150K chars）有 truncation_warning
- clause_coverage 包含 total/checked/unchecked

---

### Phase 3: 测试更新

#### 实现步骤

**Step 1: 更新 `test_checker.py`**

- 文件: `scripts/tests/compliance/test_checker.py`
- 新增测试：
  - `test_build_audit_context_with_index`: 验证 `[R1]` 编号格式
  - `test_run_compliance_check_index_mapping`: 验证 "R5" → regulations[4] 映射
  - `test_extract_clause_numbers`: 验证条款编号提取
  - `test_unmatched_ref_marked_pending`: 验证匹配失败标记"法规来源待确认"

**Step 2: 更新已有测试的 fixture**

- 已有测试中如果硬编码了 source_ref 格式（如 `【法规名-条目号】`），需改为 `R1` 格式

**Step 3: mypy 类型检查**

- `mypy scripts/lib/` 通过

---

## Complexity Tracking

无违反项。所有改动在现有模块内完成，无新增模块、无新增依赖、无过度抽象。

## Appendix

### 执行顺序建议

Phase 1（编号引用）→ Phase 3（测试）→ Phase 2（覆盖分析）

Phase 1 是核心改动，Phase 3 验证 Phase 1 的正确性，Phase 2 是增量改进可最后实施。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 条款覆盖 | SC-001: 覆盖率 ≥ 80% | test_extract_clause_numbers + E2E |
| US2 法规引用 | SC-002: 相关率 ≥ 90% | test_run_compliance_check_index_mapping + 人工验证 |
| US2 匹配成功率 | SC-003: ≥ 95% | test_run_compliance_check_index_mapping |
