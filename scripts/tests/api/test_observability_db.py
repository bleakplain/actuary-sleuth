"""Observability 数据库函数测试。"""
import pytest


class TestConversationSearch:
    def test_search_conversations_no_filter(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="", page=1, size=10)
        assert rows[1] == 3  # total count

    def test_search_conversations_by_title(self, _patch_database, make_conversation):
        import api.database as db
        make_conversation("conv_aaa", "健康保险等待期")
        make_conversation("conv_bbb", "免责条款查询")
        make_conversation("conv_ccc", "等待期相关问题")
        rows = db.search_conversations(search="等待期", page=1, size=10)
        assert rows[1] == 2
        titles = [r["title"] for r in rows[0]]
        assert "健康保险等待期" in titles
        assert "等待期相关问题" in titles

    def test_search_conversations_pagination(self, _patch_database, make_conversation):
        import api.database as db
        for i in range(5):
            make_conversation(f"conv_{i}", f"对话 {i}")
        rows = db.search_conversations(search="", page=1, size=2)
        assert len(rows[0]) == 2
        assert rows[1] == 5


class TestBatchDeleteConversations:
    def test_batch_delete(self, _patch_database, make_conversation, make_message):
        import api.database as db
        make_conversation("conv_del1", "删除1")
        make_message("conv_del1", "user", "问题1")
        make_message("conv_del1", "assistant", "回答1")
        make_conversation("conv_del2", "删除2")
        make_message("conv_del2", "user", "问题2")
        make_conversation("conv_keep", "保留")
        deleted = db.batch_delete_conversations(["conv_del1", "conv_del2"])
        assert deleted == 2
        remaining = db.get_conversations()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "conv_keep"


class TestTraceSearch:
    def _create_trace(self, trace_id="t1", message_id=1, conversation_id="conv_a", status="ok"):
        import api.database as db
        span = {
            "trace_id": trace_id, "span_id": f"{trace_id}-1",
            "parent_span_id": None, "name": "root", "category": "root",
            "input": {"question": "test"}, "output": {"answer": "ok"},
            "start_time": 1000.0, "end_time": 1001.5, "duration_ms": 1500.0,
            "status": status, "error": None,
        }
        db.save_trace(trace_id, message_id, conversation_id,
                       status=status, total_duration_ms=span["duration_ms"], span_count=1)
        db.save_spans([span])

    def test_search_traces_no_filter(self, _patch_database):
        import api.database as db
        for i in range(3):
            self._create_trace(f"t{i}", message_id=i + 1)
        rows, total = db.search_traces(page=1, size=10)
        assert total == 3

    def test_search_traces_by_trace_id(self, _patch_database):
        import api.database as db
        self._create_trace("abc123", message_id=1)
        self._create_trace("def456", message_id=2)
        rows, total = db.search_traces(trace_id="abc123", page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "abc123"

    def test_search_traces_by_conversation_id(self, _patch_database):
        import api.database as db
        self._create_trace("t1", conversation_id="conv_x")
        self._create_trace("t2", conversation_id="conv_y")
        rows, total = db.search_traces(conversation_id="conv_x", page=1, size=10)
        assert total == 1

    def test_search_traces_by_status(self, _patch_database):
        import api.database as db
        self._create_trace("t1", status="ok")
        self._create_trace("t2", status="error")
        rows, total = db.search_traces(status="error", page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "t2"

    def test_search_traces_by_date_range(self, _patch_database):
        import api.database as db
        self._create_trace("t1")
        rows, total = db.search_traces(start_date="2020-01-01", end_date="2099-12-31", page=1, size=10)
        assert total == 1

    def test_search_traces_pagination(self, _patch_database):
        import api.database as db
        for i in range(5):
            self._create_trace(f"t{i}", message_id=i + 1)
        rows, total = db.search_traces(page=1, size=2)
        assert len(rows) == 2
        assert total == 5

    def test_search_traces_has_duration(self, _patch_database):
        import api.database as db
        self._create_trace("t1", message_id=1)
        rows, _ = db.search_traces(page=1, size=10)
        assert rows[0]["total_duration_ms"] == 1500.0


class TestGetTraceByTraceId:
    def test_get_existing_trace(self, _patch_database):
        import api.database as db
        db.save_trace("abc123", 1, "conv_test")
        db.save_spans([{
            "trace_id": "abc123", "span_id": "abc123-1",
            "parent_span_id": None, "name": "root", "category": "root",
            "input": {"question": "test"}, "output": {"answer": "ok"},
            "start_time": 1000.0, "end_time": 1001.5, "duration_ms": 1500.0,
            "status": "ok", "error": None,
        }])
        trace = db.get_trace_by_id("abc123")
        assert trace is not None
        assert trace["trace_id"] == "abc123"
        assert trace["summary"]["span_count"] == 1

    def test_get_missing_trace(self, _patch_database):
        import api.database as db
        trace = db.get_trace_by_id("nonexistent")
        assert trace is None


class TestBatchDeleteTraces:
    def test_batch_delete_cascade_spans(self, _patch_database):
        import api.database as db
        db.save_trace("t_del1", 1, "conv_a")
        db.save_spans([{"trace_id": "t_del1", "span_id": "t_del1-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "ok", "error": None}])
        db.save_trace("t_del2", 2, "conv_b")
        db.save_spans([{"trace_id": "t_del2", "span_id": "t_del2-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "ok", "error": None}])
        db.save_trace("t_keep", 3, "conv_c")
        db.save_spans([{"trace_id": "t_keep", "span_id": "t_keep-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "ok", "error": None}])
        deleted = db.batch_delete_traces(["t_del1", "t_del2"])
        assert deleted == 2
        rows, total = db.search_traces(page=1, size=10)
        assert total == 1
        assert rows[0]["trace_id"] == "t_keep"


class TestCleanupTraces:
    def test_count_and_cleanup(self, _patch_database):
        import api.database as db
        db.save_trace("t1", 1, "conv_a")
        db.save_spans([{"trace_id": "t1", "span_id": "t1-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "ok", "error": None}])
        db.save_trace("t2", 2, "conv_b")
        db.save_spans([{"trace_id": "t2", "span_id": "t2-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "ok", "error": None}])
        db.save_trace("t3", 3, "conv_c", status="error")
        db.save_spans([{"trace_id": "t3", "span_id": "t3-1", "parent_span_id": None, "name": "root", "category": "root", "input": None, "output": None, "start_time": 1.0, "end_time": 2.0, "duration_ms": 1000.0, "status": "error", "error": "test error"}])
        count = db.count_traces_for_cleanup(start_date="2020-01-01", end_date="2099-12-31", status="ok")
        assert count == 2
        deleted = db.cleanup_traces(start_date="2020-01-01", end_date="2099-12-31", status="ok")
        assert deleted == 2
        _, remaining = db.search_traces(page=1, size=10)
        assert remaining == 1
