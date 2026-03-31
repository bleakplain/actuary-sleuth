#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量索引管理模块
负责创建、加载和管理法规向量索引
"""
import logging
from typing import Dict, Any, List, Optional

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.storage.storage_context import StorageContext
from llama_index.core.schema import TextNode

from .config import RAGConfig

logger = logging.getLogger(__name__)


class VectorIndexManager:
    """法规向量索引管理器"""

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.index: Optional[VectorStoreIndex] = None

    def create_index(
        self,
        documents: List,
        force_rebuild: bool = False
    ) -> Optional[VectorStoreIndex]:
        if not force_rebuild:
            loaded_index = self._load_existing_index()
            if loaded_index:
                self.index = loaded_index
                logger.info("已加载已有的索引")
                return self.index

        if not documents:
            logger.warning("没有文档可用于创建索引")
            return None

        if force_rebuild:
            self._drop_table()

        vector_store = LanceDBVectorStore(
            uri=self.config.vector_db_path,
            table_name=self.config.collection_name,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        logger.info(f"正在使用 {len(documents)} 条法规创建索引...")

        nodes = [
            TextNode(text=doc.text, metadata=doc.metadata)
            for doc in documents
        ]
        self.index = VectorStoreIndex(
            nodes,
            storage_context=storage_context,
            show_progress=True,
        )

        logger.info("索引创建成功")
        return self.index

    def _load_existing_index(self) -> Optional[VectorStoreIndex]:
        try:
            from llama_index.core import Settings
            if Settings.embed_model is None:
                logger.warning("未配置 embed_model，跳过加载已有索引")
                return None

            if not self.index_exists():
                return None

            vector_store = LanceDBVectorStore(
                uri=self.config.vector_db_path,
                table_name=self.config.collection_name,
            )
            index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
            logger.info(f"从集合 '{self.config.collection_name}' 加载了已有索引")
            return index
        except Exception as e:
            logger.warning(f"加载已有索引失败: {e}")
            return None

    def get_index(self) -> Optional[VectorStoreIndex]:
        return self.index

    def create_query_engine(self, top_k: int = None, streaming: bool = None):
        if self.index is None:
            logger.warning("索引未初始化")
            return None

        top_k = top_k or self.config.top_k_results
        streaming = streaming if streaming is not None else self.config.enable_streaming

        return self.index.as_query_engine(
            similarity_top_k=top_k,
            streaming=streaming,
        )

    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息（直接查询 LanceDB，不依赖 self.index）"""
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)
            existing_tables = db.table_names()
            if self.config.collection_name not in existing_tables:
                return {'status': 'not_initialized'}
            table = db.open_table(self.config.collection_name)
            count = len(table)
            return {
                'status': 'ok',
                'doc_count': count,
                'collection': self.config.collection_name,
            }
        except Exception as e:
            logger.warning(f"获取索引统计失败: {e}")
            return {'status': 'error', 'message': str(e)}

    def index_exists(self) -> bool:
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)
            existing_tables = db.table_names()
            return self.config.collection_name in existing_tables
        except Exception:
            return False

    def _drop_table(self) -> None:
        """删除已有的向量表（用于 force_rebuild）"""
        try:
            import lancedb
            db = lancedb.connect(self.config.vector_db_path)
            if self.config.collection_name in db.table_names():
                db.drop_table(self.config.collection_name)
                logger.info(f"已删除向量表 '{self.config.collection_name}'")
        except Exception as e:
            logger.warning(f"删除向量表失败: {e}")
