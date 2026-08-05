import json
import re
from pathlib import Path

import pytest

from extract_critical_illness_definitions import (
    _DISEASE_HEADING,
    _DISEASE_SUBSECTION_HEADING,
    _extract_sections,
)
from lib.doc_parser.pd.critical_illness_definitions import (
    find_critical_illness_term,
    list_critical_illness_terms,
)


_DATA_PATH = (
    Path(__file__).parents[4]
    / "lib"
    / "doc_parser"
    / "pd"
    / "data"
    / "critical_illness_definitions_2020.json"
)


def test_definition_library_contains_all_standard_diseases():
    canonical_codes = {code for _, code, _ in list_critical_illness_terms()}

    assert canonical_codes == {
        *(f"3.1.1.{number}" for number in range(1, 29)),
        *(f"3.1.2.{number}" for number in range(1, 4)),
    }


def test_definition_library_matches_explicit_alternate_name():
    match = find_critical_illness_term("已经实施冠状动脉旁路移植术")

    assert match is not None
    assert match.code == "3.1.1.5"
    assert match.canonical_name == "冠状动脉搭桥术（或称冠状动脉旁路移植术）"


def test_definition_library_does_not_embed_subsection_headings():
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))

    assert all(
        re.search(r"(?m)^3\.1\.[12](?:\s|$)", item["definition"]) is None
        for item in payload["diseases"]
    )


def test_definition_extractor_stops_at_disease_subsection_heading():
    text = """3.1.1.28 严重溃疡性结肠炎
重度疾病定义。
3.1.2 轻度疾病
3.1.2.1 恶性肿瘤——轻度
轻度疾病定义。
3.2 重大疾病保险的除外责任
"""

    sections = _extract_sections(
        text,
        _DISEASE_HEADING,
        "3.2 重大疾病保险的除外责任",
        _DISEASE_SUBSECTION_HEADING,
    )

    assert sections[0]["definition"] == "重度疾病定义。"
    assert sections[1]["definition"] == "轻度疾病定义。"


@pytest.mark.parametrize(
    ("text", "expected_code"),
    (
        ("重大器官移植术", "3.1.1.4"),
        ("造血干细胞移植术", "3.1.1.4"),
        ("急性重症肝炎", "3.1.1.8"),
        ("亚急性重症肝炎", "3.1.1.8"),
        ("严重脑炎后遗症", "3.1.1.11"),
        ("严重脑膜炎后遗症", "3.1.1.11"),
        ("恶性肿瘤—重度", "3.1.1.1"),
    ),
)
def test_definition_library_matches_controlled_name_variants(
    text: str,
    expected_code: str,
) -> None:
    match = find_critical_illness_term(text)

    assert match is not None
    assert match.code == expected_code
