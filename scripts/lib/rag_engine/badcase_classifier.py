"""Badcase 三分类自动分类 + 合规风险评估。

分类类型（适配本系统无路由错误的场景）：
- retrieval_failure: 检索失败 — 知识库有答案但没检索到
- hallucination: 幻觉生成 — 检索正确但 LLM 答案错误
- knowledge_gap: 知识缺失 — 知识库里确实没有
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

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
) -> Dict[str, str]:
    """三分类自动分类"""
    combined_content = " ".join(d.get("content", "") for d in retrieved_docs)
    if not combined_content.strip():
        return {
            "type": "knowledge_gap",
            "reason": "检索结果为空",
            "fix_direction": "补充相关法规文档到知识库",
        }

    if unverified_claims:
        claims_preview = "；".join(unverified_claims[:3])
        return {
            "type": "hallucination",
            "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
            "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
        }

    _gap_phrases = [
        "未找到", "未涉及", "没有找到", "无法确定",
        "未提供", "未包含", "条款中未找到",
    ]
    is_gap_answer = any(phrase in answer for phrase in _gap_phrases)
    if is_gap_answer:
        # 检查检索内容与查询的相关性（使用字符级别匹配）
        query_chars = set(query)
        content_chars = set(combined_content)
        overlap = len(query_chars & content_chars)

        # 如果有足够的字符重叠（> 2个字符），说明检索到了相关文档但答案仍有问题 → 检索失败
        # 否则说明检索到了完全不相关的内容 → 知识缺失
        if overlap > 2:
            return {
                "type": "retrieval_failure",
                "reason": f"检索到的文档与查询有 {overlap} 个重叠字符，但答案表示未找到",
                "fix_direction": "优化 Chunk 策略、混合检索权重或 RRF 参数",
            }
        else:
            return {
                "type": "knowledge_gap",
                "reason": f"系统回答表示未找到相关信息: {answer[:100]}",
                "fix_direction": "补充相关法规文档到知识库",
            }

    if unverified_claims:
        claims_preview = "；".join(unverified_claims[:3])
        return {
            "type": "hallucination",
            "reason": f"回答包含 {len(unverified_claims)} 条未引用的事实性陈述: {claims_preview}",
            "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
        }

    from .tokenizer import tokenize_chinese
    answer_bigrams = set()
    tokens = tokenize_chinese(answer)
    for i in range(len(tokens) - 1):
        answer_bigrams.add(tokens[i] + tokens[i + 1])

    context_bigrams = set()
    ctx_tokens = tokenize_chinese(combined_content)
    for i in range(len(ctx_tokens) - 1):
        context_bigrams.add(ctx_tokens[i] + ctx_tokens[i + 1])

    if answer_bigrams and context_bigrams:
        overlap = len(answer_bigrams & context_bigrams) / len(answer_bigrams)
        if overlap < 0.2:
            return {
                "type": "hallucination",
                "reason": f"答案与检索内容重叠度极低({overlap:.2f})，疑似幻觉",
                "fix_direction": "加强 Prompt 忠实度约束，要求 LLM 严格引用来源",
            }

    return {
        "type": "retrieval_failure",
        "reason": "检索结果可能不相关或排序不佳",
        "fix_direction": "优化 Chunk 策略、混合检索权重或 RRF 参数",
    }


def assess_compliance_risk(reason: str, answer: str) -> int:
    """评估合规风险等级"""
    if not answer:
        return 0

    if "答案错误" in reason and _COMPLIANCE_AMOUNT_PATTERN.search(answer):
        return 2

    if _COMPLIANCE_KEYWORD_PATTERN.search(answer):
        return 1

    return 0
