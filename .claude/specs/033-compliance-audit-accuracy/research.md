# 033-compliance-audit-accuracy 深度自检报告

**生成时间**: 2026-05-12
**范围**: 合规审查全流程 — 文档解析 → 险种识别 → 法规加载 → 合规检查 → 结果组装 → 前端展示
**用户反馈问题**: 1. 保险产品条款不完整；2. 法规要求与保险条款及法规来源存在不一致或难以对应

---

## 执行摘要

通过深度代码审计，识别出 **18 个问题**，其中 **5 个高风险**（直接影响审查准确性）、**10 个中风险**（影响报告可用性或存在潜在数据丢失）、**3 个低风险**（边界情况）。

两个用户反馈问题的根因定位：
- **问题1「条款不完整」**: 根因是 `_split_by_clauses` 丢弃首条条款前的文本 + HTML 解析器丢失大量标签内容 + DOCX 解析器只从表格提取条款
- **问题2「法规要求不一致」**: 根因是 source_ref 匹配失败时保留了 LLM 编造的 requirement + backfill 掩盖语义错误的法规匹配 + requirement/source_excerpt 硬截断丢失关键信息

---

## 一、高风险问题（5 个）

### H1. `_split_by_clauses` 丢弃首条条款前的所有文本

**文件**: `checker.py:354`
**影响**: 长文档分批时，第一个 `【条款` 标记之前的所有内容（产品概述、保险责任概述、定义等）被完全丢弃，LLM 永远看不到这些内容。

```python
# checker.py:354
current_start = clause_positions[0]  # 从第一个条款开始，丢弃前面所有内容
```

**场景**: 保险条款文档通常以"保险合同构成"、"保险责任"等非编号段落开头，这些内容对合规审查至关重要（如保险责任描述是否准确）。

**修复建议**: 将 `current_start` 改为 `0`，或保留首条款前的文本作为第一个 batch 的前缀。

---

### H2. source_ref 匹配失败时保留了 LLM 编造的 requirement

**文件**: `checker.py:328-335`
**影响**: 当 LLM 输出的 `source_ref` 无法匹配到法规时（如 `R0`、`R100`、空值），代码检查 `if not item.get("requirement")` 才覆盖。但 LLM **总是会输出** requirement 字段（prompt 要求输出），所以 LLM 编造的法规要求文本被**原样保留**，用户看到的是一个看似合法但实际未经核实的法规要求。

```python
# checker.py:328-335
else:
    item["chunk_id"] = None
    if ref:
        logger.warning(f"source_ref 匹配失败: {ref}")
    if not item.get("requirement"):      # LLM 总是写了 requirement，这里永远是 False
        item["requirement"] = "法规来源待确认"
```

**修复建议**: 匹配失败时，无论 LLM 提供了什么 requirement，都应覆盖为 `"法规来源待确认（引用 {ref} 未匹配）"` 或保留但添加标记。

---

### H3. HTML 解析器丢失大量标签内容

**文件**: `html_converter.py:63-67`
**影响**: `SimpleHTMLParser.handle_data` 只在 `self.in_p` 或 `self.in_cell` 为 True 时捕获文本。以下常见 HTML 标签的内容被完全丢弃：
- `<div>` — 富文本编辑器最常用的容器标签
- `<span>` — 行内格式
- `<ul>`/`<ol>`/`<li>` — 列表（保险条款中常见的责任免除、条件列表）
- `<br>` — 换行
- `<blockquote>` — 引用
- `<section>` — HTML5 区段

```python
# html_converter.py:63-67
def handle_data(self, data):
    if self.in_p:           # 只有 <p> 内的文本被捕获
        self.current_text += data
    elif self.in_cell:      # 只有 <td>/<th> 内的文本被捕获
        self.current_cell += data
    # 其他标签内的文本被静默丢弃
```

**修复建议**: 扩展解析器以处理 `<div>`、`<li>` 等标签，或使用更健壮的 HTML→DOCX 库（如 `htmldocx`）。

---

### H4. backfill 掩盖语义错误的法规匹配

**文件**: `checker.py:324-327`
**影响**: 当 LLM 错误地选择了 `R5`（比如疾病定义法规）来检查等待期条款时，backfill 逻辑会用 R5 法规的真实内容覆盖 LLM 的 requirement。用户看到的是一个"法规名: 真实法规内容"的字符串，看起来完全合法，但法规内容与检查项的参数完全不相关。没有任何机制检测 LLM 选择的法规是否与检查项的 `param`/`value` 语义相关。

