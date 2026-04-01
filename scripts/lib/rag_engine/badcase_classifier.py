"""Badcase 三分类 LLM 结构化分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import logging
from typing import List, Dict, Any

from lib.rag_engine._llm_utils import get_llm_client, parse_llm_json_response

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """你是一个 RAG 系统的质量分析专家。请分析以下 badcase 并分类。

用户问题：{query}

检索到的来源：
{sources}

助手回答：
{answer}

未验证声明：{unverified_claims}

用户反馈原因：{reason}

请将此 badcase 分类为以下类别之一：
- retrieval_failure: 检索失败 — 知识库中有相关信息但未被检索到
- hallucination: 幻觉生成 — 检索到了相关文档但回答包含来源不支持的内容
- knowledge_gap: 知识缺失 — 知识库中确实不存在相关信息

返回 JSON（不要包含其他内容）：
{{"type": "<分类类型>", "reason": "<分类理由>", "fix_direction": "<修复建议方向>"}}"""

_COMPLIANCE_PROMPT = """评估以下 badcase 的合规风险等级。

用户反馈原因：{reason}
助手回答：{answer}

风险等级定义：
- 0（低）：一般性回答问题，不涉及合规敏感内容
- 1（中）：涉及保险条款解读，但无明显错误
- 2（高）：包含错误的金额、比例、法律条款引用，可能误导用户

返回 JSON（不要包含其他内容）：
{{"risk_level": 0, "reason": "<评估理由>"}}"""


def classify_badcase(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
) -> Dict[str, str]:
    """LLM 驱动的三分类自动分类。"""
    llm = get_llm_client()

    sources_text = "\n".join(
        f"- [{d.get('source_file', '未知')}] {d.get('content', '')[:200]}"
        for d in retrieved_docs
    ) if retrieved_docs else "（无检索结果）"

    claims_text = "；".join(unverified_claims[:5]) if unverified_claims else "（无）"

    prompt = _CLASSIFY_PROMPT.format(
        query=query,
        sources=sources_text,
        answer=answer[:500],
        unverified_claims=claims_text,
        reason="",
    )

    response = llm.generate(prompt)
    result = parse_llm_json_response(response)

    valid_types = {"retrieval_failure", "hallucination", "knowledge_gap"}
    if result.get("type") not in valid_types:
        raise ValueError(f"Invalid classification type: {result.get('type')}")

    return {
        "type": result["type"],
        "reason": result.get("reason", ""),
        "fix_direction": result.get("fix_direction", ""),
    }


def assess_compliance_risk(reason: str, answer: str) -> int:
    """LLM 驱动的合规风险评估。失败时返回 0（安全默认值）。"""
    if not answer and not reason:
        return 0

    try:
        llm = get_llm_client()
        prompt = _COMPLIANCE_PROMPT.format(reason=reason, answer=answer[:500])
        response = llm.generate(prompt)
        result = parse_llm_json_response(response)
        risk = int(result.get("risk_level", 0))
        return max(0, min(2, risk))
    except Exception as e:
        logger.warning(f"Compliance risk assessment failed, defaulting to 0: {e}")
        return 0
