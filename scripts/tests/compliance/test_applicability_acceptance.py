from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

from lib.common.product_tags import ProductTags
from lib.config import get_kb_version_dir
from lib.compliance.applicability import (
    RegulationApplicability,
    match_regulation_applicability,
)
from lib.compliance.regulation_units import aggregate_regulation_units
from lib.doc_parser import AuditDocument, parse_product_document
from lib.rag_engine.kb_rebuild import load_catalog_rows

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "compliance_audit" / "v1"
BASELINE_PATH = FIXTURE_DIR / "applicability-baseline-v7.json"
KB_ROOT = Path(get_kb_version_dir())
PRODUCTS_DIR = KB_ROOT.parent / "products"
KB_LANCEDB_PATH = KB_ROOT / "v5" / "lancedb"
ACCEPTED_COUNTS = Counter({
    "applicable": 822,
    "not_applicable": 916,
    "indeterminate": 2,
})
EXPECTED_RISK_FACT_FIELDS = {
    "is_specific_disease_product",
    "mentions_out_of_hospital_drug",
    "is_cancer_specific_product",
    "mentions_critical_illness_definition_term",
    "is_increasing_sum_assured_product",
}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    assert isinstance(value, Mapping), f"{label} 必须是对象"
    assert all(isinstance(key, str) for key in value), f"{label} 必须使用字符串键"
    return value


def _list(value: object, label: str) -> list[object]:
    assert isinstance(value, list), f"{label} 必须是数组"
    return value


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def baseline() -> Mapping[str, object]:
    return _mapping(
        json.loads(BASELINE_PATH.read_text(encoding="utf-8")),
        "v7验收基线",
    )


def _baseline_products(baseline: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        _mapping(item, "验收产品")
        for item in _list(baseline.get("products"), "验收产品")
    ]


def _baseline_risk_fact_products(
    baseline: Mapping[str, object],
) -> list[Mapping[str, object]]:
    return [
        _mapping(item, "风险事实产品")
        for item in _list(baseline.get("risk_fact_products"), "风险事实产品")
    ]


def _baseline_units(baseline: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    units = [
        _mapping(item, "法规单元")
        for item in _list(baseline.get("regulation_units"), "法规单元")
    ]
    return {_text(unit.get("unit_id")): unit for unit in units}


def _expected_result(value: object) -> Mapping[str, object]:
    return _mapping(value, "预期适用性结果")


def _list_of_text(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item) for item in _list(value, label))


def test_v7_baseline_is_complete_and_fully_signed(
    baseline: Mapping[str, object],
) -> None:
    assert baseline["schema_version"] == "1"
    assert baseline["baseline_id"] == "compliance-audit-v1-applicability-v7"
    summary = _mapping(baseline.get("summary"), "验收汇总")
    assert summary == {
        "product_tag_count": 170,
        "risk_fact_count": 115,
        "applicability_count": 1740,
        "regulation_unit_count": 174,
        "product_tag_sample_count": 10,
        "risk_fact_sample_count": 23,
        "applicability_sample_count": 10,
    }
    inputs = _mapping(baseline.get("inputs"), "基线输入指纹")
    assert set(inputs) == {"acceptance_data_sha256", "review_values_sha256"}
    assert all(len(_text(value)) == 64 for value in inputs.values())
    products = _baseline_products(baseline)
    risk_fact_products = _baseline_risk_fact_products(baseline)
    units = _baseline_units(baseline)
    assert len(products) == 10
    assert len(risk_fact_products) == 23
    assert len(units) == 174
    assert len({product["sample_id"] for product in products}) == 10
    assert len({product["sample_id"] for product in risk_fact_products}) == 23
    assert sum(
        len(_mapping(product.get("risk_facts"), "风险事实"))
        for product in risk_fact_products
    ) == 115
    assert all(
        set(_mapping(product.get("risk_facts"), "风险事实"))
        == EXPECTED_RISK_FACT_FIELDS
        for product in risk_fact_products
    )
    assert all(
        _text(_mapping(record, "风险事实记录").get("evidence_source"))
        and _text(_mapping(record, "风险事实记录").get("evidence_text"))
        for product in risk_fact_products
        for record in _mapping(product.get("risk_facts"), "风险事实").values()
    )
    status_counts: Counter[str] = Counter()
    for product in products:
        tags = _mapping(product.get("product_tags"), "产品标签")
        risk_facts = _mapping(product.get("risk_facts"), "风险事实")
        applicability = _mapping(product.get("applicability"), "适用性矩阵")
        assert len(tags) == 22
        assert len(risk_facts) == 5
        assert set(applicability) == set(units)
        status_counts.update(
            _text(_expected_result(result).get("status"))
            for result in applicability.values()
        )
    assert status_counts == ACCEPTED_COUNTS


