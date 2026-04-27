#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文档解析器

公共接口：
- parse_knowledge_base: Markdown → List[TextNode]
- parse_product_document: Word/PDF → AuditDocument

内部实现 (不对外暴露)：
- kb.MdParser: Markdown 解析器
- kb.converter: Excel → Markdown 转换
"""
from __future__ import annotations

from .models import (
    Clause,
    DataTable,
    DocumentSection,
    AuditDocument,
    DocumentParseError,
    SectionType,
    DocumentMeta,
    TableType,
)
from .kb import parse_knowledge_base

__all__ = [
    # 数据模型
    'Clause', 'DataTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType', 'DocumentMeta', 'TableType',
    # 公共接口
    'parse_knowledge_base',
    'parse_product_document',
]


def __getattr__(name: str):
    """延迟导入 parse_product_document，避免在缺少 docx 依赖时报错。"""
    if name == 'parse_product_document':
        from .pd import parse_product_document
        return parse_product_document
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
