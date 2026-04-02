"""合规检查路由 — 产品参数检查 + 条款文档审查。"""

import uuid
import json
import asyncio
import logging
from typing import Dict

from fastapi import APIRouter, HTTPException

from api.schemas.compliance import (
    ProductCheckRequest, DocumentCheckRequest, ComplianceReportOut,
)
from api.dependencies import get_rag_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compliance", tags=["合规检查"])

_COMPLIANCE_PROMPT_PRODUCT = """你是一位保险法规合规专家。请根据以下产品参数和相关法规条款，逐项检查该产品是否符合法规要求。

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

_COMPLIANCE_PROMPT_DOCUMENT = """你是一位保险法规合规专家。请审查以下保险条款文档，检查是否符合相关法规要求。

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



def _build_context(search_results: list) -> str:
    parts = []
    for i, r in enumerate(search_results):
        law_name = r.get('law_name', '')
        article = r.get('article_number', '')
        content = r.get('content', '')
        authority = r.get('issuing_authority', '')
        doc_number = r.get('doc_number', '')
        effective = r.get('effective_date', '')
        header = f"[来源{i+1}] 【{law_name}】{article}"
        if doc_number:
            header += f"（{doc_number}）"
        if authority:
            header += f"\n发布机关：{authority}"
        if effective:
            header += f"\n生效日期：{effective}"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)


def _run_compliance_check(engine, prompt: str) -> Dict:
    result = engine.ask(prompt)
    answer = result.get("answer", "")

    try:
        json_start = answer.find("{")
        json_end = answer.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(answer[json_start:json_end])
        else:
            parsed = {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": []}
    except json.JSONDecodeError:
        parsed = {
            "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
            "items": [],
            "raw_answer": answer,
        }

    parsed["sources"] = result.get("sources", [])
    parsed["citations"] = result.get("citations", [])
    return parsed


@router.post("/check/product", response_model=ComplianceReportOut)
async def check_product(req: ProductCheckRequest):
    engine = get_rag_engine()

    query = f"{req.category} 保险产品合规要求 {req.product_name}"
    search_results = engine.search(query, top_k=10)

    context = _build_context(search_results)

    prompt = _COMPLIANCE_PROMPT_PRODUCT.format(
        product_name=req.product_name,
        category=req.category,
        params_json=json.dumps(req.params, ensure_ascii=False),
        context=context,
    )

    try:
        result = await asyncio.to_thread(_run_compliance_check, engine, prompt)
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        raise HTTPException(status_code=500, detail=f"合规检查失败: {e}")

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    from api.database import save_compliance_report
    save_compliance_report(report_id, req.product_name, req.category, "product", result)

    return ComplianceReportOut(
        id=report_id,
        product_name=req.product_name,
        category=req.category,
        mode="product",
        result=result,
        created_at="",
    )


@router.post("/check/document", response_model=ComplianceReportOut)
async def check_document(req: DocumentCheckRequest):
    engine = get_rag_engine()

    try:
        from lib.llm.factory import LLMClientFactory
        llm = LLMClientFactory.create_qa_llm()
        extract_prompt = f"请从以下保险条款中提取关键参数（险种类型、等待期、免赔额等），以 JSON 格式输出：\n\n{req.document_content[:3000]}"
        extracted = llm.chat([{"role": "user", "content": extract_prompt}])
    except Exception:
        extracted = ""

    query = f"保险合规要求 {extracted[:200]}"
    search_results = engine.search(query, top_k=10)

    context = _build_context(search_results)

    prompt = _COMPLIANCE_PROMPT_DOCUMENT.format(
        document_content=req.document_content[:5000],
        context=context,
    )

    try:
        result = await asyncio.to_thread(_run_compliance_check, engine, prompt)
    except Exception as e:
        logger.error(f"Document check failed: {e}")
        raise HTTPException(status_code=500, detail=f"条款审查失败: {e}")

    report_id = f"cr_{uuid.uuid4().hex[:8]}"
    product_name = req.product_name or "未命名产品"
    from api.database import save_compliance_report
    save_compliance_report(report_id, product_name, "", "document", result)

    return ComplianceReportOut(
        id=report_id,
        product_name=product_name,
        category="",
        mode="document",
        result=result,
        created_at="",
    )


@router.get("/reports", response_model=list[ComplianceReportOut])
async def list_compliance_reports():
    from api.database import get_compliance_reports
    return get_compliance_reports()


@router.get("/reports/{report_id}", response_model=ComplianceReportOut)
async def get_compliance_report(report_id: str):
    from api.database import get_compliance_report
    report = get_compliance_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.delete("/reports/{report_id}")
async def delete_compliance_report(report_id: str):
    from api.database import get_connection
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM compliance_reports WHERE id = ?", (report_id,)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="报告不存在")
    return {"status": "deleted"}