def test_v7_hermetic_applicability_matches_signed_oracle(
    baseline: Mapping[str, object],
) -> None:
    units = _baseline_units(baseline)
    differences: list[str] = []
    for product in _baseline_products(baseline):
        sample_id = _text(product.get("sample_id"))
        product_tags = ProductTags.from_dict(
            _mapping(product.get("product_tags"), "冻结产品标签")
        )
        expected_by_unit = _mapping(product.get("applicability"), "适用性矩阵")
        for unit_id, expected_value in expected_by_unit.items():
            unit = units[unit_id]
            regulation = RegulationApplicability.from_metadata(
                _mapping(unit.get("metadata"), "法规适用性元数据")
            )
            actual = match_regulation_applicability(product_tags, regulation)
            expected = _expected_result(expected_value)
            expected_state = (
                _text(expected.get("status")),
                _list_of_text(expected.get("excluded_by"), "排除维度"),
                _list_of_text(
                    expected.get("indeterminate_dimensions"),
                    "不确定维度",
                ),
                _text(expected.get("reason_text")),
            )
            actual_state = (
                actual.status.value,
                actual.excluded_by,
                actual.indeterminate_dimensions,
                "；".join(actual.reasons),
            )
            if actual_state != expected_state:
                differences.append(
                    f"{sample_id} | {unit_id} | {unit['law_name']} "
                    f"{unit['article_number']} | expected={expected_state} | "
                    f"actual={actual_state}"
                )
    assert not differences, "\n".join(differences[:20])


@pytest.fixture(scope="module")
def parsed_products(
    baseline: Mapping[str, object],
) -> dict[str, AuditDocument]:
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    parsed: dict[str, AuditDocument] = {}
    for product in _baseline_risk_fact_products(baseline):
        sample_id = _text(product.get("sample_id"))
        source = PRODUCTS_DIR / _text(product.get("file_name"))
        assert source.is_file(), f"验收产品缺失: {source.name}"
        assert _sha256(source) == product["file_sha256"], f"验收产品已变化: {source.name}"
        parsed[sample_id] = parse_product_document(str(source))
    return parsed


def test_all_real_products_match_signed_risk_facts(
    baseline: Mapping[str, object],
    parsed_products: dict[str, AuditDocument],
) -> None:
    differences: list[str] = []
    for product in _baseline_risk_fact_products(baseline):
        sample_id = _text(product.get("sample_id"))
        tags = parsed_products[sample_id].product_tags
        actual = tags.to_dict()
        expected = _mapping(product.get("risk_facts"), "冻结风险事实")
        for field_name, expected_record_value in expected.items():
            expected_record = _mapping(expected_record_value, "冻结风险事实记录")
            expected_value = {
                "true": True,
                "false": False,
                "unknown": None,
            }[_text(expected_record.get("value"))]
            actual_evidence = next(
                (item for item in tags.evidence if item.field_name == field_name),
                None,
            )
            expected_evidence = (
                _text(expected_record.get("evidence_source")),
                _text(expected_record.get("evidence_text")),
                expected_record.get("confidence"),
            )
            actual_evidence_state = (
                _text(actual_evidence.source) if actual_evidence else "",
                _text(actual_evidence.evidence) if actual_evidence else "",
                actual_evidence.confidence if actual_evidence else None,
            )
            if (
                actual.get(field_name) == expected_value
                and actual_evidence_state == expected_evidence
            ):
                continue
            differences.append(
                f"{sample_id}.{field_name}: expected={expected_value!r}, "
                f"actual={actual.get(field_name)!r}, "
                f"expected_evidence={expected_evidence!r}, "
                f"actual_evidence={actual_evidence_state!r}"
            )
    assert not differences, "\n".join(differences[:20])


