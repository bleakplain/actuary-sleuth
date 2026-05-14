"""合规检查核心逻辑"""
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from lib.llm.base import BaseLLMClient
from lib.rag_engine import get_engine
from lib.compliance.prompts import (
    NEGATIVE_LIST_SINGLE_PROMPT,
    CHAPTER_AUDIT_PROMPT,
)

logger = logging.getLogger(__name__)

_CLAUSE_NUM_RE = re.compile(r'(\d+(?:\.\d+)*)')


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
    clause_content: str
    status: str  # "compliant" | "non_compliant" | "attention"
    chunk_id: Optional[str]
    suggestion: str
    conclusion: str = ""


# --- Document parsing helpers ---


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
    last_count = chapter_counts[last_chapter]
    if last_count >= 10 and last_count / len(clauses) >= 0.3:
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
    regulations = [_build_regulation_item(r, source_type) for r, source_type in all_results]
    logger.info(f"加载法规: 险种专属 + 通用法规, 共 {len(regulations)} 条")
    return regulations


# --- Category identification ---


def identify_category(document_content: str, product_name: str = "") -> CategoryResult:
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


# --- Chapter-based audit ---


@dataclass(frozen=True)
class DocumentChapter:
    chapter_key: str
    chapter_title: str
    clauses: List[str]
    clause_numbers: List[str]
    total_chars: int


_MAX_CLAUSES_PER_SUBCHAPTER = 8
_DEFINITIONS_CONTEXT_LIMIT = 2000
_MAX_REGS_PER_CHAPTER = 10
_CHAPTER_MAX_WORKERS = 2
_NEGATIVE_MAX_WORKERS = 2
_STATUS_PRIORITY = {"non_compliant": 3, "attention": 2, "compliant": 1}
_CHAPTER_KEYWORDS: Dict[str, List[str]] = {
    "1": ["被保险人", "投保人", "年龄", "资格"],
    "3": ["合同", "犹豫", "解除", "效力", "中止", "复效"],
    "4": ["保险费", "费率", "缴费", "宽限"],
    "5": ["理赔", "赔偿", "给付", "时效", "诉讼时效"],
    "6": ["告知", "如实", "说明", "隐瞒", "解除权"],
}


def _extract_chapter_title(first_block: str, ch_num: str) -> str:
    m = re.match(r'【(?:附加险)?条款\s+\d+(?:\.\d+)*】\s*(.+)', first_block)
    if m:
        title_line = m.group(1).split('\n')[0].strip()
        if title_line:
            return title_line
    return f"第{ch_num}章"


def _split_by_markers(text: str) -> List[Tuple[str, str]]:
    """Split text into (marker, block) pairs at each 【...】boundary."""
    marker_re = re.compile(r'【[^】]+】')
    positions = [(m.start(), m.group(0)) for m in marker_re.finditer(text)]
    if not positions:
        return []
    blocks = []
    for i, (start, marker) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        blocks.append((marker, text[start:end].strip()))
    return blocks


def extract_chapters(document_content: str) -> List[DocumentChapter]:
    all_clauses = extract_clause_numbers(document_content)
    def_chapter = _detect_definition_chapter(all_clauses)

    by_chapter: Dict[str, List[Tuple[str, str]]] = {}
    for marker, block in _split_by_markers(document_content):
        num_m = re.match(r'【(?:附加险)?条款\s+(\d+(?:\.\d+)*)】', marker)
        if not num_m:
            continue
        num = num_m.group(1)
        ch = num.split('.')[0]
        if ch == def_chapter:
            continue
        by_chapter.setdefault(ch, []).append((num, block))

    chapters: List[DocumentChapter] = []
    for ch_num in sorted(by_chapter.keys(), key=lambda x: int(x)):
        entries = by_chapter[ch_num]
        title = _extract_chapter_title(entries[0][1], ch_num)
        _split_and_add_chapter(chapters, ch_num, title, entries)

    for marker, block in _split_by_markers(document_content):
        sec_m = re.match(r'【(投保须知|健康告知|责任免除)】', marker)
        if sec_m:
            section_name = sec_m.group(1)
            chapters.append(DocumentChapter(
                chapter_key=f"special_{section_name}", chapter_title=section_name,
                clauses=[block], clause_numbers=[], total_chars=len(block),
            ))

    rider_blocks = []
    for marker, block in _split_by_markers(document_content):
        if re.match(r'【附加险条款\s+\d+', marker):
            rider_blocks.append(block)
    if rider_blocks:
        chapters.append(DocumentChapter(
            chapter_key="special_riders", chapter_title="附加险条款",
            clauses=rider_blocks, clause_numbers=[], total_chars=sum(len(b) for b in rider_blocks),
        ))

    return chapters


