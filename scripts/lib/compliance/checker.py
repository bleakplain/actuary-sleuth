"""合规检查核心逻辑"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lib.common.constants import ComplianceConstants
from lib.common.product_types import ProductCategory, classify_product
from lib.common.regulation_registry import (
    get_category_regulations,
    get_general_regulations,
    VALID_CATEGORIES,
)
from lib.llm import get_audit_llm
from lib.rag_engine import get_engine

logger = logging.getLogger(__name__)


class CheckResult:
    PASSED = "passed"
    VIOLATED = "violated"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CategoryResult:
    category: Optional[str]
    confidence: float
    method: str


@dataclass(frozen=True)
class AuditRegulationItem:
    chunk_id: str
    law_name: str
    article_number: str
    content: str
    source_type: str  # "category" | "general" | "negative_list"
    doc_number: str = ""
    issuing_authority: str = ""
    effective_date: str = ""


@dataclass(frozen=True)
class AuditResultItem:
    clause_number: str
    check_type: str  # "regulation" | "negative_list"
    param: str
    value: str
    requirement: str
    status: str  # "compliant" | "non_compliant" | "attention"
    chunk_id: Optional[str]
    source_type: str  # "regulation" | "negative_list"
    source_excerpt: str
    suggestion: str


def _extract_real_article_number(content: str, fallback: str) -> str:
    match = re.match(r'第([一二三四五六七八九十百零]+)条', content)
    return f"第{match.group(1)}条" if match else fallback


def load_audit_regulations(category: Optional[str]) -> List[AuditRegulationItem]:
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return []

    all_results = []
    seen_keys = set()

    if category:
        for reg_name in get_category_regulations(category):
            results = engine.search_by_metadata({"law_name": reg_name})
            if not results:
                logger.warning(f"注册法规在知识库中未找到: {reg_name}")
            for r in results:
                key = (r.get("law_name", ""), r.get("article_number", ""))
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append((r, "category"))

    for reg_name in get_general_regulations():
        results = engine.search_by_metadata({"law_name": reg_name})
        if not results:
            logger.warning(f"注册法规在知识库中未找到: {reg_name}")
        for r in results:
            key = (r.get("law_name", ""), r.get("article_number", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                all_results.append((r, "general"))

    regulations = []
    for r, source_type in all_results:
        regulations.append(AuditRegulationItem(
            chunk_id=r.get("id", ""),
            law_name=r.get("law_name", ""),
            article_number=_extract_real_article_number(r.get("content", ""), r.get("article_number", "")),
            content=r.get("content", ""),
            doc_number=r.get("doc_number", ""),
            issuing_authority=r.get("issuing_authority", ""),
            effective_date=r.get("effective_date", ""),
            source_type=source_type,
        ))

    logger.info(f"加载法规: 险种专属 + 通用法规, 共 {len(regulations)} 条")
    return regulations


def build_audit_context(regulations: List[AuditRegulationItem]) -> str:
    if not regulations:
        return ""

    parts = []
    for r in regulations:
        header = f"【{r.law_name}-{r.article_number}】"
        if r.doc_number:
            header += f"（{r.doc_number}）"
        if r.issuing_authority:
            header += f"\n发布机关：{r.issuing_authority}"
        if r.effective_date:
            header += f"\n生效日期：{r.effective_date}"
        parts.append(f"{header}\n{r.content}")
    return "\n\n".join(parts)


def check_negative_list(document_content: str) -> Tuple[List[AuditResultItem], str, List[AuditRegulationItem]]:
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return [], CheckResult.SKIPPED, []

    negative_docs = engine.search_by_metadata({"category": "负面清单检查"})
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return [], CheckResult.SKIPPED, []

    regulations = []
    for doc in negative_docs:
        if doc.get("content") and doc.get("article_number"):
            regulations.append(AuditRegulationItem(
                chunk_id=doc.get("id", ""),
                law_name=doc.get("law_name", ""),
                article_number=_extract_real_article_number(doc.get("content", ""), doc.get("article_number", "")),
                content=doc.get("content", ""),
                doc_number=doc.get("doc_number", ""),
                issuing_authority=doc.get("issuing_authority", ""),
                effective_date=doc.get("effective_date", ""),
                source_type="negative_list",
            ))

    rules_text = "\n".join([
        f"【{r.law_name}-{r.article_number}】\n{r.content}"
        for r in regulations
    ])

    if not rules_text:
        return [], CheckResult.SKIPPED, regulations

    prompt = f"""你是一位保险法规合规专家。请判断以下保险产品文档是否违反负面清单规定。

## 负面清单规定（共 {len(regulations)} 条）
{rules_text}

## 待审文档内容
{document_content}

