"""JWT 编解码测试。"""

import os
import time

import pytest

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-testing-only")


@pytest.fixture(autouse=True)
def _reload_config():
    from lib.config import _get_config
    cfg = _get_config()
    cfg.reload()
    yield
    cfg.reload()


def test_create_and_decode_token():
    from lib.auth.jwt import create_token, decode_token
    payload = {"user_id": "u1", "email": "a@b.c", "role_id": "viewer", "permissions": ["ask"]}
    token = create_token(payload)
    decoded = decode_token(token)
    assert decoded["user_id"] == "u1"
    assert decoded["email"] == "a@b.c"
    assert decoded["role_id"] == "viewer"
    assert decoded["permissions"] == ["ask"]
    assert "exp" in decoded


def test_decode_expired_token():
    from lib.auth.jwt import create_token, decode_token
    import jwt
    os.environ["AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"] = "0"
    from lib.config import _get_config
    _get_config().reload()
    payload = {"user_id": "u1", "email": "a@b.c", "role_id": "viewer", "permissions": ["ask"]}
    token = create_token(payload)
    time.sleep(1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)
    os.environ.pop("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", None)
    _get_config().reload()


def test_decode_invalid_token():
    from lib.auth.jwt import decode_token
    import jwt
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("invalid.token.here")


def test_missing_secret_fails_closed_when_auth_is_enabled(monkeypatch):
    from lib.auth.jwt import create_token
    from lib.config import _get_config

    with monkeypatch.context() as scoped:
        scoped.delenv("AUTH_JWT_SECRET", raising=False)
        scoped.delenv("AUTH_SKIP", raising=False)
        _get_config().reload()
        with pytest.raises(RuntimeError, match="AUTH_JWT_SECRET"):
            create_token({"user_id": "u1"})
    _get_config().reload()


def test_short_secret_fails_closed_when_auth_is_enabled(monkeypatch):
    from lib.auth.jwt import create_token
    from lib.config import _get_config

    with monkeypatch.context() as scoped:
        scoped.setenv("AUTH_JWT_SECRET", "too-short")
        scoped.delenv("AUTH_SKIP", raising=False)
        _get_config().reload()
        with pytest.raises(RuntimeError, match="至少需要32字节"):
            create_token({"user_id": "u1"})
    _get_config().reload()
