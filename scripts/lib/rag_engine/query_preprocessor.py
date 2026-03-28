#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query 预处理器

对用户 query 进行预处理，提升检索召回质量：
1. 术语归一化：口语化表达 -> 标准术语
2. Query 扩写：基于同义词生成变体 query
"""
import json
import logging
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SYNONYMS_FILE = Path(__file__).parent / 'data' / 'synonyms.json'


def _load_synonyms() -> Dict[str, List[str]]:
    if _SYNONYMS_FILE.exists():
        with open(_SYNONYMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    logger.warning(f"同义词文件不存在: {_SYNONYMS_FILE}")
    return {}


_INSURANCE_SYNONYMS: Dict[str, List[str]] = _load_synonyms()


@dataclass(frozen=True)
class PreprocessedQuery:
    original: str
    normalized: str
    expanded: List[str]
    did_expand: bool


class QueryPreprocessor:

    def __init__(self):
        self._synonym_index = self._build_synonym_index()
        self._sorted_synonym_terms = sorted(self._synonym_index.keys(), key=len, reverse=True)
        self._sorted_standard_terms = sorted(_INSURANCE_SYNONYMS.keys(), key=len, reverse=True)

    def _build_synonym_index(self) -> Dict[str, str]:
        index: Dict[str, str] = {}
        for standard, variants in _INSURANCE_SYNONYMS.items():
            index[standard] = standard
            for variant in variants:
                index[variant] = standard
        return index

    def preprocess(self, query: str) -> PreprocessedQuery:
        normalized = self._normalize(query)
        expanded = self._expand(normalized)
        seen = {normalized}
        unique_expanded = [normalized]
        for q in expanded:
            if q not in seen:
                unique_expanded.append(q)
                seen.add(q)

        return PreprocessedQuery(
            original=query,
            normalized=normalized,
            expanded=unique_expanded,
            did_expand=len(unique_expanded) > 1,
        )

    def _normalize(self, query: str) -> str:
        result = query
        for term in self._sorted_synonym_terms:
            if term in result:
                standard = self._synonym_index[term]
                if term != standard:
                    result = result.replace(term, standard)
        return result

    def _expand(self, query: str) -> List[str]:
        variants = [query]

        matched_terms: List[str] = []
        for term in self._sorted_standard_terms:
            if term in query:
                matched_terms.append(term)

        for term in matched_terms:
            for synonym in _INSURANCE_SYNONYMS[term]:
                variant = query.replace(term, synonym)
                if variant != query:
                    variants.append(variant)

        return variants
