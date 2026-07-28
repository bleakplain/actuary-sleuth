"""合规检查核心逻辑 — 流式 NDJSON 输出"""
import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple

from lib.common.constants import ComplianceConstants
from lib.common.product_tags import (
    PRODUCT_TAG_LABELS,
    ProductDesignType,
    ProductLine,
    ProductSubtype,
    ProductTags,
)
from lib.common.product_types import ProductCategory, classify_product
from lib.compliance.prompts import (
    STREAMING_AUDIT_PROMPT,
    STREAMING_NEGATIVE_LIST_PROMPT,
)
from lib.compliance.rule_engine import check_rules as _check_rules, ProductMetadata
from lib.llm import get_audit_llm
from lib.llm.base import BaseLLMClient
from lib.rag_engine import get_engine
from lib.rag_engine.layered_retrieval import (
    get_candidate_identity,
    layer_regulation_candidates,
)

VALID_CATEGORIES = ComplianceConstants.VALID_CATEGORIES


def _get_category_regulations(category: str) -> List[str]:
    return ComplianceConstants.CATEGORY_REGULATION_REGISTRY.get(category, [])


def _get_general_regulations() -> List[str]:
    return ComplianceConstants.GENERAL_REGULATIONS.copy()


def infer_category_from_product_tags(product_tags: ProductTags) -> Optional[str]:
    """在常规险种识别失败时，用已取证的产品标签恢复法规分类。"""
    if product_tags.line is ProductLine.HEALTH:
        if product_tags.primary_subtype is ProductSubtype.MEDICAL:
            return "医疗险"
        if product_tags.primary_subtype is ProductSubtype.CRITICAL_ILLNESS:
            return "重疾险"
        return "健康险"
    if product_tags.line is ProductLine.LIFE:
        if product_tags.primary_subtype is ProductSubtype.ANNUITY:
            return "年金险"
        if product_tags.design_type is ProductDesignType.PARTICIPATING:
            return "分红险"
        return "寿险"
    if product_tags.line is ProductLine.ACCIDENT:
        return "意外险"
    return None


def build_regulation_retrieval_query(
    product_name: str,
    document_content: str,
    product_tags: ProductTags,
) -> str:
    """把受控产品标签转成检索词，避免专业子类缺少上位险种词导致弱召回。"""
    tag_terms = (
        PRODUCT_TAG_LABELS["line"].get(product_tags.line.value, ""),
        PRODUCT_TAG_LABELS["primary_subtype"].get(product_tags.primary_subtype.value, ""),
        PRODUCT_TAG_LABELS["term_class"].get(product_tags.term_class.value, ""),
    )
    parts = [product_name, *tag_terms, document_content[:3000]]
    return "\n".join(dict.fromkeys(part for part in parts if part and part != "未知"))


def _list_registered_regulations(category: Optional[str]) -> List[str]:
    if category:
        categories = [category]
        parent = ComplianceConstants.CATEGORY_PARENT_MAPPING.get(category)
        if parent:
            categories.append(parent)
        names = [
            name
            for current_category in categories
            for name in _get_category_regulations(current_category)
        ]
        return list(dict.fromkeys(names))
    all_names: List[str] = []
    for category_names in ComplianceConstants.CATEGORY_REGULATION_REGISTRY.values():
        all_names.extend(category_names)
    return list(dict.fromkeys(all_names))

logger = logging.getLogger(__name__)

_CLAUSE_NUM_RE = re.compile(r'(\d+(?:\.\d+)*(?:\(\d+\))?)')
_SOURCE_REF_RE = re.compile(r'^\[(?:R|NR)\d+\]$')
_TEMPLATE_OVERHEAD = 600

# 法规加载缓存：category → List[AuditRegulationItem]
_regulation_cache: Dict[Optional[str], List[AuditRegulationItem]] = {}
_regulation_cache_lock = threading.Lock()


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
    applicability_status: str = ""
    matched_dimensions: Tuple[str, ...] = ()
    matched_topics: Tuple[str, ...] = ()
    fallback_layer: str = ""
    retrieval_sources: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RegulationRetrievalOutcome:
    regulations: Tuple[AuditRegulationItem, ...]
    degraded: bool = False
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditResultItem:
    clause_number: str
    check_type: str
    clause_content: str
    status: str
    chunk_id: Optional[str]
    suggestion: str
    conclusion: str = ""
    source_ref: str = ""


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
        applicability_status=doc.get("applicability_status", ""),
        matched_dimensions=tuple(doc.get("matched_dimensions", ())),
        matched_topics=tuple(doc.get("matched_topics", ())),
        fallback_layer=doc.get("fallback_layer", ""),
        retrieval_sources=tuple(doc.get("retrieval_sources", ())),
    )


