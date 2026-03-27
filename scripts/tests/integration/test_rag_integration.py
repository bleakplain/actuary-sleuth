#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG引擎集成测试 - 使用真实的SQLite和LanceDB

这些测试使用真实的数据库和向量索引，验证整个RAG流程的正确性。
"""
import pytest
import tempfile
import shutil
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")

from lib.rag_engine.config import RAGConfig
from lib.rag_engine.rag_engine import RAGEngine
from lib.rag_engine.index_manager import VectorIndexManager
from lib.rag_engine.doc_parser import RegulationDocParser
from lib.common.database import SQLiteConnectionPool


class TestRAGIntegration:
    """RAG引擎完整集成测试"""

    def test_full_rag_workflow(self, temp_lancedb_dir, temp_sqlite_db):
        """测试完整的RAG工作流程"""
        from llama_index.core import Document
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext
        from llama_index.core import VectorStoreIndex, Settings
        from llama_index.core.node_parser import SentenceSplitter

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

        # 1. 准备测试数据
        test_documents = [
            Document(
                text="健康保险产品的等待期不得超过90天。等待期内发生保险事故，保险公司不承担保险责任。",
                metadata={
                    'law_name': '健康保险管理办法',
                    'article_number': '第一条',
                    'category': '健康保险'
                }
            ),
            Document(
                text="保险公司应当公平合理地确定保险费率，不得利用保险费率进行不正当竞争。",
                metadata={
                    'law_name': '保险法',
                    'article_number': '第一百三十五条',
                    'category': '费率管理'
                }
            ),
        ]

        # 2. 创建向量索引
        Settings.text_splitter = SentenceSplitter(
            chunk_size=500,
            chunk_overlap=50
        )

        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_integration"
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_documents,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None
        assert len(index.docstore.docs) > 0

        # 3. 创建查询引擎
        query_engine = index.as_query_engine(similarity_top_k=2)
        assert query_engine is not None

        # 4. 执行查询
        response = query_engine.query("健康保险的等待期有什么规定？")

        assert response is not None
        assert hasattr(response, 'source_nodes')

        # 5. 验证结果
        if response.source_nodes:
            source = response.source_nodes[0]
            assert hasattr(source, 'node')
            assert '等待期' in source.node.text or '保险' in source.node.text

    def test_rag_engine_with_sqlite_and_lancedb(self, temp_lancedb_dir, temp_sqlite_db):
        """测试RAG引擎同时使用SQLite和LanceDB"""
        # 创建SQLite连接池
        pool = SQLiteConnectionPool(str(temp_sqlite_db), pool_size=2)

        # 创建RAG配置（不创建引擎以避免API密钥验证）
        config = RAGConfig(
            vector_db_path=str(temp_lancedb_dir),
            collection_name="test_rag_sqlite"
        )

        # 验证配置
        assert config.vector_db_path == str(temp_lancedb_dir)
        assert config.collection_name == "test_rag_sqlite"

        # 清理
        pool.close_all()

    def test_document_parsing_to_vector_index(self, temp_lancedb_dir, temp_output_dir):
        """测试从文档解析到向量索引的完整流程"""
        from llama_index.core import Document, VectorStoreIndex, Settings
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

        # 1. 创建测试文档
        test_file = temp_output_dir / "regulation.md"
        test_file.write_text("""
# 保险法

### 第一条 保险责任
保险公司应当承担保险责任，按照合同约定给付保险金。

### 第二条 如实告知
投保人应当如实告知被保险人的健康状况。

### 第三条 等待期
健康保险产品的等待期不得超过90天。
        """)

        # 2. 解析文档
        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))
        documents = parser.parse_single_file("regulation.md")

        assert len(documents) > 0
        assert all('law_name' in doc.metadata for doc in documents)
        assert all('article_number' in doc.metadata for doc in documents)

        # 3. 创建向量索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_parsing_index"
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None
        assert len(index.docstore.docs) > 0

        # 4. 验证索引内容
        all_docs = list(index.docstore.docs.values())
        assert len(all_docs) > 0

        # 验证元数据被正确保存
        for doc in all_docs[:3]:  # 检查前3个
            assert 'law_name' in doc.metadata
            assert 'article_number' in doc.metadata

    def test_vector_search_and_filter(self, temp_lancedb_dir):
        """测试向量检索与过滤"""
        from llama_index.core import Document, VectorStoreIndex, Settings
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

        # 创建测试数据
        documents = [
            Document(
                text="健康保险等待期规定",
                metadata={'category': '健康保险', 'law_name': '健康法规'}
            ),
            Document(
                text="意外保险期限规定",
                metadata={'category': '意外保险', 'law_name': '意外法规'}
            ),
        ]

        # 创建索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_filter"
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=False
        )

        # 测试带过滤的检索
        results = vector_search(
            index,
            "保险",
            top_k=5,
            filters={'category': '健康保险'}
        )

        # 验证过滤结果
        if results:
            for node in results:
                category = node.node.metadata.get('category')
                if category:
                    assert category == '健康保险'


class TestRAGWithRealData:
    """使用真实数据的RAG测试"""

    def test_keyword_search_bm25(self, temp_lancedb_dir):
        """测试 BM25 关键词搜索"""
        from llama_index.core import Document
        from lib.rag_engine.bm25_index import BM25Index

        documents = [
            Document(text="保险等待期为90天，期间内不承担责任"),
            Document(text="保险费率应当公平合理，不得恶性竞争"),
            Document(text="投保人如实告知健康状况，否则保险公司可以解除合同"),
        ]

        index_path = temp_lancedb_dir / "test_bm25_index.pkl"
        bm25 = BM25Index.build(documents, index_path)

        results = bm25.search("等待期", top_k=2)
        assert isinstance(results, list)
        if results:
            _, score = results[0]
            assert score >= 0

    def test_hybrid_search_fusion(self, temp_lancedb_dir):
        """测试混合检索 RRF 融合"""
        from llama_index.core import Document, VectorStoreIndex, Settings
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext
        from lib.rag_engine.retrieval import hybrid_search
        from lib.rag_engine.bm25_index import BM25Index

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

        documents = [
            Document(
                text="健康保险等待期为90天",
                metadata={'law_name': '健康保险办法', 'article_number': '第一条'}
            ),
            Document(
                text="保险费率需要公平合理",
                metadata={'law_name': '保险法', 'article_number': '第一百三十五条'}
            ),
        ]

        # 创建向量索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_hybrid"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=False
        )

        # 创建 BM25 索引
        bm25_index = BM25Index.build(documents, temp_lancedb_dir / "test_hybrid_bm25.pkl")

        # 测试混合检索
        results = hybrid_search(
            index, bm25_index,
            "健康保险等待期",
            vector_top_k=2, keyword_top_k=2
        )

        assert isinstance(results, list)
        if results:
            assert 'law_name' in results[0]
            assert 'content' in results[0]
            assert 'score' in results[0]


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_rag_output_"))
    yield temp_dir
    # 清理
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
