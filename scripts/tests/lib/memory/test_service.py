"""MemoryService 单元测试。"""
import pytest
from unittest.mock import MagicMock
from lib.memory.service import MemoryService


@pytest.fixture
def unavailable_service():
    return MemoryService(backend=None)


def test_search_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.search("test", "user1") == []


def test_add_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.add([], "user1") == []


def test_delete_unavailable_returns_false(unavailable_service):
    assert unavailable_service.delete("mem_123") is False


def test_available_property(unavailable_service):
    assert unavailable_service.available is False


def test_create_with_mock():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)
    assert svc.available is True
    assert svc._backend is mock_backend


def test_search_delegates():
    mock_backend = MagicMock()
    mock_backend.search.return_value = [
        {"id": "m1", "memory": "test memory", "created_at": "2026-04-01T10:00:00"}
    ]
    svc = MemoryService(backend=mock_backend)
    result = svc.search("test query", "user1")
    mock_backend.search.assert_called_once_with("test query", "user1", 3)
    assert len(result) == 1


def test_add_forwards_session_id():
    mock_backend = MagicMock()
    mock_backend.add.return_value = ["m1"]
    svc = MemoryService(backend=mock_backend)
    svc.add([{"role": "user", "content": "hello"}], "user1", metadata={"session_id": "sess_1"})
    mock_backend.add.assert_called_once_with(
        [{"role": "user", "content": "hello"}], "user1",
        metadata={"session_id": "sess_1"}, run_id="sess_1",
    )
