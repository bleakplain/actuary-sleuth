#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文分词工具 - 基于 jieba
"""
import re
from typing import List

import jieba


def tokenize_chinese(text: str) -> List[str]:
    """中文分词

    使用 jieba 进行中文分词，过滤标点和空白。

    Args:
        text: 输入文本

    Returns:
        List[str]: 分词列表
    """
    if not text or not text.strip():
        return []

    tokens = jieba.lcut(text)
    # 过滤纯空白和纯标点
    return [t.strip() for t in tokens if t.strip() and re.search(r'[\w]', t)]
