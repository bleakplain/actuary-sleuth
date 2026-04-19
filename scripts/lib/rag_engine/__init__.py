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

## 架构

    RAGEngine (统一引擎)
    ├── llm_provider: 策略模式，支持不同场景
    │   └── create_qa_engine() → glm-4-flash (快速响应)
    ├── VectorIndexManager: 向量索引管理
    └── KnowledgeBuilder: 知识库构建编排
"""
from .config import RAGConfig, get_config, config_to_dict, RetrievalConfig, RerankConfig, GenerationConfig
from .exceptions import RAGEngineError, EngineInitializationError, RetrievalError
from .query_preprocessor import QueryPreprocessor, PreprocessedQuery
from .reranker_base import BaseReranker
from .llm_reranker import LLMReranker
from .gguf_reranker_adapter import GGUFReranker
from .cross_encoder_reranker import CrossEncoderReranker
from .attribution import parse_citations, AttributionResult, Citation

from .rag_engine import RAGEngine, create_qa_engine
from .index_manager import VectorIndexManager
from .builder import KnowledgeBuilder
from .retrieval import hybrid_search, vector_search
from .fusion import reciprocal_rank_fusion
from .bm25_index import BM25Index
from .evaluator import RetrievalEvaluator, GenerationEvaluator, RAGEvalReport
from .eval_dataset import EvalSample, QuestionType, load_eval_dataset, save_eval_dataset
from .dataset_validator import validate_dataset, QualityAuditReport
from .eval_rating import interpret_metric, generate_eval_summary
from .quality_detector import detect_quality, compute_retrieval_relevance, compute_info_completeness
from .badcase_classifier import classify_badcase, assess_compliance_risk

__all__ = [
    'RAGConfig',
    'get_config',
    'config_to_dict',
    'RetrievalConfig',
    'RerankConfig',
    'GenerationConfig',
    'RAGEngineError',
    'EngineInitializationError',
    'RetrievalError',
    'QueryPreprocessor',
    'PreprocessedQuery',
    'BaseReranker',
    'LLMReranker',
    'GGUFReranker',
    'CrossEncoderReranker',
    'parse_citations',
    'AttributionResult',
    'Citation',
    'RAGEngine',
    'create_qa_engine',
    'VectorIndexManager',
    'KnowledgeBuilder',
    'hybrid_search',
    'vector_search',
    'reciprocal_rank_fusion',
    'BM25Index',
    'RetrievalEvaluator',
    'GenerationEvaluator',
    'RAGEvalReport',
    'EvalSample',
    'QuestionType',
    'load_eval_dataset',
    'save_eval_dataset',
    'detect_quality',
    'compute_retrieval_relevance',
    'compute_info_completeness',
    'classify_badcase',
    'assess_compliance_risk',
    'validate_dataset',
    'QualityAuditReport',
    'interpret_metric',
    'generate_eval_summary',
]

__version__ = '0.1.0'
