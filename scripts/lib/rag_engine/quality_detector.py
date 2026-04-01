"""自动质量检测 — LLM 驱动的三维度评分（忠实度 + 相关性 + 完整性）。"""
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

_QUALITY_PROMPT = """评估以下回答的质量，从三个维度打分。

用户问题：{query}

来源内容：
{sources}

回答内容：
{answer}

维度定义：
1. faithfulness（忠实度）: 回答是否严格基于来源内容，无无依据内容
   - 1.0: 完全基于来源
   - 0.7: 基本基于来源，有少量合理推断
   - 0.4: 部分基于来源，存在一些无依据内容
   - 0.0: 主要基于来源之外的信息

2. relevance（相关性）: 回答是否切题回答了用户问题
   - 1.0: 完全切题
   - 0.7: 基本切题但有偏差
   - 0.4: 部分相关
   - 0.0: 完全不相关

3. completeness（完整性）: 回答是否充分覆盖了问题涉及的方面
   - 1.0: 充分覆盖
   - 0.7: 基本覆盖，有少量遗漏
   - 0.4: 部分覆盖
   - 0.0: 未覆盖问题核心

每个维度 0.0-1.0 评分。如果有问题请填写 issues 字段。

返回 JSON（不要包含其他内容）：
{{"faithfulness": {{"score": 0.0, "issues": ""}}, "relevance": {{"score": 0.0, "issues": ""}}, "completeness": {{"score": 0.0, "issues": ""}}}}"""


def _get_llm():
    """获取 LLM 客户端，延迟导入避免循环依赖。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise RuntimeError("RAG 引擎未就绪")
    return rag_engine.llm_provider()


def _parse_json_response(text: str) -> Dict:
    """从 LLM 响应中提取 JSON，处理 markdown 代码块包裹。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def detect_quality(
    query: str,
    answer: str,
    sources: List[Dict[str, Any]],
    faithfulness_score: float = None,
) -> Dict[str, float]:
    """LLM 驱动的三维度质量评分。

    Args:
        query: 用户问题
        answer: 助手回答
        sources: 检索到的来源列表
        faithfulness_score: 已弃用，保留参数兼容性但不再使用

    Returns:
        包含 faithfulness, relevance, completeness, overall 四个 0-1 分数的字典
    """
    if not query or not answer:
        return {"faithfulness": 0.0, "relevance": 0.0, "completeness": 0.0, "overall": 0.0}

    llm = _get_llm()

    sources_text = "\n".join(
        f"- {s.get('content', '')[:300]}"
        for s in sources
    ) if sources else "（无来源）"

    prompt = _QUALITY_PROMPT.format(
        query=query,
        sources=sources_text,
        answer=answer[:500],
    )

    response = llm.generate(prompt)
    result = _parse_json_response(response)

    faithfulness = float(result.get("faithfulness", {}).get("score", 0.0))
    relevance = float(result.get("relevance", {}).get("score", 0.0))
    completeness = float(result.get("completeness", {}).get("score", 0.0))

    # Clamp to [0, 1]
    faithfulness = max(0.0, min(1.0, faithfulness))
    relevance = max(0.0, min(1.0, relevance))
    completeness = max(0.0, min(1.0, completeness))

    overall = 0.4 * faithfulness + 0.3 * relevance + 0.3 * completeness

    return {
        "faithfulness": round(faithfulness, 4),
        "relevance": round(relevance, 4),
        "completeness": round(completeness, 4),
        "overall": round(overall, 4),
    }
