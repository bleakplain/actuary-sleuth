#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 引擎测试 - 使用真实数据库和索引

注意：这些测试需要 llama_index 模块和嵌入模型。
"""
import pytest
import tempfile
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")


class TestRAGEngineBasicOperations:
    """测试RAG引擎基本操作"""

    def test_engine_config_creation(self):
        """测试引擎配置创建"""
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            chunk_size=500,
            chunk_overlap=50,
            top_k_results=3
        )

        assert config.chunk_size == 500
        assert config.chunk_overlap == 50
        assert config.top_k_results == 3

    def test_engine_with_temp_config(self, temp_lancedb_dir):
        """测试使用临时配置创建引擎"""
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_engine_config"
        )

        assert config.vector_db_path == str(temp_lancedb_dir)
        assert config.collection_name == "test_engine_config"


class TestRAGEngineWithRealIndex:
    """测试RAG引擎与真实索引的交互"""

    def test_search_with_real_vector_index(self, real_vector_index):
        """测试使用真实向量索引的搜索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(top_k_results=3)
        engine = RAGEngine(config)
        engine._initialized = True

        # 使用真实索引创建查询引擎
        query_engine = real_vector_index.as_query_engine(
            similarity_top_k=3
        )
        engine.query_engine = query_engine

        # 执行搜索
        results = engine.search("等待期", top_k=3, use_hybrid=False)

        assert isinstance(results, list)
        if results:
            assert 'law_name' in results[0]
            assert 'content' in results[0]
            assert 'article_number' in results[0]

    def test_hybrid_search_with_real_index(self, real_vector_index):
        """测试混合检索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            top_k_results=3,
            hybrid_config__alpha=0.5
        )
        engine = RAGEngine(config)
        engine._initialized = True

        # 使用真实索引
        query_engine = real_vector_index.as_query_engine(
            similarity_top_k=3
        )
        engine.query_engine = query_engine

        # 执行混合搜索
        results = engine.search("健康保险", top_k=3, use_hybrid=True)

        assert isinstance(results, list)
        if results:
            assert 'score' in results[0]
            assert isinstance(results[0]['score'], (int, float))

    def test_search_with_filters(self, real_vector_index):
        """测试带过滤条件的搜索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig()
        engine = RAGEngine(config)
        engine._initialized = True

        query_engine = real_vector_index.as_query_engine(
            similarity_top_k=5
        )
        engine.query_engine = query_engine

        # 使用过滤条件搜索
        results = engine.search(
            "保险",
            top_k=5,
            use_hybrid=False,
            filters={'category': '健康保险'}
        )

        assert isinstance(results, list)
        # 验证过滤条件（如果结果存在）
        if results:
            for result in results:
                category = result.get('category')
                if category:  # 只检查有category字段的结果
                    assert category == '健康保险'


class TestDataFlowWithRealComponents:
    """测试使用真实组件的数据流"""

    def test_document_to_index_to_search(self, temp_lancedb_dir):
        """测试完整的文档->索引->搜索流程"""
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext
        from lib.rag_engine.retrieval import vector_search

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

        # 1. 创建测试文档
        test_docs = [
            Document(
                text="健康保险等待期为90天，期间内不承担保险责任",
                metadata={'law_name': '健康保险办法', 'article_number': '第一条', 'category': '健康保险'}
            ),
            Document(
                text="意外伤害保险期间不得少于1年",
                metadata={'law_name': '意外保险办法', 'article_number': '第二条', 'category': '意外保险'}
            ),
        ]

        # 2. 创建向量索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_data_flow"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_docs,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None

        # 3. 执行向量搜索
        results = vector_search(index, "等待期", top_k=2)

        assert isinstance(results, list)
        assert len(results) <= 2
        if results:
            assert hasattr(results[0], 'node')
            assert hasattr(results[0], 'score')

    def test_parse_documents_and_create_index(self, temp_lancedb_dir, temp_output_dir):
        """测试解析文档并创建索引"""
        from lib.rag_engine.doc_parser import RegulationDocParser
        from llama_index.core import Settings, VectorStoreIndex
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

        # 1. 创建测试文件
        test_file = temp_output_dir / "test_regulation.md"
        test_file.write_text("""
# 测试法规

### 第一条 等待期
健康保险产品的等待期不得超过90天。

### 第二条 费率
保险费率应当公平合理。
        """)

        # 2. 解析文档
        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))
        documents = parser.parse_single_file("test_regulation.md")

        assert len(documents) > 0

        # 3. 创建向量索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_parse_index"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None
        assert len(index.docstore.docs) > 0


class TestRAGEngineIntegration:
    """RAG引擎集成测试"""

    def test_index_manager_with_real_lancedb(self, temp_lancedb_dir):
        """测试索引管理器与真实LanceDB"""
        from lib.rag_engine.index_manager import VectorIndexManager
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_manager_real"
        )

        manager = VectorIndexManager(config)

        assert manager is not None
        assert manager.config == config

        # 测试表存在检查
        exists = manager.index_exists()
        assert isinstance(exists, bool)

    def test_vector_index_creation(self, temp_lancedb_dir):
        """测试向量索引创建"""
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

        test_docs = [
            Document(text="保险条款内容", metadata={'law_name': '测试法规'})
        ]

        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_index_creation"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_docs,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None
        assert len(index.docstore.docs) > 0

    def test_engine_configuration_validation(self):
        """测试引擎配置验证"""
        from lib.rag_engine.config import RAGConfig

        # 测试有效配置
        config = RAGConfig(
            chunk_size=600,
            chunk_overlap=60,
            top_k_results=10
        )

        assert config.chunk_size == 600
        assert config.chunk_overlap == 60
        assert config.top_k_results == 10

        # 测试无效配置
        with pytest.raises(ValueError):
            RAGConfig(chunk_size=100, chunk_overlap=100)


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_rag_output_"))
    yield temp_dir
    # 清理
    import shutil
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
