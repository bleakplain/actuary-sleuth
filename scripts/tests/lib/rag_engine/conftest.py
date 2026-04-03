#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG engine test fixtures."""
import os
import shutil
import tempfile
from pathlib import Path
from typing import List

import pytest

try:
    from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.vector_stores.lancedb import LanceDBVectorStore

    HAS_LLAMA_INDEX = True
except ImportError:
    HAS_LLAMA_INDEX = False
    Document = None  # type: ignore[assignment]


@pytest.fixture
def require_llm():
    """Opt-in fixture: 设置 Settings.llm 以便 as_query_engine() 不回退到 OpenAI。"""
    from llama_index.core import Settings
    from lib.llm import LLMClientFactory
    from lib.rag_engine.llamaindex_adapter import ClientLLMAdapter
    try:
        llm_client = LLMClientFactory.create_qa_llm()
        Settings.llm = ClientLLMAdapter(llm_client)
    except Exception:
        pytest.skip("LLM not available")


@pytest.fixture(scope="session")
def embedding_model():
    """Session-scoped embedding model (Ollama → OpenAI fallback)."""
    if not HAS_LLAMA_INDEX:
        pytest.skip("llama_index not installed")

    try:
        return OllamaEmbedding(model_name="jinaai/jina-embeddings-v5-text-small")
    except Exception:
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding
            return OpenAIEmbedding()
        except Exception:
            pytest.skip("No embedding model available")


@pytest.fixture(scope="session")
def sample_documents() -> List[Document]:
    """5 sample regulation documents (immutable, shared across session)."""
    if not HAS_LLAMA_INDEX:
        return []

    return [
        Document(
            text="健康保险产品的等待期不得超过90天。等待期内发生保险事故，保险公司不承担保险责任。",
            metadata={
                "law_name": "健康保险管理办法",
                "article_number": "第一条",
                "category": "健康保险",
                "source_file": "test.md",
            },
        ),
        Document(
            text="投保人应当如实告知被保险人的健康状况。故意或者因重大过失未履行如实告知义务，足以影响保险公司承保决定的，保险公司有权解除合同。",
            metadata={
                "law_name": "保险法",
                "article_number": "第十六条",
                "category": "如实告知",
                "source_file": "test.md",
            },
        ),
        Document(
            text="意外伤害保险的保险期间不得少于1年，不得多于5年。保险期间届满后，投保人可以续保。",
            metadata={
                "law_name": "意外伤害保险管理办法",
                "article_number": "第三条",
                "category": "意外保险",
                "source_file": "test.md",
            },
        ),
        Document(
            text="保险公司应当公平合理地确定保险费率，不得利用保险费率进行不正当竞争。",
            metadata={
                "law_name": "保险法",
                "article_number": "第一百三十五条",
                "category": "费率管理",
                "source_file": "test.md",
            },
        ),
        Document(
            text="保险期间为1年的，保险费应当一次性收取。保险期间超过1年的，可以分期收取保险费。",
            metadata={
                "law_name": "保险费收取管理办法",
                "article_number": "第五条",
                "category": "费率管理",
                "source_file": "test.md",
            },
        ),
    ]


@pytest.fixture
def temp_dir():
    """Temporary directory with auto-cleanup."""
    with tempfile.TemporaryDirectory(prefix="test_") as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def vector_index(embedding_model, temp_dir, sample_documents):
    """Vector index with real embedding model (function-scope, clean per test)."""
    if not HAS_LLAMA_INDEX:
        pytest.skip("llama_index not installed")

    Settings.embed_model = embedding_model
    Settings.text_splitter = SentenceSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separator="\n\n",
    )

    vector_store = LanceDBVectorStore(
        uri=str(temp_dir),
        table_name="test_regulations",
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    yield VectorStoreIndex.from_documents(
        sample_documents,
        storage_context=storage_context,
        show_progress=False,
    )


@pytest.fixture
def bm25_index(temp_dir, sample_documents):
    """BM25 index built from sample documents."""
    from lib.rag_engine.bm25_index import BM25Index

    index_path = temp_dir / "test_bm25_index.pkl"
    return BM25Index.build(sample_documents, index_path)
