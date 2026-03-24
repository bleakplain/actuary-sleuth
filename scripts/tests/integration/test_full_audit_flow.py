#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整审核流程测试 - 使用真实组件
"""
import pytest
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestFullAuditFlow:
    """完整审核流程测试"""

    def test_successful_preprocessing_flow(self):
        """测试成功预处理流程"""
        from lib.common.models import Product, ProductCategory
        from lib.common.audit import PreprocessedResult
        from lib.common.id_generator import IDGenerator
        from lib.common.date_utils import get_current_timestamp

        result = PreprocessedResult(
            audit_id=IDGenerator.generate_audit(),
            document_url="https://test.feishu.cn/docx/test",
            timestamp=get_current_timestamp(),
            product=Product(
                name="测试产品",
                company="测试公司",
                category=ProductCategory.HEALTH,
                period="1年"
            ),
            clauses=[{"number": "第一条", "title": "测试", "text": "内容"}],
            pricing_params={}
        )

        assert result.audit_id
        assert result.product.name == "测试产品"
        assert len(result.clauses) > 0

    def test_document_fetch_error_handling(self):
        """测试文档获取错误处理"""
        from lib.common.exceptions import DocumentFetchError

        invalid_urls = [
            "not-a-url",
            "https://invalid.domain/doc/test",
            "https://feishu.cn/docx/" + "a" * 100,
        ]

        for url in invalid_urls:
            with pytest.raises(DocumentFetchError):
                from lib.preprocessing.document_fetcher import fetch_feishu_document
                fetch_feishu_document(url)

    def test_real_llm_client_health_check(self):
        """测试真实LLM客户端健康检查"""
        from lib.llm import LLMClientFactory

        try:
            client = LLMClientFactory.get_qa_llm()
            # 健康检查
            is_healthy = client.health_check()
            assert isinstance(is_healthy, bool)
        except Exception as e:
            pytest.skip(f"LLM client not available: {e}")

    def test_real_rag_engine_config(self):
        """测试真实RAG引擎配置"""
        from lib.rag_engine.config import RAGConfig

        config = RAGConfig(
            chunk_size=500,
            chunk_overlap=50,
            top_k_results=5
        )

        assert config.chunk_size == 500
        assert config.top_k_results == 5

    def test_full_integration_with_real_database(self, temp_db_path):
        """测试完整集成流程与真实数据库"""
        from lib.common.database import SQLiteConnectionPool
        from lib.common.models import Product, ProductCategory
        from lib.common.id_generator import IDGenerator

        pool = SQLiteConnectionPool(str(temp_db_path), pool_size=2)

        try:
            # 初始化数据库表
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audit_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        audit_id TEXT UNIQUE NOT NULL,
                        document_url TEXT,
                        status TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()

            # 创建测试数据
            audit_id = IDGenerator.generate_audit()

            # 保存到数据库
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO audit_records (audit_id, document_url, status)
                    VALUES (?, ?, ?)
                """, (audit_id, "https://test.doc", "completed"))
                conn.commit()

            # 验证保存成功
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM audit_records WHERE audit_id = ?", (audit_id,))
                result = cursor.fetchone()
                assert result is not None

        finally:
            pool.close_all()

    def test_document_parser_with_real_file(self, temp_output_dir):
        """测试使用真实文件的文档解析"""
        from lib.rag_engine.doc_parser import RegulationDocParser

        # 创建测试文件
        test_file = temp_output_dir / "regulation.md"
        test_file.write_text("""
# 测试法规

### 第一条 基本原则
保险公司应当遵守保险法的规定。

### 第二条 产品要求
保险产品应当符合监管要求。
        """)

        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))
        documents = parser.parse_single_file("regulation.md")

        assert len(documents) > 0
        assert all('law_name' in doc.metadata for doc in documents)
        assert all('article_number' in doc.metadata for doc in documents)

    def test_vector_store_with_real_lancedb(self, temp_lancedb_dir):
        """测试使用真实LanceDB的向量存储"""
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

        # 创建测试文档
        test_docs = [
            Document(text="保险法规内容", metadata={'law_name': '测试法规'})
        ]

        # 创建向量存储
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_full_flow"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_docs,
            storage_context=storage_context,
            show_progress=False
        )

        assert index is not None
        assert len(index.docstore.docs) > 0


@pytest.fixture
def temp_db_path():
    """临时数据库路径"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    # 清理
    if Path(f.name).exists():
        Path(f.name).unlink()


@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
