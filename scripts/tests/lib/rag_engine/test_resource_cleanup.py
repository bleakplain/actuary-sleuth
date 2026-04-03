#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 RAG 引擎资源清理 - 使用真实组件
"""
import pytest
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")


class TestRAGEngineLifecycle:
    """测试RAG引擎生命周期"""

    def test_initialization_with_temp_dir(self, temp_dir, sample_documents, embedding_model):
        """测试使用临时目录初始化"""
        pytest.importorskip("llama_index")

        from llama_index.core import Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext

        Settings.embed_model = embedding_model

        vector_store = LanceDBVectorStore(
            uri=str(temp_dir),
            table_name="test_regulations",
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        index = VectorStoreIndex.from_documents(
            sample_documents,
            storage_context=storage_context,
            show_progress=False,
        )

        assert index is not None


class TestVectorIndexManager:
    """测试向量索引管理器"""

    def test_index_manager_create_without_documents(self, temp_dir):
        """测试无文档时创建索引"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_dir),
            collection_name="test_no_docs"
        )

        manager = VectorIndexManager(config)
        index = manager.create_index(documents=None, force_rebuild=True)

        assert index is None

    def test_index_manager_get_index(self, temp_dir):
        """测试获取索引"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_dir),
            collection_name="test_get_index"
        )

        manager = VectorIndexManager(config)

        index = manager.get_index()
        assert index is None

    def test_index_manager_create_query_engine_without_index(self, temp_dir):
        """测试无索引时创建查询引擎"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_dir),
            collection_name="test_no_query_engine"
        )

        manager = VectorIndexManager(config)

        query_engine = manager.create_query_engine()
        assert query_engine is None


class TestLanceDBCleanup:
    """测试LanceDB清理"""

    def test_lancedb_persistence(self, temp_dir):
        """测试LanceDB持久化"""
        import lancedb

        db = lancedb.connect(str(temp_dir))

        data = [{
            "id": "test_1",
            "text": "测试内容",
            "vector": [0.1] * 10
        }]

        table = db.create_table("test_persistence", data=data)

        assert "test_persistence" in db.table_names()

        db2 = lancedb.connect(str(temp_dir))
        assert "test_persistence" in db2.table_names()
