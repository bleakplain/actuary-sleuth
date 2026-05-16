"""JWT 编解码。"""

from datetime import datetime, timedelta, timezone

import jwt

from lib.config import get_auth_config


def create_token(payload: dict) -> str:
    """创建 JWT token。payload 需包含 user_id, email, role_id, permissions。"""
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(minutes=cfg.access_token_expire_minutes)
    payload = {**payload, "exp": expire}
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码并验证 JWT token。过期/无效时抛出异常。"""
    cfg = get_auth_config()
    return jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
