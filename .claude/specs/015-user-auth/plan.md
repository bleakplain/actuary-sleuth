# Implementation Plan: 用户认证与权限控制

**Branch**: `015-user-auth` | **Date**: 2026-05-10 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

为 actuary-sleuth 添加完整的用户认证与权限控制系统：邀请码注册 + 邮箱验证 + JWT 登录 + RBAC 权限校验 + 管理后台。当前系统零认证，66 个 API 端点公开访问。技术方案采用 PyJWT + OAuth2PasswordBearer + argon2-cffi + aiosmtplib，通过 FastAPI `Depends()` 逐路由添加权限校验，6 张新表放入 `_migrate_db()` 增量迁移，4 个预置角色覆盖 ask/compliance/eval/knowledge/memory/admin 权限。

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: fastapi>=0.104.0, PyJWT>=2.9.0, argon2-cffi>=23.1.0, aiosmtplib>=3.0.0
**Storage**: SQLite (WAL mode, busy_timeout=30s, 连接池 pool_size=5/max_overflow=10)
**Testing**: pytest
**Performance Goals**: 认证校验 <5ms (JWT decode + DB user status check)
**Constraints**: 原生 SQL（非 ORM）；配置全部来自环境变量；DDL 放入 `_migrate_db()`

## Constitution Check

- [x] **Library-First**: PyJWT/argon2-cffi/aiosmtplib 均为成熟库；复用现有 `get_connection()` 连接池、`_migrate_db()` 迁移模式、`Config` 嵌套配置类模式
- [x] **测试优先**: 每个核心模块（JWT、密码哈希、权限校验、注册/登录流程）均规划了测试
- [x] **简单优先**: 逐路由 `Depends()` 而非全局中间件；单角色单用户；无 refresh token；无 JWT 黑名单
- [x] **显式优于隐式**: 每个受保护端点显式声明 `Depends(require_permission("xxx"))`；user_id 从 JWT 注入而非请求参数
- [x] **可追溯性**: 每个 Phase 标注对应 spec.md User Story
- [x] **独立可测试**: 6 个 User Story 按优先级分 3 个 Phase，每个 Phase 可独立验证

## Project Structure

### Documentation

```text
.claude/specs/015-user-auth/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── lib/
│   ├── auth/              # 新增：认证核心逻辑
│   │   ├── __init__.py
│   │   ├── jwt.py         # JWT 编解码
│   │   ├── password.py    # 密码哈希/验证
│   │   └── permissions.py # 权限校验依赖
│   └── mail/              # 新增：邮件服务
│       ├── __init__.py
│       └── smtp.py        # SMTP 邮件发送
├── api/
│   ├── routers/
│   │   ├── auth.py        # 新增：认证端点
│   │   ├── admin.py       # 新增：管理端点
│   │   ├── ask.py         # 修改：添加权限校验
│   │   ├── compliance.py  # 修改：添加权限校验
│   │   ├── eval.py        # 修改：添加权限校验
│   │   ├── knowledge.py   # 修改：添加权限校验
│   │   ├── kb_version.py  # 修改：添加权限校验
│   │   ├── feedback.py    # 修改：添加权限校验
│   │   ├── observability.py # 修改：添加权限校验
│   │   └── memory.py      # 修改：添加权限校验 + user_id 注入
│   ├── schemas/
│   │   ├── auth.py        # 新增：认证 schemas
│   │   └── admin.py       # 新增：管理 schemas
│   ├── database.py        # 修改：新增 6 张表 + 数据访问函数
│   ├── dependencies.py    # 修改：新增 get_current_user
│   └── app.py             # 修改：include auth/admin 路由 + 启动初始化
├── lib/config.py          # 修改：新增 AuthConfig + MailConfig
├── .env.example           # 修改：新增认证/邮件环境变量
└── requirements.txt       # 修改：新增 3 个依赖
```

## Implementation Phases

### Phase 1: 基础设施 — 认证核心 + 数据库

#### 需求回溯

→ 对应 spec.md User Story 2 (P1): 用户登录
→ 对应 spec.md FR-004: 邮箱+密码登录，返回 JWT Token
→ 对应 spec.md FR-009: 防止登录暴力破解

#### 实现步骤

**步骤 1.1: 新增依赖**

- 文件: `scripts/requirements.txt`
- 追加:

```
# Auth dependencies
PyJWT>=2.9.0
argon2-cffi>=23.1.0
aiosmtplib>=3.0.0
```

**步骤 1.2: 新增 AuthConfig + MailConfig**

- 文件: `scripts/lib/config.py`
- 在 `RerankConfig` 类之后、`Config` 类之前新增两个配置类:

