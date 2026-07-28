#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析编排器"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..models import AuditDocument, DocumentParseError
from .docx_parser import DocxParser
from .legacy_doc_parser import LegacyDocParser
from .pdf_parser import PdfParser


def parse_product_document(
    file_path: str,
    *,
    original_file_name: Optional[str] = None,
    user_product_name: Optional[str] = None,
) -> AuditDocument:
    """解析保险产品文档，根据文件扩展名自动选择解析器。"""
    path = Path(file_path)
    if not path.exists():
        raise DocumentParseError("文件不存在", file_path)

    ext = path.suffix.lower()
    if ext in DocxParser.supported_extensions():
        return DocxParser().parse(
            file_path,
            original_file_name=original_file_name,
            user_product_name=user_product_name,
        )
    if ext in LegacyDocParser.supported_extensions():
        return LegacyDocParser().parse(
            file_path,
            original_file_name=original_file_name,
            user_product_name=user_product_name,
        )
    if ext in PdfParser.supported_extensions():
        return PdfParser().parse(
            file_path,
            original_file_name=original_file_name,
            user_product_name=user_product_name,
        )

    raise DocumentParseError(
        f"不支持的产品文档格式: {ext}",
        file_path,
        "支持的格式: "
        f"{DocxParser.supported_extensions() + LegacyDocParser.supported_extensions() + PdfParser.supported_extensions()}"
    )
