#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt 模板

集中管理所有 LLM prompt 模板，便于维护和 A/B 测试。
"""

# 完整文档提取的 prompt 模板
EXTRACT_DOCUMENT_PROMPT = """你是保险产品文档解析专家。请分析以下保险产品文档，提取结构化信息。

**重要要求**:
1. 识别并忽略"阅读指引"、"投保须知"等非条款内容
2. 只提取"条款正文"中的真正条款
3. 过滤HTML标签、格式化字符
4. 提取产品基本信息和所有条款内容

文档内容:
```
{document}
```

**输出要求**:
- 必须且只能返回JSON格式
- 不要包含任何解释、分析或说明文字
- 直接返回JSON，不要使用markdown代码块

返回JSON:
{{
    "product_info": {{
        "product_name": "产品名称",
        "insurance_company": "保险公司",
        "product_type": "产品类型",
        "insurance_period": "保险期间",
        "payment_method": "缴费方式",
        "age_min": "最低投保年龄",
        "age_max": "最高投保年龄",
        "waiting_period": "等待期天数"
    }},
    "clauses": [
        {{"text": "条款内容", "reference": "条款编号"}}
    ],
    "pricing_params": {{
        "interest_rate": "预定利率",
        "expense_rate": "费用率",
        "premium_rate": "保费"
    }}
}}"""

# 分块提取的 prompt 模板
EXTRACT_CHUNK_PROMPT = """你是保险产品文档解析专家。请分析以下保险产品文档片段（第{index}/{total}块），提取结构化信息。

**重要要求**:
1. 只提取"条款正文"中的真正条款
2. 过滤HTML标签、格式化字符
3. 提取所有可见的条款内容
4. 如果产品信息在前面的块中已经提取过，可以忽略或补充
5. 提取定价相关参数（利率、费用率等）

文档片段:
```
{chunk}
```

**输出要求**:
- 必须且只能返回JSON格式
- 不要包含任何解释、分析或说明文字
- 直接返回JSON，不要使用markdown代码块

返回JSON:
{{
    "product_info": {{
        "product_name": "产品名称（如果在当前块中）",
        "insurance_company": "保险公司（如果在当前块中）",
        "product_type": "产品类型（如果在当前块中）",
        "insurance_period": "保险期间（如果在当前块中）",
        "payment_method": "缴费方式（如果在当前块中）",
        "age_min": "最低投保年龄（如果在当前块中）",
        "age_max": "最高投保年龄（如果在当前块中）",
        "waiting_period": "等待期天数（如果在当前块中）"
    }},
    "clauses": [
        {{"text": "条款内容", "reference": "条款编号/标题"}}
    ],
    "pricing_params": {{
        "interest_rate": "预定利率（如果在当前块中）",
        "expense_rate": "费用率（如果在当前块中）",
        "premium_rate": "保费（如果在当前块中）"
    }}
}}"""


def format_extract_document_prompt(document: str) -> str:
    """格式化完整文档提取 prompt"""
    return EXTRACT_DOCUMENT_PROMPT.format(document=document)


def format_extract_chunk_prompt(chunk: str, index: int, total: int) -> str:
    """格式化分块提取 prompt"""
    return EXTRACT_CHUNK_PROMPT.format(
        chunk=chunk,
        index=index + 1,
        total=total
    )
