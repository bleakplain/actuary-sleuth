"""合规检查核心逻辑"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.common.regulation_registry import (
    get_category_regulations,
    get_general_regulations,
    VALID_CATEGORIES,
)
from lib.llm import get_qa_llm
from lib.rag_engine import get_engine

logger = logging.getLogger(__name__)


def _build_context(search_results: List[Dict]) -> str:
    """将检索结果构建为上下文字符串"""
    parts = []
    for i, r in enumerate(search_results):
        law_name = r.get("law_name", "")
        article = r.get("article_number", "")
        content = r.get("content", "")
        authority = r.get("issuing_authority", "")
        doc_number = r.get("doc_number", "")
        effective = r.get("effective_date", "")
        header = f"[来源{i+1}] 【{law_name}】{article}"
        if doc_number:
            header += f"（{doc_number}）"
        if authority:
            header += f"\n发布机关：{authority}"
        if effective:
            header += f"\n生效日期：{effective}"
        parts.append(f"{header}\n{content}")
    return "\n\n".join(parts)


def _load_negative_list() -> List[Dict]:
    """从知识库检索负面清单全量文档"""
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return []
    return engine.search_by_metadata({"category": "负面清单检查"})


def check_negative_list(document_content: str) -> List[Dict]:
    """执行负面清单检查

    通过知识库检索负面清单文档，逐条判断是否违规。

    Args:
        document_content: 文档内容

    Returns:
        检查项列表
    """
    negative_docs = _load_negative_list()
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return []

    items = []
    for doc in negative_docs:
        law_name = doc.get("law_name", "")
        article_number = doc.get("article_number", "")
        content = doc.get("content", "")

        if not content or not article_number:
            continue

        violation = _check_violation(document_content, content, law_name, article_number)
        if violation:
            items.append(violation)

    return items


def _check_violation(
    document_content: str,
    negative_rule: str,
    law_name: str,
    article_number: str,
) -> Optional[Dict[str, Any]]:
    """判断文档内容是否违反负面清单规定

    Args:
        document_content: 待审文档内容
        negative_rule: 负面清单规则内容
        law_name: 法规名称
        article_number: 条款编号

    Returns:
        违规项字典，无违规返回 None
    """
    try:
        llm = get_qa_llm()

        prompt = f"""你是一位保险法规合规专家。请判断以下保险产品文档内容是否违反了负面清单规定。

## 负面清单规定
{negative_rule[:500]}

## 待审文档内容
{document_content[:2000]}

## 输出要求
请以 JSON 格式输出判断结果：
{{
    "is_violation": true或false,
    "reason": "<违规原因，说明文档中哪些表述违反了规定>",
    "source_excerpt": "<文档中违规的原文片段>",
    "suggestion": "<修改建议，指导如何修改以符合规定>"
}}

注意：
1. 仅当文档内容确实存在违反负面清单规定的表述时，is_violation 为 true
2. 如果文档内容符合规定或与该负面清单无关，is_violation 为 false
3. 仅输出 JSON，不要附加其他文字"""

        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()

        # 解析 JSON
        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

        json_start = answer.find("{")
        json_end = answer.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            return None

        result = json.loads(answer[json_start:json_end])

        if not result.get("is_violation", False):
            return None

        return {
            "clause_number": "",
            "param": f"负面清单检查: {law_name} {article_number}",
            "value": result.get("source_excerpt", "")[:100],
            "requirement": f"违反负面清单 {law_name} {article_number}: {negative_rule[:200]}",
            "status": "non_compliant",
            "source": "负面清单",
            "source_excerpt": negative_rule[:300],
            "suggestion": result.get("suggestion", "请修改相关表述，确保符合负面清单要求"),
        }

    except Exception as e:
        logger.warning(f"负面清单检查失败: {e}")
        return None


def identify_category(document_content: str, product_name: str = "") -> Tuple[Optional[str], float, str]:
    """识别险种类型

    Args:
        document_content: 文档内容
        product_name: 产品名称

    Returns:
        (category, confidence, method): 险种、置信度、识别方法
    """
    from lib.common.product_types import ProductCategory, classify_product

    # 方法1: 关键词匹配（快速）
    category_enum = classify_product(product_name, document_content[:1000])
    if category_enum != ProductCategory.OTHER:
        return category_enum.value, 0.7, "keyword"

    # 方法2: LLM 提取
    try:
        llm = get_qa_llm()
        prompt = f"""请从以下保险产品文档中识别险种类型。

