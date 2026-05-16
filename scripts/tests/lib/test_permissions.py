"""权限校验依赖测试。"""

import os
import asyncio
import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-testing-only")


@pytest.fixture(autouse=True)
def _reload_config():
    from lib.config import _get_config
    cfg = _get_config()
    cfg.reload()
    yield
    cfg.reload()


def test_require_permission_allows_authorized():
    from lib.auth.permissions import require_permission
    dep = require_permission("ask")
    result = asyncio.get_event_loop().run_until_complete(dep({"permissions": ["ask", "compliance"]}))
    assert result["permissions"] == ["ask", "compliance"]


def test_require_permission_denies_unauthorized():
    from lib.auth.permissions import require_permission
    from fastapi import HTTPException
    dep = require_permission("admin")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(dep({"permissions": ["ask"]}))
    assert exc_info.value.status_code == 403