def _load_regulation_chunks(
    engine: Any,
    reg_names: List[str],
    all_results: List[Tuple[Dict, str]],
    source_type: str,
) -> None:
    for reg_name in reg_names:
        results = engine.search_by_metadata({"law_name": reg_name})
        if not results:
            logger.warning(f"注册法规在知识库中未找到: {reg_name}")
        for r in results:
            all_results.append((r, source_type))


def _merge_registered_candidates(
    registered: List[Tuple[Dict, str]],
) -> List[Tuple[Dict[str, Any], str]]:
    """按 chunk 身份合并重复注册来源，同时保留 category/general 来源轨迹。"""
    merged: Dict[str, Tuple[Dict[str, Any], str]] = {}
    for item, source_type in registered:
        identity = get_candidate_identity(item)
        if identity not in merged:
            candidate = dict(item)
            candidate["retrieval_sources"] = [f"registered:{source_type}"]
            merged[identity] = (candidate, source_type)
            continue
        candidate, current_type = merged[identity]
        sources = set(candidate.get("retrieval_sources", ()))
        sources.add(f"registered:{source_type}")
        candidate["retrieval_sources"] = sorted(sources)
        if source_type == "category":
            merged[identity] = (candidate, "category")
        else:
            merged[identity] = (candidate, current_type)
    return list(merged.values())


def load_audit_regulations(category: Optional[str]) -> List[AuditRegulationItem]:
    with _regulation_cache_lock:
        if category in _regulation_cache:
            return _regulation_cache[category]
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return []
    all_results: List[Tuple[Dict, str]] = []
    if category:
        _load_regulation_chunks(engine, _list_registered_regulations(category), all_results, "category")
    _load_regulation_chunks(engine, _get_general_regulations(), all_results, "general")
    regulations = [
        _build_regulation_item(item, source_type)
        for item, source_type in _merge_registered_candidates(all_results)
    ]
    logger.info(f"加载法规: 共 {len(regulations)} 条")
    with _regulation_cache_lock:
        _regulation_cache[category] = regulations
    return regulations


def retrieve_audit_regulations_with_status(
    query: str,
    category: Optional[str],
    product_tags: ProductTags,
    clause_topics: Tuple[str, ...] = (),
    top_k: int = 12,
) -> RegulationRetrievalOutcome:
    """用产品适用性和条款主题对混合检索及注册法规候选进行安全分层。"""
    engine = get_engine()
    if engine is None:
        fallback_regulations = load_audit_regulations(category)
        return RegulationRetrievalOutcome(
            regulations=tuple(fallback_regulations),
            degraded=True,
            warnings=("法规知识库未初始化，法规检索不可用；本次仅执行确定性规则和负面清单检查",),
        )

    warnings: List[str] = []
    registered: List[Tuple[Dict, str]] = []
    effective_category = category or infer_category_from_product_tags(product_tags)
    if category is None and effective_category:
        logger.warning("险种识别为空，按产品标签回退为 %s", effective_category)
    elif effective_category is None:
        logger.warning("险种和产品大类均未知，保守加载所有险种注册法规")
    _load_regulation_chunks(
        engine, _list_registered_regulations(effective_category), registered, "category",
    )
    _load_regulation_chunks(engine, _get_general_regulations(), registered, "general")
    merged_registered = _merge_registered_candidates(registered)
    registered_by_identity = {
        get_candidate_identity(item): (item, source_type)
        for item, source_type in merged_registered
    }

    try:
        semantic = engine.search_candidates(query, top_k=max(top_k * 3, 24))
    except Exception as exc:
        logger.warning("基础混合检索失败，使用注册法规候选继续分层: %s", exc)
        warnings.append("语义检索失败，已降级为注册法规候选检索")
        semantic = []
    candidates: List[Dict[str, Any]] = []
    for item in semantic:
        candidate = dict(item)
        registered_match = registered_by_identity.get(get_candidate_identity(candidate))
        sources = set(candidate.get("retrieval_sources", ()))
        if registered_match:
            registered_item, source_type = registered_match
            sources.update(registered_item.get("retrieval_sources", ()))
            candidate["_source_type"] = source_type
        else:
            candidate["_source_type"] = "semantic"
        candidate["retrieval_sources"] = sorted(sources)
        candidates.append(candidate)
    for item, source_type in merged_registered:
        candidate = dict(item)
        candidate["_source_type"] = source_type
        candidates.append(candidate)
    if not candidates:
        warnings.append("法规知识库未返回任何候选，无法执行基于法规正文的审核")

    layered = layer_regulation_candidates(
        candidates,
        product_tags=product_tags,
        clause_topics=clause_topics,
        top_k=top_k,
    )
    logger.info(
        "标签分层检索: 候选=%d, 排除=%d, 返回=%d, fallback=%s",
        layered.candidate_count,
        layered.excluded_count,
        len(layered.chunks),
        layered.fallback_used,
    )
    if not layered.chunks:
        logger.info("标签分层检索无结果：候选均被明确判定为不适用")
        return RegulationRetrievalOutcome(
            regulations=(),
            degraded=bool(warnings),
            warnings=tuple(warnings),
        )
    regulations = tuple(
        _build_regulation_item(item, item.get("_source_type", "tagged_retrieval"))
        for item in layered.chunks
    )
    return RegulationRetrievalOutcome(
        regulations=regulations,
        degraded=bool(warnings),
        warnings=tuple(warnings),
    )


