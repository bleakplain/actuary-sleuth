"""加载并匹配 2020 版重大疾病标准名称。

运行时只读取预先审核的结构化定义库，不重复解析 PDF；这样产品事实判断
既快，也不会因 PDF 解析器或排版差异而随请求漂移。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple


_DATA_PATH = Path(__file__).with_name("data") / "critical_illness_definitions_2020.json"


@dataclass(frozen=True)
class CriticalIllnessTermMatch:
    code: str
    canonical_name: str
    matched_term: str


@lru_cache(maxsize=1)
def list_critical_illness_terms() -> Tuple[Tuple[str, str, str], ...]:
    """返回 ``(匹配词, 标准编号, 标准名称)``，长词优先避免短名称抢占。"""
    with _DATA_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    terms = {
        (term, disease["code"], disease["name"])
        for disease in payload["diseases"]
        for term in disease["match_terms"]
        if term
    }
    return tuple(sorted(terms, key=lambda item: (-len(item[0]), item[1], item[0])))


def find_critical_illness_term(text: str) -> Optional[CriticalIllnessTermMatch]:
    """查找“重大疾病”总称或规范列明的任一疾病名称。"""
    if "重大疾病" in text:
        return CriticalIllnessTermMatch("general", "重大疾病", "重大疾病")
    for term, code, canonical_name in list_critical_illness_terms():
        if term in text:
            return CriticalIllnessTermMatch(code, canonical_name, term)
    return None
