"""把协会 2020 版重疾定义 PDF 转成受控 JSON 定义库。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional


_DISEASE_HEADING = re.compile(r"(?m)^3\.1\.(?P<section>[12])\.(?P<number>\d+)\s+(?P<name>.+)$")
_DISEASE_SUBSECTION_HEADING = re.compile(r"(?m)^3\.1\.[12]\s+.+$")
_TERM_HEADING = re.compile(r"(?m)^3\.3\.(?P<number>\d+)\s+(?P<name>.+)$")
_PAGE_FOOTER = re.compile(r"(?m)^\s*-\d+-\s*$")


def _extract_text(source: Path) -> str:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(source), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return _PAGE_FOOTER.sub("", completed.stdout.replace("\f", "\n"))


def _normalize_definition(raw: str) -> str:
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", raw.strip()):
        joined = re.sub(r"\s+", "", paragraph)
        if joined:
            paragraphs.append(joined)
    return "\n".join(paragraphs)


def _definition_metadata(definition: str) -> Dict[str, object]:
    paragraphs = definition.splitlines()
    note_indexes = [
        index for index, paragraph in enumerate(paragraphs)
        if paragraph.startswith("注：")
    ]
    exclusion_start = next((
        index for index, paragraph in enumerate(paragraphs)
        if "不在保障范围内" in paragraph
    ), None)
    exclusion_end = min(note_indexes) if note_indexes else len(paragraphs)
    exclusions = (
        paragraphs[exclusion_start:exclusion_end]
        if exclusion_start is not None
        else []
    )
    return {
        "definition": definition,
        "normalized_definition": re.sub(
            r"\s+", "", unicodedata.normalize("NFKC", definition),
        ),
        "exclusions": exclusions,
        "notes": [paragraphs[index] for index in note_indexes],
    }


def _match_terms(name: str) -> List[str]:
    terms = {name}
    if "（或称" in name:
        primary, alternate = name.split("（或称", 1)
        terms.update({primary, alternate.rstrip("）")})
    elif "或" in name:
        terms.update(part for part in name.split("或") if part)
    terms.update(
        term.replace("——", "—")
        for term in tuple(terms)
        if "——" in term
    )
    return sorted(terms, key=lambda item: (-len(item), item))


def _extract_sections(
    text: str,
    heading_pattern: re.Pattern[str],
    end_marker: str,
    subsection_heading_pattern: Optional[re.Pattern[str]] = None,
) -> List[Dict[str, object]]:
    matches = list(heading_pattern.finditer(text))
    sections: List[Dict[str, object]] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else text.index(end_marker, match.end())
        )
        if subsection_heading_pattern is not None:
            subsection_heading = subsection_heading_pattern.search(
                text,
                match.end(),
                end,
            )
            if subsection_heading is not None:
                end = subsection_heading.start()
        name = match.group("name").strip()
        definition = _normalize_definition(text[match.end():end])
        sections.append({
            "code": match.group(0).split(maxsplit=1)[0],
            "name": name,
            **_definition_metadata(definition),
        })
    return sections


def build_definition_library(source: Path) -> Dict[str, object]:
    text = _extract_text(source)
    diseases = _extract_sections(
        text,
        _DISEASE_HEADING,
        "3.2 重大疾病保险的除外责任",
        _DISEASE_SUBSECTION_HEADING,
    )
    terms = _extract_sections(
        text,
        _TERM_HEADING,
        "4 重大疾病保险宣传材料的相关规定",
    )
    if [item["code"] for item in diseases] != [
        *(f"3.1.1.{number}" for number in range(1, 29)),
        *(f"3.1.2.{number}" for number in range(1, 4)),
    ]:
        raise ValueError("疾病定义编号不连续或数量不是 31 项")
    if [item["code"] for item in terms] != [f"3.3.{number}" for number in range(1, 15)]:
        raise ValueError("术语释义编号不连续或数量不是 14 项")
    for disease in diseases:
        disease["severity"] = "severe" if str(disease["code"]).startswith("3.1.1.") else "mild"
        disease["match_terms"] = _match_terms(str(disease["name"]))
    return {
        "schema_version": "1.0",
        "definition_version": "2020-revision",
        "source_title": "重大疾病保险的疾病定义使用规范（2020年修订版）",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "disease_count": len(diseases),
        "terminology_count": len(terms),
        "diseases": diseases,
        "terminology": terms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build_definition_library(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
