"""Observability API 路由测试。"""
import pytest
from typing import Generator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient


@pytest.fixture()
def app_client(
    _patch_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from api.routers import observability
    test_app.include_router(observability.router)
    with TestClient(test_app) as client:
        yield client


def _create_trace_data(api_db):
    api_db.create_session("sess_test", "测试会话")
    msg_id = api_db.add_message("sess_test", "user", "什么是等待期？")
    api_db.add_message("sess_test", "assistant", "等待期是指...")
    span = {
        "trace_id": "trace_abc123", "span_id": "trace_abc123-1",
        "parent_span_id": None, "name": "root", "category": "root",
        "input": {"question": "什么是等待期？"}, "output": {"answer": "等待期是指..."},
        "start_time": 1000.0, "end_time": 1002.0, "duration_ms": 2000.0,
        "status": "ok", "error": None,
    }
    api_db.save_trace("trace_abc123", msg_id, "sess_test",
                       total_duration_ms=span["duration_ms"], span_count=1)
    api_db.save_spans([span])


class TestTraceListAPI:
    def test_list_traces_empty(self, app_client):
        resp = app_client.get("/api/observability/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_traces_with_data(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["trace_id"] == "trace_abc123"
        assert data["items"][0]["total_duration_ms"] == 2000.0

    def test_list_traces_filter_by_trace_id(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?trace_id=trace_abc123")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_traces_filter_by_trace_id_miss(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?trace_id=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_traces_filter_by_status(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces?status=ok")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestTraceDetailAPI:
    def test_get_trace_detail(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.get("/api/observability/traces/trace_abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "trace_abc123"
        assert data["summary"]["span_count"] == 1

    def test_get_trace_not_found(self, app_client):
        resp = app_client.get("/api/observability/traces/nonexistent")
        assert resp.status_code == 404


class TestTraceCleanupAPI:
    def test_cleanup_preview(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.post("/api/observability/traces/cleanup", json={
            "start_date": "2020-01-01", "end_date": "2099-12-31", "preview": True,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_cleanup_execute(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.post("/api/observability/traces/cleanup", json={
            "start_date": "2020-01-01", "end_date": "2099-12-31", "preview": False,
        })
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
        resp2 = app_client.get("/api/observability/traces")
        assert resp2.json()["total"] == 0

    def test_batch_delete_traces(self, app_client):
        import api.database as api_db
        _create_trace_data(api_db)
        resp = app_client.delete("/api/observability/traces?ids=trace_abc123")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
