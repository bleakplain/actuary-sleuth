#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库文档解析模块"""
from __future__ import annotations

from .md_parser import MdParser

__all__ = ['MdParser', 'parse_knowledge_base']


def parse_knowledge_base(
    regulations_dir: str,
    file_pattern: str = "**/*.md",
) -> list:
    """解析知识库目录中的所有 Markdown 文件

    Args:
        regulations_dir: 法规文档目录路径或单个 Markdown 文件路径
        file_pattern: 文件匹配模式

    Returns:
        TextNode 列表
    """
    from pathlib import Path
    from llama_index.core import Document
    from ..models import DocumentParseError

    parser = MdParser()
    regulations_path = Path(regulations_dir)

    if not regulations_path.exists():
        raise DocumentParseError("文件不存在", regulations_dir)

    if regulations_path.is_file():
        if regulations_path.suffix.lower() != '.md':
            raise DocumentParseError(
                "不支持的文件格式",
                regulations_dir,
                f"仅支持 .md 文件，当前文件: {regulations_path.suffix}"
            )
        md_files = [regulations_path]
    else:
        md_files = sorted(regulations_path.glob(file_pattern))

    documents: list = []

    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(md_file, 'r', encoding='gbk') as f:
                text = f.read()

        if text.strip():
            doc = Document(text=text, metadata={'file_name': md_file.name})
            documents.append(doc)

    return parser.chunk(documents)
