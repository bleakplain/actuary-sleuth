#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险法规检索增强生成 (RAG) 引擎模块

提供保险法规的智能检索和问答功能，支持多种使用场景：

## 数据导入
    from lib.rag_engine import RegulationDataImporter

    importer = RegulationDataImporter()
    importer.import_all(force_rebuild=True)

## 审计查询
    from lib.rag_engine import AuditQueryEngine

    audit_engine = AuditQueryEngine()
    audit_engine.initialize()
    regulations = audit_engine.search_regulations("健康保险等待期")

## 用户问答
    from lib.rag_engine import UserQAEngine

    qa_engine = UserQAEngine()
    qa_engine.initialize()
    result = qa_engine.ask("健康保险产品的等待期有什么规定？")
    print(result['answer'])
"""

# 配置
from .config import RAGConfig, get_config

# 文档解析
from .document_parser import RegulationDocumentParser

# 索引管理
from .index_manager import VectorIndexManager

# 数据导入
from .data_importer import RegulationDataImporter

# 审计查询
from .audit_query import AuditQueryEngine

# 用户问答
from .user_qa import UserQAEngine

__all__ = [
    # 配置
    'RAGConfig',
    'get_config',

    # 核心组件
    'RegulationDocumentParser',
    'VectorIndexManager',

    # 使用场景
    'RegulationDataImporter',
    'AuditQueryEngine',
    'UserQAEngine',
]

__version__ = '0.1.0'
