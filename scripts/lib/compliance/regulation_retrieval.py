"""冻结并解释产品审核所需的法规候选集。"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from lib.common.constants import ComplianceConstants
from lib.common.product_tags import (
    PRODUCT_TAG_LABELS,
    ProductDesignType,
    ProductLine,
    ProductSubtype,
    ProductTags,
)
from lib.compliance.regulation_units import (
    RegulationUnit,
    aggregate_regulation_units,
    build_regulation_unit_id,
)
from lib.rag_engine import get_engine
from lib.rag_engine.layered_retrieval import (
    get_candidate_identity,
    layer_regulation_candidates,
)

logger = logging.getLogger(__name__)
_KB_BUILD_IDENTITY_PATH = Path(__file__).parent / "data" / "kb_build_identity.json"


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
    kb_version: str = ""
    source_file: str = ""
    section_path: str = ""
    chunk_index: Optional[int] = None
    regulation_unit_id: str = ""
    chunk_ids: Tuple[str, ...] = ()
    regulation_topics: Tuple[str, ...] = ()
    indeterminate_dimensions: Tuple[str, ...] = ()
    excluded_by: Tuple[str, ...] = ()
    applicability_reasons: Tuple[str, ...] = ()
    category: str = ""


@dataclass(frozen=True)
class RegulationRetrievalCoverage:
    rag_available: bool
    catalog_available: bool
    semantic_available: bool
    registered_available: bool
    category_resolution: str
    complete_candidate_freeze: bool
    catalog_candidate_count: int = 0
    semantic_candidate_count: int = 0
    registered_candidate_count: int = 0
    uncovered_scopes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ExcludedRegulationUnit:
    regulation_unit_id: str
    kb_version: str
    source_file: str
    section_path: str
    law_name: str
    article_number: str
    chunk_ids: Tuple[str, ...]
    regulation_topics: Tuple[str, ...]
    excluded_by: Tuple[str, ...]
    reasons: Tuple[str, ...]
    category: str = ""


@dataclass(frozen=True)
class RegulationRetrievalOutcome:
    regulations: Tuple[AuditRegulationItem, ...]
    regulation_units: Tuple[RegulationUnit, ...] = ()
    excluded_regulation_units: Tuple[ExcludedRegulationUnit, ...] = ()
    degraded: bool = False
    warnings: Tuple[str, ...] = ()
    coverage: Optional[RegulationRetrievalCoverage] = None
    candidate_count: int = 0
    excluded_count: int = 0


def infer_category_from_product_tags(product_tags: ProductTags) -> Optional[str]:
    """在普通分类识别失败时，用产品标签恢复法规注册分类。"""
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
    """补入受控类别词，避免专业子类因正文缺少上位词而弱召回。"""
    tag_terms = (
        PRODUCT_TAG_LABELS["line"].get(product_tags.line.value, ""),
        PRODUCT_TAG_LABELS["primary_subtype"].get(
            product_tags.primary_subtype.value,
            "",
        ),
        PRODUCT_TAG_LABELS["term_class"].get(product_tags.term_class.value, ""),
    )
    parts = (product_name, *tag_terms, document_content[:3000])
    return "\n".join(
        dict.fromkeys(part for part in parts if part and part != "未知")
    )


def _registered_names(category: Optional[str]) -> List[str]:
    if not category:
        return list(dict.fromkeys(
            name
            for names in ComplianceConstants.CATEGORY_REGULATION_REGISTRY.values()
            for name in names
        ))
    categories = [category]
    parent = ComplianceConstants.CATEGORY_PARENT_MAPPING.get(category)
    if parent:
        categories.append(parent)
    return list(dict.fromkeys(
        name
        for current in categories
        for name in ComplianceConstants.CATEGORY_REGULATION_REGISTRY.get(current, ())
    ))


def _metadata(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    value = candidate.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _value(candidate: Mapping[str, Any], key: str, default: Any = "") -> Any:
    value = candidate.get(key)
    if value not in (None, ""):
        return value
    return _metadata(candidate).get(key, default)


def _strings(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = value.replace("，", ",").replace("、", ",").replace("\n", ",")
        return tuple(part.strip() for part in normalized.split(",") if part.strip())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _chunk_index(candidate: Mapping[str, Any]) -> Optional[int]:
    for key in ("chunk_index", "chunk_id"):
        value = _value(candidate, key, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _registered_from_catalog(
    catalog: Iterable[Dict[str, Any]],
    names: Iterable[str],
    source_type: str,
) -> List[Tuple[Dict[str, Any], str]]:
    """从已加载的目录标记注册来源，避免为每个法规名重复扫描向量表。"""
    wanted = tuple(dict.fromkeys(name for name in names if name))
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in catalog:
        law_name = str(_value(candidate, "law_name", ""))
        by_name.setdefault(law_name, []).append(candidate)
    results: List[Tuple[Dict[str, Any], str]] = []
    for name in wanted:
        chunks = by_name.get(name, ())
        if not chunks:
            logger.warning("注册法规在知识库中未找到: %s", name)
        results.extend((dict(chunk), source_type) for chunk in chunks)
    return results


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_metadata_value(key: str, value: Any) -> Any:
    """消除 Arrow→Pandas 对 nullable 整数字段造成的类型漂移。"""
    if isinstance(value, float) and math.isnan(value):
        return None
    if (
        key in {"chunk_id", "level", "next_chunk_id", "prev_chunk_id"}
        and isinstance(value, float)
        and value.is_integer()
    ):
        return int(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _canonical_metadata_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _canonical_metadata_value(key, child_value)
            for child_value in value
        ]
    return value


def _stable_catalog_sha256(catalog: Iterable[Mapping[str, Any]]) -> str:
    """冻结全局 chunk 身份、正文、定位和全部业务 metadata。"""
    rows = []
    for candidate in catalog:
        metadata = {
            str(key): _canonical_metadata_value(str(key), value)
            for key, value in _metadata(candidate).items()
            if not str(key).startswith("_")
        }
        rows.append({
            "id": str(candidate.get("id", "")),
            "content": str(_value(candidate, "content", "")),
            "location": {
                key: _value(candidate, key, "")
                for key in (
                    "source_file",
                    "law_name",
                    "article_number",
                    "section_path",
                    "hierarchy_path",
                    "chunk_index",
                    "chunk_id",
                )
            },
            "metadata": metadata,
        })
    canonical = json.dumps(
        sorted(rows, key=lambda row: str(row["id"])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _explicit_kb_versions(candidate: Mapping[str, Any]) -> Tuple[str, ...]:
    """读取原始行显式携带的版本，不把运行时回填值冒充构建元数据。"""
    versions = []
    for value in (
        candidate.get("kb_version"),
        _metadata(candidate).get("kb_version"),
    ):
        text = str(value).strip() if value not in (None, "") else ""
        if text:
            versions.append(text)
    return tuple(dict.fromkeys(versions))


def _validate_candidate_identity_conservation(
    catalog: Iterable[Mapping[str, Any]],
    merged: Iterable[Mapping[str, Any]],
    layered: Any,
) -> Tuple[str, ...]:
    """证明目录经 merge 与分层后每个全局 chunk 身份恰好出现一次。"""
    catalog_identities = tuple(get_candidate_identity(item) for item in catalog)
    merged_identities = tuple(get_candidate_identity(item) for item in merged)
    trace_identities = tuple(
        f"id:{trace.chunk_id}"
        for trace in layered.trace
        if getattr(trace, "chunk_id", "")
    )
    errors: List[str] = []
    if Counter(catalog_identities) != Counter(merged_identities):
        missing = sorted(set(catalog_identities).difference(merged_identities))
        extra = sorted(set(merged_identities).difference(catalog_identities))
        errors.append(
            "法规目录身份在候选 merge 后不守恒: "
            f"catalog={len(catalog_identities)}, merged={len(merged_identities)}, "
            f"missing={missing[:3]}, extra={extra[:3]}"
        )
    if Counter(merged_identities) != Counter(trace_identities):
        missing = sorted(set(merged_identities).difference(trace_identities))
        extra = sorted(set(trace_identities).difference(merged_identities))
        errors.append(
            "法规候选身份在适用性分层后不守恒: "
            f"merged={len(merged_identities)}, trace={len(trace_identities)}, "
            f"missing={missing[:3]}, extra={extra[:3]}"
        )
    if layered.candidate_count != len(merged_identities):
        errors.append(
            "法规候选分层计数不守恒: "
            f"merged={len(merged_identities)}, "
            f"layered={layered.candidate_count}"
        )
    return tuple(errors)


def _validate_catalog_identity(
    engine: Any,
    catalog: Tuple[Dict[str, Any], ...],
    version: str,
    identity_path: Path = _KB_BUILD_IDENTITY_PATH,
) -> Tuple[str, ...]:
    """将在线候选冻结绑定到精算验收所用的知识库构建身份。"""
    errors: List[str] = []
    try:
        expected = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"无法读取受控知识库身份: {exc}",)
    if not isinstance(expected, Mapping):
        return ("受控知识库身份必须是 JSON object",)
    expected_version = str(expected.get("kb_version", ""))
    if version != expected_version:
        errors.append(
            f"知识库版本不匹配: active={version or 'unknown'}, expected={expected_version}"
        )
    global_ids = tuple(str(candidate.get("id", "")).strip() for candidate in catalog)
    missing_id_rows = tuple(
        index for index, chunk_id in enumerate(global_ids) if not chunk_id
    )
    if missing_id_rows:
        errors.append(
            "知识库 chunk 缺少顶层全局 id: "
            f"rows={list(missing_id_rows[:5])}"
        )
    duplicate_ids = tuple(
        chunk_id
        for chunk_id, count in Counter(global_ids).items()
        if chunk_id and count > 1
    )
    if duplicate_ids:
        errors.append(
            f"知识库目录存在重复全局 id: {list(sorted(duplicate_ids)[:5])}"
        )
    mixed_versions = tuple(
        (index, explicit_version)
        for index, candidate in enumerate(catalog)
        for explicit_version in _explicit_kb_versions(candidate)
        if explicit_version != expected_version
    )
    if mixed_versions:
        errors.append(
            "知识库 chunk 显式版本与受控版本不一致: "
            f"{list(mixed_versions[:5])}"
        )
    expected_chunks = expected.get("chunks")
    if not isinstance(expected_chunks, int) or len(catalog) != expected_chunks:
        errors.append(
            f"知识库 chunk 数不匹配: actual={len(catalog)}, expected={expected_chunks}"
        )
    source_files = {
        str(_value(candidate, "source_file", ""))
        for candidate in catalog
        if str(_value(candidate, "source_file", ""))
    }
    expected_documents = expected.get("documents")
    if (
        not isinstance(expected_documents, int)
        or len(source_files) != expected_documents
    ):
        errors.append(
            "知识库文档数不匹配: "
            f"actual={len(source_files)}, expected={expected_documents}"
        )
    expected_catalog_sha = str(expected.get("catalog_sha256", ""))
    actual_catalog_sha = _stable_catalog_sha256(catalog)
    if actual_catalog_sha != expected_catalog_sha:
        errors.append("知识库目录内容指纹与受控 v5 不一致")

    config = getattr(engine, "config", None)
    vector_db_path = getattr(config, "vector_db_path", None)
    if not isinstance(vector_db_path, str) or not vector_db_path:
        errors.append("无法从 RAG 配置定位知识库构建清单")
        return tuple(errors)
    vector_path = Path(vector_db_path)
    kb_root = (
        vector_path.parent.parent
        if vector_path.name == "lancedb"
        else vector_path.parent
    )
    manifest_path = kb_root / "references" / f"{expected_version}-build-manifest.json"
    try:
        manifest_sha = _sha256(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"无法读取知识库构建清单: {exc}")
        return tuple(errors)
    if manifest_sha != str(expected.get("build_manifest_sha256", "")):
        errors.append("知识库构建清单指纹与受控 v5 不一致")
    if not isinstance(manifest, Mapping):
        errors.append("知识库构建清单必须是 JSON object")
        return tuple(errors)
    for field in ("source_file", "source_sha256", "documents", "chunks"):
        if manifest.get(field) != expected.get(field):
            errors.append(f"知识库构建清单字段不匹配: {field}")
    return tuple(dict.fromkeys(errors))


def _merge_registered(
    candidates: Iterable[Tuple[Dict[str, Any], str]],
) -> List[Tuple[Dict[str, Any], str]]:
    merged: Dict[str, Tuple[Dict[str, Any], str]] = {}
    for candidate, source_type in candidates:
        identity = get_candidate_identity(candidate)
        current = merged.get(identity)
        if current is None:
            item = dict(candidate)
            item["retrieval_sources"] = [f"registered:{source_type}"]
            merged[identity] = (item, source_type)
            continue
        item, current_type = current
        sources = set(item.get("retrieval_sources", ()))
        sources.add(f"registered:{source_type}")
        item["retrieval_sources"] = sorted(sources)
        merged[identity] = (
            item,
            "category" if source_type == "category" else current_type,
        )
    return list(merged.values())


def _kb_version(engine: Any, candidates: Iterable[Mapping[str, Any]]) -> str:
    for candidate in candidates:
        version = _value(candidate, "kb_version", "")
        if version:
            return str(version)
    config = getattr(engine, "config", None)
    vector_db_path = getattr(config, "vector_db_path", None)
    if not isinstance(vector_db_path, str) or not vector_db_path:
        return ""
    path = Path(vector_db_path)
    return path.parent.name if path.name == "lancedb" else path.name


def _merge_candidates(
    catalog: Iterable[Dict[str, Any]],
    semantic: Iterable[Dict[str, Any]],
    registered: Iterable[Tuple[Dict[str, Any], str]],
    kb_version: str,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    priority = {"catalog": 0, "semantic": 1, "general": 2, "category": 3}

    def add(candidate: Dict[str, Any], source_type: str) -> None:
        identity = get_candidate_identity(candidate)
        current = merged.get(identity)
        if current is None:
            item = dict(candidate)
            item["_source_type"] = source_type
            sources = set(item.get("retrieval_sources", ()))
            sources.add(source_type)
            item["retrieval_sources"] = sorted(sources)
            item["kb_version"] = str(_value(item, "kb_version", "")) or kb_version
            merged[identity] = item
            return
        sources = set(current.get("retrieval_sources", ()))
        sources.update(candidate.get("retrieval_sources", ()))
        sources.add(source_type)
        current["retrieval_sources"] = sorted(sources)
        if priority[source_type] > priority.get(
            str(current.get("_source_type", "catalog")),
            0,
        ):
            current["_source_type"] = source_type
        incoming_score = candidate.get("score")
        current_score = current.get("score")
        if isinstance(incoming_score, (int, float)) and (
            not isinstance(current_score, (int, float))
            or incoming_score > current_score
        ):
            current["score"] = incoming_score

    for candidate in catalog:
        add(candidate, "catalog")
    for candidate in semantic:
        add(candidate, "semantic")
    for candidate, source_type in registered:
        add(candidate, source_type)
    return list(merged.values())


def _regulation_item(candidate: Mapping[str, Any]) -> AuditRegulationItem:
    topics = candidate.get("regulation_topics")
    if topics is None:
        topics = _metadata(candidate).get("条款主题")
    return AuditRegulationItem(
        chunk_id=str(_value(candidate, "id", "")),
        law_name=str(_value(candidate, "law_name", "")),
        article_number=str(_value(candidate, "article_number", "")),
        content=str(_value(candidate, "content", "")),
        source_type=str(candidate.get("_source_type", "tagged_retrieval")),
        doc_number=str(_value(candidate, "doc_number", "")),
        issuing_authority=str(_value(candidate, "issuing_authority", "")),
        effective_date=str(_value(candidate, "effective_date", "")),
        applicability_status=str(candidate.get("applicability_status", "")),
        matched_dimensions=_strings(candidate.get("matched_dimensions")),
        matched_topics=_strings(candidate.get("matched_topics")),
        fallback_layer=str(candidate.get("fallback_layer", "")),
        retrieval_sources=_strings(candidate.get("retrieval_sources")),
        kb_version=str(_value(candidate, "kb_version", "")),
        source_file=str(_value(candidate, "source_file", "")),
        section_path=str(_value(candidate, "section_path", "")),
        chunk_index=_chunk_index(candidate),
        regulation_unit_id=str(candidate.get("regulation_unit_id", "")),
        chunk_ids=_strings(candidate.get("chunk_ids")),
        regulation_topics=_strings(topics),
        indeterminate_dimensions=_strings(
            candidate.get("indeterminate_dimensions")
        ),
        excluded_by=_strings(candidate.get("excluded_by")),
        applicability_reasons=_strings(candidate.get("applicability_reasons")),
        category=str(_value(candidate, "category", "")),
    )


def _excluded_units(traces: Iterable[Any], kb_version: str) -> Tuple[ExcludedRegulationUnit, ...]:
    grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for trace in traces:
        if getattr(getattr(trace, "status", None), "value", "") != "not_applicable":
            continue
        version = trace.kb_version or kb_version or "unknown"
        source_file = trace.source_file or trace.law_name or "unknown"
        locator = trace.article_number or trace.section_path or trace.chunk_id
        key = (version, source_file, locator)
        item = grouped.setdefault(key, {
            "chunk_ids": [],
            "topics": [],
            "excluded_by": [],
            "reasons": [],
            "trace": trace,
        })
        item["chunk_ids"].append(trace.chunk_id)
        item["topics"].extend(trace.regulation_topics)
        item["excluded_by"].extend(trace.excluded_by)
        item["reasons"].extend(trace.reasons)
    return tuple(
        ExcludedRegulationUnit(
            regulation_unit_id=build_regulation_unit_id(*key),
            kb_version=key[0],
            source_file=key[1],
            section_path=item["trace"].section_path,
            law_name=item["trace"].law_name,
            article_number=item["trace"].article_number,
            chunk_ids=tuple(dict.fromkeys(item["chunk_ids"])),
            regulation_topics=tuple(dict.fromkeys(item["topics"])),
            excluded_by=tuple(dict.fromkeys(item["excluded_by"])),
            reasons=tuple(dict.fromkeys(item["reasons"])),
            category=item["trace"].category,
        )
        for key, item in grouped.items()
    )


def retrieve_regulation_candidates(
    query: str,
    category: Optional[str],
    product_tags: ProductTags,
    clause_topics: Tuple[str, ...] = (),
    semantic_top_k: int = 12,
) -> RegulationRetrievalOutcome:
    """冻结全库 applicable/indeterminate 候选，语义检索仅提供排序信号。"""
    engine = get_engine()
    if engine is None:
        coverage = RegulationRetrievalCoverage(
            rag_available=False,
            catalog_available=False,
            semantic_available=False,
            registered_available=False,
            category_resolution="provided" if category else "unknown",
            complete_candidate_freeze=False,
            uncovered_scopes=(
                "regulation_catalog",
                "semantic_retrieval",
                "registered_retrieval",
            ),
        )
        return RegulationRetrievalOutcome(
            regulations=(),
            degraded=True,
            warnings=("法规知识库未初始化，无法冻结法规候选集",),
            coverage=coverage,
        )

    warnings: List[str] = []
    uncovered: List[str] = []
    effective_category = category or infer_category_from_product_tags(product_tags)
    if category:
        category_resolution = "provided"
    elif effective_category:
        category_resolution = "product_tags"
        warnings.append(f"产品分类识别失败，已按产品标签回退为 {effective_category}")
    else:
        category_resolution = "unknown_all_categories"
        warnings.append("产品分类未知，已保守纳入全库法规候选")
        uncovered.append("product_category_resolution")

    try:
        catalog = [dict(item) for item in engine.search_by_metadata({})]
    except Exception as exc:
        logger.warning("法规目录加载失败: %s", exc)
        catalog = []
    if not catalog:
        warnings.append("法规全库目录为空，无法证明候选集完整")
        uncovered.append("regulation_catalog")

    try:
        registered_raw = (
            [
                *_registered_from_catalog(
                    catalog,
                    _registered_names(effective_category),
                    "category",
                ),
                *_registered_from_catalog(
                    catalog,
                    ComplianceConstants.GENERAL_REGULATIONS,
                    "general",
                ),
            ]
            if catalog
            else []
        )
    except Exception as exc:
        logger.warning("注册法规加载失败: %s", exc)
        registered_raw = []
        warnings.append("注册法规加载失败，已使用全库目录继续")
        uncovered.append("registered_retrieval")
    registered = _merge_registered(registered_raw)
    if not registered:
        warnings.append("注册法规候选为空")
        uncovered.append("registered_retrieval")

    semantic_available = True
    try:
        semantic = [
            dict(item)
            for item in engine.search_candidates(
                query,
                top_k=max(semantic_top_k * 3, 24),
            )
        ]
    except Exception as exc:
        logger.warning("语义检索失败: %s", exc)
        semantic = []
        semantic_available = False
        warnings.append("语义检索失败，已使用全库目录继续")
        uncovered.append("semantic_retrieval")

    version = _kb_version(
        engine,
        (*catalog, *semantic, *(item for item, _ in registered)),
    )
    if not version:
        warnings.append("无法确定知识库版本")
        uncovered.append("kb_version")
    candidates = _merge_candidates(catalog, semantic, registered, version)
    all_units = aggregate_regulation_units(candidates, version)
    if all_units.errors:
        warnings.append(
            f"{len(all_units.errors)} 个原始法规 chunk 缺少稳定身份字段"
        )
        uncovered.append("regulation_unit_identity")
    identity_errors = _validate_catalog_identity(
        engine,
        tuple(catalog),
        version,
    )
    if identity_errors:
        warnings.extend(identity_errors)
        uncovered.append("kb_build_identity")
    layered = layer_regulation_candidates(
        candidates,
        product_tags=product_tags,
        clause_topics=clause_topics,
        top_k=None,
    )
    conservation_errors = _validate_candidate_identity_conservation(
        catalog,
        candidates,
        layered,
    )
    if conservation_errors:
        warnings.extend(conservation_errors)
        uncovered.append("candidate_identity_conservation")
    units = aggregate_regulation_units(layered.chunks, version)
    excluded_units = _excluded_units(layered.trace, version)
    if units.errors:
        warnings.append(
            f"{len(units.errors)} 个法规 chunk 因身份字段缺失未形成审核单元"
        )
        uncovered.append("regulation_unit_identity")
    unit_by_chunk = {
        chunk_id: unit
        for unit in units.units
        for chunk_id in unit.chunk_ids
    }
    enriched: List[Dict[str, Any]] = []
    for candidate in layered.chunks:
        item = dict(candidate)
        chunk_id = str(_value(item, "id", "") or _value(item, "chunk_id", ""))
        unit = unit_by_chunk.get(chunk_id)
        if unit is not None:
            item["regulation_unit_id"] = unit.unit_id
            item["chunk_ids"] = unit.chunk_ids
        enriched.append(item)
    coverage = RegulationRetrievalCoverage(
        rag_available=True,
        catalog_available=bool(catalog),
        semantic_available=semantic_available,
        registered_available=bool(registered),
        category_resolution=category_resolution,
        complete_candidate_freeze=(
            bool(catalog)
            and bool(version)
            and not all_units.errors
            and not units.errors
            and not identity_errors
            and not conservation_errors
        ),
        catalog_candidate_count=len(catalog),
        semantic_candidate_count=len(semantic),
        registered_candidate_count=len(registered),
        uncovered_scopes=tuple(dict.fromkeys(uncovered)),
    )
    return RegulationRetrievalOutcome(
        regulations=tuple(_regulation_item(item) for item in enriched),
        regulation_units=units.units,
        excluded_regulation_units=excluded_units,
        degraded=bool(warnings),
        warnings=tuple(warnings),
        coverage=coverage,
        candidate_count=len(units.units),
        excluded_count=len(excluded_units),
    )