```python
class AuthConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('auth', {})

    @property
    def jwt_secret(self) -> str:
        return self._config.get('jwt_secret', '')

    @property
    def jwt_algorithm(self) -> str:
        return self._config.get('jwt_algorithm', 'HS256')

    @property
    def access_token_expire_minutes(self) -> int:
        return self._config.get('access_token_expire_minutes', 480)

    @property
    def max_login_attempts(self) -> int:
        return self._config.get('max_login_attempts', 5)

    @property
    def lockout_minutes(self) -> int:
        return self._config.get('lockout_minutes', 15)


class MailConfig:

    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('mail', {})

    @property
    def smtp_host(self) -> str:
        return self._config.get('smtp_host', '')

    @property
    def smtp_port(self) -> int:
        return self._config.get('smtp_port', 465)

    @property
    def smtp_user(self) -> str:
        return self._config.get('smtp_user', '')

    @property
    def smtp_password(self) -> str:
        return self._config.get('smtp_password', '')

    @property
    def from_address(self) -> str:
        return self._config.get('from_address', '')

    @property
    def enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user)
```

- 在 `Config._load()` 中追加 `auth` 和 `mail` 配置节:

```python
            # auth
            'auth': {
                'jwt_secret': os.getenv('AUTH_JWT_SECRET', ''),
                'jwt_algorithm': os.getenv('AUTH_JWT_ALGORITHM', 'HS256'),
                'access_token_expire_minutes': int(os.getenv('AUTH_ACCESS_TOKEN_EXPIRE_MINUTES', '480')),
                'max_login_attempts': int(os.getenv('AUTH_MAX_LOGIN_ATTEMPTS', '5')),
                'lockout_minutes': int(os.getenv('AUTH_LOCKOUT_MINUTES', '15')),
            },
            # mail
            'mail': {
                'smtp_host': os.getenv('MAIL_SMTP_HOST', ''),
                'smtp_port': int(os.getenv('MAIL_SMTP_PORT', '465')),
                'smtp_user': os.getenv('MAIL_SMTP_USER', ''),
                'smtp_password': os.getenv('MAIL_SMTP_PASSWORD', ''),
                'from_address': os.getenv('MAIL_FROM_ADDRESS', ''),
            },
```

- 在 `Config._init_nested_configs()` 中追加:

```python
        self._auth = AuthConfig(self._config)
        self._mail = MailConfig(self._config)
```

- 在 `Config` 类中追加属性:

```python
    @property
    def auth(self) -> AuthConfig:
        return self._auth

    @property
    def mail(self) -> MailConfig:
        return self._mail
```

- 在模块级快捷函数区追加:

```python
def get_auth_config() -> AuthConfig:
    return _get_config().auth

def get_mail_config() -> MailConfig:
    return _get_config().mail
```

**步骤 1.3: 新增 lib/auth/ 模块**

- 文件: `scripts/lib/auth/__init__.py`

```python
"""认证核心逻辑。"""
```

- 文件: `scripts/lib/auth/jwt.py`

```python
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
```

- 文件: `scripts/lib/auth/password.py`

```python
"""密码哈希与验证（argon2id）。"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1)


def hash_password(password: str) -> str:
    """对密码进行 argon2id 哈希。"""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配哈希。"""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
```

- 文件: `scripts/lib/auth/permissions.py`

```python
"""FastAPI 权限校验依赖。"""

from fastapi import Depends, HTTPException

from api.dependencies import get_current_user


def require_permission(permission: str):
    """FastAPI 依赖：校验当前用户是否拥有指定权限。"""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if permission not in user.get("permissions", []):
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return _check
```

**步骤 1.4: 新增 lib/mail/ 模块**

- 文件: `scripts/lib/mail/__init__.py`

```python
"""邮件发送服务。"""
```

- 文件: `scripts/lib/mail/smtp.py`

```python
"""SMTP 邮件发送。"""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from lib.config import get_mail_config

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """发送 HTML 邮件。返回 True 表示成功，False 表示失败。"""
    cfg = get_mail_config()
    if not cfg.enabled:
        logger.warning("邮件服务未配置，邮件未发送")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = cfg.from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user,
            password=cfg.smtp_password,
            use_tls=True,
        )
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


async def send_verification_email(email: str, token: str) -> bool:
    """发送邮箱验证邮件。"""
    verify_url = f"/api/auth/verify-email?token={token}"
    html = f'<p>请点击以下链接验证邮箱：</p><p><a href="{verify_url}">验证邮箱</a></p><p>链接 24 小时内有效。</p>'
    return await send_email(email, "邮箱验证 - Actuary Sleuth", html)


async def send_reset_email(email: str, token: str) -> bool:
    """发送密码重置邮件。"""
    reset_url = f"/reset-password?token={token}"
    html = f'<p>请点击以下链接重置密码：</p><p><a href="{reset_url}">重置密码</a></p><p>链接 24 小时内有效。</p>'
    return await send_email(email, "密码重置 - Actuary Sleuth", html)
```

