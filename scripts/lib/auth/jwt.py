"""JWT 编解码。"""

import os
from datetime import datetime, timedelta, timezone

import jwt

from lib.config import get_auth_config

_DEV_ONLY_JWT_SECRET = b"actuary-sleuth/dev-auth-skip-only/v1"


def _auth_skipped() -> bool:
    return os.getenv("AUTH_SKIP", "").lower() in {"true", "1"}


def get_jwt_signing_secret() -> bytes:
    """生产认证必须显式配置密钥；免认证开发模式使用固定隔离密钥。"""
    configured = get_auth_config().jwt_secret
    if configured:
        if not _auth_skipped() and len(configured.encode("utf-8")) < 32:
            raise RuntimeError(
                "AUTH_JWT_SECRET 至少需要32字节，认证服务拒绝启动"
            )
        return configured.encode("utf-8")
    if _auth_skipped():
        return _DEV_ONLY_JWT_SECRET
    raise RuntimeError("AUTH_JWT_SECRET 未配置，认证服务拒绝启动")


def validate_auth_configuration() -> None:
    """在应用启动阶段提前暴露不安全的认证配置。"""
    get_jwt_signing_secret()


def create_token(payload: dict) -> str:
    """创建 JWT token。payload 需包含 user_id, email, role_id, permissions。"""
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {**payload, "exp": expire}
    return jwt.encode(payload, get_jwt_signing_secret(), algorithm=cfg.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码并验证 JWT token。过期/无效时抛出异常。"""
    cfg = get_auth_config()
    return jwt.decode(
        token,
        get_jwt_signing_secret(),
        algorithms=[cfg.jwt_algorithm],
    )