def retrieve_audit_regulations(
    query: str,
    category: Optional[str],
    product_tags: ProductTags,
    clause_topics: Tuple[str, ...] = (),
    top_k: int = 12,
) -> List[AuditRegulationItem]:
    """兼容原调用方，只返回法规列表；API 应使用带状态的入口。"""
    outcome = retrieve_audit_regulations_with_status(
        query, category, product_tags, clause_topics, top_k,
    )
    return list(outcome.regulations)


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


def _split_document_by_clauses(document_content: str, budget: int) -> List[str]:
    markers = list(re.finditer(r'【[^】]+】', document_content))
    if not markers:
        return [document_content]
    clause_positions = [m.start() for m in markers if re.match(r'【(?:附加险)?条款\s+\d+', m.group(0))]
    if not clause_positions:
        return [document_content]
    prefix_len = clause_positions[0]
    avg_clause_len = (len(document_content) - prefix_len) / len(clause_positions) if clause_positions else 500
    max_clauses = max(50, int(budget / avg_clause_len))
    if len(clause_positions) <= max_clauses:
        return [document_content]
    batches = []
    for i in range(0, len(clause_positions), max_clauses):
        start = clause_positions[i]
        end = clause_positions[i + max_clauses] if i + max_clauses < len(clause_positions) else len(document_content)
        batches.append(document_content[start:end].strip())
    batches[0] = document_content[:prefix_len] + batches[0]
    return batches


# --- NDJSON stream parser ---


def _normalize_violation(raw: Dict, ref_to_chunk: Dict[str, str], check_type: str) -> Optional[AuditResultItem]:
    clause_content = raw.get("clause_content", "")
    if not clause_content:
        return None
    raw_cn = raw.get("clause_number", "")
    normalized = normalize_clause_number(raw_cn) if raw_cn else None
    source_ref = raw.get("source_ref", "")
    chunk_id = None
    if source_ref and _SOURCE_REF_RE.match(source_ref) and source_ref in ref_to_chunk:
        chunk_id = ref_to_chunk[source_ref]
    else:
        source_ref = ""
    return AuditResultItem(
        clause_number=normalized or "未知",
        check_type=check_type,
        clause_content=clause_content,
        status=raw.get("status", "non_compliant"),
        chunk_id=chunk_id,
        source_ref=source_ref,
        suggestion=raw.get("suggestion", ""),
        conclusion=raw.get("conclusion", ""),
    )


def _parse_ndjson_tokens(
    token_iter: Any,
    ref_to_chunk: Dict[str, str],
    check_type: str,
) -> Generator[AuditResultItem, None, None]:
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
    category: Optional[str] = None,
    product_metadata: Optional[ProductMetadata] = None,
) -> Generator[Dict, None, None]:
    """Yield regulation audit violations as they stream from LLM.

    Yields: {"type": "violation"|"progress", "data": dict|string}
    """
    # Phase 1: 确定性规则检查
    if category:
        yield {"type": "progress", "data": "确定性规则检查中..."}
        for v in _check_rules(document_content, category, product_metadata):
            yield {"type": "violation", "data": v}

    # Phase 2: LLM 语义审查
    if not regulations:
        return
    regs_text, ref_to_chunk = _build_numbered_regulations(regulations)
    budget = BaseLLMClient.MAX_PROMPT_LENGTH - len(regs_text) - _TEMPLATE_OVERHEAD
    llm = get_audit_llm()
    if len(document_content) <= budget:
        batches = [document_content]
    else:
        batches = _split_document_by_clauses(document_content, budget)
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
            yield {"type": "progress", "data": f"⚠ 法规审查批次 {i + 1}/{len(batches)} 失败"}


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
