"""问答路由测试。"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    mock_engine = MagicMock()
    mock_engine.search.return_value = [
        {"law_name": "保险法", "article_number": "第一条", "content": "测试内容",
         "category": "保险", "source_file": "test.md", "hierarchy_path": ""}
    ]
    mock_engine.ask.return_value = {
        "answer": "根据法规，等待期不超过180天。",
        "citations": [{"source_idx": 0, "law_name": "保险法", "article_number": "第一条", "content": "..."}],
        "sources": [{"law_name": "保险法", "article_number": "第一条", "content": "...",
                     "category": "", "source_file": "test.md", "hierarchy_path": ""}],
    }

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        with patch("api.app.rag_engine", mock_engine):
            from api.app import app
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestSearchMode:
    def test_search_returns_results(self, client):
        resp = client.post("/api/ask/chat", json={
            "question": "等待期多久",
            "mode": "search",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "search"
        assert len(data["sources"]) == 1


class TestConversationManagement:
    def test_list_empty_conversations(self, client):
        resp = client.get("/api/ask/conversations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_conversation_created_after_chat(self, client):
        client.post("/api/ask/chat", json={"question": "测试问题"})
        resp = client.get("/api/ask/conversations")
        convs = resp.json()
        assert len(convs) == 1

    def test_get_conversation_messages(self, client):
        resp = client.post("/api/ask/chat", json={"question": "测试", "mode": "search"})
        conv_id = resp.json()["conversation_id"]
        resp = client.get(f"/api/ask/conversations/{conv_id}/messages")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 2

    def test_delete_conversation(self, client):
        resp = client.post("/api/ask/chat", json={"question": "测试", "mode": "search"})
        conv_id = resp.json()["conversation_id"]
        resp = client.delete(f"/api/ask/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted_messages"] == 2

    def test_delete_nonexistent_conversation(self, client):
        resp = client.delete("/api/ask/conversations/nonexistent")
        assert resp.status_code == 404
