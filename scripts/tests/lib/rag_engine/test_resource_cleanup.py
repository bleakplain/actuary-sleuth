import pytest

# Skip RAG tests if llama_index is not available
pytest.importorskip("llama_index", reason="llama_index not installed")

from unittest.mock import patch, Mock
from lib.rag_engine.rag_engine import RAGEngine


class TestResourceCleanup:
    @patch('lib.rag_engine.rag_engine.VectorIndexManager')
    def test_initialization_failure_restores_settings(self, mock_index_manager):
        mock_manager_instance = Mock()
        mock_manager_instance.create_index.return_value = None
        mock_index_manager.return_value = mock_manager_instance

        engine = RAGEngine()
        result = engine.initialize()

        assert result is False
        assert engine.query_engine is None

    @patch('lib.rag_engine.rag_engine.VectorIndexManager')
    def test_exception_during_initialization(self, mock_index_manager):
        mock_manager_instance = Mock()
        mock_manager_instance.create_index.side_effect = RuntimeError("数据库连接失败")
        mock_index_manager.return_value = mock_manager_instance

        engine = RAGEngine()
        result = engine.initialize()

        assert result is False

    @patch('lib.rag_engine.rag_engine.VectorIndexManager')
    def test_successful_initialization(self, mock_index_manager):
        mock_index = Mock()
        mock_index.docstore.docs.values.return_value = []

        mock_manager_instance = Mock()
        mock_manager_instance.create_index.return_value = mock_index
        mock_query_engine = Mock()
        mock_manager_instance.create_query_engine.return_value = mock_query_engine
        mock_index_manager.return_value = mock_manager_instance

        engine = RAGEngine()
        result = engine.initialize()

        assert result is True
        assert engine.query_engine is not None

    def test_explicit_cleanup(self):
        engine = RAGEngine()
        engine.query_engine = Mock()

        engine.cleanup()

        assert engine.query_engine is None
