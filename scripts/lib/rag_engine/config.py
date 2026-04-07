#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    enable_rerank: bool = True
    rerank_top_k: int = 5
    reranker_type: str = "gguf"
    max_chunks_per_article: int = 3
    min_rrf_score: float = 0.0
    rerank_min_score: float = 0.0

    _VALID_RERANKER_TYPES = {"llm", "gguf", "none"}

    def __post_init__(self):
        if self.vector_top_k < 1:
            raise ValueError(f"vector_top_k must be >= 1, got {self.vector_top_k}")
        if self.keyword_top_k < 1:
            raise ValueError(f"keyword_top_k must be >= 1, got {self.keyword_top_k}")
        if self.rrf_k < 1:
            raise ValueError(f"rrf_k must be >= 1, got {self.rrf_k}")
        if self.rerank_top_k < 1:
            raise ValueError(f"rerank_top_k must be >= 1, got {self.rerank_top_k}")
        if self.reranker_type not in self._VALID_RERANKER_TYPES:
            raise ValueError(
                f"reranker_type must be one of {self._VALID_RERANKER_TYPES}, "
                f"got {self.reranker_type}"
            )
        if not 0.0 <= self.rerank_min_score <= 1.0:
            raise ValueError(
                f"rerank_min_score must be between 0.0 and 1.0, "
                f"got {self.rerank_min_score}"
            )


@dataclass
class RAGConfig:
    """法规 RAG 引擎配置"""

    # 数据目录配置（绝对路径，__post_init__ 中解析）
    regulations_dir: str = ""
    vector_db_path: Optional[str] = None

    # 检索配置
    top_k_results: int = 5
    enable_streaming: bool = False
    hybrid_config: Optional[HybridQueryConfig] = None

    # 生成配置
    max_context_chars: int = 12000
    enable_faithfulness: bool = False

    # 向量数据库配置
    collection_name: str = "regulations_vectors"

    def __post_init__(self):
        from lib.config import get_regulations_dir

        # regulations_dir：参数 > settings.json > 默认
        if not self.regulations_dir:
            self.regulations_dir = get_regulations_dir()

        if self.max_context_chars < 1:
            raise ValueError(f"max_context_chars must be >= 1, got {self.max_context_chars}")

        if self.hybrid_config is None:
            self.hybrid_config = HybridQueryConfig()


def get_config(**kwargs) -> RAGConfig:
    """
    获取配置实例

    Args:
        **kwargs: 覆盖默认配置的参数

    Returns:
        RAGConfig: 配置实例
    """
    config = RAGConfig()
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config
