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
from lib.compliance.prompts import COMPLIANCE_PROMPT_DOCUMENT

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


def extract_clause_numbers(document_content: str) -> List[str]:
    return re.findall(r'【(?:附加险)?条款\s+(\d+(?:\.\d+)*)】', document_content)


def extract_section_numbers(document_content: str) -> Dict[str, Any]:
    clauses = extract_clause_numbers(document_content)
    return {
        "clauses": clauses,
        "has_notices": bool(re.search(r'【投保须知】', document_content)),
        "has_health": bool(re.search(r'【健康告知】', document_content)),
        "has_exclusions": bool(re.search(r'【责任免除】', document_content)),
        "has_tables": bool(re.search(r'【数据表 \d+】', document_content)),
    }


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
    for i, r in enumerate(regulations):
        header = f"[R{i + 1}] {r.law_name}"
        if r.doc_number:
            header += f"（{r.doc_number}）"
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

    rules_text = "\n\n".join([
        f"[R{i + 1}] {r.law_name}\n{r.content}"
        for i, r in enumerate(regulations)
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
  {{"source_ref": "<对应上面法规的编号，如 R5>", "clause_number": "<文档中涉及违规的条款编号，如'3.2'，无法确定时写'未知'>", "is_violation": true, "reason": "<违规原因>", "source_excerpt": "<文档中违规原文>", "suggestion": "<修改建议>"}},
  {{"is_violation": false}},
  ...
]

注意：
1. 仅输出 is_violation 为 true 的项（或省略 false 项）
2. source_ref 必须是上面法规的编号（如 R1、R5）
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



def _build_reg_index(regulations: List[AuditRegulationItem]) -> Dict[str, AuditRegulationItem]:
    return {f"R{i + 1}": r for i, r in enumerate(regulations)}


def _parse_violation_response(answer: str, regulations: List[AuditRegulationItem]) -> List[AuditResultItem]:
    from lib.common.json_utils import extract_json_array
    try:
        json_str = extract_json_array(answer)
        if json_str is None:
            return []

        reg_index = _build_reg_index(regulations)
        violations = json.loads(json_str)
        items = []
        for v in violations:
            if not v.get("is_violation", False):
                continue
            ref = v.get("source_ref", "")
            matched = reg_index.get(ref) if ref else None
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
    category_enum = classify_product(product_name, document_content[:5000])
    if category_enum != ProductCategory.OTHER:
        mapped = ComplianceConstants.SUBCATEGORY_MAPPING.get(category_enum.value)
        if mapped:
            return CategoryResult(mapped, 0.7, "keyword")

    try:
        llm = get_audit_llm()
        category_list = "、".join(VALID_CATEGORIES)
        prompt = f"""请从以下保险产品文档中识别险种类型。

可选险种类型：{category_list}

产品名称：{product_name}
文档内容：
{document_content[:5000]}

仅输出险种类型名称，不要输出其他内容。"""

        response = llm.chat([{"role": "user", "content": prompt}])
        extracted = str(response).strip()

        for vc in VALID_CATEGORIES:
            if vc in extracted:
                return CategoryResult(vc, 0.85, "llm")
    except Exception as e:
        logger.warning(f"LLM category identification failed: {e}")

    return CategoryResult(None, 0.0, "unknown")


def _check_relevance(param: str, content: str) -> bool:
    """检查检查项参数与法规内容是否相关（基于关键词子串匹配）"""
    param_text = param.replace("、", " ").replace("：", " ")
    keywords: set[str] = set()
    for word in param_text.split():
        if len(word) >= 2:
            keywords.add(word)
        if len(word) >= 4:
            for j in range(len(word) - 1):
                keywords.add(word[j:j+2])
    return any(kw in content for kw in keywords)


def _enrich_matched_item(item: Dict, matched: AuditRegulationItem) -> None:
    """根据匹配的法规填充 item 的 requirement 和 source_excerpt"""
    item["chunk_id"] = matched.chunk_id
    if _check_relevance(item.get("param", ""), matched.content[:500]):
        item["requirement"] = f"{matched.law_name}: {matched.content[:200]}"
    else:
        item["requirement"] = f"[法规相关性待确认] {matched.law_name}: {matched.content[:200]}"
        logger.info(f"法规相关性低: param={item.get('param')}, regulation={matched.law_name}")
    item["source_excerpt"] = matched.content[:300]


def run_compliance_check(prompt: str, regulations: Optional[List[AuditRegulationItem]] = None) -> Dict:
    try:
        llm = get_audit_llm()

        logger.info(f"Prompt length: {len(prompt)}")
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response)

        logger.info(f"LLM response length: {len(answer)}, preview: {answer[:200]}")

        from lib.common.json_utils import extract_json_object
        json_str = extract_json_object(answer)
        if json_str is None:
            logger.warning(f"No JSON found in LLM response: {answer[:200]}")
            return {
                "summary": {"compliant": 0, "non_compliant": 0, "attention": 0},
                "items": [],
                "error": "json_not_found",
                "raw_answer": answer[:1000],
            }

        result = json.loads(json_str)

        reg_index = _build_reg_index(regulations) if regulations else {}
        items = result.get("items", [])
        valid_statuses = {"compliant", "non_compliant", "attention"}
        items = [item for item in items if item.get("status") in valid_statuses]
        result["items"] = items
        for item in items:
            if not item.get("clause_number"):
                item["clause_number"] = "未知"
            ref = item.get("source_ref", "")
            matched = reg_index.get(ref) if ref else None
            if matched:
                _enrich_matched_item(item, matched)
            else:
                item["chunk_id"] = None
                if ref:
                    logger.warning(f"source_ref 匹配失败: {ref}")
                    item["requirement"] = f"法规来源待确认（引用 {ref} 未匹配）"
                else:
                    item["requirement"] = "法规来源待确认"
                item["source_excerpt"] = ""
            item["check_type"] = "regulation"
            item["source_type"] = "regulation"

        return result

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": [], "error": str(e)}


