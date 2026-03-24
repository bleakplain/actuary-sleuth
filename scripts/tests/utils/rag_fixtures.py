#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG引擎测试fixtures - 使用真实数据库
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any

try:
    from llama_index.core import Document, VectorStoreIndex, Settings
    from llama_index.vector_stores.lancedb import LanceDBVectorStore
    from llama_index.core.storage.storage_context import StorageContext
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.llms.ollama import Ollama
    from llama_index.embeddings.ollama import OllamaEmbedding
    HAS_LLAMA_INDEX = True
except ImportError:
    HAS_LLAMA_INDEX = False
    Document = None


@pytest.fixture
def temp_lancedb_dir():
    """临时LanceDB目录"""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_lancedb_"))
    yield temp_dir
    # 清理
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_sqlite_db():
    """临时SQLite数据库"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    # 清理
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sample_regulation_documents() -> List[Document]:
    """示例法规文档"""
    if not HAS_LLAMA_INDEX:
        return []

    return [
        Document(
            text="健康保险产品的等待期不得超过90天。等待期内发生保险事故，保险公司不承担保险责任。",
            metadata={
                'law_name': '健康保险管理办法',
                'article_number': '第一条',
                'category': '健康保险',
                'source_file': 'test.md'
            }
        ),
        Document(
            text="投保人应当如实告知被保险人的健康状况。故意或者因重大过失未履行如实告知义务，足以影响保险公司承保决定的，保险公司有权解除合同。",
            metadata={
                'law_name': '保险法',
                'article_number': '第十六条',
                'category': '如实告知',
                'source_file': 'test.md'
            }
        ),
        Document(
            text="意外伤害保险的保险期间不得少于1年，不得多于5年。保险期间届满后，投保人可以续保。",
            metadata={
                'law_name': '意外伤害保险管理办法',
                'article_number': '第三条',
                'category': '意外保险',
                'source_file': 'test.md'
            }
        ),
        Document(
            text="保险公司应当公平合理地确定保险费率，不得利用保险费率进行不正当竞争。",
            metadata={
                'law_name': '保险法',
                'article_number': '第一百三十五条',
                'category': '费率管理',
                'source_file': 'test.md'
            }
        ),
        Document(
            text="保险期间为1年的，保险费应当一次性收取。保险期间超过1年的，可以分期收取保险费。",
            metadata={
                'law_name': '保险费收取管理办法',
                'article_number': '第五条',
                'category': '费率管理',
                'source_file': 'test.md'
            }
        ),
    ]


@pytest.fixture
def real_vector_index(temp_lancedb_dir, sample_regulation_documents):
    """创建真实的向量索引用于测试"""
    if not HAS_LLAMA_INDEX:
        pytest.skip("llama_index not installed")

    # 配置嵌入模型（使用轻量级模型）
    try:
        embed_model = OllamaEmbedding(model_name="nomic-embed-text")
        Settings.embed_model = embed_model
    except Exception:
        # 如果ollama不可用，使用默认嵌入
        from llama_index.embeddings.openai import OpenAIEmbedding
        try:
            embed_model = OpenAIEmbedding()
            Settings.embed_model = embed_model
        except Exception:
            pytest.skip("No embedding model available")

    # 配置文本分割器
    Settings.text_splitter = SentenceSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separator="\n\n",
    )

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

    yield index

    # 清理：LanceDB会在temp_lancedb_dir删除时自动清理


@pytest.fixture
def real_llm_client():
    """创建真实的LLM客户端用于测试"""
    from lib.llm import LLMClientFactory

    try:
        # 尝试获取QA LLM（通常是快速模型）
        client = LLMClientFactory.get_qa_llm()
        # 健康检查
        if not client.health_check():
            pytest.skip("LLM client health check failed")
        return client
    except Exception as e:
        pytest.skip(f"Failed to create LLM client: {e}")


@pytest.fixture
def real_rag_config(temp_lancedb_dir):
    """创建真实的RAG配置"""
    from lib.rag_engine.config import RAGConfig

    return RAGConfig(
        regulations_dir="./references",
        vector_db_path=str(temp_lancedb_dir),
        chunk_size=500,
        chunk_overlap=50,
        top_k_results=5,
        collection_name="test_regulations"
    )


def create_test_documents(count: int = 10) -> List[Document]:
    """创建测试文档"""
    if not HAS_LLAMA_INDEX:
        return []

    documents = []
    categories = ['健康保险', '意外保险', '寿险', '年金保险', '费率管理']

    for i in range(count):
        category = categories[i % len(categories)]
        documents.append(Document(
            text=f"这是第{i+1}条测试法规内容。{category}产品应当遵守相关规定，确保合规经营。",
            metadata={
                'law_name': f'测试法规{i+1}',
                'article_number': f'第{i+1}条',
                'category': category,
                'source_file': 'test.md'
            }
        ))

    return documents
