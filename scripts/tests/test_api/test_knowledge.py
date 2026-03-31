"""知识库管理路由测试。"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def client(tmp_path):
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    (refs_dir / "01_保险法.md").write_text("# 保险法\n\n第一条 为了规范保险活动...", encoding="utf-8")
    (refs_dir / "02_健康险.md").write_text("# 健康保险管理办法\n\n第一条 ...", encoding="utf-8")

    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)
    mock_config.regulations_dir = str(refs_dir)

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None), \
         patch("lib.rag_engine.config.get_config", return_value=mock_config):
        from lib.common import database as db_mod
        db_mod._connection_pool = None
        from api.database import init_db
        init_db()

        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c

    try:
        db_mod.close_pool()
    except Exception:
        pass


class TestListDocuments:
    def test_list_documents(self, client):
        resp = client.get("/api/kb/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 2
        assert docs[0]["name"] == "01_保险法.md"

    def test_document_has_metadata(self, client):
        resp = client.get("/api/kb/documents")
        doc = resp.json()[0]
        assert "file_size" in doc
        assert "clause_count" in doc
        assert doc["file_size"] > 0


class TestPreviewDocument:
    def test_preview_existing(self, client):
        resp = client.get("/api/kb/documents/01_保险法.md/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert "保险法" in data["content"]
        assert data["total_chars"] > 0

    def test_preview_nonexistent(self, client):
        resp = client.get("/api/kb/documents/nonexistent.md/preview")
        assert resp.status_code == 404


class TestTaskStatus:
    def test_nonexistent_task(self, client):
        resp = client.get("/api/kb/tasks/nonexistent")
        assert resp.status_code == 404
