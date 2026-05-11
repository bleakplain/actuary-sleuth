# 合规审查 source 准确性修复 - 技术调研

生成时间: 2026-05-11
分析范围: scripts/lib/compliance/, scripts/lib/rag_engine/

---

## 问题

合规审查报告中 `source_id` 是 checker.py 运行时分配的顺序编号（1, 2, 3...），LLM 需要在 88+ 条法规中通过 `[来源X]` 数字编号精确映射 source_id，实测错误率 74%。

三个表象共享同一根因：
- source_id 张冠李戴 → LLM 编号错位
- article_number 非法条号 → RAG 存的是解析顺序路径，实际法条号在 content 中
- 检查项与法规不相关 → source_id 错位导致关联错误

## 数据验证

RAG 知识库（v4 LanceDB, 329 条），每条法规全局唯一标识：`(law_name, article_number)` — 329 条零重复。

| 字段 | 示例 | 说明 |
|------|------|------|
| id | `9dca75aa-22da-40b6-...` | LanceDB UUID，全局唯一 |
| law_name | `中华人民共和国保险法（2015年修订版）` | 法规全称 |
| article_number | `第1项` | 解析顺序编号（非实际法条号） |
| content | `第十三条　投保人提出保险要求...` | 法规原文 |

article_number 可提取性：保险法 28 条 content 中含实际法条号（`re.match(r'第([一二三四五六七八九十百]+)条', content)`），健康保险管理办法、重疾规范无传统法条号，保持"第X项"。

## 方案：chunk_id 贯穿全链路

**用 RAG chunk UUID（`id` 字段）作为唯一关联键，删除人为构造的 `source_id`。**

`source_ref`（如"健康保险管理办法-第2项"）是 LLM 输出中引用法规的标识，解析时精确匹配 `f"{s.law_name}-{s.article_number}"`，取 chunk_id 写入 AuditItem。source_ref 不出现在 API 和前端。

### 改动清单

| # | 改动 | 文件 |
|---|------|------|
| 1 | `search_by_metadata` 返回值增加 `id` 字段 | `rag_engine.py:532` |
| 2 | `AuditSource` → `AuditRegulationItem`（`source_id` → `chunk_id`） | `checker.py` |
| 3 | `AuditItem` → `AuditResultItem`（`source_id` → `chunk_id`） | `checker.py` |
| 4 | `load_audit_sources` → `load_audit_regulations`，保存 chunk_id + 提取实际法条号 | `checker.py` |
| 5 | `format_context_for_llm` → `build_audit_context`，用 `【法规名-条号】` 替代 `[来源X]` | `checker.py` |
| 6 | prompt 要求 LLM 输出 `source_ref` 替代 `source_id` | `prompts.py` |
| 7 | `run_compliance_check` 用 source_ref 匹配 AuditSource 取 chunk_id（source_ref 不暴露到 API） | `checker.py` |
| 8 | `check_negative_list` 用 chunk_id，prompt 用 `【法规名-条号】` 标识，LLM 输出 `source_ref` | `checker.py` |
| 9 | `_parse_violation_response` 用 source_ref 匹配，删除 `rule_id` 索引逻辑 | `checker.py` |
| 10 | 路由层删除负面清单重新编号逻辑 | `compliance.py` |
| 11 | API schema `source_id` → `chunk_id` | `schemas/compliance.py` |
| 12 | 前端类型重命名 + regulationMap 按 chunk_id 查找（API key `sources` 不变） | `types/index.ts`, `CompliancePage.tsx` |
| 13 | 测试全面适配 | `test_checker.py`, `test_negative_list.py` |

### 涉及文件

| 文件 | 改动 |
|------|------|
| `scripts/lib/rag_engine/rag_engine.py` | 返回 id 字段 |
| `scripts/lib/compliance/checker.py` | 数据模型 + 法条号提取 + context 格式 + ref 匹配 |
| `scripts/lib/compliance/prompts.py` | source_ref 替代 source_id |
| `scripts/api/schemas/compliance.py` | source_id → chunk_id |
| `scripts/api/routers/compliance.py` | 删除重新编号，直接合并 |
| `scripts/web/src/types/index.ts` | source_id → chunk_id |
| `scripts/web/src/pages/CompliancePage.tsx` | sourceMap 改 string key |
| `scripts/tests/compliance/test_checker.py` | 全面适配 |
| `scripts/tests/compliance/test_negative_list.py` | fixtures 加 id 字段 |

### 不涉及的文件

- `database.py` — compliance_reports 表存 result_json，无 source_id 列
