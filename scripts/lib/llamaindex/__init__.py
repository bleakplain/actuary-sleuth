#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 集成模块 - 用于法规检索增强生成

提供:
- 文档加载和解析
- 向量索引创建和管理
- RAG 查询引擎

使用示例:
    from lib.llamaindex import RegulationRAG, get_rag_engine

    # 创建 RAG 引擎
    rag = get_rag_engine(data_dir="./references")
    rag.create_index()
    result = rag.query("健康保险产品的等待期有什么规定？")
"""

from .rag_engine import RegulationRAG, get_rag_engine
from .document_loader import RegulationDocumentLoader
from .config import LlamaIndexConfig

__all__ = [
    'RegulationRAG',
    'get_rag_engine',
    'RegulationDocumentLoader',
    'LlamaIndexConfig',
]

__version__ = '0.1.0'
