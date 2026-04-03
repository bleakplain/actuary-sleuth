#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 引擎测试 - 使用真实数据库和索引

注意：这些测试需要 llama_index 模块和嵌入模型。
"""
import pytest
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")


class TestRAGEngineWithRealIndex:
    """测试RAG引擎与真实索引的交互（需要 LLM API key）"""

    def test_search_with_real_vector_index(self, vector_index, require_llm):
        """测试使用真实向量索引的搜索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(top_k_results=3)
        engine = RAGEngine(config)
        engine._initialized = True

        query_engine = vector_index.as_query_engine(similarity_top_k=3)
        engine.query_engine = query_engine

        results = engine.search("等待期", top_k=3, use_hybrid=False)

        assert isinstance(results, list)
        if results:
            assert 'law_name' in results[0]
            assert 'content' in results[0]
            assert 'article_number' in results[0]

    def test_hybrid_search_with_real_index(self, vector_index, require_llm):
        """测试混合检索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(top_k_results=3)
        engine = RAGEngine(config)
        engine._initialized = True

        query_engine = vector_index.as_query_engine(similarity_top_k=3)
        engine.query_engine = query_engine

        results = engine.search("健康保险", top_k=3, use_hybrid=True)

        assert isinstance(results, list)
        if results:
            assert 'score' in results[0]
            assert isinstance(results[0]['score'], (int, float))

    def test_search_with_filters(self, vector_index, require_llm):
        """测试带过滤条件的搜索"""
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig()
        engine = RAGEngine(config)
        engine._initialized = True

        query_engine = vector_index.as_query_engine(similarity_top_k=5)
        engine.query_engine = query_engine

        results = engine.search(
            "保险", top_k=5, use_hybrid=False,
            filters={'category': '健康保险'}
        )

        assert isinstance(results, list)
        if results:
            for result in results:
                category = result.get('category')
                if category:
                    assert category == '健康保险'


class TestDataFlowWithRealComponents:
    """测试使用真实组件的数据流"""

    def test_document_to_index_to_search(self, temp_dir, embedding_model):
        """测试完整的文档->索引->搜索流程"""
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext
        from lib.rag_engine.retrieval import vector_search

        Settings.embed_model = embedding_model

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

        vector_store = LanceDBVectorStore(
            uri=str(temp_dir), table_name="test_data_flow"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_docs, storage_context=storage_context, show_progress=False
        )

        assert index is not None

        results = vector_search(index, "等待期", top_k=2)

        assert isinstance(results, list)
        assert len(results) <= 2
        if results:
            assert hasattr(results[0], 'node')
            assert hasattr(results[0], 'score')

    def test_parse_and_create_index(self, temp_dir, embedding_model):
        """测试解析文档并创建索引"""
        pytest.importorskip("llama_index_readers", reason="llama-index-readers-file not installed")
        from llama_index.core import Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext

        Settings.embed_model = embedding_model

        test_file = temp_dir / "test_regulation.md"
        test_file.write_text("""---
regulation: 测试法规
collection: test_测试法规
---

# 测试法规

## 第1项
健康保险产品的等待期不得超过90天。

## 第2项
保险费率应当公平合理。
        """)

        from lib.rag_engine.builder import KnowledgeBuilder
        from lib.rag_engine.config import RAGConfig
        importer_config = RAGConfig(regulations_dir=str(temp_dir), vector_db_path=str(temp_dir))
        builder = KnowledgeBuilder(importer_config)
        raw_docs = builder.parse(file_pattern="test_regulation.md")
        documents = builder.chunk(raw_docs)

        assert len(documents) > 0

        vector_store = LanceDBVectorStore(
            uri=str(temp_dir), table_name="test_parse_index"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            documents, storage_context=storage_context, show_progress=False
        )

        assert index is not None