def test_real_products_match_signed_product_tags(
    baseline: Mapping[str, object],
    parsed_products: dict[str, AuditDocument],
) -> None:
    differences: list[str] = []
    for product in _baseline_products(baseline):
        sample_id = _text(product.get("sample_id"))
        tags = parsed_products[sample_id].product_tags
        actual = tags.to_dict()
        expected = _mapping(product.get("product_tags"), "冻结产品标签")
        for field_name, expected_value in expected.items():
            if actual.get(field_name) == expected_value:
                continue
            evidence = tuple(
                item.evidence for item in tags.evidence if item.field_name == field_name
            )
            differences.append(
                f"{sample_id}.{field_name}: expected={expected_value!r}, "
                f"actual={actual.get(field_name)!r}, evidence={evidence!r}"
            )
    assert not differences, "\n".join(differences[:20])


def test_real_products_and_v5_catalog_match_signed_applicability(
    baseline: Mapping[str, object],
    parsed_products: dict[str, AuditDocument],
) -> None:
    if not KB_LANCEDB_PATH.exists():
        pytest.skip(f"知识库索引不存在: {KB_LANCEDB_PATH}")
    catalog = load_catalog_rows(KB_LANCEDB_PATH)
    baseline_units = _baseline_units(baseline)
    differences: list[str] = []
    for product in _baseline_products(baseline):
        sample_id = _text(product.get("sample_id"))
        candidates: list[dict[str, object]] = []
        for row in catalog:
            candidate: dict[str, object] = dict(row)
            result = match_regulation_applicability(
                parsed_products[sample_id].product_tags,
                RegulationApplicability.from_metadata(
                    _mapping(row.get("metadata"), "法规元数据")
                ),
            )
            candidate.update({
                "applicability_status": result.status.value,
                "matched_dimensions": result.matched_dimensions,
                "indeterminate_dimensions": result.indeterminate_dimensions,
                "excluded_by": result.excluded_by,
                "applicability_reasons": result.reasons,
            })
            candidates.append(candidate)
        actual_units = {
            unit.unit_id: unit
            for unit in aggregate_regulation_units(candidates, "v5").units
        }
        expected_by_unit = _mapping(product.get("applicability"), "适用性矩阵")
        missing = set(expected_by_unit).difference(actual_units)
        added = set(actual_units).difference(expected_by_unit)
        if missing or added:
            differences.append(
                f"{sample_id}: removed={sorted(missing)}, added={sorted(added)}"
            )
        for unit_id in set(expected_by_unit).intersection(actual_units):
            unit = actual_units[unit_id]
            locator = baseline_units[unit_id]
            expected_identity = (
                _text(locator.get("source_file")),
                _text(locator.get("law_name")),
                _text(locator.get("article_number")),
                _text(locator.get("content_sha256")),
            )
            actual_identity = (
                unit.source_file,
                unit.law_name,
                unit.article_number,
                hashlib.sha256(unit.content.strip().encode("utf-8")).hexdigest(),
            )
            if actual_identity != expected_identity:
                differences.append(
                    f"{sample_id} | {unit_id} | identity expected="
                    f"{expected_identity} | actual={actual_identity}"
                )
            expected = _expected_result(expected_by_unit[unit_id])
            expected_state = (
                _text(expected.get("status")),
                _list_of_text(expected.get("excluded_by"), "排除维度"),
                _list_of_text(
                    expected.get("indeterminate_dimensions"),
                    "不确定维度",
                ),
                _text(expected.get("reason_text")),
            )
            actual_state = (
                unit.applicability_status,
                unit.excluded_by,
                unit.indeterminate_dimensions,
                "；".join(unit.applicability_reasons),
            )
            if actual_state != expected_state:
                differences.append(
                    f"{sample_id} | {unit_id} | {locator.get('law_name', '')} "
                    f"{locator.get('article_number', '')} | expected={expected_state} | "
                    f"actual={actual_state}"
                )
    assert not differences, "\n".join(differences[:20])
