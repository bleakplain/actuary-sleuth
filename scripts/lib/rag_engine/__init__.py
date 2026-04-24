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
import logging
import threading
from typing import Optional

from .config import RAGConfig, get_config, config_to_dict, RetrievalConfig, RerankConfig, GenerationConfig
from .exceptions import RAGEngineError, EngineInitializationError, RetrievalError
from .query_preprocessor import QueryPreprocessor, PreprocessedQuery
from .reranker_base import BaseReranker
from .llm_reranker import LLMReranker
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
from .quality_checker import QualityChecker, QualityReport, QualityIssue
from .kb_manager import KBManager

_logger = logging.getLogger(__name__)

# ===== 引擎单例管理 =====

_engine: Optional[RAGEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> Optional[RAGEngine]:
    """获取 RAG 引擎实例"""
    return _engine


def init_engine(config: Optional[RAGConfig] = None) -> Optional[RAGEngine]:
    """初始化 RAG 引擎（应用启动时调用一次）

    Args:
        config: RAG 配置，默认从 KBManager 加载

    Returns:
        初始化后的引擎实例，失败返回 None
    """
    global _engine

    with _engine_lock:
        if _engine is not None:
            return _engine

        try:
            if config is None:
                kb_mgr = KBManager()
                config = kb_mgr.load_kb()

            _engine = create_qa_engine(config)
            if _engine.initialize():
                return _engine
            else:
                _engine = None
                return None
        except Exception as e:
            _logger.warning(f"RAG 引擎初始化失败: {e}")
            return None


def reset_engine() -> None:
    """重置引擎（测试用）"""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.cleanup()
        _engine = None

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
    'CrossEncoderReranker',
    'parse_citations',
    'AttributionResult',
    'Citation',
    'RAGEngine',
    'create_qa_engine',
    'get_engine',
    'init_engine',
    'reset_engine',
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
    'QualityChecker',
    'QualityReport',
    'QualityIssue',
]

__version__ = '0.1.0'
