#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 配置模块
管理 RAG 引擎的配置参数
"""
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class LlamaIndexConfig:
    """LlamaIndex RAG 引擎配置"""

    # 数据目录
    data_dir: str = "./references"
    lancedb_uri: Optional[str] = None

    # Ollama 配置
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen2:7b"
    embed_model: str = "nomic-embed-text"

    # 文本分块配置
    chunk_size: int = 500
    chunk_overlap: int = 50

    # 查询配置
    similarity_top_k: int = 5
    streaming: bool = False

    # 索引配置
    table_name: str = "regulations_vectors"

    def __post_init__(self):
        """初始化后处理"""
        # 设置默认 LanceDB 路径
        if self.lancedb_uri is None:
            # 获取项目根目录 (scripts/lib/llamaindex -> ../../.. -> data/lancedb)
            project_root = Path(__file__).parent.parent.parent.parent
            self.lancedb_uri = str(project_root / 'data' / 'lancedb')

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'LlamaIndexConfig':
        """
        从字典创建配置

        Args:
            config_dict: 配置字典

        Returns:
            LlamaIndexConfig: 配置实例
        """
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        """
        转换为字典

        Returns:
            dict: 配置字典
        """
        from dataclasses import asdict
        return asdict(self)


# 默认配置实例
default_config = LlamaIndexConfig()


def get_config(**kwargs) -> LlamaIndexConfig:
    """
    获取配置实例

    Args:
        **kwargs: 覆盖默认配置的参数

    Returns:
        LlamaIndexConfig: 配置实例
    """
    config = LlamaIndexConfig()
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config