**步骤 1.5: 数据库层 — 新增 6 张表 + 数据访问函数**

- 文件: `scripts/api/database.py`
- 在 `_migrate_db()` 函数末尾追加 auth 表 DDL:

```python
        # ===== Auth tables =====
        conn.execute("""
        CREATE TABLE IF NOT EXISTS roles (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            permissions_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            role_id TEXT NOT NULL REFERENCES roles(id),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'disabled')),
            email_verified_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            role_id TEXT NOT NULL REFERENCES roles(id),
            created_by TEXT NOT NULL REFERENCES users(id),
            used_by TEXT REFERENCES users(id),
            used_at TEXT,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            verified_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_verify_hash ON email_verification_tokens(token_hash)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash ON password_reset_tokens(token_hash)")
```

- 在 `api/database.py` 文件末尾追加数据访问函数:

```python
# ===== Auth data access functions =====

def get_user_by_email(email: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_user(email: str, password_hash: str, role_id: str, status: str = 'pending') -> str:
    user_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role_id, status) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, password_hash, role_id, status),
        )
    return user_id


def update_user_status(user_id: str, status: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, user_id),
        )
    return cursor.rowcount > 0


def update_user_role(user_id: str, role_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET role_id = ?, updated_at = datetime('now') WHERE id = ?",
            (role_id, user_id),
        )
    return cursor.rowcount > 0


def update_user_password(user_id: str, password_hash: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (password_hash, user_id),
        )
    return cursor.rowcount > 0


def verify_user_email(user_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET email_verified_at = datetime('now'), status = 'active', updated_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
    return cursor.rowcount > 0


def list_users() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, email, display_name, role_id, status, email_verified_at, created_at FROM users ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_user_display_name(user_id: str, display_name: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET display_name = ?, updated_at = datetime('now') WHERE id = ?",
            (display_name, user_id),
        )
    return cursor.rowcount > 0


# ===== Role data access =====

def get_role(role_id: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        return dict(row) if row else None


def list_roles() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM roles ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def update_role_permissions(role_id: str, permissions: List[str]) -> bool:
    import json
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE roles SET permissions_json = ? WHERE id = ?",
            (json.dumps(permissions), role_id),
        )
    return cursor.rowcount > 0


def ensure_default_roles() -> None:
    """启动时插入 4 个预置角色（幂等）。"""
    defaults = [
        ('admin', '管理员', json.dumps(['ask', 'compliance', 'eval', 'knowledge', 'memory', 'admin'])),
        ('actuary', '精算师', json.dumps(['ask', 'compliance', 'memory'])),
        ('compliance', '合规专员', json.dumps(['ask', 'compliance', 'memory'])),
        ('viewer', '查看者', json.dumps(['ask'])),
    ]
    with get_connection() as conn:
        for role_id, display_name, perms in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO roles (id, display_name, permissions_json) VALUES (?, ?, ?)",
                (role_id, display_name, perms),
            )


def ensure_default_admin() -> None:
    """若 users 表为空，从环境变量创建默认管理员。"""
    import os
    from lib.auth.password import hash_password
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return
    email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    password = os.getenv('ADMIN_PASSWORD', '')
    if not password:
        logger.warning("ADMIN_PASSWORD 未设置，跳过默认管理员创建")
        return
    user_id = create_user(email, hash_password(password), 'admin', status='active')
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET email_verified_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
    logger.info(f"默认管理员已创建: {email}")


# ===== Invite code data access =====

def create_invite_code(code: str, role_id: str, created_by: str, expires_at: str) -> str:
    code_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO invite_codes (id, code, role_id, created_by, expires_at) VALUES (?, ?, ?, ?, ?)",
            (code_id, code, role_id, created_by, expires_at),
        )
    return code_id


def get_invite_code_by_code(code: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None


def use_invite_code(code_id: str, used_by: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE invite_codes SET used_by = ?, used_at = datetime('now') WHERE id = ? AND used_by IS NULL",
            (used_by, code_id),
        )
    return cursor.rowcount > 0


def list_invite_codes() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM invite_codes ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def disable_invite_code(code_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE invite_codes SET expires_at = datetime('now') WHERE id = ? AND used_by IS NULL",
            (code_id,),
        )
    return cursor.rowcount > 0


# ===== Email verification token data access =====

def create_email_token(user_id: str, token_hash: str, expires_at: str) -> str:
    token_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO email_verification_tokens (id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
            (token_id, user_id, token_hash, expires_at),
        )
    return token_id


def get_email_token_by_hash(token_hash: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_verification_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(row) if row else None


def verify_email_token(token_hash: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE email_verification_tokens SET verified_at = datetime('now') WHERE token_hash = ? AND verified_at IS NULL",
            (token_hash,),
        )
    return cursor.rowcount > 0


def invalidate_pending_email_tokens(user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM email_verification_tokens WHERE user_id = ? AND verified_at IS NULL",
            (user_id,),
        )


# ===== Password reset token data access =====

def create_reset_token(user_id: str, token_hash: str, expires_at: str) -> str:
    token_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
            (token_id, user_id, token_hash, expires_at),
        )
    return token_id


def get_reset_token_by_hash(token_hash: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(row) if row else None


def use_reset_token(token_hash: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE token_hash = ? AND used_at IS NULL",
            (token_hash,),
        )
    return cursor.rowcount > 0


# ===== Login attempt data access =====

def record_login_attempt(email: str, success: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO login_attempts (email, success) VALUES (?, ?)",
            (email, 1 if success else 0),
        )


def get_recent_failed_attempts(email: str, minutes: int = 15) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE email = ? AND success = 0 AND attempted_at > datetime('now', ?)",
            (email, f'-{minutes} minutes'),
        ).fetchone()
    return row[0]
```

