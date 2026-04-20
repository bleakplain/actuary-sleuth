#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析"""
from __future__ import annotations

__all__ = ['parse_product_document']


def __getattr__(name: str):
    """延迟导入，避免缺少 docx/pdfplumber 依赖时报错。"""
    if name == 'parse_product_document':
        from .parser import parse_product_document
        return parse_product_document
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
