"""Badcase 三分类自动分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import json
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT = """分析以下 RAG 系统的失败案例，判断失败原因类型。

## 用户问题
{query}

## 检索到的文档（Top3）
{docs}

## 系统回答
{answer}

## 未验证声明
{unverified}

请判断失败类型（只能选一个）：
A. retrieval_failure — 检索失败：文档里有答案但没检索到
B. hallucination — 幻觉生成：检索结果正确但 LLM 生成了错误答案
C. knowledge_gap — 知识缺失：知识库里确实没有这个信息

输出 JSON（不要输出其他内容）：{{"type": "A/B/C", "reason": "具体原因"}}"""

_HEURISTIC_GAP_PHRASES = [
    "未找到", "未涉及", "没有找到", "无法确定",
    "未提供", "未包含", "条款中未找到",
]

_FIX_DIRECTIONS = {
    "retrieval_failure": "优化 Chunk 策略、混合检索权重或 RRF 参数",
    "hallucination": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
    "knowledge_gap": "补充相关法规文档到知识库",
}

_COMPLIANCE_AMOUNT_PATTERN = re.compile(
    r'\d+[%元万元]|身故保险金|赔付|赔偿|保额|保费|等待期|免赔'
)
_COMPLIANCE_KEYWORD_PATTERN = re.compile(
    r'(不得|必须|禁止|严禁|不得以|免除|承担|退还|返还)'
)


def classify_badcase(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
    llm_client: Optional[Any] = None,
) -> Dict[str, str]:
    """三分类自动分类

    Args:
        query: 用户问题
        retrieved_docs: 检索到的文档列表
        answer: 系统回答
        unverified_claims: 未验证声明列表
        llm_client: 可选 LLM 客户端，提供时使用 LLM 分类

    Returns:
        包含 type, reason, fix_direction 的字典
    """
    combined_content = " ".join(d.get("content", "") for d in retrieved_docs)
    if not combined_content.strip():
        return {
            "type": "knowledge_gap",
            "reason": "检索结果为空",
            "fix_direction": _FIX_DIRECTIONS["knowledge_gap"],
        }

    if any(phrase in answer for phrase in _HEURISTIC_GAP_PHRASES):
        query_chars = set(query)
        content_chars = set(combined_content)
        if len(query_chars & content_chars) <= 2:
            return {
                "type": "knowledge_gap",
                "reason": f"系统回答表示未找到相关信息: {answer[:100]}",
                "fix_direction": _FIX_DIRECTIONS["knowledge_gap"],
            }

    if llm_client is not None:
        result = _classify_with_llm(
            query, retrieved_docs, answer, unverified_claims, llm_client
        )
        if result is not None:
            return result

    return _classify_heuristic(combined_content, answer, unverified_claims)


def _classify_with_llm(
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    answer: str,
    unverified_claims: List[str],
    llm_client: Any,
) -> Optional[Dict[str, str]]:
    docs_text = "\n".join(
        f"[{i}] {d.get('content', '')[:300]}"
        for i, d in enumerate(retrieved_docs[:3], 1)
    )
    unverified_text = "；".join(unverified_claims[:5]) if unverified_claims else "无"

    prompt = _CLASSIFY_PROMPT.format(
        query=query,
        docs=docs_text,
        answer=answer[:500],
        unverified=unverified_text,
    )

    try:
        response = llm_client.generate(prompt)
        return _parse_llm_classification(str(response).strip())
    except Exception as e:
        logger.warning(f"LLM 分类失败，回退到启发式: {e}")
        return None


def _parse_llm_classification(response: str) -> Optional[Dict[str, str]]:
    json_match = re.search(r'\{[^}]+\}', response)
    if not json_match:
        return None

    try:
        data = json.loads(json_match.group())
        type_map = {
            "A": "retrieval_failure",
            "B": "hallucination",
            "C": "knowledge_gap",
            "retrieval_failure": "retrieval_failure",
            "hallucination": "hallucination",
            "knowledge_gap": "knowledge_gap",
        }
        mapped_type = type_map.get(data.get("type", ""))
        if not mapped_type:
            return None

        return {
            "type": mapped_type,
            "reason": data.get("reason", ""),
            "fix_direction": _FIX_DIRECTIONS[mapped_type],
        }
    except (json.JSONDecodeError, KeyError):
        return None


def _classify_heuristic(
    combined_content: str,
    answer: str,
    unverified_claims: List[str],
) -> Dict[str, str]:
    if unverified_claims:
        claims_preview = "；".join(unverified_claims[:3])
        return {
            "type": "hallucination",
            "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
            "fix_direction": _FIX_DIRECTIONS["hallucination"],
        }

    if any(phrase in answer for phrase in _HEURISTIC_GAP_PHRASES):
        return {
            "type": "retrieval_failure",
            "reason": "检索到的文档与查询相关但答案表示未找到",
            "fix_direction": _FIX_DIRECTIONS["retrieval_failure"],
        }

    return {
        "type": "retrieval_failure",
        "reason": "检索结果可能不相关或排序不佳",
        "fix_direction": _FIX_DIRECTIONS["retrieval_failure"],
    }


def assess_compliance_risk(badcase_type: str, reason: str, answer: str) -> int:
    """评估合规风险等级

    Args:
        badcase_type: 分类类型 (retrieval_failure / hallucination / knowledge_gap)
        reason: 分类原因
        answer: 系统回答

    Returns:
        风险等级: 0=低, 1=中, 2=高
    """
    if not answer:
        return 0

    if badcase_type == "hallucination" and _COMPLIANCE_AMOUNT_PATTERN.search(answer):
        return 2

    if _COMPLIANCE_KEYWORD_PATTERN.search(answer):
        return 1

    return 0