**步骤 1.6: 新增 get_current_user 依赖**

- 文件: `scripts/api/dependencies.py`
- 追加:

```python
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from lib.auth.jwt import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """从 JWT 解析当前用户。返回 {user_id, email, role_id, permissions}。"""
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="无效的认证凭据")
    from api.database import get_user_by_id
    user = get_user_by_id(payload["user_id"])
    if not user or user["status"] != "active":
        raise HTTPException(status_code=401, detail="账户已被禁用")
    return payload
```

**步骤 1.7: 新增 Schemas**

- 文件: `scripts/api/schemas/auth.py`

```python
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')
    password: str = Field(..., min_length=8, max_length=128)
    invite_code: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role_id: str
    status: str
    email_verified_at: str | None
    created_at: str


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class ResendVerificationRequest(BaseModel):
    email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')
```

- 文件: `scripts/api/schemas/admin.py`

```python
from pydantic import BaseModel, Field


class InviteCodeCreate(BaseModel):
    role_id: str = Field(..., pattern=r'^(admin|actuary|compliance|viewer)$')
    expires_hours: int = Field(72, ge=1, le=720)


class InviteCodeOut(BaseModel):
    id: str
    code: str
    role_id: str
    created_by: str
    used_by: str | None
    used_at: str | None
    expires_at: str
    created_at: str


class UserUpdate(BaseModel):
    status: str | None = Field(None, pattern=r'^(active|disabled)$')
    role_id: str | None = None
    display_name: str | None = None
    password: str | None = Field(None, min_length=8, max_length=128)
    email_verified: bool | None = None


class RoleUpdate(BaseModel):
    permissions: list[str]
```

**步骤 1.8: 更新 .env.example**

- 文件: `scripts/.env.example`
- 追加:

```
# ===== 认证 =====
# AUTH_JWT_SECRET=            # 必填，256-bit 随机密钥
# AUTH_JWT_ALGORITHM=HS256
# AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=480
# AUTH_MAX_LOGIN_ATTEMPTS=5
# AUTH_LOCKOUT_MINUTES=15
# ADMIN_EMAIL=admin@example.com
# ADMIN_PASSWORD=             # 初始管理员密码

# ===== 邮件 =====
# MAIL_SMTP_HOST=
# MAIL_SMTP_PORT=465
# MAIL_SMTP_USER=
# MAIL_SMTP_PASSWORD=
# MAIL_FROM_ADDRESS=
```

**步骤 1.9: 测试 — 认证核心模块**

- 文件: `scripts/tests/lib/test_password.py`

```python
"""argon2 密码哈希/验证测试。"""

from lib.auth.password import hash_password, verify_password


def test_hash_and_verify_success():
    hashed = hash_password("SecureP@ss1")
    assert verify_password("SecureP@ss1", hashed)


def test_verify_wrong_password():
    hashed = hash_password("SecureP@ss1")
    assert not verify_password("wrong", hashed)


def test_different_hashes_for_same_password():
    h1 = hash_password("SecureP@ss1")
    h2 = hash_password("SecureP@ss1")
    assert h1 != h2  # argon2 使用随机 salt
    assert verify_password("SecureP@ss1", h1)
    assert verify_password("SecureP@ss1", h2)
```

- 文件: `scripts/tests/lib/test_jwt.py`

```python
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
```

---

### Phase 2: 核心流程 — 注册/登录/权限校验

#### 需求回溯

→ 对应 spec.md User Story 1 (P1): 邀请码注册
→ 对应 spec.md User Story 2 (P1): 用户登录
→ 对应 spec.md User Story 3 (P1): API 权限校验
→ 对应 spec.md FR-001 ~ FR-011

#### 实现步骤

**步骤 2.1: 新增认证路由**

- 文件: `scripts/api/routers/auth.py`

