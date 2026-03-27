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

# 真实法规数据目录路径
# 从scripts/tests/utils/rag_fixtures.py -> 往上3级 -> references
REAL_REFERENCES_DIR = Path(__file__).parent.parent.parent.parent / "references"
# 从scripts/tests/utils/rag_fixtures.py -> 往上2级 -> data
REAL_DATA_DIR = Path(__file__).parent.parent.parent / "data"


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


@pytest.fixture
def real_references_dir():
    """真实的法规文档目录"""
    if not REAL_REFERENCES_DIR.exists():
        pytest.skip(f"真实法规目录不存在: {REAL_REFERENCES_DIR}")
    return REAL_REFERENCES_DIR


@pytest.fixture
def real_lancedb_dir():
    """真实的LanceDB数据目录（在data目录下）"""
    lancedb_dir = REAL_DATA_DIR / "lancedb"
    # 如果不存在，创建它
    lancedb_dir.mkdir(parents=True, exist_ok=True)
    return lancedb_dir


@pytest.fixture
def real_regulation_vector_index(real_lancedb_dir, real_references_dir):
    """
    使用真实法规文档创建的向量索引

    这个fixture会：
    1. 读取references目录下的所有法规markdown文件
    2. 解析成Document对象
    3. 创建向量索引并存储到data/lancedb
    """
    if not HAS_LLAMA_INDEX:
        pytest.skip("llama_index not installed")

    from lib.rag_engine.doc_parser import RegulationDocParser

    # 配置嵌入模型
    try:
        embed_model = OllamaEmbedding(model_name="nomic-embed-text")
        Settings.embed_model = embed_model
    except Exception:
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

    # 解析真实法规文档
    parser = RegulationDocParser(regulations_dir=str(real_references_dir))
    all_documents = parser.parse_all()

    if not all_documents:
        pytest.skip(f"未能从 {real_references_dir} 解析出任何法规文档")

    print(f"\n加载了 {len(all_documents)} 条法规文档")

    # 创建或获取向量存储
    vector_store = LanceDBVectorStore(
        uri=str(real_lancedb_dir),
        table_name="regulations",
    )

    # 创建存储上下文
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # 创建索引
    index = VectorStoreIndex.from_documents(
        all_documents,
        storage_context=storage_context,
        show_progress=True,
    )

    yield index

    # 不清理真实数据目录，保留用于后续测试


@pytest.fixture
def production_rag_config():
    """使用生产环境配置的RAG配置"""
    if not REAL_REFERENCES_DIR.exists():
        pytest.skip(f"真实法规目录不存在: {REAL_REFERENCES_DIR}")

    lancedb_dir = REAL_DATA_DIR / "lancedb"
    lancedb_dir.mkdir(parents=True, exist_ok=True)

    from lib.rag_engine.config import RAGConfig

    return RAGConfig(
        regulations_dir=str(REAL_REFERENCES_DIR),
        vector_db_path=str(lancedb_dir),
        chunk_size=500,
        chunk_overlap=50,
        top_k_results=5,
        collection_name="regulations"
    )


@pytest.fixture
def production_rag_engine(production_rag_config):
    """
    使用生产环境配置和真实法规数据的RAG引擎

    这个fixture会：
    1. 使用真实的法规文档（references目录）
    2. 使用真实的LanceDB存储（data/lancedb）
    3. 创建完整的RAG引擎，可直接用于查询
    """
    from lib.rag_engine.engine import RAGEngine

    try:
        engine = RAGEngine(production_rag_config)
        # 预加载索引
        engine.preload_index()
        return engine
    except Exception as e:
        pytest.skip(f"无法创建生产RAG引擎: {e}")


@pytest.fixture
def temp_bm25_index(sample_regulation_documents, temp_lancedb_dir):
    """创建临时 BM25 索引用于测试"""
    from lib.rag_engine.bm25_index import BM25Index
    index_path = temp_lancedb_dir / "test_bm25_index.pkl"
    return BM25Index.build(sample_regulation_documents, index_path)
