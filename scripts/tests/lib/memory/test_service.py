"""MemoryService 单元测试。"""
import pytest
from unittest.mock import MagicMock, patch

from lib.memory.service import MemoryService


class MockProfileRequest:
    def __init__(self, focus_areas=None, preference_tags=None, summary=None):
        self.focus_areas = focus_areas
        self.preference_tags = preference_tags
        self.summary = summary


@pytest.fixture
def unavailable_service():
    return MemoryService(backend=None)


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.search.return_value = [{"id": "m1", "memory": "test", "created_at": "2026-04-01"}]
    backend.add.return_value = ["m1"]
    return backend


@pytest.fixture
def service_with_backend(mock_backend):
    return MemoryService(backend=mock_backend)


def test_search_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.search("test", "user1") == []


def test_add_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.add([], "user1") == []


def test_delete_unavailable_returns_false(unavailable_service):
    assert unavailable_service.delete("mem_123") is False


def test_get_all_unavailable_returns_empty(unavailable_service):
    assert unavailable_service.get_all("user1") == []


def test_cleanup_expired_unavailable_returns_zero(unavailable_service):
    assert unavailable_service.cleanup_expired() == 0


def test_available_property(unavailable_service):
    assert unavailable_service.available is False


def test_create_with_mock():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)
    assert svc.available is True
    assert svc._backend is mock_backend


def test_search_delegates(mock_backend):
    svc = MemoryService(backend=mock_backend)
    result = svc.search("test query", "user1")
    mock_backend.search.assert_called_once_with("test query", "user1", 3)
    assert len(result) == 1


def test_search_with_custom_limit(mock_backend):
    svc = MemoryService(backend=mock_backend)
    svc.search("test query", "user1", limit=5)
    mock_backend.search.assert_called_once_with("test query", "user1", 5)


def test_add_forwards_session_id(mock_backend):
    mock_backend.search.return_value = []
    svc = MemoryService(backend=mock_backend)
    svc.add([{"role": "user", "content": "hello"}], "user1", metadata={"session_id": "sess_1"})
    mock_backend.add.assert_called_once_with(
        [{"role": "user", "content": "hello"}], "user1",
        metadata={"session_id": "sess_1"}, run_id="sess_1",
    )


def test_delete_success(service_with_backend):
    result = service_with_backend.delete("mem_123")
    assert result is True
    service_with_backend._backend.delete.assert_called_once_with("mem_123")


def test_get_all_delegates(service_with_backend):
    service_with_backend._backend.get_all.return_value = [{"id": "m1"}]
    result = service_with_backend.get_all("user1")
    service_with_backend._backend.get_all.assert_called_once_with("user1")
    assert len(result) == 1


def test_get_user_profile_not_found(unavailable_service):
    assert unavailable_service.get_user_profile("user1") is None


def test_get_user_profile_success(service_with_backend):
    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ('["重疾险"]', '["等待期"]', "测试摘要")
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = service_with_backend.get_user_profile("user1")
        assert result is not None
        assert result["focus_areas"] == ["重疾险"]
        assert result["preference_tags"] == ["等待期"]


def test_patch_user_profile_not_found_raises():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        req = MockProfileRequest(focus_areas=["医疗险"])
        with pytest.raises(ValueError, match="用户画像不存在"):
            svc.patch_user_profile(req, "user1")


def test_patch_user_profile_success():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = ('["重疾险"]', '["等待期"]', "旧摘要")
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        req = MockProfileRequest(focus_areas=["医疗险"], summary="新摘要")
        result = svc.patch_user_profile(req, "user1")
        assert result["focus_areas"] == ["医疗险"]
        assert result["summary"] == "新摘要"


def test_cleanup_expired_returns_count(service_with_backend):
    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        conn.execute.return_value.fetchall.side_effect = [[("mem_1",), ("mem_2",)], []]
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = service_with_backend.cleanup_expired()
        assert result == 2


def test_search_updates_access_stats(service_with_backend):
    service_with_backend._backend.search.return_value = [
        {"id": "m1", "memory": "test", "created_at": "2026-04-01"},
        {"id": "m2", "memory": "test2", "created_at": "2026-04-01"},
    ]

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        service_with_backend.search("test", "user1")
        conn.execute.assert_called()


