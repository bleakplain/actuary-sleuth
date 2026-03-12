#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量索引管理模块
负责创建、加载和管理法规向量索引
"""
from typing import List, Optional

from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.storage.storage_context import StorageContext

from .config import RAGConfig


class VectorIndexManager:
    """法规向量索引管理器"""

    def __init__(self, config: RAGConfig = None):
        """
        初始化索引管理器

        Args:
            config: RAG 配置
        """
        self.config = config or RAGConfig()
        self.index: Optional[VectorStoreIndex] = None

        # 配置文本分块器
        Settings.text_splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            separator="\n\n",
        )

    def create_index(
        self,
        documents: List,
        force_rebuild: bool = False
    ) -> Optional[VectorStoreIndex]:
        """
        创建或加载向量索引

        Args:
            documents: 文档列表
            force_rebuild: 是否强制重建索引

        Returns:
            Optional[VectorStoreIndex]: 向量索引
        """
        # 如果不强制重建，尝试加载已有索引
        if not force_rebuild:
            loaded_index = self._load_existing_index()
            if loaded_index:
                self.index = loaded_index
                print(f"已加载已有的索引")
                return self.index

        if not documents:
            print("没有文档可用于创建索引")
            return None

        # 创建向量存储
        vector_store = LanceDBVectorStore(
            uri=self.config.vector_db_path,
            table_name=self.config.collection_name,
        )

        # 创建存储上下文
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 创建索引
        print(f"正在使用 {len(documents)} 条法规创建索引...")
        self.index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True,
        )

        print("索引创建成功")
        return self.index

    def _load_existing_index(self) -> Optional[VectorStoreIndex]:
        """
        从已有向量存储加载索引

        Returns:
            Optional[VectorStoreIndex]: 向量索引，如果加载失败返回 None
        """
        try:
            vector_store = LanceDBVectorStore(
                uri=self.config.vector_db_path,
                table_name=self.config.collection_name,
            )

            index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
            print(f"从集合 '{self.config.collection_name}' 加载了已有索引")
            return index

        except Exception as e:
            print(f"加载已有索引失败: {e}")
            return None

    def get_index(self) -> Optional[VectorStoreIndex]:
        """
        获取当前索引

        Returns:
            Optional[VectorStoreIndex]: 向量索引
        """
        return self.index

    def create_query_engine(self, top_k: int = None, streaming: bool = None):
        """
        从索引创建查询引擎

        Args:
            top_k: 返回最相关的 K 个结果
            streaming: 是否使用流式输出

        Returns:
            查询引擎实例
        """
        if self.index is None:
            print("索引未初始化")
            return None

        top_k = top_k or self.config.top_k_results
        streaming = streaming if streaming is not None else self.config.enable_streaming

        return self.index.as_query_engine(
            similarity_top_k=top_k,
            streaming=streaming,
        )

    def index_exists(self) -> bool:
        """
        检查索引是否存在

        Returns:
            bool: 索引存在返回 True
        """
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)
            existing_tables = db.table_names()
            return self.config.collection_name in existing_tables
        except Exception:
            return False