```python
"""认证路由 — 注册、登录、邮箱验证、密码管理。"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.database import (
    create_email_token,
    create_invite_code,
    create_reset_token,
    create_user,
    get_email_token_by_hash,
    get_invite_code_by_code,
    get_recent_failed_attempts,
    get_reset_token_by_hash,
    get_role,
    get_user_by_email,
    get_user_by_id,
    invalidate_pending_email_tokens,
    record_login_attempt,
    use_invite_code,
    use_reset_token,
    verify_email_token,
    verify_user_email,
)
from api.dependencies import get_current_user
from api.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenOut,
    UserOut,
    VerifyEmailRequest,
)
from lib.auth.jwt import create_token
from lib.auth.password import hash_password, verify_password
from lib.config import get_auth_config
from lib.mail.smtp import send_reset_email, send_verification_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["认证"])


def _generate_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    """邀请码注册。"""
    # 检查邮箱是否已注册
    if get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="邮箱已注册")
    # 验证邀请码
    invite = get_invite_code_by_code(req.invite_code)
    if not invite:
        raise HTTPException(status_code=400, detail="邀请码无效")
    now = datetime.now(timezone.utc).isoformat()
    if invite["used_by"] is not None or invite["expires_at"] < now:
        raise HTTPException(status_code=400, detail="邀请码无效")
    # 创建用户
    user_id = create_user(req.email, hash_password(req.password), invite["role_id"])
    # 标记邀请码已使用
    use_invite_code(invite["id"], user_id)
    # 生成邮箱验证 token
    raw_token = uuid.uuid4().hex
    token_hash = _generate_token_hash(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    create_email_token(user_id, token_hash, expires_at)
    # 发送验证邮件
    mail_sent = await send_verification_email(req.email, raw_token)
    if not mail_sent:
        logger.warning(f"验证邮件发送失败: {req.email}")
    return {
        "message": "注册成功，请查收验证邮件" if mail_sent else "注册成功，但验证邮件发送失败，请联系管理员激活",
        "user_id": user_id,
        "mail_sent": mail_sent,
    }


@router.post("/login", response_model=TokenOut)
async def login(req: LoginRequest):
    """邮箱密码登录。"""
    cfg = get_auth_config()
    # 暴力破解检查
    if get_recent_failed_attempts(req.email, cfg.lockout_minutes) >= cfg.max_login_attempts:
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    # 查找用户
    user = get_user_by_email(req.email)
    # 统一错误消息：不泄露用户是否存在
    if not user or not verify_password(req.password, user["password_hash"]):
        record_login_attempt(req.email, False)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    # 状态检查
    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="请先验证邮箱")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="账户已被禁用")
    # 获取角色权限
    role = get_role(user["role_id"])
    permissions = json.loads(role["permissions_json"]) if role else []
    # 创建 JWT
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "role_id": user["role_id"],
        "permissions": permissions,
    }
    token = create_token(payload)
    record_login_attempt(req.email, True)
    return TokenOut(
        access_token=token,
        expires_in=cfg.access_token_expire_minutes * 60,
    )


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    """验证邮箱。"""
    token_hash = _generate_token_hash(req.token)
    token_record = get_email_token_by_hash(token_hash)
    if not token_record:
        raise HTTPException(status_code=400, detail="验证链接无效")
    now = datetime.now(timezone.utc).isoformat()
    if token_record["verified_at"] is not None:
        raise HTTPException(status_code=400, detail="邮箱已验证")
    if token_record["expires_at"] < now:
        raise HTTPException(status_code=400, detail="验证链接已过期")
    # 激活用户
    verify_user_email(token_record["user_id"])
    verify_email_token(token_hash)
    return {"message": "邮箱验证成功"}


@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest):
    """重发验证邮件。"""
    user = get_user_by_email(req.email)
    if not user or user["email_verified_at"] is not None:
        # 不泄露用户是否存在，统一返回成功
        return {"message": "如果该邮箱已注册且未验证，验证邮件已发送"}
    # 使旧 token 失效
    invalidate_pending_email_tokens(user["id"])
    # 生成新 token
    raw_token = uuid.uuid4().hex
    token_hash = _generate_token_hash(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    create_email_token(user["id"], token_hash, expires_at)
    await send_verification_email(req.email, raw_token)
    return {"message": "如果该邮箱已注册且未验证，验证邮件已发送"}


@router.get("/me", response_model=UserOut)
async def get_me(user: dict = Depends(get_current_user)):
    """获取当前用户信息。"""
    db_user = get_user_by_id(user["user_id"])
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserOut(
        id=db_user["id"],
        email=db_user["email"],
        display_name=db_user["display_name"],
        role_id=db_user["role_id"],
        status=db_user["status"],
        email_verified_at=db_user["email_verified_at"],
        created_at=db_user["created_at"],
    )


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """修改自己密码。"""
    from api.database import update_user_password
    db_user = get_user_by_id(user["user_id"])
    if not verify_password(req.old_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    update_user_password(user["user_id"], hash_password(req.new_password))
    return {"message": "密码修改成功"}


@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """请求重置密码。"""
    user = get_user_by_email(req.email)
    if not user or user["status"] != "active":
        # 不泄露用户是否存在
        return {"message": "如果该邮箱已注册，重置邮件已发送"}
    raw_token = uuid.uuid4().hex
    token_hash = _generate_token_hash(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    create_reset_token(user["id"], token_hash, expires_at)
    mail_sent = await send_reset_email(req.email, raw_token)
    if not mail_sent:
        logger.warning(f"重置邮件发送失败: {req.email}")
    return {"message": "如果该邮箱已注册，重置邮件已发送"}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """重置密码。"""
    from api.database import update_user_password
    token_hash = _generate_token_hash(req.token)
    token_record = get_reset_token_by_hash(token_hash)
    if not token_record:
        raise HTTPException(status_code=400, detail="重置链接无效")
    now = datetime.now(timezone.utc).isoformat()
    if token_record["used_at"] is not None:
        raise HTTPException(status_code=400, detail="重置链接已使用")
    if token_record["expires_at"] < now:
        raise HTTPException(status_code=400, detail="重置链接已过期")
    # 更新密码
    update_user_password(token_record["user_id"], hash_password(req.new_password))
    use_reset_token(token_hash)
    return {"message": "密码重置成功"}
```

