#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 引擎配置模块
管理法规检索增强生成引擎的配置参数
"""
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class RAGConfig:
    """法规 RAG 引擎配置"""

    # 数据目录配置
    regulations_dir: str = "./references"
    vector_db_path: Optional[str] = None

    # Ollama 服务配置
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen2:7b"
    embedding_model: str = "nomic-embed-text"

    # 文本处理配置
    chunk_size: int = 500
    chunk_overlap: int = 50

    # 检索配置
    top_k_results: int = 5
    enable_streaming: bool = False

    # 向量数据库配置
    collection_name: str = "regulations_vectors"

    def __post_init__(self):
        """初始化后处理"""
        if self.vector_db_path is None:
            # 默认路径: 项目根目录/data/lancedb
            project_root = Path(__file__).parent.parent.parent.parent
            self.vector_db_path = str(project_root / 'data' / 'lancedb')

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