_PROMPT_TEMPLATE_OVERHEAD = 600


def _split_by_clauses(text: str, budget: int, max_clauses_per_batch: int = 15) -> List[str]:
    clause_positions = [m.start() for m in re.finditer(r'【(?:附加险)?条款\s+', text)]
    if not clause_positions:
        return [text[i:i + budget] for i in range(0, len(text), budget)]
    batches = []
    current_start = 0
    batch_clause_count = 0
    for i in range(1, len(clause_positions)):
        batch_clause_count += 1
        if clause_positions[i] - current_start >= budget or batch_clause_count >= max_clauses_per_batch:
            batches.append(text[current_start:clause_positions[i]])
            current_start = clause_positions[i]
            batch_clause_count = 0
    batches.append(text[current_start:])
    return batches


def batch_compliance_check(
    document_content: str,
    regulations: List[AuditRegulationItem],
) -> Dict:
    context = build_audit_context(regulations)
    budget = 200000 - len(context) - _PROMPT_TEMPLATE_OVERHEAD

    if budget < 10000:
        logger.warning(f"法规上下文过长 ({len(context)} chars)，可用文档预算不足")
        budget = 30000

    if len(document_content) <= budget:
        prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
            document_content=document_content,
            context=context,
            regulation_count=len(regulations),
        )
        return run_compliance_check(prompt, regulations=regulations)

    logger.info(f"文档 {len(document_content)} 字符超过预算 {budget}，按条款分批检查")
    batches = _split_by_clauses(document_content, budget)
    all_items: List[Dict] = []
    partial_error = False
    for i, batch_text in enumerate(batches):
        logger.info(f"分批检查 {i + 1}/{len(batches)}: {len(batch_text)} 字符")
        prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
            document_content=batch_text,
            context=context,
            regulation_count=len(regulations),
        )
        batch_result = run_compliance_check(prompt, regulations=regulations)
        if "error" in batch_result:
            logger.warning(f"分批检查 {i + 1}/{len(batches)} 失败: {batch_result['error']}")
            partial_error = True
            continue
        all_items.extend(batch_result.get("items", []))

    compliant = sum(1 for i in all_items if i.get("status") == "compliant")
    non_compliant = sum(1 for i in all_items if i.get("status") == "non_compliant")
    attention = sum(1 for i in all_items if i.get("status") == "attention")
    result = {"summary": {"compliant": compliant, "non_compliant": non_compliant, "attention": attention}, "items": all_items}
    if partial_error:
        result["partial_error"] = True
    return result