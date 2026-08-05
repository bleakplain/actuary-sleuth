"""审核主链的数据就绪只读扫描。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class BoundaryIssue:
    source_file: str
    previous_section: str
    current_section: str
    issue_type: str
    overlap_chars: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "previous_section": self.previous_section,
            "current_section": self.current_section,
            "issue_type": self.issue_type,
            "overlap_chars": self.overlap_chars,
        }


@dataclass(frozen=True)
class KnowledgeBaseReadiness:
    version: str
    document_count: int
    chunk_count: int
    expected_document_count: int
    expected_chunk_count: int
    applicability_tagged_chunks: int
    limited_tagged_chunks: int
    involved_tagged_chunks: int
    risk_trigger_tagged_chunks: int
    check_target_tagged_chunks: int
    ambiguous_semantics_chunks: int
    regulation_topic_tagged_chunks: int
    missing_section_path_chunks: int
    boundary_issues: tuple[BoundaryIssue, ...]

    @property
    def manifest_matches(self) -> bool:
        return (
            self.document_count == self.expected_document_count
            and self.chunk_count == self.expected_chunk_count
        )

    @property
    def blocking(self) -> bool:
        return (
            not self.manifest_matches
            or self.missing_section_path_chunks > 0
            or bool(self.boundary_issues)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "expected_document_count": self.expected_document_count,
            "expected_chunk_count": self.expected_chunk_count,
            "manifest_matches": self.manifest_matches,
            "applicability_tagged_chunks": self.applicability_tagged_chunks,
            "limited_tagged_chunks": self.limited_tagged_chunks,
            "involved_tagged_chunks": self.involved_tagged_chunks,
            "risk_trigger_tagged_chunks": self.risk_trigger_tagged_chunks,
            "check_target_tagged_chunks": self.check_target_tagged_chunks,
            "ambiguous_semantics_chunks": self.ambiguous_semantics_chunks,
            "regulation_topic_tagged_chunks": self.regulation_topic_tagged_chunks,
            "missing_section_path_chunks": self.missing_section_path_chunks,
            "boundary_issue_count": len(self.boundary_issues),
            "boundary_issues": [issue.to_dict() for issue in self.boundary_issues],
        }


@dataclass(frozen=True)
class ProductReadiness:
    document_count: int
    parsed_document_count: int
    extension_counts: tuple[tuple[str, int], ...]
    subtype_counts: tuple[tuple[str, int], ...]
    clause_block_count: int
    tagged_clause_block_count: int
    clause_char_count: int
    tagged_clause_char_count: int
    topic_code_count: int
    keyword_mapping_count: int
    parse_failures: tuple[str, ...]
    unknown_subtype_files: tuple[str, ...]

    @property
    def tagged_block_ratio(self) -> float:
        if not self.clause_block_count:
            return 0.0
        return self.tagged_clause_block_count / self.clause_block_count

    @property
    def tagged_char_ratio(self) -> float:
        if not self.clause_char_count:
            return 0.0
        return self.tagged_clause_char_count / self.clause_char_count

    @property
    def blocking(self) -> bool:
        return bool(self.parse_failures)

    def to_dict(self) -> dict[str, object]:
        return {
            "document_count": self.document_count,
            "parsed_document_count": self.parsed_document_count,
            "extension_counts": dict(self.extension_counts),
            "subtype_counts": dict(self.subtype_counts),
            "clause_block_count": self.clause_block_count,
            "tagged_clause_block_count": self.tagged_clause_block_count,
            "untagged_clause_block_count": self.clause_block_count - self.tagged_clause_block_count,
            "tagged_block_ratio": round(self.tagged_block_ratio, 6),
            "clause_char_count": self.clause_char_count,
            "tagged_clause_char_count": self.tagged_clause_char_count,
            "untagged_clause_char_count": self.clause_char_count - self.tagged_clause_char_count,
            "tagged_char_ratio": round(self.tagged_char_ratio, 6),
            "topic_code_count": self.topic_code_count,
            "keyword_mapping_count": self.keyword_mapping_count,
            "parse_failures": list(self.parse_failures),
            "unknown_subtype_files": list(self.unknown_subtype_files),
        }


@dataclass(frozen=True)
class ReadinessReport:
    knowledge_base: KnowledgeBaseReadiness
    products: ProductReadiness
    known_gaps: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.knowledge_base.blocking or self.products.blocking:
            return "blocked"
        if self.known_gaps:
            return "ready_with_known_gaps"
        return "ready"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": self.status,
            "knowledge_base": self.knowledge_base.to_dict(),
            "products": self.products.to_dict(),
            "known_gaps": list(self.known_gaps),
        }


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _metadata(row: Mapping[str, object]) -> Mapping[str, object]:
    value = row.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _longest_boundary_overlap(previous: str, current: str, minimum: int = 30) -> int:
    upper = min(len(previous), len(current))
    for size in range(upper, minimum - 1, -1):
        if previous[-size:] == current[:size]:
            return size
    return 0


def inspect_knowledge_base_rows(
    rows: Sequence[Mapping[str, object]],
    version: str,
    expected_documents: int,
    expected_chunks: int,
) -> KnowledgeBaseReadiness:
    """从已加载的 LanceDB 行计算可重复的数据质量指标。"""
    source_files: set[str] = set()
    applicability_count = 0
    limited_count = 0
    involved_count = 0
    risk_trigger_count = 0
    check_target_count = 0
    ambiguous_count = 0
    topic_count = 0
    missing_section_count = 0
    ordered_by_source: dict[str, list[tuple[int, str, str]]] = defaultdict(list)

    for fallback_index, row in enumerate(rows):
        metadata = _metadata(row)
        source_file = _text(metadata.get("source_file"))
        if source_file:
            source_files.add(source_file)
        applicability = _text(metadata.get("适用标签"))
        involved = _text(metadata.get("涉及标签"))
        semantics = _text(metadata.get("适用标签语义"))
        is_involved = bool(involved) or bool(applicability and semantics == "涉及")
        if applicability:
            applicability_count += 1
            if semantics == "限定":
                limited_count += 1
            elif semantics != "涉及":
                ambiguous_count += 1
        if is_involved:
            involved_count += 1
        if _text(metadata.get("风险触发标签")):
            risk_trigger_count += 1
        if _text(metadata.get("检查目标标签")):
            check_target_count += 1
        if _text(metadata.get("条款主题")):
            topic_count += 1
        section_path = _text(metadata.get("section_path"))
        if not section_path:
            missing_section_count += 1
        chunk_id = metadata.get("chunk_id")
        order = chunk_id if isinstance(chunk_id, int) else fallback_index
        content = _text(row.get("text"))
        if source_file and section_path and content:
            ordered_by_source[source_file].append((order, section_path, content))

    boundary_issues: list[BoundaryIssue] = []
    for source_file, source_rows in ordered_by_source.items():
        source_rows.sort(key=lambda item: item[0])
        for previous, current in zip(source_rows, source_rows[1:]):
            _, previous_section, previous_text = previous
            _, current_section, current_text = current
            if previous_section == current_section:
                continue
            if previous_text == current_text:
                boundary_issues.append(
                    BoundaryIssue(
                        source_file=source_file,
                        previous_section=previous_section,
                        current_section=current_section,
                        issue_type="duplicate_text_across_sections",
                        overlap_chars=len(current_text),
                    )
                )
                continue
            overlap = _longest_boundary_overlap(previous_text, current_text)
            if overlap:
                boundary_issues.append(
                    BoundaryIssue(
                        source_file=source_file,
                        previous_section=previous_section,
                        current_section=current_section,
                        issue_type="suffix_prefix_overlap_across_sections",
                        overlap_chars=overlap,
                    )
                )

    return KnowledgeBaseReadiness(
        version=version,
        document_count=len(source_files),
        chunk_count=len(rows),
        expected_document_count=expected_documents,
        expected_chunk_count=expected_chunks,
        applicability_tagged_chunks=applicability_count,
        limited_tagged_chunks=limited_count,
        involved_tagged_chunks=involved_count,
        risk_trigger_tagged_chunks=risk_trigger_count,
        check_target_tagged_chunks=check_target_count,
        ambiguous_semantics_chunks=ambiguous_count,
        regulation_topic_tagged_chunks=topic_count,
        missing_section_path_chunks=missing_section_count,
        boundary_issues=tuple(boundary_issues),
    )


def inspect_product_documents(
    product_dir: Path,
    topic_keywords_path: Path,
) -> ProductReadiness:
    """解析目录内全部受支持产品条款并统计主题覆盖率。"""
    from lib.common.product_tags import ProductSubtype
    from lib.doc_parser import parse_product_document
    from lib.doc_parser.pd.clause_topics import (
        load_clause_topic_keywords,
        load_clause_topic_registry,
    )

    registry = load_clause_topic_registry(
        topic_keywords_path.with_name("clause_topics.json")
    )
    topic_keywords = load_clause_topic_keywords(registry, topic_keywords_path)
    keyword_mapping_count = sum(len(values) for values in topic_keywords.values())

    paths = sorted(
        path
        for path in product_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".doc", ".docx", ".pdf"}
    )
    extension_counts = Counter(path.suffix.lower() for path in paths)
    subtype_counts: Counter[str] = Counter()
    parsed_count = 0
    block_count = 0
    tagged_block_count = 0
    char_count = 0
    tagged_char_count = 0
    failures: list[str] = []
    unknown_subtypes: list[str] = []

    for path in paths:
        try:
            document = parse_product_document(str(path))
        except Exception as exc:
            failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        parsed_count += 1
        subtype_counts[document.product_tags.primary_subtype.value] += 1
        if document.product_tags.primary_subtype is ProductSubtype.UNKNOWN:
            unknown_subtypes.append(path.name)
        for clause in (*document.clauses, *document.rider_clauses):
            block_chars = len(clause.title) + len(clause.text)
            block_count += 1
            char_count += block_chars
            if clause.topics:
                tagged_block_count += 1
                tagged_char_count += block_chars

    return ProductReadiness(
        document_count=len(paths),
        parsed_document_count=parsed_count,
        extension_counts=tuple(sorted(extension_counts.items())),
        subtype_counts=tuple(sorted(subtype_counts.items())),
        clause_block_count=block_count,
        tagged_clause_block_count=tagged_block_count,
        clause_char_count=char_count,
        tagged_clause_char_count=tagged_char_count,
        topic_code_count=len(registry.codes),
        keyword_mapping_count=keyword_mapping_count,
        parse_failures=tuple(failures),
        unknown_subtype_files=tuple(unknown_subtypes),
    )


def _load_kb_rows(lancedb_dir: Path) -> list[Mapping[str, object]]:
    import lancedb  # type: ignore[import-untyped]

    database = lancedb.connect(str(lancedb_dir))
    table = database.open_table("regulations_vectors")
    raw_rows = table.to_arrow().to_pylist()
    return [row for row in raw_rows if isinstance(row, Mapping)]


def scan_readiness(
    kb_root: Path,
    references_dir: Path,
    product_dir: Path,
    topic_keywords_path: Path,
    version: str = "v5",
) -> ReadinessReport:
    """检查现有数据但不修改知识库、法规原文或产品文件。"""
    manifest_path = references_dir / f"{version}-build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("知识库构建清单必须是对象")
    expected_documents = manifest.get("documents")
    expected_chunks = manifest.get("chunks")
    if not isinstance(expected_documents, int) or not isinstance(expected_chunks, int):
        raise ValueError("知识库构建清单缺少 documents/chunks")

    kb = inspect_knowledge_base_rows(
        _load_kb_rows(kb_root / version / "lancedb"),
        version,
        expected_documents,
        expected_chunks,
    )
    products = inspect_product_documents(product_dir, topic_keywords_path)
    gaps: list[str] = []
    if kb.involved_tagged_chunks == 0:
        gaps.append("v5 当前没有涉及标签；涉及/限定分离仍是目标能力")
    if products.tagged_clause_block_count < products.clause_block_count:
        gaps.append("产品条款仍有未标主题内容；unknown 条款必须保守保留")
    if products.unknown_subtype_files:
        gaps.append("部分真实产品未能从产品名称确定子类")
    return ReadinessReport(kb, products, tuple(gaps))
