#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中文分词工具
"""
import re
from typing import List


def tokenize_chinese(text: str) -> List[str]:
    """
    中文分词

    提取中文词汇和英文/数字序列

    Args:
        text: 输入文本

    Returns:
        List[str]: 分词列表
    """
    return re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text.lower())
