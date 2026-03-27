#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 5
    keyword_top_k: int = 5
    rrf_k: int = 60

    def __post_init__(self):
        if self.vector_top_k < 1:
            raise ValueError(f"vector_top_k must be >= 1, got {self.vector_top_k}")
        if self.keyword_top_k < 1:
            raise ValueError(f"keyword_top_k must be >= 1, got {self.keyword_top_k}")
        if self.rrf_k < 1:
            raise ValueError(f"rrf_k must be >= 1, got {self.rrf_k}")


@dataclass
class ChunkingConfig:
    """分块策略配置

    支持三种分块策略:
    - fixed: 固定长度分块（传统方式）
    - semantic: 语义感知分块（推荐）
    - hybrid: 混合策略
    """
    # 策略选择
    strategy: str = "semantic"

    # 尺寸约束
    min_chunk_size: int = 200
    max_chunk_size: int = 1500
    target_chunk_size: int = 800

    # 重叠窗口配置
    overlap_sentences: int = 3
    overlap_tokens: int = 150

    # 合并策略
    enable_semantic_merge: bool = True
    merge_short_threshold: int = 300

    # 结构处理
    preserve_structure: bool = True
    split_long_chunks: bool = True

    def __post_init__(self):
        valid_strategies = {"fixed", "semantic", "hybrid"}
        if self.strategy not in valid_strategies:
            raise ValueError(
                f"chunking_strategy must be one of {valid_strategies}, "
                f"got '{self.strategy}'"
            )
        if self.min_chunk_size >= self.max_chunk_size:
            raise ValueError(
                f"min_chunk_size ({self.min_chunk_size}) must be "
                f"less than max_chunk_size ({self.max_chunk_size})"
            )
        if self.overlap_sentences < 0:
            raise ValueError(
                f"overlap_sentences must be >= 0, got {self.overlap_sentences}"
            )


@dataclass
class RAGConfig:
    """法规 RAG 引擎配置"""

    # 数据目录配置
    regulations_dir: str = "./references"
    vector_db_path: Optional[str] = None

    # 文本处理配置（固定分块策略使用）
    chunk_size: int = 1000
    chunk_overlap: int = 100

    # 分块策略配置
    chunking_strategy: str = "semantic"
    chunking_config: Optional[ChunkingConfig] = None

    # 检索配置
    top_k_results: int = 5
    enable_streaming: bool = False
    hybrid_config: HybridQueryConfig = None

    # 向量数据库配置
    collection_name: str = "regulations_vectors"

    def __post_init__(self):
        if self.vector_db_path is None:
            # 使用统一的配置系统
            from lib.config import get_config
            config = get_config()
            rel_path = config.data_paths.lancedb_uri
            # 解析相对路径（相对于 scripts/ 目录）
            if not Path(rel_path).is_absolute():
                # __file__ 在 scripts/lib/rag_engine/，需要往上3层到 scripts/
                scripts_dir = Path(__file__).parent.parent.parent
                self.vector_db_path = str(scripts_dir / rel_path)
            else:
                self.vector_db_path = str(Path(rel_path))

        if not Path(self.regulations_dir).is_absolute():
            # 使用统一的配置系统
            from lib.config import get_config
            config = get_config()
            reg_dir = config.regulation_search.data_dir
            if not Path(reg_dir).is_absolute():
                # reg_dir 是相对于 scripts/ 目录的路径
                # __file__ 在 scripts/lib/rag_engine/，需要往上3层到 scripts/
                scripts_dir = Path(__file__).parent.parent.parent
                self.regulations_dir = str(scripts_dir / reg_dir)
            else:
                self.regulations_dir = reg_dir

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(f"chunk_overlap ({self.chunk_overlap}) must be less than chunk_size ({self.chunk_size})")

        if self.hybrid_config is None:
            self.hybrid_config = HybridQueryConfig()

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'RAGConfig':
        """从字典创建配置"""
        valid_fields = {k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)

    def to_dict(self) -> dict:
        """转换为字典"""
        from dataclasses import asdict
        return asdict(self)


# 全局默认配置
_default_config = RAGConfig()


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
