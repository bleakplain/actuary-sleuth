#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文分词工具 - 基于 jieba

支持保险领域自定义词典和停用词过滤。
停用词从 scripts/lib/rag_engine/data/stopwords.txt 加载，回退到内置最小集。
"""
import re
import logging
from pathlib import Path
from typing import List, Optional, Set

import jieba

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r'[\w]')

_SINGLE_CHAR_WHITELIST: Set[str] = {'险', '保', '赔', '费', '额', '期', '率', '金'}

_BUILTIN_STOPWORDS: Set[str] = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些', '什么',
    '怎么', '如何', '可以', '应该', '需要', '以及', '或者', '还是',
}

_DICT_LOADED = False
_STOPWORDS: Optional[Set[str]] = None


def _load_stopwords() -> Set[str]:
    global _STOPWORDS
    if _STOPWORDS is not None:
        return _STOPWORDS
    stopwords_path = Path(__file__).parent / 'data' / 'stopwords.txt'
    if stopwords_path.exists():
        with open(stopwords_path, 'r', encoding='utf-8') as f:
            _STOPWORDS = {line.strip() for line in f if line.strip()}
    else:
        _STOPWORDS = _BUILTIN_STOPWORDS
    return _STOPWORDS


def _load_custom_dict():
    global _DICT_LOADED
    if _DICT_LOADED:
        return

    dict_path = Path(__file__).parent / 'data' / 'insurance_dict.txt'
    if dict_path.exists():
        jieba.load_userdict(str(dict_path))
        logger.info(f"已加载自定义词典: {dict_path}")
    else:
        logger.warning(f"自定义词典不存在: {dict_path}")

    _DICT_LOADED = True


def tokenize_chinese(text: str) -> List[str]:
    """中文分词"""
    if not text or not text.strip():
        return []

    _load_custom_dict()
    stopwords = _load_stopwords()

    tokens = jieba.lcut(text)
    result = []
    for t in tokens:
        t = t.strip()
        if not t or not _WORD_RE.search(t):
            continue
        if t in stopwords:
            continue
        if len(t) == 1 and t not in _SINGLE_CHAR_WHITELIST:
            continue
        result.append(t)

    return result