**步骤 2.2: 新增管理路由**

- 文件: `scripts/api/routers/admin.py`

```python
"""管理路由 — 邀请码、用户、角色管理。"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.database import (
    create_invite_code,
    disable_invite_code,
    get_user_by_id,
    list_invite_codes,
    list_roles,
    list_users,
    update_role_permissions,
    update_user_display_name,
    update_user_password,
    update_user_role,
    update_user_status,
    verify_user_email,
)
from api.dependencies import get_current_user
from api.schemas.admin import InviteCodeCreate, InviteCodeOut, RoleUpdate, UserUpdate
from lib.auth.password import hash_password
from lib.auth.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["管理"], dependencies=[Depends(require_permission("admin"))])


# 注: 路由级已配置 admin 权限校验，端点级无需重复添加 require_permission


@router.get("/invite-codes", response_model=list[InviteCodeOut])
def get_invite_codes():
    """列出邀请码。"""
    return list_invite_codes()


@router.post("/invite-codes", response_model=InviteCodeOut, status_code=201)
def create_new_invite_code(req: InviteCodeCreate, user: dict = Depends(get_current_user)):
    """创建邀请码。"""
    code = uuid.uuid4().hex[:8].upper()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=req.expires_hours)).isoformat()
    code_id = create_invite_code(code, req.role_id, user["user_id"], expires_at)
    return InviteCodeOut(
        id=code_id, code=code, role_id=req.role_id,
        created_by=user["user_id"], used_by=None, used_at=None,
        expires_at=expires_at, created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.patch("/invite-codes/{code_id}/disable")
def disable_code(code_id: str):
    """禁用邀请码。"""
    if not disable_invite_code(code_id):
        raise HTTPException(status_code=404, detail="邀请码不存在或已使用")
    return {"message": "邀请码已禁用"}


@router.get("/users")
def get_users():
    """列出用户。"""
    return list_users()


@router.patch("/users/{user_id}")
def update_user(user_id: str, req: UserUpdate, admin: dict = Depends(get_current_user)):
    """修改用户（状态、角色、手动激活、密码重置）。"""
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 保护管理员自我禁用
    if user_id == admin["user_id"] and req.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用自己")
    # 保护唯一管理员
    if target["role_id"] == "admin" and req.role_id and req.role_id != "admin":
        from api.database import get_connection
        with get_connection() as conn:
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role_id = 'admin' AND id != ?", (user_id,)
            ).fetchone()[0]
        if admin_count == 0:
            raise HTTPException(status_code=400, detail="不能移除唯一管理员角色")
    if req.status is not None:
        update_user_status(user_id, req.status)
    if req.role_id is not None:
        update_user_role(user_id, req.role_id)
    if req.display_name is not None:
        update_user_display_name(user_id, req.display_name)
    if req.password is not None:
        update_user_password(user_id, hash_password(req.password))
    if req.email_verified is True and target["email_verified_at"] is None:
        verify_user_email(user_id)
    return {"message": "用户更新成功"}


@router.get("/roles")
def get_roles():
    """列出角色。"""
    return list_roles()


@router.patch("/roles/{role_id}")
def update_role(role_id: str, req: RoleUpdate):
    """修改角色权限。"""
    from api.database import get_role
    if not get_role(role_id):
        raise HTTPException(status_code=404, detail="角色不存在")
    update_role_permissions(role_id, req.permissions)
    return {"message": "角色权限更新成功"}
```