def _split_and_add_chapter(
    chapters: List[DocumentChapter],
    ch_num: str, title: str, entries: List[Tuple[str, str]],
) -> None:
    if len(entries) <= _MAX_CLAUSES_PER_SUBCHAPTER:
        nums, blocks = zip(*entries)
        chapters.append(DocumentChapter(
            chapter_key=ch_num, chapter_title=title,
            clauses=list(blocks), clause_numbers=list(nums),
            total_chars=sum(len(b) for _, b in entries),
        ))
        return
    for i in range(0, len(entries), _MAX_CLAUSES_PER_SUBCHAPTER):
        batch = entries[i:i + _MAX_CLAUSES_PER_SUBCHAPTER]
        nums, blocks = zip(*batch)
        suffix = f" ({i + 1}-{i + len(batch)})" if len(entries) > _MAX_CLAUSES_PER_SUBCHAPTER else ""
        chapters.append(DocumentChapter(
            chapter_key=f"{ch_num}_{i // _MAX_CLAUSES_PER_SUBCHAPTER}",
            chapter_title=f"{title}{suffix}",
            clauses=list(blocks), clause_numbers=list(nums),
            total_chars=sum(len(b) for _, b in batch),
        ))


def _extract_definitions_text(document_content: str) -> str:
    all_clauses = extract_clause_numbers(document_content)
    def_chapter = _detect_definition_chapter(all_clauses)
    if def_chapter is None:
        return ""
    parts: List[str] = []
    for marker, block in _split_by_markers(document_content):
        num_m = re.match(r'【(?:附加险)?条款\s+(\d+(?:\.\d+)*)】', marker)
        if num_m and num_m.group(1).startswith(f"{def_chapter}."):
            parts.append(block)
    text = "\n\n".join(parts)
    return text[:_DEFINITIONS_CONTEXT_LIMIT]


def _select_chapter_regulations(
    chapter: DocumentChapter,
    regulations: List[AuditRegulationItem],
) -> List[AuditRegulationItem]:
    """Select most relevant regulations for a chapter, capped at _MAX_REGS_PER_CHAPTER."""
    ch_num = chapter.chapter_key.split("_")[0]
    keywords = _CHAPTER_KEYWORDS.get(ch_num, [])
    if not keywords:
        return regulations[:_MAX_REGS_PER_CHAPTER]
    scored: List[Tuple[int, AuditRegulationItem]] = []
    for reg in regulations:
        score = sum(1 for kw in keywords if kw in reg.content)
        scored.append((score, reg))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [reg for score, reg in scored if score > 0]
    if len(selected) < _MAX_REGS_PER_CHAPTER:
        remaining = [reg for score, reg in scored if score == 0]
        selected.extend(remaining[:_MAX_REGS_PER_CHAPTER - len(selected)])
    return selected[:_MAX_REGS_PER_CHAPTER]


def _audit_single_chapter(
    chapter: DocumentChapter,
    regulations: List[AuditRegulationItem],
    definitions_text: str,
    llm: BaseLLMClient,
) -> Optional[List[Dict]]:
    regs_block_parts = []
    article_to_chunk: Dict[str, str] = {}
    for r in regulations:
        regs_block_parts.append(f"### {r.article_number}（{r.law_name}）\n{r.content}")
        article_to_chunk[r.article_number] = r.chunk_id
    regs_block = "\n\n".join(regs_block_parts)
    chapter_clauses = "\n\n".join(chapter.clauses)

    prompt = CHAPTER_AUDIT_PROMPT.format(
        chapter_title=chapter.chapter_title,
        chapter_clauses=chapter_clauses,
        definitions_context=definitions_text or "（无释义章节）",
        regulation_count=len(regulations),
        regulations_block=regs_block,
    )
    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        answer = str(response).strip()
        return _parse_chapter_response(answer, article_to_chunk, regulations)
    except Exception as e:
        logger.warning(f"Chapter audit failed ({chapter.chapter_key} {chapter.chapter_title}): {e}")
        return None


def _parse_chapter_response(
    answer: str,
    article_to_chunk: Dict[str, str],
    regulations: List[AuditRegulationItem],
) -> List[Dict]:
    from lib.common.json_utils import extract_json_object
    try:
        json_str = extract_json_object(answer)
        if json_str is None:
            return []
        result = json.loads(json_str)
        valid_statuses = {"compliant", "non_compliant", "attention"}
        items = []
        for item in result.get("items", []):
            if item.get("status") not in valid_statuses:
                continue
            if not item.get("clause_content"):
                continue
            if not item.get("clause_number"):
                item["clause_number"] = "未知"
            article_num = item.get("article_number", "")
            chunk_id = article_to_chunk.get(article_num)
            if chunk_id is None and article_num:
                for key, cid in article_to_chunk.items():
                    if key in article_num or article_num in key:
                        chunk_id = cid
                        break
            if chunk_id is None and regulations:
                conclusion = item.get("conclusion", "")
                for r in regulations:
                    if r.content[:80] in conclusion or conclusion[:80] in r.content:
                        chunk_id = r.chunk_id
                        break
            item["chunk_id"] = chunk_id
            item["check_type"] = "regulation"
            items.append(item)
        return items
    except Exception as e:
        logger.warning(f"Failed to parse chapter response: {e}")
        return []


