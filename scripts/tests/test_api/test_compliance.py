"""合规检查路由测试。"""

import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    mock_engine = MagicMock()
    mock_engine.search.return_value = [
        {"law_name": "保险法", "article_number": "第一条", "content": "法规内容",
         "category": "", "source_file": "test.md", "hierarchy_path": ""}
    ]
    mock_engine.ask.return_value = {
        "answer": json.dumps({
            "summary": {"compliant": 2, "non_compliant": 0, "attention": 1},
            "items": [
                {"param": "等待期", "value": "90天", "requirement": "≤180天",
                 "status": "compliant", "source": "[来源1]"},
                {"param": "免赔额", "value": "0元", "requirement": "无限制",
                 "status": "compliant", "source": "[来源1]"},
                {"param": "犹豫期", "value": "10天", "requirement": "≥15天",
                 "status": "attention", "source": "未找到明确法规限制"},
            ],
        }, ensure_ascii=False),
        "sources": mock_engine.search.return_value,
        "citations": [],
    }

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"category": "健康险", "waiting_period": "90天"}'

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None), \
         patch("api.app.rag_engine", mock_engine), \
         patch("lib.llm.factory.LLMClientFactory.get_qa_llm", return_value=mock_llm):
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


class TestProductCheck:
    def test_check_product(self, client):
        resp = client.post("/api/compliance/check/product", json={
            "product_name": "测试健康险A",
            "category": "健康险",
            "params": {"等待期": "90天", "免赔额": "0元", "保险期间": "1年"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "product"
        assert data["product_name"] == "测试健康险A"
        assert data["result"]["summary"]["compliant"] >= 1


class TestDocumentCheck:
    def test_check_document(self, client):
        resp = client.post("/api/compliance/check/document", json={
            "document_content": "# 测试健康保险条款\n\n等待期：自合同生效日起90天\n免赔额：0元",
            "product_name": "测试产品B",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "document"


class TestReportHistory:
    def test_list_reports(self, client):
        client.post("/api/compliance/check/product", json={
            "product_name": "测试产品", "category": "健康险", "params": {},
        })
        resp = client.get("/api/compliance/reports")
        assert len(resp.json()) == 1

    def test_get_report(self, client):
        resp = client.post("/api/compliance/check/product", json={
            "product_name": "测试产品", "category": "健康险", "params": {},
        })
        report_id = resp.json()["id"]
        resp = client.get(f"/api/compliance/reports/{report_id}")
        assert resp.status_code == 200

    def test_nonexistent_report(self, client):
        resp = client.get("/api/compliance/reports/nonexistent")
        assert resp.status_code == 404
