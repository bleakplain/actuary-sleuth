"""API 集成测试 — 共享 fixtures。

使用临时 SQLite 数据库，不依赖真实配置或 RAG 引擎。
"""
import sqlite3
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """返回临时 SQLite 数据库路径（文件数据库，支持 WAL）。"""
    return tmp_path / "test.db"


@pytest.fixture()
def db_conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """创建原生 SQLite 连接，用于直接操作测试数据库。"""
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    yield conn
    conn.close()


@pytest.fixture()
def _patch_database(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """将 api.database.get_connection 和 lib.common.database 指向临时数据库。"""
    import lib.common.database as db_mod
    import lib.common.connection_pool as pool_mod
    import api.database as api_db

    # 重置全局连接池
    pool_mod._global_pool = None
    db_mod._connection_pool = None

    # 用临时路径替换数据库路径
    monkeypatch.setattr(db_mod, "get_sqlite_db_path", lambda: str(db_path))
    monkeypatch.setattr(db_mod, "get_db_path", lambda: db_path)

    # 重新初始化连接池
    pool_mod.get_connection_pool(
        db_path=db_path, pool_size=2, max_overflow=2
    )

    # 建表
    api_db.init_db()

    yield

    # 清理连接池
    pool_mod.reset_connection_pool()
    db_mod.close_pool()


@pytest.fixture()
def mock_rag_engine(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock RAG 引擎，返回固定问答结果。"""
    engine = MagicMock()
    engine.ask.return_value = {
        "answer": "根据法规，健康保险等待期不得超过90天。",
        "sources": [
            {
                "law_name": "健康保险管理办法",
                "article_number": "第一条",
                "category": "健康保险",
                "content": "健康保险产品的等待期不得超过90天。",
                "source_file": "health_insurance.md",
                "hierarchy_path": "",
                "score": 0.95,
            }
        ],
        "citations": [
            {
                "source_idx": 1,
                "law_name": "健康保险管理办法",
                "article_number": "第一条",
                "content": "健康保险产品的等待期不得超过90天。",
            }
        ],
        "unverified_claims": [],
        "faithfulness_score": 0.95,
    }
    engine.search.return_value = engine.ask.return_value["sources"]
    monkeypatch.setattr("api.dependencies.get_rag_engine", lambda: engine)
    return engine


@pytest.fixture()
def app_client(
    _patch_database: None,
    mock_rag_engine: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """创建测试用 FastAPI TestClient，跳过 lifespan。"""
    # 跳过 eval 默认数据集初始化
    monkeypatch.setattr(
        "api.routers.eval._ensure_default_dataset", lambda: None
    )

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from api.routers import ask, feedback
    test_app.include_router(ask.router)
    test_app.include_router(feedback.router)

    with TestClient(test_app) as client:
        yield client


# ===== 测试数据工厂 fixtures =====

@pytest.fixture()
def make_conversation():
    """创建对话的工厂 fixture。"""
    import api.database as api_db

    def _create(
        conversation_id: str = "conv_test1",
        title: str = "测试对话",
    ) -> Dict[str, Any]:
        api_db.create_conversation(conversation_id, title)
        return {"id": conversation_id, "title": title}

    return _create


@pytest.fixture()
def make_message():
    """创建消息的工厂 fixture。"""
    import api.database as api_db

    def _create(
        conversation_id: str = "conv_test1",
        role: str = "assistant",
        content: str = "测试回答",
    ) -> int:
        return api_db.add_message(conversation_id, role, content)

    return _create
