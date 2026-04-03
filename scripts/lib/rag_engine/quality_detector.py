"""自动质量检测 — 三维度评分（忠实度 + 检索相关性 + 完整性）。"""
import re
import logging
from typing import List, Dict, Any, Optional

from .evaluator import _token_bigrams

logger = logging.getLogger(__name__)

_NUMBER_PATTERN = re.compile(r'\d+[%年月天元周岁条]|第[一二三四五六七八九十百千\d]+条')
_QUESTION_NUMBER_PATTERN = re.compile(r'多少|几|哪些|什么比例|多少天|多少年|上限|下限')


def compute_retrieval_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    """计算 query 与检索结果的 bigram 重叠度"""
    if not query or not sources:
        return 0.0

    query_bigrams = _token_bigrams(query)
    if not query_bigrams:
        return 0.0

    context_bigrams: set = set()
    for s in sources:
        content = s.get("content", "")
        if content:
            context_bigrams |= _token_bigrams(content)

    if not context_bigrams:
        return 0.0

    matched = query_bigrams & context_bigrams
    return len(matched) / len(query_bigrams)


def compute_info_completeness(query: str, answer: str) -> float:
    """检测关键信息完整性"""
    if not query or not answer:
        return 0.0

    if not _QUESTION_NUMBER_PATTERN.search(query) and not _NUMBER_PATTERN.search(query):
        return 1.0

    answer_numbers = _NUMBER_PATTERN.findall(answer)
    if not answer_numbers:
        return 0.0

    question_numbers = _NUMBER_PATTERN.findall(query)
    if not question_numbers:
        return 1.0

    matched = sum(1 for qn in question_numbers if any(qn in an for an in answer_numbers))
    return matched / len(question_numbers) if question_numbers else 1.0


def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: Optional[float] = None,
) -> Dict[str, float]:
    """三维度自动质量评分

    当 faithfulness_score 不可用时，自动将权重重新分配给
    retrieval_relevance 和 completeness（各 50%）。
    """
    faithfulness = faithfulness_score if faithfulness_score is not None else 0.0
    retrieval_relevance = compute_retrieval_relevance(query, sources)
    completeness = compute_info_completeness(query, answer)

    if faithfulness_score is not None:
        overall = (
            0.4 * faithfulness +
            0.3 * retrieval_relevance +
            0.3 * completeness
        )
    else:
        overall = (
            0.5 * retrieval_relevance +
            0.5 * completeness
        )

    return {
        "faithfulness": round(faithfulness, 4),
        "retrieval_relevance": round(retrieval_relevance, 4),
        "completeness": round(completeness, 4),
        "overall": round(overall, 4),
    }
