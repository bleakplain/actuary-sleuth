"""评估路由测试。"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None), \
         patch("api.routers.eval._ensure_default_dataset"):
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


class TestEvalSamplesCRUD:
    def test_create_sample(self, client):
        resp = client.post("/api/eval/dataset/samples", json={
            "id": "f001",
            "question": "健康保险等待期最长多少天？",
            "ground_truth": "180天",
            "question_type": "factual",
            "difficulty": "easy",
            "topic": "健康保险",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "f001"

    def test_list_samples(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1", "question_type": "factual",
        })
        resp = client.get("/api/eval/dataset")
        assert len(resp.json()) == 1

    def test_filter_by_type(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1", "question_type": "factual",
        })
        client.post("/api/eval/dataset/samples", json={
            "id": "m001", "question": "q2", "question_type": "multi_hop",
        })
        resp = client.get("/api/eval/dataset?question_type=factual")
        assert len(resp.json()) == 1

    def test_update_sample(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1",
        })
        resp = client.put("/api/eval/dataset/samples/f001", json={
            "id": "f001", "question": "q1-updated",
        })
        assert resp.status_code == 200
        assert resp.json()["question"] == "q1-updated"

    def test_update_nonexistent(self, client):
        resp = client.put("/api/eval/dataset/samples/nonexistent", json={
            "id": "nonexistent", "question": "q",
        })
        assert resp.status_code == 404

    def test_delete_sample(self, client):
        client.post("/api/eval/dataset/samples", json={
            "id": "f001", "question": "q1",
        })
        resp = client.delete("/api/eval/dataset/samples/f001")
        assert resp.status_code == 200
        assert len(client.get("/api/eval/dataset").json()) == 0

    def test_import_samples(self, client):
        resp = client.post("/api/eval/dataset/import", json={
            "samples": [
                {"id": "f001", "question": "q1"},
                {"id": "f002", "question": "q2"},
            ]
        })
        assert resp.json()["imported"] == 2


class TestSnapshots:
    def test_create_and_list(self, client):
        client.post("/api/eval/dataset/samples", json={"id": "f001", "question": "q1"})
        resp = client.post("/api/eval/dataset/snapshots", json={
            "name": "v1", "description": "初始版本",
        })
        assert resp.status_code == 200
        snap_id = resp.json()["snapshot_id"]

        resp = client.get("/api/eval/dataset/snapshots")
        assert len(resp.json()) == 1

    def test_restore(self, client):
        client.post("/api/eval/dataset/samples", json={"id": "f001", "question": "q1"})
        client.post("/api/eval/dataset/samples", json={"id": "f002", "question": "q2"})
        resp = client.post("/api/eval/dataset/snapshots", json={"name": "v1"})
        snap_id = resp.json()["snapshot_id"]

        client.delete("/api/eval/dataset/samples/f002")
        assert len(client.get("/api/eval/dataset").json()) == 1

        resp = client.post(f"/api/eval/dataset/snapshots/{snap_id}/restore")
        assert resp.json()["restored"] == 2
        assert len(client.get("/api/eval/dataset").json()) == 2


class TestEvalRuns:
    def test_create_run(self, client):
        resp = client.post("/api/eval/runs", json={
            "mode": "retrieval", "top_k": 5,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
        run_id = resp.json()["run_id"]

        resp = client.get(f"/api/eval/runs/{run_id}/status")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "retrieval"

    def test_list_runs(self, client):
        client.post("/api/eval/runs", json={"mode": "retrieval"})
        resp = client.get("/api/eval/runs")
        assert len(resp.json()) == 1

    def test_nonexistent_run(self, client):
        resp = client.get("/api/eval/runs/nonexistent/status")
        assert resp.status_code == 404

    def test_compare_runs(self, client):
        from api.database import create_eval_run, save_eval_report
        create_eval_run("run-a", "full", {})
        save_eval_report("run-a", {
            "retrieval": {"precision_at_k": 0.6, "recall_at_k": 0.5},
            "generation": {"faithfulness": 0.8},
        })
        create_eval_run("run-b", "full", {})
        save_eval_report("run-b", {
            "retrieval": {"precision_at_k": 0.8, "recall_at_k": 0.6},
            "generation": {"faithfulness": 0.9},
        })

        resp = client.post("/api/eval/runs/compare", json={
            "baseline_id": "run-a",
            "compare_id": "run-b",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["improved"]) >= 1
