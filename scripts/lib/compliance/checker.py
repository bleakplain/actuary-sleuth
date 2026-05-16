"""合规检查核心逻辑 — 流式 NDJSON 输出"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple

from lib.common.constants import ComplianceConstants
from lib.common.product_types import ProductCategory, classify_product
from lib.common.regulation_registry import (
    get_category_regulations,
    get_general_regulations,
    VALID_CATEGORIES,
)
from lib.llm import get_audit_llm
from lib.llm.base import BaseLLMClient
from lib.rag_engine import get_engine
from lib.compliance.prompts import (
    STREAMING_AUDIT_PROMPT,
    STREAMING_NEGATIVE_LIST_PROMPT,
)

logger = logging.getLogger(__name__)

_CLAUSE_NUM_RE = re.compile(r'(\d+(?:\.\d+)*(?:\(\d+\))?)')
_TEMPLATE_OVERHEAD = 600
_MAX_CLAUSES_PER_BATCH = 25


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
    source_type: str
    doc_number: str = ""
    issuing_authority: str = ""
    effective_date: str = ""


@dataclass(frozen=True)
class AuditResultItem:
    clause_number: str
    check_type: str
    clause_content: str
    status: str
    chunk_id: Optional[str]
    suggestion: str
    conclusion: str = ""


# --- Document helpers ---


def extract_clause_numbers(document_content: str) -> List[str]:
    return [m.group(1) for m in re.finditer(r'【(?:附加险)?条款\s+(\d+(?:\.\d+)*)】', document_content)]


def normalize_clause_number(raw: str) -> Optional[str]:
    m = _CLAUSE_NUM_RE.search(raw)
    return m.group(1) if m else None


def _detect_definition_chapter(clauses: List[str]) -> Optional[str]:
    if not clauses:
        return None
    chapter_counts: Dict[str, int] = {}
    for c in clauses:
        parts = c.split(".")
        if parts:
            chapter_counts[parts[0]] = chapter_counts.get(parts[0], 0) + 1
    if not chapter_counts:
        return None
    numeric_keys = sorted(chapter_counts.keys(), key=lambda x: int(x))
    last_chapter = numeric_keys[-1]
    if chapter_counts[last_chapter] >= 10 and chapter_counts[last_chapter] / len(clauses) >= 0.3:
        return last_chapter
    return None


def extract_section_numbers(document_content: str) -> Dict[str, Any]:
    clauses = extract_clause_numbers(document_content)
    definition_chapter = _detect_definition_chapter(clauses)
    auditable = [c for c in clauses if not c.startswith(f"{definition_chapter}.")] if definition_chapter else clauses
    return {
        "clauses": auditable,
        "all_clauses": clauses,
        "definition_chapter": definition_chapter,
        "has_notices": bool(re.search(r'【投保须知】', document_content)),
        "has_health": bool(re.search(r'【健康告知】', document_content)),
        "has_exclusions": bool(re.search(r'【责任免除】', document_content)),
        "has_tables": bool(re.search(r'【数据表 \d+】', document_content)),
    }


# --- Regulation loading ---


def _extract_real_article_number(content: str, fallback: str) -> str:
    match = re.match(r'第([一二三四五六七八九十百零]+)条', content)
    return f"第{match.group(1)}条" if match else fallback


def _build_regulation_item(doc: Dict, source_type: str) -> AuditRegulationItem:
    return AuditRegulationItem(
        chunk_id=doc.get("id") or "",
        law_name=doc.get("law_name") or "",
        article_number=_extract_real_article_number(doc.get("content", ""), doc.get("article_number", "")),
        content=doc.get("content", ""),
        doc_number=doc.get("doc_number", ""),
        issuing_authority=doc.get("issuing_authority", ""),
        effective_date=doc.get("effective_date", ""),
        source_type=source_type,
    )


def _load_regulation_chunks(
    engine: Any,
    reg_names: List[str],
    seen_keys: set,
    all_results: List[Tuple[Dict, str]],
    source_type: str,
) -> None:
    for reg_name in reg_names:
        results = engine.search_by_metadata({"law_name": reg_name})
        if not results:
            logger.warning(f"注册法规在知识库中未找到: {reg_name}")
        for r in results:
            key = (r.get("law_name", ""), r.get("article_number", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                all_results.append((r, source_type))


def load_audit_regulations(category: Optional[str]) -> List[AuditRegulationItem]:
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return []
    all_results: List[Tuple[Dict, str]] = []
    seen_keys: set = set()
    if category:
        _load_regulation_chunks(engine, get_category_regulations(category), seen_keys, all_results, "category")
    _load_regulation_chunks(engine, get_general_regulations(), seen_keys, all_results, "general")
    regulations = [_build_regulation_item(r, st) for r, st in all_results]
    logger.info(f"加载法规: 共 {len(regulations)} 条")
    return regulations


# --- Category identification ---


def identify_category(document_content: str, product_name: str = "") -> CategoryResult:
    category_enum = classify_product(product_name, document_content[:5000])
    if category_enum != ProductCategory.OTHER:
        mapped = ComplianceConstants.SUBCATEGORY_MAPPING.get(category_enum.value)
        if mapped:
            confidence = 0.9 if category_enum.value in product_name else 0.7
            return CategoryResult(mapped, confidence, "keyword")
    try:
        llm = get_audit_llm()
        category_list = "、".join(VALID_CATEGORIES)
        prompt = f"请从以下保险产品文档中识别险种类型。\n\n可选险种类型：{category_list}\n\n产品名称：{product_name}\n文档内容：\n{document_content[:5000]}\n\n仅输出险种类型名称。"
        response = llm.chat([{"role": "user", "content": prompt}])
        for vc in VALID_CATEGORIES:
            if vc in str(response):
                return CategoryResult(vc, 0.85, "llm")
    except Exception as e:
        logger.warning(f"LLM category identification failed: {e}")
    return CategoryResult(None, 0.0, "unknown")


# --- Numbered regulations builder ---


def _build_numbered_regulations(
    regulations: List[AuditRegulationItem],
    prefix: str = "[R",
) -> Tuple[str, Dict[str, str]]:
    parts: List[str] = []
    ref_to_chunk: Dict[str, str] = {}
    for i, reg in enumerate(regulations, 1):
        ref = f"{prefix}{i}]"
        parts.append(f"{ref} {reg.article_number}（{reg.law_name}）\n{reg.content}")
        ref_to_chunk[ref] = reg.chunk_id
    return "\n\n".join(parts), ref_to_chunk


def _split_document_by_clauses(document_content: str, max_clauses: int) -> List[str]:
    markers = list(re.finditer(r'【[^】]+】', document_content))
    if not markers:
        return [document_content]
    clause_positions = [m.start() for m in markers if re.match(r'【(?:附加险)?条款\s+\d+', m.group(0))]
    if not clause_positions or len(clause_positions) <= max_clauses:
        return [document_content]
    batches = []
    for i in range(0, len(clause_positions), max_clauses):
        start = clause_positions[i]
        end = clause_positions[i + max_clauses] if i + max_clauses < len(clause_positions) else len(document_content)
        batches.append(document_content[start:end].strip())
    if clause_positions[0] > 0:
        batches[0] = document_content[:clause_positions[0]] + batches[0]
    return batches


# --- NDJSON stream parser ---


def _normalize_violation(raw: Dict, ref_to_chunk: Dict[str, str], check_type: str) -> Optional[Dict]:
    clause_content = raw.get("clause_content", "")
    if not clause_content:
        return None
    raw_cn = raw.get("clause_number", "")
    normalized = normalize_clause_number(raw_cn) if raw_cn else None
    source_ref = raw.get("source_ref", "")
    return {
        "clause_number": normalized or "未知",
        "check_type": check_type,
        "clause_content": clause_content,
        "status": raw.get("status", "non_compliant"),
        "chunk_id": ref_to_chunk.get(source_ref) if source_ref else None,
        "source_ref": source_ref,
        "suggestion": raw.get("suggestion", ""),
        "conclusion": raw.get("conclusion", ""),
    }


def _parse_ndjson_tokens(
    token_iter: Any,
    ref_to_chunk: Dict[str, str],
    check_type: str,
) -> Generator[Dict, None, None]:
    buffer = ""
    for token in token_iter:
        buffer += token
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line or line in ("[]", "{}"):
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    normalized = _normalize_violation(item, ref_to_chunk, check_type)
                    if normalized:
                        yield normalized
            except json.JSONDecodeError:
                pass
    remaining = buffer.strip()
    if remaining and remaining not in ("[]", "{}"):
        try:
            item = json.loads(remaining)
            if isinstance(item, dict):
                normalized = _normalize_violation(item, ref_to_chunk, check_type)
                if normalized:
                    yield normalized
        except json.JSONDecodeError:
            pass


# --- Streaming generators ---


def streaming_compliance_check(
    document_content: str,
    regulations: List[AuditRegulationItem],
) -> Generator[Dict, None, None]:
    """Yield regulation audit violations as they stream from LLM.

    Yields: {"type": "violation"|"progress", "data": dict|string}
    """
    if not regulations:
        return
    regs_text, ref_to_chunk = _build_numbered_regulations(regulations)
    budget = BaseLLMClient.MAX_PROMPT_LENGTH - len(regs_text) - _TEMPLATE_OVERHEAD
    llm = get_audit_llm()
    if len(document_content) <= budget:
        batches = [document_content]
    else:
        batches = _split_document_by_clauses(document_content, _MAX_CLAUSES_PER_BATCH)
        logger.info(f"文档分为 {len(batches)} 批审查")
    for i, batch_doc in enumerate(batches):
        if len(batches) > 1:
            yield {"type": "progress", "data": f"法规审查中 (批次 {i + 1}/{len(batches)})..."}
        prompt = STREAMING_AUDIT_PROMPT.format(
            document_content=batch_doc,
            regulation_count=len(regulations),
            regulations_block=regs_text,
        )
        try:
            token_iter = llm.stream_chat([{"role": "user", "content": prompt}])
            count = 0
            for item in _parse_ndjson_tokens(token_iter, ref_to_chunk, "regulation"):
                yield {"type": "violation", "data": item}
                count += 1
            logger.info(f"法规审查批次 {i + 1}/{len(batches)}: {count} 条违规")
        except Exception as e:
            logger.warning(f"Streaming audit batch {i + 1} failed: {e}")


def streaming_negative_check(
    document_content: str,
) -> Generator[Dict, None, None]:
    """Yield negative list violations as they stream from LLM.

    Yields: {"type": "violation"|"progress"|"negative_list_result", "data": ...}
    """
    engine = get_engine()
    if engine is None:
        yield {"type": "negative_list_result", "data": CheckResult.SKIPPED, "regulations": []}
        return
    negative_docs = engine.search_by_metadata({"category": "负面清单检查"})
    if not negative_docs:
        yield {"type": "negative_list_result", "data": CheckResult.SKIPPED, "regulations": []}
        return
    regulations = [
        _build_regulation_item(doc, "negative_list")
        for doc in negative_docs
        if doc.get("content") and doc.get("article_number")
    ]
    if not regulations:
        yield {"type": "negative_list_result", "data": CheckResult.SKIPPED, "regulations": []}
        return
    rules_block, ref_to_chunk = _build_numbered_regulations(regulations, prefix="[NR")
    prompt = STREAMING_NEGATIVE_LIST_PROMPT.format(
        rule_count=len(regulations),
        rules_block=rules_block,
        document_content=document_content,
    )
    yield {"type": "progress", "data": "负面清单检查中..."}
    llm = get_audit_llm()
    try:
        token_iter = llm.stream_chat([{"role": "user", "content": prompt}])
        count = 0
        for item in _parse_ndjson_tokens(token_iter, ref_to_chunk, "negative_list"):
            yield {"type": "violation", "data": item}
            count += 1
        result_status = CheckResult.VIOLATED if count > 0 else CheckResult.PASSED
        yield {"type": "negative_list_result", "data": result_status, "regulations": [r.__dict__ for r in regulations]}
        logger.info(f"负面清单检查: {count} 条违规")
    except Exception as e:
        logger.warning(f"Streaming negative check failed: {e}")
        yield {"type": "negative_list_result", "data": CheckResult.SKIPPED, "regulations": [r.__dict__ for r in regulations]}
