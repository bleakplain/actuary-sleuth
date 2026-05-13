"""合规检查提示词模板"""

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
            "suggestion": "<修改建议，合规时留空>",
            "conclusion": "<简要说明审核结论，解释该条款为何合规/不合规/需关注，一句话概括>"
        }}
    ]
}}

注意：
1. 必须检查文档中的每一项条款，不要遗漏任何条款
2. source_ref 必须是上面法规的编号，范围为 R1 到 R{regulation_count}，引用与该条款最相关的法规
3. 选择 source_ref 时，先理解条款内容，再找到法规列表中内容最匹配的编号
4. clause_number 必须对应文档中实际的条款编号
5. conclusion 必须填写，简要说明该条款的审核结论及原因
6. 仅输出 JSON"""
