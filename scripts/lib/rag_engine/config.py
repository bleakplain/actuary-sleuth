#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class HybridQueryConfig:
    """混合查询配置"""
    vector_top_k: int = 5
    keyword_top_k: int = 5
    alpha: float = 0.5  # 向量检索权重 (0-1), 1-alpha 为关键词检索权重


@dataclass
class RAGConfig:
    """法规 RAG 引擎配置"""

    # 数据目录配置
    regulations_dir: str = "./references"
    vector_db_path: Optional[str] = None

    # 文本处理配置
    chunk_size: int = 1000
    chunk_overlap: int = 100

    # 检索配置
    top_k_results: int = 5
    enable_streaming: bool = False
    hybrid_config: HybridQueryConfig = None

    # 向量数据库配置
    collection_name: str = "regulations_vectors"

    def __post_init__(self):
        if self.vector_db_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            self.vector_db_path = str(project_root / 'data' / 'lancedb')

        if not Path(self.regulations_dir).is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            self.regulations_dir = str(project_root / self.regulations_dir)

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