```python
# checker.py:324-327
if matched:
    item["chunk_id"] = matched.chunk_id
    item["requirement"] = f"{matched.law_name}: {matched.content[:200]}"  # 真实法规，但可能语义无关
    item["source_excerpt"] = matched.content[:300]
```

**修复建议**: 在 prompt 中要求 LLM 说明选择该法规的原因，或在后端添加简单相关性校验（如 param 关键词是否出现在 regulation content 中）。

---

### H5. DOCX 解析器只从表格提取条款，忽略段落中的条款

**文件**: `doc_parser/pd/docx_parser.py:50-52`
**影响**: DOCX 解析器的 `extract_clauses` 只扫描 `doc.tables`，不扫描 `doc.paragraphs`。如果条款以段落格式（而非表格格式）存在于 DOCX 文件中，这些条款被完全遗漏。PDF 解析器不存在此问题（它从文本流提取条款）。

这意味着同一份保险文档，PDF 版本和 DOCX 版本可能产生完全不同的解析结果。

**修复建议**: 在 DOCX 解析器中增加从段落提取条款的备选路径。

---

## 二、中风险问题（10 个）

### M1. `extract_clause_numbers` 不覆盖非条款区块

**文件**: `checker.py:61-62`
**影响**: 正则只匹配 `【条款 X.Y】` 和 `【附加险条款 X.Y】`。`_build_combined_text` 生成的 `【数据表】`、`【投保须知】`、`【健康告知】`、`【责任免除】` 区块不计入条款总数。

`compliance.py:86-95` 的 `clause_coverage` 计算因此不准确：如果 LLM 检查了「投保须知」和「责任免除」区块并输出检查项，这些项不计入 "已检查" 覆盖率。

**修复建议**: 扩展 `extract_clause_numbers` 为 `extract_section_numbers`，返回所有区块标记。

---

### M2. `regulation_sources` 缺失负面清单法规（无违规时）

**文件**: `compliance.py:74-76`
**影响**: `regulation_sources` 的"负面清单"条目仅在 `negative_items` 非空时添加。如果负面清单检查通过（无违规），用户看不到哪些负面清单法规被参考了，误以为系统没有进行负面清单检查。

```python
# compliance.py:74-76
if negative_items:  # 只有违规时才添加负面清单法规来源
    result["items"].extend(...)
    result["regulation_sources"]["负面清单"] = [...]
```

**修复建议**: 无论是否有违规，都将负面清单法规添加到 `regulation_sources`。

---

### M3. prompt 未告知 LLM 法规编号的有效范围

**文件**: `prompts.py:34`
**影响**: prompt 只给出示例（`R1`、`R5`、`R12`），未明确告知范围是 `R1` 到 `R{regulation_count}`。LLM 可能输出超出范围的编号，导致匹配失败（H2 问题）。

```python
# prompts.py:34
"source_ref": "<引用上面法规的编号，如 R5>",
```

**修复建议**: 添加 `"source_ref 必须在 R1 到 R{regulation_count} 范围内"`。

---

### M4. LLM max_tokens=8192 可能截断大型审查响应

**文件**: `llm/zhipu.py`（默认配置）
**影响**: 当文档有 30+ 条款时，每条生成一个 JSON item，LLM 响应可能超过 8192 tokens。如果截断发生在 items 数组中间，`checker.py:300-315` 的 JSON 修复会补全括号，但丢失的 items 永远无法恢复。用户看到的报告不完整但无任何截断提示。

**修复建议**: 在 `batch_compliance_check` 中，对每个 batch 的 item 数量设置上限（如 20 条），或增加 max_tokens 配置。

---

### M5. batch 失败时丢弃之前所有成功批次的结果

**文件**: `checker.py:392-394`
**影响**: 3 批检查中，如果第 3 批失败，前 2 批的有效结果被完全丢弃，用户只看到错误提示。

```python
# checker.py:392-394
if "error" in batch_result:
    return batch_result  # 丢弃 all_items 中已收集的结果
```

**修复建议**: 记录失败批次信息，但仍返回已收集的 items，在结果中标注"部分检查未完成"。

---

### M6. 分批合并后无条款去重

**文件**: `checker.py:383-395`
**影响**: LLM 可能在不同 batch 中对同一条款编号输出检查项（如 batch 1 的 LLM 注意到 batch 2 范围内的条款并输出检查项，batch 2 也检查了同一条款），导致同一条款出现两条可能矛盾的检查结果。