def test_search_exception_returns_empty(service_with_backend):
    service_with_backend._backend.search.side_effect = Exception("DB error")
    result = service_with_backend.search("test", "user1")
    assert result == []


def test_add_exception_returns_empty(service_with_backend):
    service_with_backend._backend.add.side_effect = Exception("DB error")
    result = service_with_backend.add([{"role": "user", "content": "hi"}], "user1")
    assert result == []


def test_delete_exception_returns_false(service_with_backend):
    service_with_backend._backend.delete.side_effect = Exception("DB error")
    result = service_with_backend.delete("mem_1")
    assert result is False


def test_add_skips_duplicate_memory():
    mock_backend = MagicMock()
    mock_backend.search.return_value = [{"id": "m1", "memory": "等待期180天", "score": 0.95}]
    mock_backend.add.return_value = ["m2"]

    svc = MemoryService(backend=mock_backend)
    result = svc.add([{"role": "user", "content": "等待期是180天"}], "user1")

    assert result == []
    mock_backend.add.assert_not_called()


def test_add_writes_when_below_threshold():
    mock_backend = MagicMock()
    mock_backend.search.return_value = [{"id": "m1", "memory": "等待期180天", "score": 0.5}]
    mock_backend.add.return_value = ["m2"]

    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.add([{"role": "user", "content": "等待期是180天"}], "user1")
        assert result == ["m2"]


def test_update_user_profile_skips_low_confidence():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch("lib.llm.factory.LLMClientFactory") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.chat.return_value = '{"focus_areas": ["重疾险"], "confidence": 0.3}'
        mock_factory.create_qa_llm.return_value = mock_llm

        with patch("lib.memory.service.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value.__enter__ = lambda self: conn
            mock_conn.return_value.__exit__ = lambda self, *args: None

            svc.update_user_profile("问题", "回答", "user1")
            conn.execute.assert_not_called()


def test_update_user_profile_accepts_high_confidence():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch("lib.llm.factory.LLMClientFactory") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.chat.return_value = '{"focus_areas": ["重疾险"], "preference_tags": [], "summary": "测试", "confidence": 0.8}'
        mock_factory.create_qa_llm.return_value = mock_llm

        with patch("lib.memory.service.get_connection") as mock_conn:
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None
            mock_conn.return_value.__enter__ = lambda self: conn
            mock_conn.return_value.__exit__ = lambda self, *args: None

            svc.update_user_profile("问题", "回答", "user1")
            conn.execute.assert_called()


def test_add_writes_when_no_similar_memory():
    mock_backend = MagicMock()
    mock_backend.search.return_value = []
    mock_backend.add.return_value = ["m1"]

    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.add([{"role": "user", "content": "新的问题"}], "user1")
        assert result == ["m1"]


def test_delete_order_sqlite_first():
    mock_backend = MagicMock()
    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        call_order = []
        conn.execute.side_effect = lambda *args: call_order.append("sqlite")
        mock_backend.delete.side_effect = lambda *args: call_order.append("lancedb")

        svc.delete("mem_123")
        assert call_order == ["sqlite", "lancedb"]


def test_delete_rollback_on_lancedb_failure():
    mock_backend = MagicMock()
    mock_backend.delete.side_effect = Exception("LanceDB error")
    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.delete("mem_123")

        assert result is False
        restore_calls = [c for c in conn.execute.call_args_list if "is_deleted = 0" in str(c)]
        assert len(restore_calls) >= 1


def test_add_rollback_on_metadata_failure():
    mock_backend = MagicMock()
    mock_backend.search.return_value = []
    mock_backend.add.return_value = ["m1"]
    svc = MemoryService(backend=mock_backend)

    with patch("lib.memory.service.get_connection") as mock_conn:
        conn = MagicMock()

        def execute_side_effect(sql, *args):
            if "INSERT" in sql:
                raise Exception("SQLite error")
            return MagicMock()

        conn.execute.side_effect = execute_side_effect
        mock_conn.return_value.__enter__ = lambda self: conn
        mock_conn.return_value.__exit__ = lambda self, *args: None

        result = svc.add([{"role": "user", "content": "test"}], "user1")

        assert result == []
        mock_backend.delete.assert_called_once_with("m1")
