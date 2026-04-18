#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class RetrievalConfig:
    """检索配置（召回 + 融合 + 结果截断）"""
    vector_top_k: int = 20
    keyword_top_k: int = 20
    rrf_k: int = 60
    max_chunks_per_article: int = 3
    min_rrf_score: float = 0.02

    def __post_init__(self):
        if self.vector_top_k < 1:
            raise ValueError(f"vector_top_k must be >= 1, got {self.vector_top_k}")
        if self.keyword_top_k < 1:
            raise ValueError(f"keyword_top_k must be >= 1, got {self.keyword_top_k}")
        if self.rrf_k < 1:
            raise ValueError(f"rrf_k must be >= 1, got {self.rrf_k}")
        if self.max_chunks_per_article < 1:
            raise ValueError(f"max_chunks_per_article must be >= 1, got {self.max_chunks_per_article}")


@dataclass
class RerankConfig:
    """重排序配置"""
    enable_rerank: bool = True
    reranker_type: str = "llm"
    rerank_top_k: int = 5
    rerank_min_score: float = 0.0

    _VALID_RERANKER_TYPES = {"llm", "hf", "none"}

    def __post_init__(self):
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
class GenerationConfig:
    """生成配置"""
    max_context_chars: int = 12000

    def __post_init__(self):
        if self.max_context_chars < 1:
            raise ValueError(f"max_context_chars must be >= 1, got {self.max_context_chars}")


def config_to_dict(retrieval: RetrievalConfig, rerank: RerankConfig,
                   generation: GenerationConfig) -> dict:
    return {
        "retrieval": vars(retrieval),
        "rerank": vars(rerank),
        "generation": vars(generation),
    }


@dataclass
class RAGConfig:
    """法规 RAG 引擎配置"""

    regulations_dir: str = ""
    vector_db_path: Optional[str] = None
    top_k_results: int = 5
    enable_streaming: bool = False
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    rerank: RerankConfig = field(default_factory=RerankConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    collection_name: str = "regulations_vectors"

    def __post_init__(self):
        from lib.config import get_regulations_dir

        if not self.regulations_dir:
            self.regulations_dir = get_regulations_dir()

    def to_dict(self) -> dict:
        return config_to_dict(self.retrieval, self.rerank, self.generation)

    @classmethod
    def from_dict(cls, data: dict) -> 'RAGConfig':
        return cls(
            retrieval=RetrievalConfig(**data.get("retrieval", {})),
            rerank=RerankConfig(**data.get("rerank", {})),
            generation=GenerationConfig(**data.get("generation", {})),
        )


def get_config(**kwargs) -> RAGConfig:
    """获取配置实例，kwargs 覆盖默认值。"""
    config = RAGConfig()
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config
