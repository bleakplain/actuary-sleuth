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

## 架构

    RAGEngine (统一引擎)
    ├── llm_provider: 策略模式，支持不同场景
    │   ├── create_qa_engine() → glm-4-flash (快速响应)
    │   └── create_audit_engine() → glm-4-plus (高质量分析)
    ├── VectorIndexManager: 向量索引管理
    └── KBDataImporter: 数据导入编排
"""
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from .config import RAGConfig, get_config, HybridQueryConfig
from .exceptions import RAGEngineError, EngineInitializationError, RetrievalError
from .query_preprocessor import QueryPreprocessor, PreprocessedQuery
from .reranker import LLMReranker, RerankConfig
from .attribution import parse_citations, AttributionResult, Citation

# Optional RAG engine components (require llama_index)
try:
    from .rag_engine import RAGEngine, create_qa_engine, create_audit_engine
    from .index_manager import VectorIndexManager
    from .data_importer import KBDataImporter
    from .retrieval import hybrid_search, vector_search
    from .fusion import reciprocal_rank_fusion
    from .bm25_index import BM25Index
    from .kb_chunker import KBChecklistChunker
    from .evaluator import RetrievalEvaluator, GenerationEvaluator, RAGEvalReport
    from .eval_dataset import EvalSample, QuestionType, load_eval_dataset, create_default_eval_dataset, save_eval_dataset, DEFAULT_DATASET_PATH
    from .quality_detector import detect_quality, compute_retrieval_relevance, compute_info_completeness
    from .badcase_classifier import classify_badcase, assess_compliance_risk

    _has_rag = True
except ImportError:
    RAGEngine = None
    create_qa_engine = None
    create_audit_engine = None
    VectorIndexManager = None
    KBDataImporter = None
    hybrid_search = None
    vector_search = None
    reciprocal_rank_fusion = None
    BM25Index = None
    KBChecklistChunker = None
    RetrievalEvaluator = None
    GenerationEvaluator = None
    RAGEvalReport = None
    EvalSample = None
    QuestionType = None
    load_eval_dataset = None
    create_default_eval_dataset = None
    save_eval_dataset = None
    DEFAULT_DATASET_PATH = None
    detect_quality = None
    compute_retrieval_relevance = None
    compute_info_completeness = None
    classify_badcase = None
    assess_compliance_risk = None
    _has_rag = False

__all__ = [
    'RAGConfig',
    'get_config',
    'HybridQueryConfig',
    'RAGEngineError',
    'EngineInitializationError',
    'RetrievalError',
    'QueryPreprocessor',
    'PreprocessedQuery',
    'LLMReranker',
    'RerankConfig',
    'parse_citations',
    'AttributionResult',
    'Citation',
    'RAGEngine',
    'create_qa_engine',
    'create_audit_engine',
    'VectorIndexManager',
    'KBDataImporter',
    'hybrid_search',
    'vector_search',
    'reciprocal_rank_fusion',
    'BM25Index',
    'KBChecklistChunker',
    'RetrievalEvaluator',
    'GenerationEvaluator',
    'RAGEvalReport',
    'EvalSample',
    'QuestionType',
    'load_eval_dataset',
    'create_default_eval_dataset',
    'save_eval_dataset',
    'DEFAULT_DATASET_PATH',
    'detect_quality',
    'compute_retrieval_relevance',
    'compute_info_completeness',
    'classify_badcase',
    'assess_compliance_risk',
]

__version__ = '0.1.0'
