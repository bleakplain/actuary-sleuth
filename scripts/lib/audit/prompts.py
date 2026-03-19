#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合规审核 Prompt 模板

用于产品条款合规性审核的提示词。
"""

from typing import List, Dict, Any

UNKNOWN_REGULATION = "未知法规"
CONTENT_PREVIEW_LENGTH = 300

AUDIT_SYSTEM_PROMPT = """你是一位保险产品合规审核专家，负责根据监管规定审核保险产品条款。

【审核标准】
1. 条款合规性：是否符合相关法律法规
2. 信息披露：是否充分披露产品信息
3. 条款清晰度：条款表述是否清晰易懂
4. 费率合理性：费率制定是否符合规定

【审核维度】
- 合规性
- 信息披露
- 条款清晰度
- 费率合理性

【审核输出】
对每个条款进行审核，输出：
- 合规问题（如有）
- 审核维度（问题属于哪个维度）
- 风险等级（high/medium/low）
- 依据法规
- 问题描述
- 改进建议

【评定依据】
在 assessment_reason 中说明：
- 通过/不通过的具体判定依据
- 主要风险点总结
- 整体合规水平评价

严格按照以下 JSON 格式输出：
```json
{{
  "overall_assessment": "通过/有条件通过/不通过",
  "assessment_reason": "评定依据说明，包括判定理由、主要风险点、整体评价",
  "issues": [
    {{
      "clause": "条款内容摘要",
      "severity": "high/medium/low",
      "dimension": "合规性/信息披露/条款清晰度/费率合理性",
      "regulation": "违反的法规名称和条款号",
      "description": "问题描述",
      "suggestion": "改进建议"
    }}
  ],
  "score": 0-100,
  "summary": "审核总结"
}}
```
"""


def get_system_prompt() -> str:
    return AUDIT_SYSTEM_PROMPT


def get_user_prompt(
    product_clause: str,
    regulation_references: List[Dict[str, Any]]
) -> str:
    references = []
    for ref in regulation_references:
        metadata = ref.get('metadata', {})
        law_name = metadata.get('law_name', UNKNOWN_REGULATION)
        article_num = metadata.get('article_number', '')
        content = ref.get('content', '')[:CONTENT_PREVIEW_LENGTH]

        references.append(f"- {law_name} {article_num}: {content}...")

    reference_text = "\n".join(references)

    return f"""请根据以下监管规定审核产品条款：

【产品条款】
{product_clause}

【相关法规依据】
{reference_text}

【审核要求】
1. 分析产品条款是否符合相关法规要求
2. 标注违反的具体法规条款
3. 标注问题所属的审核维度（合规性/信息披露/条款清晰度/费率合理性）
4. 评估合规风险
5. 提供改进建议
6. 说明评定依据（为什么给出通过/不通过的结论）

严格按照以下 JSON 格式输出：
```json
{{
  "overall_assessment": "通过/有条件通过/不通过",
  "assessment_reason": "评定依据说明",
  "issues": [
    {{
      "clause": "条款内容摘要",
      "severity": "high/medium/low",
      "dimension": "合规性/信息披露/条款清晰度/费率合理性",
      "regulation": "违反的法规名称和条款号",
      "description": "问题描述",
      "suggestion": "改进建议"
    }}
  ],
  "score": 0-100,
  "summary": "审核总结"
}}
```
"""
