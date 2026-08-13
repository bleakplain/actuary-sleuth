#!/usr/bin/env python3
"""测量冻结真实产品的完整条款法规审核包。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Sequence

from lib.config import get_kb_version_dir
from lib.compliance.audit_pipeline import (
    AuditPipelineRequest,
    build_regulation_audit_packages,
)
from lib.compliance.package_measurement import (
    build_audit_clause_snapshots,
    build_measurement_report,
    list_applicable_regulation_units,
    measure_product_packages,
    render_measurement_markdown,
)
from lib.doc_parser import parse_product_document
from lib.rag_engine.kb_rebuild import load_catalog_rows

_DEFAULT_MANIFEST = (
    Path(__file__).parent
    / "tests" / "fixtures" / "compliance_audit" / "v1" / "manifest.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} 必须是对象")
    return value


def run_measurement(
    manifest_path: Path,
    products_dir: Path,
    kb_dir: Path,
    output_json: Path,
    output_markdown: Path,
) -> None:
    manifest = _mapping(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        "验收清单",
    )
    kb = _mapping(manifest.get("kb"), "知识库身份")
    kb_version = str(kb.get("version", ""))
    catalog = load_catalog_rows(kb_dir / kb_version / "lancedb")
    measurements = []
    raw_products = manifest.get("products")
    if not isinstance(raw_products, list):
        raise ValueError("验收产品必须是数组")
    for raw_product in raw_products:
        product = _mapping(raw_product, "验收产品")
        file_name = str(product.get("file_name", ""))
        source = products_dir / file_name
        if _sha256(source) != str(product.get("sha256", "")):
            raise ValueError(f"产品文件指纹不一致: {file_name}")
        document = parse_product_document(str(source))
        clauses = build_audit_clause_snapshots(document)
        units = list_applicable_regulation_units(
            catalog,
            document.product_tags,
            kb_version,
        )
        request = AuditPipelineRequest(
            product_name=document.product_name or file_name,
            document_content=document.canonical_text,
            product_tags=document.product_tags,
            clauses=clauses,
            document_fingerprint=document.document_fingerprint,
            audit_input_fingerprint=document.audit_input_fingerprint,
            product_name_source=document.product_name_source,
            parse_warnings=tuple(document.warnings),
        )
        packages, _, _ = build_regulation_audit_packages(request, units)
        measurements.append(measure_product_packages(
            str(product.get("sample_id", "")),
            file_name,
            len(clauses),
            sum(len(clause.text) for clause in clauses),
            packages,
            max_concurrency=5,
            deadline_seconds=300,
        ))
    report = build_measurement_report(
        measurements,
        kb_version=kb_version,
        max_concurrency=5,
        deadline_seconds=300,
        inputs={
            "product_manifest_sha256": _sha256(manifest_path),
            "kb_build_manifest_sha256": str(
                kb.get("build_manifest_sha256", "")
            ),
            "catalog_chunk_count": len(catalog),
        },
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_markdown.write_text(
        render_measurement_markdown(report),
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    kb_dir = Path(get_kb_version_dir())
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--products-dir", type=Path, default=kb_dir.parent / "products")
    parser.add_argument("--kb-dir", type=Path, default=kb_dir)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    run_measurement(
        args.manifest,
        args.products_dir,
        args.kb_dir,
        args.output_json,
        args.output_markdown,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
