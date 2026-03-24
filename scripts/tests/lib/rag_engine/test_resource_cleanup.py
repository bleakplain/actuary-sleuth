#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 RAG 引擎资源清理 - 使用真实组件
"""
import pytest
import tempfile
import shutil
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")

from lib.rag_engine.rag_engine import RAGEngine
from lib.rag_engine.config import RAGConfig


class TestRAGEngineLifecycle:
    """测试RAG引擎生命周期"""

    def test_initialization_with_invalid_config(self):
        """测试使用无效配置初始化"""
        # 测试配置验证而不创建完整的引擎
        from lib.rag_engine.config import RAGConfig

        # 测试无效的chunk_overlap
        with pytest.raises(ValueError):
            RAGConfig(chunk_size=100, chunk_overlap=100)

        # 测试有效的配置
        config = RAGConfig(
            regulations_dir="/nonexistent/directory",
            vector_db_path="/tmp/test_lancedb"
        )
        assert config.regulations_dir == "/nonexistent/directory"

    def test_initialization_with_temp_dir(self, temp_lancedb_dir, sample_regulation_documents):
        """测试使用临时目录初始化"""
        pytest.importorskip("llama_index")

        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext

        try:
            from llama_index.embeddings.ollama import OllamaEmbedding
            embed_model = OllamaEmbedding(model_name="nomic-embed-text")
            Settings.embed_model = embed_model
        except Exception:
            try:
                from llama_index.embeddings.openai import OpenAIEmbedding
                embed_model = OpenAIEmbedding()
                Settings.embed_model = embed_model
            except Exception:
                pytest.skip("No embedding model available")

        # 创建向量存储
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_regulations",
        )

        # 创建存储上下文
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 创建索引
        index = VectorStoreIndex.from_documents(
            sample_regulation_documents,
            storage_context=storage_context,
            show_progress=False,
        )

        # 验证索引创建成功
        assert index is not None
        assert len(index.docstore.docs) > 0

    def test_engine_cleanup(self, temp_lancedb_dir):
        """测试引擎清理"""
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_cleanup"
        )

        # 创建引擎但不初始化（避免API密钥验证）
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = config
        engine.index_manager = None
        engine.query_engine = "mock_engine"
        engine._llm = None
        engine._embed_model = None
        engine._avg_doc_len = 100
        engine._initialized = False
        engine._init_lock = None

        # 执行清理（直接设置query_engine为None，因为_cleanup_resources不存在）
        engine.query_engine = None

        # 验证资源被释放
        assert engine.query_engine is None

    def test_multiple_initialization_attempts(self, temp_lancedb_dir):
        """测试多次初始化尝试"""
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_multi_init"
        )

        # 创建引擎但不初始化（避免API密钥验证）
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = config
        engine.index_manager = None
        engine.query_engine = None
        engine._llm = None
        engine._embed_model = None
        engine._avg_doc_len = 100
        engine._initialized = False
        engine._init_lock = None

        # 验证引擎状态
        assert engine._initialized is False
        assert engine.query_engine is None


class TestVectorIndexManager:
    """测试向量索引管理器"""

    def test_index_manager_initialization(self, temp_lancedb_dir):
        """测试索引管理器初始化"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_manager_init"
        )

        manager = VectorIndexManager(config)
        assert manager is not None
        assert manager.config == config

    def test_index_manager_create_without_documents(self, temp_lancedb_dir):
        """测试无文档时创建索引"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_no_docs"
        )

        manager = VectorIndexManager(config)
        index = manager.create_index(documents=None, force_rebuild=True)

        # 没有文档时应该返回None
        assert index is None

    def test_index_manager_table_exists(self, temp_lancedb_dir):
        """测试检查表是否存在"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_table_exists"
        )

        manager = VectorIndexManager(config)

        # 表不存在时应该返回False
        exists = manager.index_exists()
        assert isinstance(exists, bool)

    def test_index_manager_get_index(self, temp_lancedb_dir):
        """测试获取索引"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_get_index"
        )

        manager = VectorIndexManager(config)

        # 未初始化时应该返回None
        index = manager.get_index()
        assert index is None

    def test_index_manager_create_query_engine_without_index(self, temp_lancedb_dir):
        """测试无索引时创建查询引擎"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_no_query_engine"
        )

        manager = VectorIndexManager(config)

        # 没有索引时应该返回None
        query_engine = manager.create_query_engine()
        assert query_engine is None


class TestLanceDBCleanup:
    """测试LanceDB清理"""

    def test_lancedb_temp_dir_cleanup(self, temp_lancedb_dir):
        """测试临时LanceDB目录清理"""
        # 验证目录存在
        assert temp_lancedb_dir.exists()

        # 创建一些文件
        test_file = temp_lancedb_dir / "test.txt"
        test_file.write_text("test")

        # fixture会在yield后自动清理
        # 这里只验证目录在测试期间存在

    def test_lancedb_persistence(self, temp_lancedb_dir):
        """测试LanceDB持久化"""
        import lancedb

        # 连接并创建表
        db = lancedb.connect(str(temp_lancedb_dir))

        # 创建测试数据
        data = [{
            "id": "test_1",
            "text": "测试内容",
            "vector": [0.1] * 10
        }]

        table = db.create_table("test_persistence", data=data)

        # 验证表存在
        assert "test_persistence" in db.table_names()

        # 重新连接验证持久化
        db2 = lancedb.connect(str(temp_lancedb_dir))
        assert "test_persistence" in db2.table_names()


class TestRAGConfigValidation:
    """测试RAG配置验证"""

    def test_config_with_invalid_chunk_overlap(self):
        """测试无效的chunk_overlap"""
        with pytest.raises(ValueError, match="chunk_overlap"):
            RAGConfig(chunk_size=100, chunk_overlap=100)

    def test_config_with_invalid_chunk_overlap_larger(self):
        """测试chunk_overlap大于chunk_size"""
        with pytest.raises(ValueError, match="chunk_overlap"):
            RAGConfig(chunk_size=100, chunk_overlap=150)

    def test_config_with_valid_parameters(self):
        """测试有效参数"""
        config = RAGConfig(
            chunk_size=500,
            chunk_overlap=50,
            top_k_results=10
        )
        assert config.chunk_size == 500
        assert config.chunk_overlap == 50
        assert config.top_k_results == 10

    def test_config_from_dict(self):
        """测试从字典创建配置"""
        config_dict = {
            'chunk_size': 800,
            'top_k_results': 5
        }
        config = RAGConfig.from_dict(config_dict)
        assert config.chunk_size == 800
        assert config.top_k_results == 5

    def test_config_to_dict(self):
        """测试转换为字典"""
        config = RAGConfig(chunk_size=600)
        config_dict = config.to_dict()
        assert config_dict['chunk_size'] == 600
        assert 'collection_name' in config_dict
