import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.database import (
    get_compliance_report,
    list_compliance_reports,
    save_compliance_report,
)
from api.routers.compliance import (
    delete_compliance_report,
    get_report,
    list_reports,
)


def _save(report_id: str, owner_user_id: str) -> None:
    save_compliance_report(
        report_id,
        f"{owner_user_id}产品",
        "健康险",
        "document",
        {"summary": {}},
        owner_user_id,
    )


def test_existing_report_table_migrates_owner_without_losing_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.database as api_db
    import lib.common.connection_pool as pool_mod
    import lib.common.database as db_mod

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            CREATE TABLE compliance_reports (
                id TEXT PRIMARY KEY,
                product_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL CHECK(mode IN ('product', 'document')),
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        connection.execute(
            "INSERT INTO compliance_reports "
            "(id, product_name, category, mode, result_json) "
            "VALUES ('legacy', '历史产品', '健康险', 'document', '{}')"
        )

    pool_mod.reset_connection_pool()
    db_mod._connection_pool = None
    monkeypatch.setattr(db_mod, "get_sqlite_db_path", lambda: str(db_path))
    monkeypatch.setattr(db_mod, "get_db_path", lambda: db_path)
    pool_mod.get_connection_pool(
        db_path=db_path,
        pool_size=2,
        max_overflow=2,
    )
    try:
        api_db.init_db()
        legacy = api_db.get_compliance_report("legacy")
        assert legacy is not None
        assert legacy["owner_user_id"] == ""
        with db_mod.get_connection() as connection:
            indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(compliance_reports)"
                ).fetchall()
            }
        assert "idx_compliance_reports_owner" in indexes
    finally:
        pool_mod.reset_connection_pool()
        db_mod._connection_pool = None


def test_database_report_queries_are_owner_scoped(
    _patch_database: None,
) -> None:
    _save("report-a", "user-a")
    _save("report-b", "user-b")

    assert [item["id"] for item in list_compliance_reports("user-a")] == [
        "report-a"
    ]
    assert get_compliance_report("report-b", "user-a") is None
    assert get_compliance_report("report-b", "user-b") is not None
    assert {item["id"] for item in list_compliance_reports()} == {
        "report-a",
        "report-b",
    }


@pytest.mark.asyncio
async def test_report_routes_hide_other_users_and_allow_admin_governance(
    _patch_database: None,
) -> None:
    _save("report-a", "user-a")
    _save("report-b", "user-b")
    user_a = {"user_id": "user-a", "role_id": "actuary"}
    admin = {"user_id": "admin", "role_id": "admin"}

    assert [item["id"] for item in await list_reports(user_a)] == ["report-a"]
    with pytest.raises(HTTPException) as exc_info:
        await get_report("report-b", user_a)
    assert exc_info.value.status_code == 404
    assert {item["id"] for item in await list_reports(admin)} == {
        "report-a",
        "report-b",
    }

    with pytest.raises(HTTPException) as exc_info:
        await delete_compliance_report("report-b", user_a)
    assert exc_info.value.status_code == 404
    assert await delete_compliance_report("report-b", admin) == {
        "status": "deleted"
    }