**步骤 2.3: 注册路由 + 启动初始化**

- 文件: `scripts/api/app.py`
- 在路由 import 区追加:

```python
from api.routers import auth, admin as admin_router
app.include_router(auth.router)
app.include_router(admin_router.router)
```

- 在 `lifespan()` 函数中，`init_db()` 之后追加:

```python
    from api.database import ensure_default_roles, ensure_default_admin
    ensure_default_roles()
    ensure_default_admin()
    logger.info("认证初始化完成")
```

**步骤 2.4: 现有路由添加权限校验**

对每个路由文件，在需要保护的端点添加 `Depends(require_permission("xxx"))` 参数。以下是逐文件的修改说明:

**ask.py** — 9 个端点，添加 `ask` 权限:

- 导入: `from fastapi import Depends` 和 `from lib.auth.permissions import require_permission`
- `chat` 函数签名改为: `async def chat(req: ChatRequest, user: dict = Depends(require_permission("ask"))):`
  - `req.user_id` 改为 `user["user_id"]`（JWT 注入）
- 其余端点（sessions, messages, feedback 等）添加 `user: dict = Depends(require_permission("ask"))`

**compliance.py** — 7 个端点，添加 `compliance` 权限:

- 每个端点添加 `user: dict = Depends(require_permission("compliance"))`

**eval.py** — 31 个端点，添加 `eval` 权限:

- 每个端点添加 `user: dict = Depends(require_permission("eval"))`

**knowledge.py** — 8 个端点:

- 读操作（list, search, preview）: `require_permission("knowledge")`
- 写操作（import, rebuild, save_document）: `require_permission("admin")`

**kb_version.py** — 5 个端点:

- 读操作（list, get）: `require_permission("knowledge")`
- 写操作（activate, delete）: `require_permission("admin")`

**feedback.py** — 8 个端点:

- submit: `require_permission("ask")`
- badcase 管理: `require_permission("admin")`

**observability.py** — 8 个端点:

- 全部: `require_permission("admin")`

**memory.py** — 7 个端点，添加 `memory` 权限 + user_id 注入:

- 每个端点添加 `user: dict = Depends(require_permission("memory"))`
- 所有 `user_id: str = "default"` 参数移除，改为从 `user["user_id"]` 获取

memory.py 改造示例:

```python
# 改造前
@router.get("/list", response_model=MemoryListResponse)
def list_memories(user_id: str = "default"):
    svc = get_memory_service()
    ...

# 改造后
@router.get("/list", response_model=MemoryListResponse)
def list_memories(user: dict = Depends(require_permission("memory"))):
    user_id = user["user_id"]
    svc = get_memory_service()
    ...
```

**步骤 2.5: 测试 — 注册/登录/权限校验**

- 文件: `scripts/tests/api/test_auth.py`

```python
"""认证端点集成测试。"""

import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminP@ss1")


@pytest.fixture(scope="module")
def client():
    from api.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    """获取管理员 JWT token。"""
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "AdminP@ss1"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_login_success(client, admin_token):
    assert admin_token  # token 非空


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
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role_id"] == "admin"


def test_change_password(client, admin_token):
    # 改回原密码以确保后续测试不受影响
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "AdminP@ss1", "new_password": "AdminP@ss1"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
```

- 文件: `scripts/tests/api/test_admin.py`

```python
"""管理端点集成测试。"""

import os
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "AdminP@ss1")


@pytest.fixture(scope="module")
def client():
    from api.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "AdminP@ss1"})
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


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
    assert len(resp.json()) >= 1  # 至少有默认管理员


def test_admin_cannot_disable_self(client, admin_token):
    # 先获取自己的 user_id
    me = client.get("/api/auth/me", headers=_auth(admin_token)).json()
    resp = client.patch(
        f"/api/admin/users/{me['id']}",
        json={"status": "disabled"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400
```

---

### Phase 3: 增强功能 — 密码重置 + 用户管理 + 角色管理

#### 需求回溯

→ 对应 spec.md User Story 4 (P2): 密码重置
→ 对应 spec.md User Story 5 (P2): 用户管理
→ 对应 spec.md User Story 6 (P3): 角色权限管理
→ 对应 spec.md FR-006, FR-007, FR-008, FR-012

#### 实现步骤

Phase 3 的核心端点已在 Phase 2 的步骤 2.1 和 2.2 中实现（auth.py 包含 forgot-password/reset-password，admin.py 包含用户/角色/邀请码管理）。本 Phase 专注于测试覆盖和边界场景验证。

**步骤 3.1: 测试 — 密码重置流程**

- 文件: `scripts/tests/api/test_auth.py` 追加:

