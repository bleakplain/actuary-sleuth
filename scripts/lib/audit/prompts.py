#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合规审核 Prompt 模板

用于产品条款合规性审核的提示词。
"""

# 合规审核提示词
AUDIT_SYSTEM_PROMPT = """你是一位保险产品合规审核专家，负责根据监管规定审核保险产品条款。

【审核标准】
1. 条款合规性：是否符合相关法律法规
2. 信息披露：是否充分披露产品信息
3. 条款清晰度：条款表述是否清晰易懂
4. 费率合理性：费率制定是否符合规定

【审核输出】
对每个条款进行审核，输出：
- 合规问题（如有）
- 风险等级（high/medium/low）
- 改进建议

严格按照以下 JSON 格式输出：
```json
{{
  "overall_assessment": "通过/有条件通过/不通过",
  "issues": [
    {{
      "clause": "条款内容摘要",
      "severity": "high/medium/low",
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

# 条款对比提示词
CLAUSE_COMPARISON_PROMPT = """请对比以下产品条款与监管规定的差异。

【产品条款】
{product_clause}

【监管规定】
{regulation_content}

【对比维度】
1. 内容一致性
2. 覆盖完整性
3. 表述准确性

请返回对比结果：
```json
{{
  "is_compliant": true|false,
  "differences": ["差异1", "差异2"],
  "missing_points": ["缺失点1", "缺失点2"],
  "risk_level": "high/medium/low"
}}
```
"""


def get_audit_prompt() -> str:
    """获取合规审核提示词"""
    return AUDIT_SYSTEM_PROMPT


def format_comparison_prompt(product_clause: str, regulation_content: str) -> str:
    """格式化条款对比提示词"""
    return CLAUSE_COMPARISON_PROMPT.format(
        product_clause=product_clause,
        regulation_content=regulation_content
    )
