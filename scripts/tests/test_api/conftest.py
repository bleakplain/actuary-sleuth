"""API 测试公共 fixture。"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture()
def api_client(tmp_path):
    db_path = tmp_path / "test_api.db"

    mock_config = MagicMock()
    mock_config.data_paths.sqlite_db = str(db_path)

    with patch("lib.config.get_config", return_value=mock_config), \
         patch("lib.common.database._connection_pool", None), \
         patch("lib.common.connection_pool._global_pool", None):
        from lib.common import database as db_mod
        db_mod._connection_pool = None

        from api.database import init_db
        init_db()

        from api.app import app
        with TestClient(app) as client:
            yield client

    try:
        from lib.common import database as db_mod
        db_mod.close_pool()
    except Exception:
        pass
