#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器模块

包含各种提取器实现，每个提取器使用不同的方法提取文档信息。
"""

from .base import Extractor, ExtractionResult

__all__ = [
    'Extractor',
    'ExtractionResult',
]
