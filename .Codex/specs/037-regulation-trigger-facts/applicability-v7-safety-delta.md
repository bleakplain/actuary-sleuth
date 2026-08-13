# v7 签收基线完整性差异闭环

> **2026-08-13 最终结论**：下文的 23/53/92 项变化是 Phase 8 的中间安全诊断，已被 Phase 9 的正文识别结果消除。页眉、页脚和已确认二维码按用户决定排除；实质文本框及引用脚注/尾注已纳入正文。最终对照 v7：170 项产品标签变化 0、115 项风险事实变化 0、1740 项法规适用性变化 0。因此不需要因本问题重新做精算验收。

- **生成日期**：2026-08-07
- **对照基线**：`compliance-audit-v1-applicability-v7`

**历史状态**：已被 Phase 9 闭环；以下保留中间诊断供追溯

## 为什么产生差异

新解析完整性规则不再把“正文段落和表格都已归属”等同于“全部条款原文均已覆盖”。只要 DOCX 存在尚未纳入审核块的文本框、图像、页眉/页脚、脚注/尾注/批注等内容，或 PDF 存在未经 OCR 验证的图像，就不允许用“全文没有搜到”推导 `false`/`无续保` 等负向事实。

这些差异全部是从确定值退回 `unknown/indeterminate`，不会新增法规排除。

## 产品标签差异（10 份签收样本）

v7 的 170 个普通产品标签中，共 23 个字段值发生安全降级：

| 字段 | 原值 → 新值 | 数量 |
|---|---:|---:|
| `is_tax_advantaged_health` | `false → unknown` | 10 |
| `renewal_type` | `none → unknown` | 7 |
| `term_class` | `short_term → unknown` | 3 |
| `health_term_class` | `short_health → unknown` | 3 |

如果把同一组 10 份样本的 5 个风险事实也计入 `ProductTags.to_dict()`，还有 24 个变化：`is_increasing_sum_assured_product=10`、`mentions_out_of_hospital_drug=9`、`mentions_critical_illness_definition_term=5`；合计为 47 个字段值变化。

## 风险事实差异（23 份真实产品）

共 53 个负向事实从 `false` 退回 `unknown`：

| 字段 | 数量 |
|---|---:|
| `is_increasing_sum_assured_product` | 23 |
| `mentions_out_of_hospital_drug` | 20 |
| `mentions_critical_illness_definition_term` | 10 |

## 法规适用性影响（10 份产品 × 174 个法规单元）

| 状态变化 | 数量 |
|---|---:|
| `not_applicable → indeterminate` | 75 |
| `applicable → indeterminate` | 17 |
| 变为 `not_applicable` | 0 |

新状态汇总：`applicable=805`、`not_applicable=841`、`indeterminate=94`。

变化主要集中于税优事项说明（28）、金规〔2023〕2号（18）、短期健康险续保通知（13）、《健康保险管理办法》（10）和监管通报问题（10）。根因是原来的 `false/none/short_term` 负向推断退回未知，不再对 `special_feature`、`renewal_condition`、`term_class` 等维度形成明确排除。

## 处理建议

原建议已经由 Phase 9 取代，最终处理如下：

1. 页眉、页脚和通过本地结构验证的二维码不进入产品条款审核范围。
2. 只有纯导航提示或可由正文逐项印证的目录副本可忽略；混有条款编号或实质正文的文本框必须保留。
3. 被正文引用的脚注/尾注归入引用条款；批注仅留作审计记录。
4. 普通图片、部分文字层覆盖的大图或无法确认的对象继续撤销覆盖，禁止以零命中形成负向结论。
5. 五类零命中事实由受控覆盖键分别授权，并由 v3 解析凭证签名绑定。

真实 23 份产品（9 DOC、11 DOCX、3 PDF）均通过覆盖证明；23 个模板二维码被安全忽略，未解析正文图片/文本框/辅助部件均为 0。失能收入损失保险中的 49 条正式脚注已全部归入引用条款。审核块从 1569 增至 1575，正文字符从 440149 增至 447861。

最终法规适用性仍为 `applicable=822`、`indeterminate=2`、`not_applicable=916`，新增排除为 0。v7 签收继续有效，无需生成一份仅恢复原值的 v8 验收表。
