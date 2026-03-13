#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险法规检索增强生成 (RAG) 引擎模块

提供保险法规的智能检索和问答功能。

## 快速开始

### 用户问答
    from lib.rag_engine import create_qa_engine

    qa = create_qa_engine()
    result = qa.ask("健康保险产品的等待期有什么规定？")
    print(result['answer'])

### 审计查询
    from lib.rag_engine import create_audit_engine

    audit = create_audit_engine()
    regulations = audit.search("健康保险等待期", top_k=5)

### 数据导入
    from lib.rag_engine import RegulationDataImporter

    importer = RegulationDataImporter()
    importer.import_all(force_rebuild=True)

## 架构

    RAGEngine (统一引擎)
    ├── llm_provider: 策略模式，支持不同场景
    │   ├── create_qa_engine() → glm-4-flash (快速响应)
    │   └── create_audit_engine() → glm-4-plus (高质量分析)
    ├── VectorIndexManager: 向量索引管理
    ├── RegulationDocParser: 法规文档解析
    └── RegulationDataImporter: 数据导入编排
"""
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from .config import RAGConfig, get_config
from .rag_engine import RAGEngine, create_qa_engine, create_audit_engine
from .doc_parser import RegulationDocParser
from .index_manager import VectorIndexManager
from .data_importer import RegulationDataImporter

__all__ = [
    'RAGConfig',
    'get_config',
    'RAGEngine',
    'create_qa_engine',
    'create_audit_engine',
    'RegulationDocParser',
    'VectorIndexManager',
    'RegulationDataImporter',
]

__version__ = '0.1.0'
