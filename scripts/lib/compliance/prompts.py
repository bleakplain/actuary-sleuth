"""合规检查提示词模板"""

COMPLIANCE_PROMPT_PRODUCT = """你是一位保险法规合规专家。请根据以下产品参数和相关法规条款，逐项检查该产品是否符合法规要求。

## 产品信息
- 产品名称：{product_name}
- 险种类型：{category}
- 产品参数：{params_json}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<参数名称>",
            "value": "<产品实际值>",
            "requirement": "<法规要求，引用法规原文关键句>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：[来源X]>",
            "source_excerpt": "<从来源法规中直接摘录的原文片段，作为该判断的事实依据>",
            "suggestion": "<修改建议，仅不合规时填写>"
        }}
    ]
}}

注意：
1. 每个参数都要检查，未找到明确法规要求的标注为 attention
2. source 必须使用 [来源X] 格式引用法规条款
3. source_excerpt 必须是从对应来源中直接摘录的原文，不得自行编造或改写
4. requirement 应结合法规原文表述，使合规判断有据可查
5. 仅输出 JSON，不要附加其他文字
"""

COMPLIANCE_PROMPT_DOCUMENT = """你是一位保险法规合规专家。请审查以下保险条款文档，检查是否符合相关法规要求。

## 条款文档内容
{document_content}

## 相关法规条款
{context}

## 输出要求
请以 JSON 格式输出检查结果，严格遵循以下结构：
{{
    "summary": {{
        "compliant": <合规项数>,
        "non_compliant": <不合规项数>,
        "attention": <需关注项数>
    }},
    "items": [
        {{
            "param": "<检查项名称>",
            "value": "<条款中的实际内容>",
            "requirement": "<法规要求，引用法规原文关键句>",
            "status": "<compliant|non_compliant|attention>",
            "source": "<法规来源，格式：[来源X]>",
            "source_excerpt": "<从来源法规中直接摘录的原文片段，作为该判断的事实依据>",
            "suggestion": "<修改建议>"
        }}
    ],
    "extracted_params": {{
        "<参数名>": "<提取值>"
    }}
}}

注意：
1. 先提取条款中的关键参数，再逐项检查合规性
2. 检查项包括但不限于：等待期、免赔额、保险期间、缴费方式、免责条款等
3. source 必须使用 [来源X] 格式引用法规条款
4. source_excerpt 必须是从对应来源中直接摘录的原文，不得自行编造或改写
5. requirement 应结合法规原文表述，使合规判断有据可查
6. 仅输出 JSON，不要附加其他文字
"""