**修复建议**: 合并后按 `clause_number` 去重，保留 non_compliant 优先。

---

### M7. JSON 修复可能产生不完整 items

**文件**: `checker.py:300-307`
**影响**: LLM 输出截断时，`json_str_fixed` 补全括号后可能产生只有部分字段的 item（如只有 `clause_number` 和 `param`，缺少 `status` 和 `source_ref`）。这些不完整 items 进入后续流程，`status` 为空字符串，导致 summary 统计丢失（不计入 compliant/non_compliant/attention 任何一类）。

**修复建议**: 在 items 处理后过滤掉 `status` 不在有效值集合的 items。

---

### M8. `identify_category` 只看文档前 1000-2000 字符

**文件**: `checker.py:242, 256`
**影响**: `classify_product` 只看 `document_content[:1000]`，LLM fallback 只看 `document_content[:2000]`。如果产品类型标识（如"重大疾病保险条款"）出现在文档中后段，分类会失败或降级为 OTHER，导致险种专属法规不被加载。

**修复建议**: 增大采样窗口或从文档标题/前 5000 字符中提取产品类型。

---

### M9. `extra='ignore'` 静默丢弃 API 响应中的未声明字段

**文件**: `schemas/compliance.py:7, 32`
**影响**: `AuditRegulationItemResponse` 和 `ComplianceReportDataResponse` 使用 `extra='ignore'`。如果 checker 返回的数据中包含 Pydantic schema 未声明的字段（如 `error`、`raw_answer`），这些字段被静默丢弃。虽然 `check_document` 路由在 `error` 情况下直接 raise HTTPException，但 `list_reports`/`get_report` 端点从数据库读取后也通过此 schema 序列化，可能丢失存储在 DB 中但 schema 未声明的字段。

**修复建议**: 审查所有端点的序列化路径，确保关键字段不会被 schema 过滤。

---

### M10. clause_coverage 的 checked_clause_set 不验证条款号有效性

**文件**: `compliance.py:87-90`
**影响**: LLM 可能输出文档中不存在的条款编号（如编造"9.5"），这些假编号被加入 `checked_clause_set`。虽然不会影响最终结果（因为与 `doc_clause_set` 做交集），但 LLM 输出 `"未知"` 的条目被排除可能导致合规问题的条款不被计入覆盖率。

**修复建议**: 无需修复。交集运算自然过滤了无效编号，影响有限。

---

## 三、低风险问题（3 个）

### L1. `_split_by_clauses` 无条款标记时退化为字符级切割

**文件**: `checker.py:351-352`
**影响**: 当文档中没有 `【条款` 标记时，fallback 在原始字符边界切割，可能在句子、表格中间截断，LLM 收到不完整内容。

**修复建议**: 增加 fallback 的句子级/段落级切割逻辑。

---

### L2. R-index 编号依赖法规列表的非确定性顺序

**文件**: `checker.py:200-201`
**影响**: `search_by_metadata` 的返回顺序依赖 LanceDB 内部迭代（`df.iterrows()`），可能不稳定。同一法规在不同请求中可能获得不同的 R 编号。但由于 R-index 仅在单次请求内使用（prompt 和解析共享同一列表），实际影响有限。

**修复建议**: 对 regulations 列表排序后再编号，确保确定性。

---

### L3. negative_list 和 regulation checks 的字段语义不一致

**文件**: `checker.py:222-233` vs `checker.py:322-337`
**影响**: 两种检查类型的 `requirement`、`value`、`source_excerpt` 字段的含义不同：
- Regulation: `value` = 条款内容, `requirement` = 法规名+内容前200字, `source_excerpt` = 法规内容前300字
- Negative list: `value` = 文档违规原文前100字, `requirement` = "违反负面清单"+法规信息, `source_excerpt` = 法规内容前300字

前端需要统一处理这两类 items，但字段语义差异可能导致展示不一致。

**修复建议**: 统一字段语义，或在 API 响应中明确标注字段含义随 check_type 变化。

---

## 四、问题汇总表

