"""MemoryService 单元测试。"""
import pytest
from unittest.mock import MagicMock, patch
from lib.memory.service import MemoryService


@pytest.fixture
def unavailable_service():
    return MemoryService(memory=None)


def test_search_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.search("test", "user1") == []


def test_add_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.add([], "user1") == []


def test_delete_unavailable_returns_false(unavailable_service):
    assert unavailable_service.delete("mem_123") is False


def test_available_property(unavailable_service):
    assert unavailable_service.available is False


def test_create_with_mock():
    mock_memory = MagicMock()
    mock_memory.from_config.return_value = mock_memory
    svc = MemoryService(memory=mock_memory)
    assert svc.available is True
    assert svc._memory is mock_memory
