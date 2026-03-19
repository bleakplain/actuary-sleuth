#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合规审核 Prompt 模板

用于产品条款合规性审核的提示词。
"""

from typing import List, Dict, Any, Optional, Union

# 常量配置
UNKNOWN_REGULATION = "未知法规"
CONTENT_PREVIEW_LENGTH = 300

# 产品类别名称映射
CATEGORY_NAMES = {
    'critical_illness': "重大疾病险",
    'medical_insurance': "医疗保险",
    'life_insurance': "人身保险",
    'participating_life': "分红型寿险",
    'universal_life': "万能险",
    'annuity': "年金保险",
    'accident': "意外伤害保险",
    'health': "健康保险",
    'pension': "养老保险",
    'other': "其他保险",
}

# 审核维度定义
AUDIT_DIMENSIONS = [
    "合规性",
    "信息披露",
    "条款清晰度",
    "费率合理性"
]

# 风险等级定义
SEVERITY_LEVELS = [
    "high",
    "medium",
    "low"
]

# 评定结果定义
ASSESSMENT_RESULTS = [
    "通过",
    "有条件通过",
    "不通过"
]


def _get_category_name(category) -> str:
    """获取产品类别中文名称"""
    # 处理 Enum 和字符串两种情况
    if hasattr(category, 'value'):
        key = category.value
    else:
        key = str(category)
    return CATEGORY_NAMES.get(key, "其他保险")

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
    product_context: Optional[Dict[str, Any]],
    clause: Dict[str, str],
    regulation_references: List[Dict[str, Any]]
) -> str:
    """
    构建审核提示词

    Args:
        product_context: 产品上下文信息（可选）
        clause: 条款对象，包含 text, number, title
        regulation_references: 相关法规引用
    """
    references = []
    for ref in regulation_references:
        metadata = ref.get('metadata', {})
        law_name = metadata.get('law_name', UNKNOWN_REGULATION)
        article_num = metadata.get('article_number', '')
        content = ref.get('content', '')[:CONTENT_PREVIEW_LENGTH]

        references.append(f"- {law_name} {article_num}: {content}...")

    reference_text = "\n".join(references)

    # 如果有产品上下文，构建产品信息部分
    product_info = ""
    if product_context:
        parts = []

        if product_context.get('product_name'):
            parts.append(f"产品名称：{product_context['product_name']}")
        if product_context.get('company'):
            parts.append(f"保险公司：{product_context['company']}")
        if product_context.get('category'):
            parts.append(f"产品类型：{_get_category_name(product_context['category'])}")
        if product_context.get('period'):
            parts.append(f"保险期间：{product_context['period']}")
        if product_context.get('waiting_period'):
            parts.append(f"等待期：{product_context['waiting_period']}天")

        age_min = product_context.get('age_min')
        age_max = product_context.get('age_max')
        if age_min or age_max:
            parts.append(f"投保年龄：{age_min or '-'}-{age_max or '-'}岁")

        # 保障信息
        coverage = product_context.get('coverage')
        if coverage:
            if coverage.get('scope'):
                parts.append(f"保障范围：{coverage['scope']}")
            if coverage.get('deductible'):
                parts.append(f"免赔额：{coverage['deductible']}")
            if coverage.get('payout_ratio'):
                parts.append(f"赔付比例：{coverage['payout_ratio']}")

        # 费率信息
        premium = product_context.get('premium')
        if premium:
            if premium.get('payment_method'):
                parts.append(f"缴费方式：{premium['payment_method']}")
            if premium.get('payment_period'):
                parts.append(f"缴费期间：{premium['payment_period']}")

        if parts:
            product_info = "\n".join(["【产品信息】", *parts, ""])

    # 构建条款标识
    clause_header = ""
    if clause:
        parts = []
        if clause.get('number'):
            parts.append(f"条款编号：{clause['number']}")
        if clause.get('title'):
            parts.append(f"条款标题：{clause['title']}")
        if parts:
            clause_header = "\n".join(["【条款信息】", *parts, ""])

    clause_text = clause.get('text', '') if clause else ''

    return f"""请根据以下监管规定审核产品条款：

{product_info}{clause_header}【待审核条款】
{clause_text}

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


__all__ = [
    'get_system_prompt',
    'get_user_prompt',
    'UNKNOWN_REGULATION',
    'CONTENT_PREVIEW_LENGTH',
    'CATEGORY_NAMES',
    'AUDIT_DIMENSIONS',
    'SEVERITY_LEVELS',
    'ASSESSMENT_RESULTS',
    '_get_category_name',
]
