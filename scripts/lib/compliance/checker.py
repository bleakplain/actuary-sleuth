"""合规检查核心逻辑"""
import json
import logging
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
    """检查结果状态"""
    PASSED = "passed"
    VIOLATED = "violated"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CategoryResult:
    """险种识别结果"""
    category: Optional[str]
    confidence: float
    method: str


@dataclass(frozen=True)
class AuditSource:
    """法规溯源记录"""
    source_id: int
    law_name: str
    article_number: str
    content: str
    source_type: str  # "category" | "general" | "negative_list"
    doc_number: str = ""
    issuing_authority: str = ""
    effective_date: str = ""


@dataclass(frozen=True)
class AuditItem:
    """审查结果项"""
    clause_number: str
    check_type: str  # "regulation" | "negative_list"
    param: str
    value: str
    requirement: str
    status: str  # "compliant" | "non_compliant" | "attention"
    source_id: Optional[int]
    source_type: str  # "regulation" | "negative_list"
    source_excerpt: str
    suggestion: str


def load_audit_sources(category: Optional[str]) -> List[AuditSource]:
    """从 RAG 加载法规溯源记录，去重后按险种专属→通用法规排序"""
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return []

    all_results = []
    seen_keys = set()

    # 险种专属法规
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

    # 通用法规（与险种专属去重）
    for reg_name in get_general_regulations():
        results = engine.search_by_metadata({"law_name": reg_name})
        if not results:
            logger.warning(f"注册法规在知识库中未找到: {reg_name}")
        for r in results:
            key = (r.get("law_name", ""), r.get("article_number", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                all_results.append((r, "general"))

    sources = []
    for i, (r, source_type) in enumerate(all_results):
        sources.append(AuditSource(
            source_id=i + 1,
            law_name=r.get("law_name", ""),
            article_number=r.get("article_number", ""),
            content=r.get("content", ""),
            doc_number=r.get("doc_number", ""),
            issuing_authority=r.get("issuing_authority", ""),
            effective_date=r.get("effective_date", ""),
            source_type=source_type,
        ))

    logger.info(
        f"加载法规溯源: 险种专属 + 通用法规, 共 {len(sources)} 条"
    )
    return sources


def format_context_for_llm(sources: List[AuditSource]) -> str:
    """将 AuditSource 列表格式化为 LLM 上下文字符串"""
    if not sources:
        return ""

    parts = []
    for s in sources:
        header = f"[来源{s.source_id}] 【{s.law_name}】{s.article_number}"
        if s.doc_number:
            header += f"（{s.doc_number}）"
        if s.issuing_authority:
            header += f"\n发布机关：{s.issuing_authority}"
        if s.effective_date:
            header += f"\n生效日期：{s.effective_date}"
        parts.append(f"{header}\n{s.content}")
    return "\n\n".join(parts)


def check_negative_list(document_content: str) -> Tuple[List[AuditItem], str, List[AuditSource]]:
    """执行负面清单检查

    Returns:
        (items, result, sources): 审查项列表 + 检查状态 + 溯源记录
    """
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return [], CheckResult.SKIPPED, []

    negative_docs = engine.search_by_metadata({"category": "负面清单检查"})
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return [], CheckResult.SKIPPED, []

    # 构建溯源记录（仅有效条目）
    sources = []
    for i, doc in enumerate(negative_docs):
        if doc.get("content") and doc.get("article_number"):
            sources.append(AuditSource(
                source_id=i + 1,
                law_name=doc.get("law_name", ""),
                article_number=doc.get("article_number", ""),
                content=doc.get("content", ""),
                doc_number=doc.get("doc_number", ""),
                issuing_authority=doc.get("issuing_authority", ""),
                effective_date=doc.get("effective_date", ""),
                source_type="negative_list",
            ))

    rules_text = "\n".join([
        f"{i+1}. 【{doc.get('law_name', '')}】{doc.get('article_number', '')}: {doc.get('content', '')}"
        for i, doc in enumerate(negative_docs)
        if doc.get("content") and doc.get("article_number")
    ])

    if not rules_text:
        return [], CheckResult.SKIPPED, sources

    prompt = f"""你是一位保险法规合规专家。请判断以下保险产品文档是否违反负面清单规定。

## 负面清单规定（共 {len(sources)} 条）
{rules_text}

## 待审文档内容
{document_content}

## 输出要求
请以 JSON 格式输出所有违规项：
[
  {{"rule_id": 1, "clause_number": "<文档中涉及违规的条款编号，如'3.2'，无法确定时写'未知'>", "is_violation": true, "reason": "<违规原因>", "source_excerpt": "<文档中违规原文>", "suggestion": "<修改建议>"}},
  {{"rule_id": 2, "is_violation": false}},
  ...
]

注意：
1. 仅输出 is_violation 为 true 的项（或省略 false 项）
2. rule_id 对应上面规则的编号
3. clause_number 应尽量从文档中提取实际条款编号
4. 仅输出 JSON，不要附加其他文字
"""

    try:
        llm = get_audit_llm()
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()

        items = _parse_violation_response(answer, sources)
        result = CheckResult.VIOLATED if items else CheckResult.PASSED
        return items, result, sources
    except Exception as e:
        logger.error(f"Negative list check failed: {e}")
        return [], CheckResult.SKIPPED, sources


def _parse_violation_response(answer: str, sources: List[AuditSource]) -> List[AuditItem]:
    """解析 LLM 返回的违规项列表"""
    from lib.common.json_utils import extract_json_array
    try:
        json_str = extract_json_array(answer)
        if json_str is None:
            return []

        violations = json.loads(json_str)
        items = []
        for v in violations:
            if not v.get("is_violation", False):
                continue
            rule_id = v.get("rule_id", 0)
            source = None
            if 0 < rule_id <= len(sources):
                source = sources[rule_id - 1]
            else:
                logger.warning(f"Negative list rule_id {rule_id} out of range")

            items.append(AuditItem(
                clause_number=v.get("clause_number") or "未知",
                check_type="negative_list",
                param=f"负面清单检查: {source.law_name if source else ''} {source.article_number if source else ''}",
                value=v.get("source_excerpt", "")[:100],
                requirement=f"违反负面清单 {source.law_name if source else ''} {source.article_number if source else ''}: {source.content[:200] if source else ''}",
                status="non_compliant",
                source_id=source.source_id if source else None,
                source_type="negative_list",
                source_excerpt=source.content[:300] if source else "",
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


def run_compliance_check(prompt: str, num_sources: int = 0) -> Dict:
    """执行合规检查 LLM 调用

    Args:
        prompt: 完整的合规检查提示词（已包含法规 context）
        num_sources: 法规溯源记录数量，用于验证 source_id
    """
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

        # 验证并修复 items
        items = result.get("items", [])
        for item in items:
            if not item.get("clause_number"):
                item["clause_number"] = "未知"
            sid = item.get("source_id")
            if sid is not None and (sid < 1 or sid > num_sources):
                logger.warning(f"source_id {sid} out of range (1..{num_sources})")
                item["source_id"] = None
            item["check_type"] = "regulation"
            item["source_type"] = "regulation"

        return result

    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": [], "error": str(e)}