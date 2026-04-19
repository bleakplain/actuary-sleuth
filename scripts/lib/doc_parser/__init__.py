#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一文档解析器"""
from __future__ import annotations

from .models import (
    Clause,
    PremiumTable,
    DocumentSection,
    AuditDocument,
    DocumentParseError,
    SectionType,
)
from .kb import parse_knowledge_base
from .pd import parse_product_document

__all__ = [
    'Clause', 'PremiumTable', 'DocumentSection', 'AuditDocument',
    'DocumentParseError', 'SectionType',
    'parse_knowledge_base', 'parse_product_document',
]
