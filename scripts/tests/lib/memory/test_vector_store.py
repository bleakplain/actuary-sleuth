"""LanceDBMemoryStore 单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
import numpy as np

from lib.memory.vector_store import LanceDBMemoryStore, OutputData


@pytest.fixture
def mock_lancedb():
    with patch("lib.memory.vector_store.lancedb") as mock:
        db = MagicMock()
        mock.connect.return_value = db
        yield db


@pytest.fixture
def mock_table():
    table = MagicMock()
    table.count_rows.return_value = 10
    return table


def test_init_creates_connection(mock_lancedb):
    store = LanceDBMemoryStore("/path/to/db", "test_table")
    assert store._table_name == "test_table"
    assert store._vector_size == 1024


def test_init_with_custom_vector_size(mock_lancedb):
    store = LanceDBMemoryStore("/path/to/db", "test_table", vector_size=768)
    assert store._vector_size == 768


def test_get_table_opens_existing(mock_lancedb, mock_table):
    mock_lancedb.table_names.return_value = ["test_table"]
    mock_lancedb.open_table.return_value = mock_table

    store = LanceDBMemoryStore("/path/to/db", "test_table")
    table = store._get_table()

    mock_lancedb.open_table.assert_called_once_with("test_table")
    assert table is mock_table


def test_get_table_creates_new(mock_lancedb, mock_table):
    mock_lancedb.table_names.return_value = []
    mock_lancedb.create_table.return_value = mock_table

    store = LanceDBMemoryStore("/path/to/db", "test_table")
    table = store._get_table()

    mock_lancedb.create_table.assert_called_once()
    assert table is mock_table


def test_insert_adds_rows(mock_lancedb, mock_table):
    mock_lancedb.table_names.return_value = ["test_table"]
    mock_lancedb.open_table.return_value = mock_table

    store = LanceDBMemoryStore("/path/to/db", "test_table")
    vectors = [[0.1, 0.2] * 512]  # 1024 维
    payloads = [{"data": "test", "user_id": "u1"}]

    store.insert(vectors, payloads=payloads, ids=["id1"])

    mock_table.add.assert_called_once()


def test_search_returns_results(mock_lancedb, mock_table):
    mock_lancedb.table_names.return_value = ["test_table"]
    mock_lancedb.open_table.return_value = mock_table

    class MockColumn:
        def __init__(self, values):
            self._values = values
        def __getitem__(self, idx):
            class MockValue:
                def as_py(inner_self):
                    return self._values[idx]
            return MockValue()

    class MockArrow:
        def __len__(self):
            return 1
        def __getitem__(self, key):
            if key == "id":
                return MockColumn(["id1"])
            elif key == "metadata":
                return MockColumn(['{"data": "test"}'])
            elif key == "_distance":
                return MockColumn([0.5])
            return MockColumn([])
        column_names = ["id", "metadata", "_distance"]

    mock_search = MagicMock()
    mock_search.limit.return_value = mock_search
    mock_search.to_arrow.return_value = MockArrow()
    mock_table.search.return_value = mock_search

    store = LanceDBMemoryStore("/path/to/db", "test_table")
    vectors = [[0.1, 0.2] * 512]

    results = store.search("query", vectors, limit=1)

    assert len(results) == 1
    assert results[0].id == "id1"


def test_delete_removes_record(mock_lancedb, mock_table):
    mock_lancedb.table_names.return_value = ["test_table"]
    mock_lancedb.open_table.return_value = mock_table

    store = LanceDBMemoryStore("/path/to/db", "test_table")
    store.delete("id1")

    mock_table.delete.assert_called_once_with("id = 'id1'")


def test_build_where_with_filters():
    filters = {"user_id": "u1", "agent_id": "a1"}
    result = LanceDBMemoryStore._build_where(filters)
    assert "user_id = 'u1'" in result
    assert "agent_id = 'a1'" in result


def test_build_where_without_filters():
    result = LanceDBMemoryStore._build_where(None)
    assert result is None


def test_build_where_ignores_unknown_keys():
    filters = {"user_id": "u1", "unknown_key": "value"}
    result = LanceDBMemoryStore._build_where(filters)
    assert "user_id = 'u1'" in result
    assert "unknown_key" not in result


def test_output_data_model():
    data = OutputData(id="test_id", score=0.95, payload={"key": "value"})
    assert data.id == "test_id"
    assert data.score == 0.95
    assert data.payload == {"key": "value"}
