#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JinaEmbeddingAdapter 单元测试"""
from unittest.mock import patch, MagicMock
import pytest


class TestJinaEmbeddingAdapter:
    """测试 Jina v5 嵌入适配器的前缀逻辑"""

    def test_query_prefix_added(self):
        """查询时添加 search_query: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('llama_index.embeddings.ollama.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embedding.return_value = [0.1] * 1024
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_query_embedding("等待期规定")

            mock_instance.get_text_embedding.assert_called_once_with("search_query: 等待期规定")
            assert result == [0.1] * 1024

    def test_text_prefix_added(self):
        """文档嵌入时添加 passage: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('llama_index.embeddings.ollama.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embedding.return_value = [0.2] * 1024
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_text_embedding("健康保险等待期不超过90天")

            mock_instance.get_text_embedding.assert_called_once_with("passage: 健康保险等待期不超过90天")
            assert result == [0.2] * 1024

    def test_batch_text_prefix_added(self):
        """批量文档嵌入时添加 passage: 前缀"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        with patch('llama_index.embeddings.ollama.OllamaEmbedding') as mock_ollama_cls:
            mock_instance = MagicMock()
            mock_instance.get_text_embeddings.return_value = [[0.1] * 1024, [0.2] * 1024]
            mock_ollama_cls.return_value = mock_instance

            adapter = JinaEmbeddingAdapter(
                model_name="jinaai/jina-embeddings-v5-text-small",
                base_url="http://localhost:11434",
            )
            result = adapter._get_text_embeddings(["条款一", "条款二"])

            mock_instance.get_text_embeddings.assert_called_once_with(["passage: 条款一", "passage: 条款二"])
            assert len(result) == 2

    def test_get_embedding_model_factory_jina(self):
        """工厂函数对 jina 模型返回 JinaEmbeddingAdapter"""
        from lib.rag_engine.llamaindex_adapter import get_embedding_model, JinaEmbeddingAdapter

        with patch('llama_index.embeddings.ollama.OllamaEmbedding'):
            config = {
                'provider': 'ollama',
                'model': 'jinaai/jina-embeddings-v5-text-small',
                'host': 'http://localhost:11434',
            }
            model = get_embedding_model(config)
            assert isinstance(model, JinaEmbeddingAdapter)

    def test_get_embedding_model_factory_non_jina(self):
        """工厂函数对非 jina 模型返回原始 OllamaEmbedding"""
        from lib.rag_engine.llamaindex_adapter import get_embedding_model
        from llama_index.embeddings.ollama import OllamaEmbedding

        config = {
            'provider': 'ollama',
            'model': 'nomic-embed-text',
            'host': 'http://localhost:11434',
        }
        model = get_embedding_model(config)
        assert isinstance(model, OllamaEmbedding)

    def test_prefix_constants(self):
        """验证前缀常量值"""
        from lib.rag_engine.llamaindex_adapter import JinaEmbeddingAdapter

        # Pydantic wraps plain class attributes starting with _ as PrivateAttr
        assert JinaEmbeddingAdapter._PREFIX_QUERY.default == "search_query: "
        assert JinaEmbeddingAdapter._PREFIX_PASSAGE.default == "passage: "