```python
def test_forgot_password_silent_success(client):
    """不存在的邮箱也返回成功（不泄露用户存在）。"""
    resp = client.post("/api/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200


def test_reset_password_invalid_token(client):
    resp = client.post("/api/auth/reset-password", json={"token": "invalid", "new_password": "NewP@ss1"})
    assert resp.status_code == 400
```

**步骤 3.2: 测试 — 邀请码注册完整流程**

- 文件: `scripts/tests/api/test_auth.py` 追加:

```python
def test_register_with_invite_code(client, admin_token):
    """完整注册流程：创建邀请码 → 注册 → 验证邮箱 → 登录。"""
    # 创建邀请码
    code_resp = client.post(
        "/api/admin/invite-codes",
        json={"role_id": "viewer", "expires_hours": 72},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    invite_code = code_resp.json()["code"]
    # 注册
    reg_resp = client.post("/api/auth/register", json={
        "email": "newuser@test.com",
        "password": "UserP@ss1",
        "invite_code": invite_code,
    })
    assert reg_resp.status_code == 201
    # 未验证时登录应失败
    login_resp = client.post("/api/auth/login", json={"email": "newuser@test.com", "password": "UserP@ss1"})
    assert login_resp.status_code == 403
    # 管理员手动激活
    users_resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    new_user = next(u for u in users_resp.json() if u["email"] == "newuser@test.com")
    client.patch(
        f"/api/admin/users/{new_user['id']}",
        json={"email_verified": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # 激活后登录应成功
    login_resp2 = client.post("/api/auth/login", json={"email": "newuser@test.com", "password": "UserP@ss1"})
    assert login_resp2.status_code == 200


def test_register_duplicate_email(client, admin_token):
    """重复邮箱注册失败。"""
    code_resp = client.post(
        "/api/admin/invite-codes",
        json={"role_id": "viewer", "expires_hours": 72},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    invite_code = code_resp.json()["code"]
    resp = client.post("/api/auth/register", json={
        "email": "admin@test.com",  # 已存在
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
```

**步骤 3.3: 测试 — 权限校验**

- 文件: `scripts/tests/lib/test_permissions.py`

```python
"""权限校验依赖测试。"""

import os
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
    # 模拟有权限的用户
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(dep({"permissions": ["ask", "compliance"]}))
    assert result["permissions"] == ["ask", "compliance"]


def test_require_permission_denies_unauthorized():
    from lib.auth.permissions import require_permission
    from fastapi import HTTPException
    dep = require_permission("admin")
    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(dep({"permissions": ["ask"]}))
    assert exc_info.value.status_code == 403
```

**步骤 3.4: 测试 — 暴力破解防护**

- 文件: `scripts/tests/api/test_auth.py` 追加:

```python
def test_brute_force_lockout(client, admin_token):
    """连续 5 次错误密码后锁定。"""
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    resp = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "AdminP@ss1"})
    assert resp.status_code == 429
```

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | — | — |

本方案无 Constitution Check 违反。所有选择均为最简方案：
- 逐路由 `Depends()` 而非全局中间件（避免路径排除复杂性）
- 单角色单用户（暂不支持多角色，简化 RBAC）
- 无 refresh token / JWT 黑名单（过期重登录，简化实现）
- 邮件不可用时管理员手动激活（降级而非复杂重试机制）

## Appendix

### 执行顺序建议

```
Phase 1 (基础设施) → Phase 2 (核心流程) → Phase 3 (增强功能 + 测试)
```

Phase 1 是 Phase 2 的前置依赖（JWT/密码/数据库层必须先就绪）。
Phase 3 的端点已在 Phase 2 中实现，Phase 3 专注补充测试。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 邀请码注册 | 有效邀请码注册成功；无效/已用邀请码失败；邮箱已注册失败；邮箱验证后可登录 | test_register_with_invite_code, test_register_invalid_invite_code, test_register_duplicate_email |
| US2 用户登录 | 正确邮箱密码返回 JWT；错误密码统一错误；disabled 账户拒绝；5 次失败锁定 | test_login_success, test_login_wrong_password, test_login_nonexistent_user, test_brute_force_lockout |
| US3 API 权限校验 | 有权限正常响应；无权限 403；无 Token 401；过期 Token 401 | test_unauthorized_access, test_require_permission_denies_unauthorized |
| US4 密码重置 | 存在邮箱发送重置邮件；不存在邮箱静默成功；有效 token 重置成功；过期 token 失败 | test_forgot_password_silent_success, test_reset_password_invalid_token |
| US5 用户管理 | 管理员可列出/禁用/启用/修改角色用户；不能禁用自己 | test_list_users, test_admin_cannot_disable_self |
| US6 角色权限管理 | 管理员可查看/修改角色权限；权限变更下次登录生效 | test_list_roles |