可选险种类型：健康险、医疗险、重疾险、寿险、意外险、年金险、财产险

产品名称：{product_name}
文档内容：
{document_content[:2000]}

仅输出险种类型名称，不要输出其他内容。"""

        response = llm.chat([{"role": "user", "content": prompt}])
        extracted = str(response).strip()

        for vc in VALID_CATEGORIES:
            if vc in extracted:
                return vc, 0.85, "llm"
    except Exception as e:
        logger.warning(f"LLM category identification failed: {e}")

    return None, 0.0, "unknown"


def build_enhanced_context(
    category: Optional[str],
    top_k: int = 10,
) -> Tuple[str, Dict[str, List[str]]]:
    """构建增强的法规上下文

    采用两层检索策略：
    1. 险种专属法规（精确匹配）
    2. 通用法规（强制全量加载）

    Args:
        category: 险种类型
        top_k: 保留参数（兼容性）

    Returns:
        (context_str, sources_info): 法规上下文字符串和来源信息
    """
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return "", {"险种专属": [], "通用法规": []}

    all_results = []
    sources_info: Dict[str, List[str]] = {
        "险种专属": [],
        "通用法规": [],
    }

    # 第1层：加载险种专属法规（全量精确匹配）
    if category:
        category_regs = get_category_regulations(category)
        for reg_name in category_regs:
            results = engine.search_by_metadata({"law_name": reg_name})
            all_results.extend(results)
            if results:
                logger.debug(f"险种专属法规 {reg_name}: {len(results)} 条")
        sources_info["险种专属"] = category_regs

    # 第2层：加载通用法规（全量强制包含）
    general_regs = get_general_regulations()
    for reg_name in general_regs:
        results = engine.search_by_metadata({"law_name": reg_name})
        all_results.extend(results)
        if results:
            logger.debug(f"通用法规 {reg_name}: {len(results)} 条")
    sources_info["通用法规"] = general_regs

    context = _build_context(all_results)
    logger.info(
        f"构建法规上下文: 险种专属 {len(sources_info['险种专属'])} 部, "
        f"通用法规 {len(sources_info['通用法规'])} 部, 共 {len(all_results)} 条"
    )
    return context, sources_info


def run_compliance_check(prompt: str) -> Dict:
    """执行合规检查 LLM 调用

    Args:
        prompt: 完整的合规检查提示词（已包含法规 context）

    Returns:
        检查结果字典
    """
    try:
        llm = get_qa_llm()

        logger.info(f"Prompt length: {len(prompt)}")
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response)

        logger.info(f"LLM response length: {len(answer)}, preview: {answer[:200]}")

        # 移除思维链标签
        if "<tool_call>" in answer and "遭遇" in answer:
            think_end = answer.rfind("遭遇") + len("遭遇")
            answer = answer[think_end:].strip()

        # 移除 markdown 代码块标记
        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

        try:
            json_start = answer.find("{")
            json_end = answer.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = answer[json_start:json_end]
                try:
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    # 尝试修复截断的 JSON
                    open_brackets = json_str.count("{") - json_str.count("}")
                    open_arrays = json_str.count("[") - json_str.count("]")
                    json_str_fixed = json_str + "]" * open_arrays + "}" * open_brackets
                    try:
                        parsed = json.loads(json_str_fixed)
                    except json.JSONDecodeError:
                        parsed = {
                            "summary": {
                                "compliant": len(re.findall(r'"compliant":\s*\d+', answer)),
                                "non_compliant": len(re.findall(r'"non_compliant":\s*\d+', answer)),
                                "attention": len(re.findall(r'"attention":\s*\d+', answer)),
                            },
                            "items": [],
                            "raw_answer": answer[:1000],
                        }
            else:
                logger.warning(f"No JSON found in LLM response: {answer[:200]}")
                parsed = {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": []}
        except Exception as e:
            logger.warning(f"JSON parse error: {e}, response: {answer[:500]}")
            parsed = {
                "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                "items": [],
                "raw_answer": answer[:1000],
            }

        return parsed

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": [], "error": str(e)}
