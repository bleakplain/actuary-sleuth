"""EmbeddingBridge 集成测试（需要 Ollama 运行）。"""
import pytest
from lib.memory.embeddings import EmbeddingBridge


def test_embed_query_returns_vector():
    bridge = EmbeddingBridge()
    result = bridge.embed_query("等待期规定")
    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(x, float) for x in result)


def test_embed_documents_returns_vectors():
    bridge = EmbeddingBridge()
    result = bridge.embed_documents(["等待期90天", "免责条款"])
    assert len(result) == 2
    assert all(len(v) == 1024 for v in result)