def check_chapter_audit(
    document_content: str,
    regulations: List[AuditRegulationItem],
) -> Dict:
    if not regulations:
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": []}

    chapters = extract_chapters(document_content)
    if not chapters:
        return {"summary": {"compliant": 0, "non_compliant": 0, "attention": 0}, "items": []}

    definitions_text = _extract_definitions_text(document_content)
    llm = get_audit_llm()

    logger.info(f"Chapter audit: {len(regulations)} regulations -> {len(chapters)} chapters")
    all_items: List[Dict] = []
    errors: List[str] = []
    lock = threading.Lock()
    completed = 0

    def _audit_chapter_worker(ch: DocumentChapter) -> Optional[List[Dict]]:
        nonlocal completed
        try:
            chapter_regs = _select_chapter_regulations(ch, regulations)
            items = _audit_single_chapter(ch, chapter_regs, definitions_text, llm)
            with lock:
                completed += 1
                logger.info(f"Chapter {completed}/{len(chapters)} {ch.chapter_key} ({ch.chapter_title}): "
                            f"{len(items) if items else 'FAILED'} items")
            return items
        except Exception as e:
            with lock:
                completed += 1
                errors.append(f"Chapter {ch.chapter_key} ({ch.chapter_title})")
                logger.warning(f"Chapter worker failed: {ch.chapter_key}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=_CHAPTER_MAX_WORKERS) as executor:
        futures = {executor.submit(_audit_chapter_worker, ch): ch for ch in chapters}
        for future in as_completed(futures):
            try:
                items = future.result()
                if items is not None:
                    all_items.extend(items)
                else:
                    ch = futures[future]
                    errors.append(f"Chapter {ch.chapter_key} ({ch.chapter_title})")
            except Exception as e:
                logger.error(f"Chapter worker raised: {e}")
                errors.append(str(e))

    deduped = _deduplicate_items(all_items)
    counts: Dict[str, int] = {"compliant": 0, "non_compliant": 0, "attention": 0}
    for item in deduped:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    result: Dict[str, Any] = {"summary": counts, "items": deduped}
    if errors:
        result["partial_error"] = True
    return result


def _deduplicate_items(items: List[Dict]) -> List[Dict]:
    """Keep highest-priority result per clause_number (non_compliant > attention > compliant)."""
    best: Dict[str, Dict] = {}
    for item in items:
        cn = item.get("clause_number", "未知")
        if cn == "未知":
            continue
        existing = best.get(cn)
        if existing is None:
            best[cn] = item
        elif _STATUS_PRIORITY.get(str(item.get("status")), 0) > _STATUS_PRIORITY.get(str(existing.get("status")), 0):
            best[cn] = item
    result = list(best.values())
    for item in items:
        if item.get("clause_number", "未知") == "未知":
            result.append(item)
    return result


# --- Negative list checking ---


def check_negative_list(document_content: str) -> Tuple[List[AuditResultItem], str, List[AuditRegulationItem]]:
    engine = get_engine()
    if engine is None:
        logger.warning("RAG 引擎未初始化")
        return [], CheckResult.SKIPPED, []

    negative_docs = engine.search_by_metadata({"category": "负面清单检查"})
    if not negative_docs:
        logger.warning("知识库中未找到负面清单文档")
        return [], CheckResult.SKIPPED, []

    regulations = [
        _build_regulation_item(doc, "negative_list")
        for doc in negative_docs
        if doc.get("content") and doc.get("article_number")
    ]
    if not regulations:
        return [], CheckResult.SKIPPED, regulations

    llm = get_audit_llm()
    all_items: List[AuditResultItem] = []

    def _check_one_negative(reg: AuditRegulationItem) -> Optional[AuditResultItem]:
        prompt = NEGATIVE_LIST_SINGLE_PROMPT.format(
            law_name=reg.law_name,
            article_number=reg.article_number,
            regulation_content=reg.content,
            document_content=document_content,
        )
        try:
            response = llm.chat([{"role": "user", "content": prompt}])
            answer = str(response).strip()
            return _parse_negative_single_response(answer, reg)
        except Exception as e:
            logger.warning(f"Negative list check failed for {reg.article_number}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=_NEGATIVE_MAX_WORKERS) as executor:
        futures = {executor.submit(_check_one_negative, r): r for r in regulations}
        for future in as_completed(futures):
            try:
                item = future.result()
                if item is not None:
                    all_items.append(item)
            except Exception as e:
                logger.error(f"Negative list worker error: {e}")

    result_status = CheckResult.VIOLATED if all_items else CheckResult.PASSED
    return all_items, result_status, regulations


def _parse_negative_single_response(answer: str, reg: AuditRegulationItem) -> Optional[AuditResultItem]:
    from lib.common.json_utils import extract_json_object
    try:
        json_str = extract_json_object(answer)
        if json_str is None:
            return None
        result = json.loads(json_str)
        if not result.get("is_violation", False):
            return None
        return AuditResultItem(
            clause_number=result.get("clause_number") or "未知",
            check_type="negative_list",
            clause_content=result.get("clause_content", ""),
            status="non_compliant",
            chunk_id=reg.chunk_id,
            suggestion=result.get("suggestion", "请修改相关表述"),
            conclusion=result.get("conclusion", result.get("reason", "")),
        )
    except Exception as e:
        logger.warning(f"Failed to parse negative list response: {e}")
        return None
