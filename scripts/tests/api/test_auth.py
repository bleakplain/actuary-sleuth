"""认证端点集成测试。"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminP@ss1")


@pytest.fixture(scope="module", autouse=True)
def _reset_pools():
    from lib.common.database import close_pool
    from lib.config import _get_config
    close_pool()
    _get_config().reload()
    yield
    close_pool()


@pytest.fixture(scope="module")
def client(_reset_pools):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        os.environ["DATA_PATHS_SQLITE_DB"] = db_path
        os.environ["DATA_PATHS_EVAL_SNAPSHOTS_DIR"] = os.path.join(tmpdir, "snapshots")
        os.environ["DATA_PATHS_MEMORY_DIR"] = os.path.join(tmpdir, "memory")
        from lib.common.database import close_pool
        from lib.config import _get_config
        close_pool()
        _get_config().reload()
        from api.app import app
        with TestClient(app) as c:
            yield c
        os.environ.pop("DATA_PATHS_SQLITE_DB", None)
        os.environ.pop("DATA_PATHS_EVAL_SNAPSHOTS_DIR", None)
        os.environ.pop("DATA_PATHS_MEMORY_DIR", None)


@pytest.fixture(scope="module")
def admin_token(client):
    """获取管理员 JWT token。"""
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "AdminP@ss1"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_success(client, admin_token):
    assert admin_token


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post("/api/auth/login", json={"email": "nobody@test.com", "password": "whatever"})
    assert resp.status_code == 401


def test_unauthorized_access(client):
    resp = client.get("/api/ask/sessions")
    assert resp.status_code == 401


def test_get_me(client, admin_token):
    resp = client.get("/api/auth/me", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role_id"] == "admin"


def test_change_password(client, admin_token):
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "AdminP@ss1", "new_password": "AdminP@ss1"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200


def test_forgot_password_silent_success(client):
    """不存在的邮箱也返回成功（不泄露用户存在）。"""
    resp = client.post("/api/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200


def test_reset_password_invalid_token(client):
    resp = client.post("/api/auth/reset-password", json={"token": "invalid", "new_password": "NewP@ss1"})
    assert resp.status_code == 400


def test_register_with_invite_code(client, admin_token):
    """完整注册流程：创建邀请码 → 注册 → 未验证登录失败 → 管理员激活 → 登录成功。"""
    code_resp = client.post(
        "/api/admin/invite-codes",
        json={"role_id": "viewer", "expires_hours": 72},
        headers=_auth(admin_token),
    )
    invite_code = code_resp.json()["code"]
    reg_resp = client.post("/api/auth/register", json={
        "email": "newuser@test.com",
        "password": "UserP@ss1",
        "invite_code": invite_code,
    })
    assert reg_resp.status_code == 201
    login_resp = client.post("/api/auth/login", json={"email": "newuser@test.com", "password": "UserP@ss1"})
    assert login_resp.status_code == 403
    users_resp = client.get("/api/admin/users", headers=_auth(admin_token))
    new_user = next(u for u in users_resp.json() if u["email"] == "newuser@test.com")
    client.patch(
        f"/api/admin/users/{new_user['id']}",
        json={"email_verified": True},
        headers=_auth(admin_token),
    )
    login_resp2 = client.post("/api/auth/login", json={"email": "newuser@test.com", "password": "UserP@ss1"})
    assert login_resp2.status_code == 200


def test_register_duplicate_email(client, admin_token):
    """重复邮箱注册失败。"""
    code_resp = client.post(
        "/api/admin/invite-codes",
        json={"role_id": "viewer", "expires_hours": 72},
        headers=_auth(admin_token),
    )
    invite_code = code_resp.json()["code"]
    resp = client.post("/api/auth/register", json={
        "email": "admin@test.com",
        "password": "UserP@ss1",
        "invite_code": invite_code,
    })
    assert resp.status_code == 400


def test_register_invalid_invite_code(client):
    """无效邀请码注册失败。"""
    resp = client.post("/api/auth/register", json={
        "email": "another@test.com",
        "password": "UserP@ss1",
        "invite_code": "INVALID1",
    })
    assert resp.status_code == 400


def test_brute_force_lockout(client, admin_token):
    """连续 5 次错误密码后锁定。"""
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "AdminP@ss1"})
    assert resp.status_code == 429


# ===== Admin endpoints =====

def test_list_roles(client, admin_token):
    resp = client.get("/api/admin/roles", headers=_auth(admin_token))
    assert resp.status_code == 200
    roles = {r["id"] for r in resp.json()}
    assert roles == {"admin", "actuary", "compliance", "viewer"}


def test_create_invite_code(client, admin_token):
    resp = client.post(
        "/api/admin/invite-codes",
        json={"role_id": "viewer", "expires_hours": 72},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role_id"] == "viewer"
    assert len(data["code"]) == 8


def test_list_users(client, admin_token):
    resp = client.get("/api/admin/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_admin_cannot_disable_self(client, admin_token):
    me = client.get("/api/auth/me", headers=_auth(admin_token)).json()
    resp = client.patch(
        f"/api/admin/users/{me['id']}",
        json={"status": "disabled"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400