| # | 严重度 | 文件:行 | 问题 | 用户反馈关联 |
|---|--------|---------|------|-------------|
| H1 | **高** | checker.py:354 | 分批时丢弃首条款前文本 | 问题1 条款不完整 |
| H2 | **高** | checker.py:328-335 | source_ref 失败时保留 LLM 编造 requirement | 问题2 法规要求不一致 |
| H3 | **高** | html_converter.py:63-67 | HTML 解析器丢失 div/ul/li 等标签 | 问题1 条款不完整 |
| H4 | **高** | checker.py:324-327 | backfill 掩盖语义错误匹配 | 问题2 法规要求不一致 |
| H5 | **高** | docx_parser.py:50 | DOCX 只从表格提取条款 | 问题1 条款不完整 |
| M1 | 中 | checker.py:61-62 | 条款覆盖率不计非条款区块 | 问题1 条款不完整 |
| M2 | 中 | compliance.py:74-76 | 无违规时隐藏负面清单法规 | 报告不完整 |
| M3 | 中 | prompts.py:34 | 未约束 R 编号有效范围 | 问题2 法规要求不一致 |
| M4 | 中 | llm/zhipu.py | max_tokens 截断大型响应 | 问题1 条款不完整 |
| M5 | 中 | checker.py:392-394 | batch 失败丢弃成功结果 | 报告不完整 |
| M6 | 中 | checker.py:383-395 | 合并无条款去重 | 报告重复 |
| M7 | 中 | checker.py:300-307 | JSON 修复产生不完整 items | 报告不完整 |
| M8 | 中 | checker.py:242,256 | 分类只看前 1000-2000 字 | 法规加载可能错误 |
| M9 | 中 | schemas/compliance.py:7,32 | extra='ignore' 丢弃字段 | 数据丢失 |
| M10 | 中 | compliance.py:87-90 | 覆盖率不验证条款号 | 覆盖率不准确 |
| L1 | 低 | checker.py:351-352 | 无条款标记时字符级切割 | 边界情况 |
| L2 | 低 | checker.py:200-201 | R-index 非确定性排序 | 边界情况 |
| L3 | 低 | checker.py:222-337 | 两种检查类型字段语义不同 | 报告一致性 |

---

## 五、修复优先级建议

### 第一批（必须修复 — 直接影响审查准确性）

| 优先级 | 问题 | 修复工作量 |
|--------|------|-----------|
| P0 | H1 分批丢弃首条款前文本 | 小（改 1 行） |
| P0 | H2 source_ref 失败保留编造 requirement | 小（改 3 行） |
| P0 | M3 prompt 约束 R 编号范围 | 小（改 prompt） |

### 第二批（应该修复 — 影响报告质量和完整性）

| 优先级 | 问题 | 修复工作量 |
|--------|------|-----------|
| P1 | M2 无违规时隐藏负面清单法规 | 小（改 2 行） |
| P1 | M4 max_tokens 截断 | 中（需配置+分批策略） |
| P1 | M5 batch 失败丢弃结果 | 小（改 5 行） |
| P1 | M7 不完整 items 过滤 | 小（加 3 行） |

### 第三批（建议修复 — 需要较大改动）

| 优先级 | 问题 | 修复工作量 |
|--------|------|-----------|
| P2 | H3 HTML 解析器 | 大（重写或替换库） |
| P2 | H4 backfill 掩盖语义错误 | 中（需相关性校验） |
| P2 | H5 DOCX 只从表格提取条款 | 中（增加段落提取） |
| P2 | M1 条款覆盖率不全 | 中（扩展正则+逻辑） |
| P2 | M8 分类采样窗口小 | 小（改参数） |

---

## 六、与已修复问题（issues-fix.md）的关系

issues-fix.md 已修复的问题与本次自检的关系：

| 已修复 | 本次是否仍然存在 | 说明 |
|--------|-----------------|------|
| 分批合规审查替代截断 | 部分解决 | 分批机制已实现，但 H1（首条款前文本丢弃）是新发现问题 |
| 重疾险分类错误 | 已解决 | CRITICAL_ILLNESS 枚举已添加 |
| clause_coverage 前端展示 | 已解决 | 但 M1 发现覆盖率计算本身不完整 |
| checkDocument 超时 | 已解决 | 360s 超时已配置 |
| error 结果透传 | 已解决 | 但 M5 发现分批错误处理不完善 |
| 摘要计数校验 | 已解决 | 后端重算 summary |
| 附加险条款覆盖率 | 已解决 | 正则已包含附加险 |

本次新发现的关键问题：**H2（编造 requirement 被保留）和 H4（backfill 掩盖错误匹配）** 是用户反馈"法规要求不一致"的根本原因，之前未被识别。