## 输出要求
请以 JSON 格式输出所有违规项：
[
  {{"source_ref": "<对应上面【法规名-条目号】>", "clause_number": "<文档中涉及违规的条款编号，如'3.2'，无法确定时写'未知'>", "is_violation": true, "reason": "<违规原因>", "source_excerpt": "<文档中违规原文>", "suggestion": "<修改建议>"}},
  {{"is_violation": false}},
  ...
]

注意：
1. 仅输出 is_violation 为 true 的项（或省略 false 项）
2. source_ref 必须对应上面【法规名-条目号】
3. clause_number 应尽量从文档中提取实际条款编号
4. 仅输出 JSON，不要附加其他文字
"""

    try:
        llm = get_audit_llm()
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()

        items = _parse_violation_response(answer, regulations)
        result = CheckResult.VIOLATED if items else CheckResult.PASSED
        return items, result, regulations
    except Exception as e:
        logger.error(f"Negative list check failed: {e}")
        return [], CheckResult.SKIPPED, regulations


def _normalize_ref(ref: str) -> str:
    ref = ref.strip()
    for ch in "《》【】（）() \u3000":
        ref = ref.replace(ch, "")
    return ref


def _build_ref_map(regulations: List[AuditRegulationItem]) -> Dict[str, AuditRegulationItem]:
    return {_normalize_ref(f"{r.law_name}-{r.article_number}"): r for r in regulations}
    return {f"{r.law_name}-{r.article_number}": r for r in regulations}


def _parse_violation_response(answer: str, regulations: List[AuditRegulationItem]) -> List[AuditResultItem]:
    from lib.common.json_utils import extract_json_array
    try:
        json_str = extract_json_array(answer)
        if json_str is None:
            return []

        ref_map = _build_ref_map(regulations)
        violations = json.loads(json_str)
        items = []
        for v in violations:
            if not v.get("is_violation", False):
                continue
            ref = v.pop("source_ref", "")
            normalized = _normalize_ref(ref) if ref else ""
            matched = ref_map.get(normalized) if normalized else None
            if not matched and ref:
                logger.warning(f"负面清单 source_ref 匹配失败: {ref}")

            items.append(AuditResultItem(
                clause_number=v.get("clause_number") or "未知",
                check_type="negative_list",
                param=f"负面清单检查: {matched.law_name if matched else ''} {matched.article_number if matched else ''}",
                value=v.get("source_excerpt", "")[:100],
                requirement=f"违反负面清单 {matched.law_name if matched else ''} {matched.article_number if matched else ''}: {matched.content[:200] if matched else ''}",
                status="non_compliant",
                chunk_id=matched.chunk_id if matched else None,
                source_type="negative_list",
                source_excerpt=matched.content[:300] if matched else "",
                suggestion=v.get("suggestion", "请修改相关表述"),
            ))
        return items
    except Exception as e:
        logger.warning(f"Failed to parse violation response: {e}")
        return []


def identify_category(document_content: str, product_name: str = "") -> CategoryResult:
    """识别险种类型"""
    category_enum = classify_product(product_name, document_content[:1000])
    if category_enum != ProductCategory.OTHER:
        mapped = ComplianceConstants.SUBCATEGORY_MAPPING.get(category_enum.value)
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


def run_compliance_check(prompt: str, regulations: Optional[List[AuditRegulationItem]] = None) -> Dict:
    try:
        llm = get_audit_llm()

        logger.info(f"Prompt length: {len(prompt)}")
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response)

        logger.info(f"LLM response length: {len(answer)}, preview: {answer[:200]}")

        if "```json" in answer:
            answer = answer.split("```json")[1].split("```")[0]
        elif "```" in answer:
            answer = answer.split("```")[1].split("```")[0]

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

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            open_brackets = json_str.count("{") - json_str.count("}")
            open_arrays = json_str.count("[") - json_str.count("]")
            json_str_fixed = json_str + "]" * open_arrays + "}" * open_brackets
            try:
                result = json.loads(json_str_fixed)
            except json.JSONDecodeError:
                logger.warning(f"JSON repair failed, returning empty result")
                return {
                    "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                    "items": [],
                    "error": "json_parse_failed",
                    "raw_answer": answer[:1000],
                }

        ref_map = _build_ref_map(regulations) if regulations else {}
        items = result.get("items", [])
        for item in items:
            if not item.get("clause_number"):
                item["clause_number"] = "未知"
            ref = item.pop("source_ref", "")
            normalized = _normalize_ref(ref) if ref else ""
            matched = ref_map.get(normalized) if normalized else None
            item["chunk_id"] = matched.chunk_id if matched else None
            if not matched and ref:
                logger.warning(f"source_ref 匹配失败: {ref}")
            item["check_type"] = "regulation"
            item["source_type"] = "regulation"

        return result

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": [], "error": str(e)}