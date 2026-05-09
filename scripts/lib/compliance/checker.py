"""合规检查核心逻辑"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lib.common.product_types import ProductCategory, classify_product
from lib.common.regulation_registry import (
    get_category_regulations,
    get_general_regulations,
    VALID_CATEGORIES,
)
from lib.llm import get_audit_llm
from lib.rag_engine import get_engine

# ProductCategory 枚举值(全称) → VALID_CATEGORIES(简称) 映射
_ENUM_TO_CATEGORY: Dict[ProductCategory, str] = {
    ProductCategory.HEALTH: "健康险",
    ProductCategory.ACCIDENT: "意外险",
    ProductCategory.ANNUITY: "年金险",
    ProductCategory.PROPERTY: "财产险",
    ProductCategory.LIFE: "寿险",
    ProductCategory.MOTOR: "财产险",
    ProductCategory.PENSION: "年金险",
    ProductCategory.EDUCATION: "年金险",
    ProductCategory.TRAVEL: "意外险",
}

logger = logging.getLogger(__name__)


class CheckResult:
    """检查结果状态"""
    PASSED = "passed"          # 已检查，无违规
    VIOLATED = "violated"      # 已检查，有违规
    SKIPPED = "skipped"        # 未检查（引擎不可用等）


class ViolationSource:
    """违规来源"""
    NEGATIVE_LIST = "负面清单"
    REGULATION = "法规"


@dataclass(frozen=True)
class CategoryResult:
    """险种识别结果"""
    category: Optional[str]
    confidence: float
    method: str


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


def check_negative_list(document_content: str) -> Tuple[List[Dict], str]:
    """执行负面清单检查（批量，一次 LLM 调用）

    Args:
        document_content: 文档内容

    Returns:
        (items, result): 违规项列表 + 检查结果状态
        result: "passed" | "violated" | "skipped"
    """
    negative_docs = _load_negative_list()
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return [], CheckResult.SKIPPED

    rules_text = "\n".join([
        f"{i+1}. 【{doc.get('law_name', '')}】{doc.get('article_number', '')}: {doc.get('content', '')}"
        for i, doc in enumerate(negative_docs)
        if doc.get("content") and doc.get("article_number")
    ])

    if not rules_text:
        return [], CheckResult.SKIPPED

    prompt = f"""你是一位保险法规合规专家。请判断以下保险产品文档是否违反负面清单规定。

## 负面清单规定（共 {len(negative_docs)} 条）
{rules_text}

## 待审文档内容
{document_content}

## 输出要求
请以 JSON 格式输出所有违规项：
[
  {{"rule_id": 1, "is_violation": true, "reason": "<违规原因>", "source_excerpt": "<文档中违规原文>", "suggestion": "<修改建议>"}},
  {{"rule_id": 2, "is_violation": false}},
  ...
]

注意：
1. 仅输出 is_violation 为 true 的项（或省略 false 项）
2. rule_id 对应上面规则的编号
3. 仅输出 JSON，不要附加其他文字
"""

    try:
        llm = get_audit_llm()
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()

        items = _parse_violation_response(answer, negative_docs)
        result = CheckResult.VIOLATED if items else CheckResult.PASSED
        return items, result
    except Exception as e:
        logger.error(f"Negative list check failed: {e}")
        return [], CheckResult.SKIPPED


def _parse_violation_response(answer: str, negative_docs: List[Dict]) -> List[Dict]:
    """解析 LLM 返回的违规项列表"""
    from lib.doc_parser.kb.converter.excel_to_md import extract_json_array
    try:
        json_str = extract_json_array(answer)
        if json_str is None:
            return []

        violations = json.loads(json_str)
        items = []
        for v in violations:
            if not v.get("is_violation", False):
                continue
            rule_id = v.get("rule_id", 0) - 1
            if 0 <= rule_id < len(negative_docs):
                doc = negative_docs[rule_id]
                items.append({
                    "clause_number": "",
                    "param": f"负面清单检查: {doc.get('law_name', '')} {doc.get('article_number', '')}",
                    "value": v.get("source_excerpt", "")[:100],
                    "requirement": f"违反负面清单 {doc.get('law_name', '')} {doc.get('article_number', '')}: {doc.get('content', '')[:200]}",
                    "status": "non_compliant",
                    "source": ViolationSource.NEGATIVE_LIST,
                    "source_excerpt": doc.get("content", "")[:300],
                    "suggestion": v.get("suggestion", "请修改相关表述"),
                })
        return items
    except Exception as e:
        logger.warning(f"Failed to parse violation response: {e}")
        return []


def identify_category(document_content: str, product_name: str = "") -> CategoryResult:
    """识别险种类型

    Args:
        document_content: 文档内容
        product_name: 产品名称

    Returns:
        CategoryResult: 包含 category, confidence, method
    """
    category_enum = classify_product(product_name, document_content[:1000])
    if category_enum != ProductCategory.OTHER:
        mapped = _ENUM_TO_CATEGORY.get(category_enum)
        if mapped:
            return CategoryResult(mapped, 0.7, "keyword")

    try:
        llm = get_audit_llm()
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
                return CategoryResult(vc, 0.85, "llm")
    except Exception as e:
        logger.warning(f"LLM category identification failed: {e}")

    return CategoryResult(None, 0.0, "unknown")


def build_enhanced_context(
    category: Optional[str],
) -> Tuple[str, Dict[str, List[str]]]:
    """构建增强的法规上下文

    采用两层检索策略：
    1. 险种专属法规（精确匹配）
    2. 通用法规（强制全量加载）

    Args:
        category: 险种类型

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
        llm = get_audit_llm()

        logger.info(f"Prompt length: {len(prompt)}")
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response)

        logger.info(f"LLM response length: {len(answer)}, preview: {answer[:200]}")

<<<<<<< HEAD
        # 层级 1: 移除思维链标签
        if "<tool_call>" in answer and "遭遇" in answer:
            think_end = answer.rfind("遭遇") + len("遭遇")
            answer = answer[think_end:].strip()

        # 层级 2: 移除 markdown 代码块标记
=======
        # 移除 markdown 代码块标记
>>>>>>> origin/master
        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

        # 层级 3: 提取 JSON
        json_start = answer.find("{")
        json_end = answer.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            logger.warning(f"No JSON found in LLM response: {answer[:200]}")
            return {
                "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                "items": [],
                "error": "json_not_found",
                "raw_answer": answer[:1000],
            }

        json_str = answer[json_start:json_end]

        # 层级 4: 解析或修复
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            open_brackets = json_str.count("{") - json_str.count("}")
            open_arrays = json_str.count("[") - json_str.count("]")
            json_str_fixed = json_str + "]" * open_arrays + "}" * open_brackets
            try:
                return json.loads(json_str_fixed)
            except json.JSONDecodeError:
                logger.warning(f"JSON repair failed, returning empty result")
                return {
                    "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                    "items": [],
                    "error": "json_parse_failed",
                    "raw_answer": answer[:1000],
                }

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": [], "error": str(e)}
