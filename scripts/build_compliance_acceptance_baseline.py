#!/usr/bin/env python3
"""将已签收验收数据压缩为可提交、可自动回归的确定性基线。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError(f"{label} 必须是字符串键对象")
    return value


def _rows(value: object, label: str) -> list[list[object]]:
    if not isinstance(value, list) or not all(
        isinstance(row, list) for row in value
    ):
        raise ValueError(f"{label} 必须是二维数组")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是数组")
    return value


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


_BOOLEAN_TAG_FIELDS = frozenset({
    "is_internet_exclusive",
    "is_rate_adjustable",
    "is_tax_advantaged_health",
    "is_city_customized_medical",
})
_RISK_FACT_FIELDS = frozenset({
    "is_specific_disease_product",
    "mentions_out_of_hospital_drug",
    "is_cancer_specific_product",
    "mentions_critical_illness_definition_term",
    "is_increasing_sum_assured_product",
})


def _term_options(value: str) -> list[dict[str, object]]:
    if not value:
        return []
    options: list[dict[str, object]] = []
    for raw_option in value.split("｜"):
        attributes = {}
        for part in raw_option.split("；"):
            key, separator, raw_value = part.partition("=")
            if separator:
                attributes[key] = raw_value
        raw_number = attributes.get("value", "")
        number = float(raw_number) if raw_number else None
        options.append({
            "kind": attributes.get("kind", ""),
            "value": int(number) if number is not None and number.is_integer() else number,
            "unit": attributes.get("unit", ""),
        })
    return options


def _product_tag_value(field_name: str, value: str) -> object:
    if field_name in _BOOLEAN_TAG_FIELDS:
        return True if value == "是" else False if value == "否" else None
    if field_name in {"term_forms", "coverage_components"}:
        return [part for part in value.split("、") if part]
    if field_name == "term_options":
        return _term_options(value)
    return value


def _tri_state_value(value: str, label: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "unknown":
        return None
    raise ValueError(f"{label} 的三态值无效: {value!r}")


def _risk_fact_records(
    items: list[dict[str, object]],
    sample_id: str,
) -> dict[str, dict[str, object]]:
    records = {
        _text(item.get("field_name")): item
        for item in items
    }
    if "" in records or len(records) != len(items):
        raise ValueError(f"{sample_id} 的风险事实字段为空或重复")
    if set(records) != _RISK_FACT_FIELDS:
        missing = sorted(_RISK_FACT_FIELDS.difference(records))
        extra = sorted(set(records).difference(_RISK_FACT_FIELDS))
        raise ValueError(
            f"{sample_id} 的风险事实字段集合不完整: missing={missing}, extra={extra}"
        )
    for field_name, item in records.items():
        _tri_state_value(
            _text(item.get("system_value")),
            f"{sample_id}.{field_name}",
        )
        if not _text(item.get("evidence_source")) or not _text(item.get("evidence_text")):
            raise ValueError(f"{sample_id}.{field_name} 缺少已签收证据")
    return records


def _risk_fact_values(
    items: list[dict[str, object]],
    sample_id: str,
) -> dict[str, str]:
    records = _risk_fact_records(items, sample_id)
    values = {
        field_name: _text(item.get("system_value"))
        for field_name, item in records.items()
    }
    return values


def _confidence(value: object) -> float | None:
    return float(value) if value not in (None, "") else None


def _cross_check_review_values(
    review_values: dict[str, object],
    risk_facts: list[dict[str, object]],
    applicability: list[dict[str, object]],
) -> None:
    risk_review: dict[tuple[str, str], tuple[object, ...]] = {}
    for row in _rows(review_values.get("新增风险事实验收"), "新增风险事实验收")[4:]:
        if len(row) < 14 or not _text(row[1]):
            continue
        key = (_text(row[1]), _text(row[6]))
        if key in risk_review:
            raise ValueError(f"工作簿风险事实键重复: {key}")
        risk_review[key] = (
            _text(row[4]),
            _text(row[8]),
            _text(row[10]),
            _text(row[11]),
            _confidence(row[12]),
            _text(row[13]),
        )
    acceptance_risk = {
        (_text(item.get("sample_id")), _text(item.get("field_name"))): (
            _text(item.get("file_sha256")),
            _text(item.get("system_value")),
            _text(item.get("evidence_source")),
            _text(item.get("evidence_text")),
            _confidence(item.get("confidence")),
            _text(item.get("review_status")),
        )
        for item in risk_facts
    }
    if risk_review != acceptance_risk:
        raise ValueError("风险事实验收数据与工作簿值不一致")

    applicability_review: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in _rows(review_values.get("法规适用性验收"), "法规适用性验收")[4:]:
        if len(row) < 22 or not _text(row[1]):
            continue
        key = (_text(row[1]), _text(row[3]))
        if key in applicability_review:
            raise ValueError(f"工作簿法规适用性键重复: {key}")
        applicability_review[key] = (
            _text(row[4]),
            _text(row[5]),
            _text(row[12]),
            _text(row[13]),
            _text(row[15]),
            _text(row[16]),
            _text(row[17]),
            _text(row[19]),
            _text(row[21]),
        )
    acceptance_applicability = {
        (_text(item.get("sample_id")), _text(item.get("unit_id"))): (
            _text(item.get("law_name")),
            _text(item.get("article_number")),
            _text(item.get("system_status")),
            _text(item.get("review_status")),
            _text(item.get("excluded_by")),
            _text(item.get("indeterminate_dimensions")),
            _text(item.get("reasons")),
            _text(item.get("source_file")),
            _text(item.get("content")),
        )
        for item in applicability
    }
    if applicability_review != acceptance_applicability:
        raise ValueError("法规适用性验收数据与工作簿值不一致")


def _accepted_product_tags(review_values: dict[str, object]) -> dict[str, dict[str, object]]:
    sheet = _rows(review_values.get("产品标签验收"), "产品标签验收")
    accepted: dict[str, dict[str, object]] = {}
    for row in sheet[4:]:
        if len(row) < 11 or not _text(row[1]):
            continue
        if _text(row[10]) != "确认":
            raise ValueError(f"产品标签尚未签收: sample={row[1]}, field={row[3]}")
        field_name = _text(row[3])
        accepted.setdefault(_text(row[1]), {})[field_name] = _product_tag_value(
            field_name,
            _text(row[5]),
        )
    return accepted


def build_baseline(
    acceptance_data_path: Path,
    review_values_path: Path,
    source_workbook_path: Path,
) -> dict[str, object]:
    acceptance_data = _mapping(
        json.loads(acceptance_data_path.read_text(encoding="utf-8")),
        "验收数据",
    )
    review_values = _mapping(
        json.loads(review_values_path.read_text(encoding="utf-8")),
        "验收反馈",
    )
    source_workbook_sha256 = _sha256(source_workbook_path)
    if _text(review_values.get("__source_workbook_sha256")) != source_workbook_sha256:
        raise ValueError("工作簿值提取物未绑定当前源工作簿SHA-256")
    product_tags = _accepted_product_tags(review_values)
    applicability = [
        _mapping(item, "法规适用性记录")
        for item in _list(acceptance_data.get("applicability"), "法规适用性记录")
    ]
    risk_facts = [
        _mapping(item, "风险事实记录")
        for item in _list(acceptance_data.get("risk_facts"), "风险事实记录")
    ]
    if any(_text(item.get("review_status")) != "确认" for item in applicability):
        raise ValueError("法规适用性仍有未签收记录")
    if any(_text(item.get("review_status")) != "确认" for item in risk_facts):
        raise ValueError("风险事实仍有未签收记录")
    _cross_check_review_values(review_values, risk_facts, applicability)

    accepted_sample_ids = acceptance_data.get("acceptance_sample_ids")
    if not isinstance(accepted_sample_ids, list) or not all(
        isinstance(sample_id, str) for sample_id in accepted_sample_ids
    ):
        raise ValueError("acceptance_sample_ids 必须是字符串数组")
    product_values = [
        _mapping(value, "产品记录")
        for value in _list(acceptance_data.get("products"), "产品记录")
    ]
    product_records = {
        _text(item.get("sample_id")): item
        for item in product_values
    }
    if len(product_records) != len(product_values) or "" in product_records:
        raise ValueError("产品记录 sample_id 为空或重复")
    if len(set(accepted_sample_ids)) != len(accepted_sample_ids):
        raise ValueError("acceptance_sample_ids 不得重复")
    risk_facts_by_sample: dict[str, list[dict[str, object]]] = {}
    for item in risk_facts:
        sample_id = _text(item.get("sample_id"))
        if sample_id not in product_records:
            raise ValueError(f"风险事实引用未知产品: {sample_id}")
        risk_facts_by_sample.setdefault(sample_id, []).append(item)
    risk_fact_products: list[dict[str, object]] = []
    for product in product_values:
        sample_id = _text(product.get("sample_id"))
        records = _risk_fact_records(risk_facts_by_sample.get(sample_id, []), sample_id)
        risk_fact_products.append({
            "sample_id": sample_id,
            "product_name": _text(product.get("product_name")),
            "file_name": _text(product.get("file_name")),
            "file_sha256": _text(product.get("file_sha256")),
            "risk_facts": {
                field_name: {
                    "value": _text(item.get("system_value")),
                    "evidence_source": _text(item.get("evidence_source")),
                    "evidence_text": _text(item.get("evidence_text")),
                    "confidence": _confidence(item.get("confidence")),
                }
                for field_name, item in records.items()
            },
        })
    unit_catalog: dict[str, dict[str, object]] = {}
    products: list[dict[str, object]] = []
    for sample_id in accepted_sample_ids:
        product = product_records[sample_id]
        product_applicability = [
            item for item in applicability if _text(item.get("sample_id")) == sample_id
        ]
        product_risk_facts = _risk_fact_values(
            risk_facts_by_sample.get(sample_id, []),
            sample_id,
        )
        unit_ids = [_text(item.get("unit_id")) for item in product_applicability]
        if "" in unit_ids or len(set(unit_ids)) != len(unit_ids):
            raise ValueError(f"{sample_id} 的法规单元ID为空或重复")
        for item in product_applicability:
            unit_id = _text(item.get("unit_id"))
            content = _text(item.get("content"))
            catalog_entry: dict[str, object] = {
                "unit_id": unit_id,
                "law_name": _text(item.get("law_name")),
                "article_number": _text(item.get("article_number")),
                "source_file": _text(item.get("source_file")),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "metadata": {
                    "适用标签": _text(item.get("applicability_tags")),
                    "适用条件": _text(item.get("applicability_condition")),
                    "风险触发标签": _text(item.get("risk_triggers")),
                    "检查目标标签": _text(item.get("check_targets")),
                    "条款主题": _text(item.get("regulation_topics")),
                },
            }
            existing_entry = unit_catalog.get(unit_id)
            if existing_entry is not None and existing_entry != catalog_entry:
                raise ValueError(
                    f"法规单元在不同产品行中的内容或元数据不一致: {unit_id}"
                )
            unit_catalog[unit_id] = catalog_entry
        if sample_id not in product_tags:
            raise ValueError(f"验收产品缺少已签收标签: {sample_id}")
        frozen_tags = dict(product_tags[sample_id])
        for field_name, raw_value in product_risk_facts.items():
            frozen_tags[field_name] = _tri_state_value(
                raw_value,
                f"{sample_id}.{field_name}",
            )
        products.append({
            "sample_id": sample_id,
            "product_name": _text(product.get("product_name")),
            "file_name": _text(product.get("file_name")),
            "file_sha256": _text(product.get("file_sha256")),
            "product_tags": frozen_tags,
            "risk_facts": product_risk_facts,
            "applicability": {
                _text(item.get("unit_id")): {
                    "status": _text(item.get("system_status")),
                    "excluded_by": [
                        part for part in _text(item.get("excluded_by")).split("、") if part
                    ],
                    "indeterminate_dimensions": [
                        part
                        for part in _text(item.get("indeterminate_dimensions")).split("、")
                        if part
                    ],
                    # The workbook serializes the complete reason tuple with Chinese
                    # semicolons, while individual controlled-tag values may contain
                    # the same punctuation. Preserve the signed display text verbatim
                    # instead of attempting an ambiguous reverse split.
                    "reason_text": _text(item.get("reasons")),
                }
                for item in product_applicability
            },
        })
    summary = _mapping(acceptance_data.get("summary"), "验收汇总")
    risk_fact_count = sum(
        len(_mapping(item.get("risk_facts"), "风险事实"))
        for item in risk_fact_products
    )
    applicability_count = sum(
        len(_mapping(item.get("applicability"), "适用性矩阵"))
        for item in products
    )
    if risk_fact_count != int(str(summary["risk_fact_count"])):
        raise ValueError("冻结风险事实数量与验收汇总不一致")
    if applicability_count != int(str(summary["applicability_row_count"])):
        raise ValueError("冻结法规适用性数量与验收汇总不一致")
    return {
        "schema_version": "1",
        "baseline_id": "compliance-audit-v1-applicability-v7",
        "accepted_at": "2026-08-05",
        "source_workbook": {
            "file_name": source_workbook_path.name,
            "sha256": source_workbook_sha256,
        },
        "inputs": {
            "acceptance_data_sha256": _sha256(acceptance_data_path),
            "review_values_sha256": _sha256(review_values_path),
        },
        "kb": _mapping(acceptance_data.get("kb_identity"), "KB身份"),
        "summary": {
            "product_tag_count": sum(len(item) for item in product_tags.values()),
            "risk_fact_count": risk_fact_count,
            "applicability_count": applicability_count,
            "regulation_unit_count": len(unit_catalog),
            "product_tag_sample_count": len(products),
            "risk_fact_sample_count": len(risk_fact_products),
            "applicability_sample_count": len(products),
        },
        "regulation_units": list(unit_catalog.values()),
        "risk_fact_products": risk_fact_products,
        "products": products,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成精算签收回归基线")
    parser.add_argument("--acceptance-data", type=Path, required=True)
    parser.add_argument("--review-values", type=Path, required=True)
    parser.add_argument("--source-workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    baseline = build_baseline(
        args.acceptance_data,
        args.review_values,
        args.source_workbook,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(baseline["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
