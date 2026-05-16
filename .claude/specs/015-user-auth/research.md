# 015-user-auth - 技术调研报告

生成时间: 2026-05-10
源规格: .claude/specs/015-user-auth/spec.md

## 执行摘要

actuary-sleuth 当前零认证，所有 66 个 API 端点公开访问。本调研分析了现有代码架构的集成点、66 个端点的权限映射、技术选型（PyJWT + argon2-cffi + aiosmtplib + OAuth2PasswordBearer），以及关键风险（SSE 端点认证、user_id 冒充、SPA 路由拦截、邮件服务依赖）。推荐采用 FastAPI 原生 `Depends()` 模式逐路由添加权限校验，避免全局中间件带来的路径排除复杂性。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 邀请码注册 | `api/database.py` | 需新增 users/invite_codes 表 + 数据访问函数 |
| FR-002 管理员生成邀请码 | `api/routers/admin.py`（新增） | 需新增路由 |
| FR-003 邮箱验证 | `api/routers/auth.py`（新增） | 需新增路由 + 邮件服务 |
| FR-004 登录/JWT | `api/dependencies.py` | 需新增 `get_current_user` 依赖 |
| FR-005 权限校验 | 所有 `api/routers/*.py` | 需逐路由添加 `Depends(get_current_user)` + 权限检查 |
| FR-006 RBAC | `api/database.py` | 需新增 roles 表 + 权限查询函数 |
| FR-007 暴力破解防护 | `api/database.py` | 需新增 login_attempts 表 |
| FR-008 不泄露用户存在 | `api/routers/auth.py` | 统一错误消息 |
| FR-009 管理员自我保护 | `api/routers/admin.py` | 业务逻辑校验 |
| FR-010 手动激活用户 | `api/routers/admin.py` | PATCH 端点 |

### 1.2 可复用组件

- `lib.common.database.get_connection()`: 所有 auth DB 操作复用现有连接池（`api.database` 从 `lib.common.database` 导入）
- `api.database._deserialize_json_fields()`: roles.permissions_json 反序列化
- `api.database._migrate_db()`: auth 表 DDL 放入此处，与 memory_metadata、user_profiles 等后期表的模式一致
- `lib.config.Config` + 嵌套配置类模式: 新增 `AuthConfig` / `MailConfig`（配置全部来自环境变量，无 settings.json）
- `api.dependencies` 的 `get_*` / `on_shutdown` 模式: 新增 `get_current_user`（现有: `get_rag_engine`, `get_memory_service`, `get_ask_graph`, `on_shutdown`）
- `api.schemas.*` 的 `*Request` / `*Out` / `*Response` 命名: 新增 auth schemas
- `api.database._migrate_db()` 增量迁移模式: auth 表 DDL 放入此处

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `api/routers/auth.py` | 新增 | 注册、登录、邮箱验证、密码重置端点 |
| `api/routers/admin.py` | 新增 | 邀请码管理、用户管理、角色管理端点 |
| `api/schemas/auth.py` | 新增 | RegisterRequest, LoginRequest, TokenOut, UserOut 等 |
| `api/schemas/admin.py` | 新增 | InviteCodeCreate, UserUpdate, RoleUpdate 等 |
| `lib/auth/` | 新增 | JWT 编解码、密码哈希、权限校验核心逻辑 |
| `lib/auth/jwt.py` | 新增 | create_token, decode_token |
| `lib/auth/password.py` | 新增 | hash_password, verify_password |
| `lib/auth/permissions.py` | 新增 | require_permission 装饰器/依赖 |
| `lib/mail/` | 新增 | 邮件发送服务 |
| `lib/mail/smtp.py` | 新增 | send_verification_email, send_reset_email |
| `api/database.py` | 修改 | 新增 6 张表 DDL + 数据访问函数 |
| `api/dependencies.py` | 修改 | 新增 get_current_user（现有: get_rag_engine, get_memory_service, get_ask_graph, on_shutdown） |
| `api/app.py` | 修改 | include auth/admin 路由, lifespan 中 ensure_default_roles + ensure_default_admin |
| `lib/config.py` | 修改 | 新增 AuthConfig, MailConfig |
| `api/routers/ask.py` | 修改 | 添加 ask 权限校验 |
| `api/routers/compliance.py` | 修改 | 添加 compliance 权限校验 |
| `api/routers/eval.py` | 修改 | 添加 eval 权限校验 |
| `api/routers/knowledge.py` | 修改 | 添加 knowledge 权限校验 |
| `api/routers/kb_version.py` | 修改 | 添加 knowledge/admin 权限校验 |
| `api/routers/feedback.py` | 修改 | 添加 ask/admin 权限校验 |
| `api/routers/observability.py` | 修改 | 添加 admin 权限校验 |
| `api/routers/memory.py` | 修改 | 添加 memory 权限校验 + user_id 鉴权 |
| `scripts/requirements.txt` | 修改 | 新增 PyJWT, argon2-cffi, aiosmtplib |

---

## 二、技术选型研究

### 2.1 JWT 库对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **PyJWT >=2.9.0** | 零依赖；活跃维护；cryptography 已在项目中 | 仅做 JWT 编解码，需配合 OAuth2PasswordBearer | ✅ |
| python-jose 3.5.0 | JWT+JWS+JWE 一体 | 停止维护；CVE-2024-23342 修复慢；额外 4 个依赖 | ❌ |
| OAuth2PasswordBearer | FastAPI 内置；Swagger 自动显示 Authorize 按钮 | 不是 JWT 库，仅提取 Bearer token | ✅ 配合 PyJWT |

**结论**: PyJWT（编解码）+ OAuth2PasswordBearer（token 提取 + Swagger 集成）

### 2.2 密码哈希对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **argon2-cffi >=23.1.0** | OWASP/NIST 推荐；内存硬抗 GPU/ASIC；活跃维护 | 2 个子包（均有预编译 wheel） | ✅ |
| bcrypt 5.0.0 | 久经验证；简单 | 非 memory-hard；passlib 停滞且有兼容问题 | 可接受 |
| passlib[bcrypt] | 多后端抽象 | 停滞；bcrypt 4.x+ 不兼容 | ❌ |
| hashlib+salt | 零依赖 | 无 key stretching，不安全 | ❌ |

**结论**: argon2-cffi（argon2id 算法），参数 `time_cost=2, memory_cost=65536, parallelism=1`

### 2.3 邮件发送对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **aiosmtplib >=3.0.0** | 原生 async；零依赖；支持任意 SMTP 服务器 | 需 SMTP 服务器 | ✅ |
| smtplib (stdlib) | 零安装 | 同步阻塞 event loop | ❌ |
| SendGrid SDK | 高送达率；模板支持 | 3 个额外依赖；中国邮箱送达差；付费 | ❌ |

**结论**: aiosmtplib，配合阿里云 DirectMail / 腾讯 SES / 企业 SMTP

### 2.4 认证模式对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **OAuth2PasswordBearer + Depends** | FastAPI 原生；Swagger 集成；可组合权限 | 每个端点需显式添加 | ✅ |
| 全局中间件 | 一次配置全局生效 | 路径排除逻辑脆弱；无 Swagger 集成；SPA 路由冲突 | ❌ |
| API Key Header | 最简单 | 无用户身份/角色/过期；不适合登录流程 | ❌ |

**结论**: OAuth2PasswordBearer + Depends，逐路由添加权限校验

### 2.5 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| PyJWT | >=2.9.0 | JWT 编解码 | 零依赖，cryptography 可选 |
| argon2-cffi | >=23.1.0 | 密码哈希 | 预编译 wheel，Win/Linux/Mac |
| aiosmtplib | >=3.0.0 | 异步 SMTP | 零依赖，Python 3.8+ |
| fastapi.security | 内置 | OAuth2PasswordBearer | 已有 fastapi>=0.104.0 |

**新增依赖共 3 个包**，均为轻量且活跃维护。

---

## 三、数据流分析

### 3.1 现有数据流（认证前）

```
客户端 → FastAPI → 路由函数（无认证）→ api.database → SQLite
```

所有端点公开访问，`ChatRequest.user_id` 和 memory 的 `user_id` 参数由客户端自由指定，无鉴权。

### 3.2 新增/变更的数据流

```
注册: 客户端 → POST /api/auth/register → 验证邀请码 → 创建用户(pending) → 发送验证邮件 → 201
验证: 客户端 → POST /api/auth/verify-email → 验证 token → 激活用户(active) → 200
登录: 客户端 → POST /api/auth/login → 验证密码 → 检查暴力破解 → 返回 JWT → 200
请求: 客户端 → Authorization: Bearer <JWT> → get_current_user 解析 → require_permission 校验 → 路由函数
重置: 客户端 → POST /api/auth/forgot-password → 生成 token → 发送邮件 → 客户端 → POST /api/auth/reset-password → 更新密码
```

### 3.3 关键数据结构

```python
# JWT Payload
@dataclass(frozen=True)
class TokenPayload:
    user_id: str      # UUID
    email: str
    role_id: str      # 'admin' | 'actuary' | 'compliance' | 'viewer'
    permissions: list[str]  # ['ask', 'compliance', ...]
    exp: int          # Unix timestamp

# 当前用户（注入到路由）
@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str
    role_id: str
    permissions: frozenset[str]
```

---

## 四、端点权限映射

### 4.1 完整端点-权限映射表

| 路由 | 端点数 | 权限 | 特殊说明 |
|------|--------|------|----------|
| `ask.py` `/api/ask/*` | 9 | ask | POST /chat 为 SSE，需在返回 EventSourceResponse 前完成认证 |
| `compliance.py` `/api/compliance/*` | 7 | compliance | — |
| `eval.py` `/api/eval/*` | 31 | eval | 最大路由，无 SSE |
| `knowledge.py` `/api/kb/*` | 8 | knowledge（读）/ admin（写） | import/rebuild/save_document 建议需 admin |
| `kb_version.py` `/api/kb/versions/*` | 5 | knowledge（读）/ admin（写） | activate/delete 需 admin |
| `feedback.py` `/api/feedback/*` | 8 | ask（submit）/ admin（badcase 管理） | submit 属于 ask 流程 |
| `observability.py` `/api/observability/*` | 8 | admin | 全部运维端点 |
| `memory.py` `/api/memory/*` | 7 | memory | **user_id 参数需从 JWT 注入，禁止客户端指定** |
| `auth.py` `/api/auth/*`（新增） | 8 | 无（公开） | register/login/verify/forgot/reset/me/change-password |
| `admin.py` `/api/admin/*`（新增） | 7 | admin | 邀请码/用户/角色管理 |
| `/api/health` | 1 | 无（公开） | 健康检查 |

**总计**: 66 个现有端点 + 15 个新增端点 = 81 个

### 4.2 需要特殊处理的端点

1. **POST `/api/ask/chat`** (SSE): 认证必须在 `EventSourceResponse` 返回前完成，流开始后无法发送 401
2. **memory.py 的 5 个端点**: `user_id` 参数当前由客户端指定，认证后必须从 JWT 提取，忽略请求中的 `user_id`
3. **ask.py 的 `ChatRequest.user_id`**: 同理，从 JWT 注入而非请求体

---

## 五、集成方案详细设计

### 5.1 数据库层 (`api/database.py`)

**DDL 位置**: 放入 `_migrate_db()` 中使用 `CREATE TABLE IF NOT EXISTS`，与 `memory_metadata`、`user_profiles` 等后期表的模式一致。不修改 `_SCHEMA_SQL`。

**新增数据访问函数** (遵循 `with get_connection() as conn:` 模式，`get_connection` 从 `lib.common.database` 导入):

```python
from lib.common.database import get_connection
# 用户
def get_user_by_email(email: str) -> Optional[Dict]
def get_user_by_id(user_id: str) -> Optional[Dict]
def create_user(email: str, password_hash: str, role_id: str, status: str = 'pending') -> str
def update_user_status(user_id: str, status: str) -> bool
def update_user_role(user_id: str, role_id: str) -> bool
def update_user_password(user_id: str, password_hash: str) -> bool
def verify_user_email(user_id: str) -> bool
def list_users() -> List[Dict]

# 角色
def get_role(role_id: str) -> Optional[Dict]
def list_roles() -> List[Dict]
def update_role_permissions(role_id: str, permissions: List[str]) -> bool
def ensure_default_roles() -> None  # 启动时插入 4 个预置角色

# 邀请码
def create_invite_code(code: str, role_id: str, created_by: str, expires_at: str) -> str
def get_invite_code_by_code(code: str) -> Optional[Dict]
def use_invite_code(code_id: str, used_by: str) -> bool
def list_invite_codes() -> List[Dict]
def disable_invite_code(code_id: str) -> bool

# 邮箱验证
def create_email_token(user_id: str, token_hash: str, expires_at: str) -> str
def get_email_token_by_hash(token_hash: str) -> Optional[Dict]
def verify_email_token(token_hash: str) -> bool
def invalidate_pending_email_tokens(user_id: str) -> None

# 密码重置
def create_reset_token(user_id: str, token_hash: str, expires_at: str) -> str
def get_reset_token_by_hash(token_hash: str) -> Optional[Dict]
def use_reset_token(token_hash: str) -> bool

# 登录尝试
def record_login_attempt(email: str, success: bool) -> None
def get_recent_failed_attempts(email: str, minutes: int = 15) -> int
```

### 5.2 配置层 (`lib/config.py`)

新增 `AuthConfig` 和 `MailConfig`:

> 注意: 项目配置全部来自环境变量（通过 `lib/config.py` 的 `Config` 类加载），无 settings.json。AuthConfig/MailConfig 遵循相同模式，从环境变量读取。

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
        return self._config.get('access_token_expire_minutes', 480)  # 8h

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

**环境变量**:
```
AUTH_JWT_SECRET=           # 必填，256-bit 随机密钥
AUTH_JWT_ALGORITHM=HS256
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=480
AUTH_MAX_LOGIN_ATTEMPTS=5
AUTH_LOCKOUT_MINUTES=15
MAIL_SMTP_HOST=
MAIL_SMTP_PORT=465
MAIL_SMTP_USER=
MAIL_SMTP_PASSWORD=
MAIL_FROM_ADDRESS=
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=            # 初始管理员密码
```

### 5.3 依赖注入 (`api/dependencies.py`)

> 现有依赖: `on_shutdown()`, `get_rag_engine()`, `init_memory_service()`, `get_memory_service()`, `init_ask_graph()`, `get_ask_graph()`。路由直接调用 `get_*()` 而非通过 `Depends()`。新增 `get_current_user` 将是首个 `Depends()` 模式的依赖。

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

    # 检查用户是否仍为 active（防止 disabled 用户的未过期 token 继续使用）
    from api.database import get_user_by_id
    user = get_user_by_id(payload["user_id"])
    if not user or user["status"] != "active":
        raise HTTPException(status_code=401, detail="账户已被禁用")

    return payload
```

### 5.4 权限校验 (`lib/auth/permissions.py`)

```python
from functools import wraps
from fastapi import Depends, HTTPException
from api.dependencies import get_current_user

def require_permission(permission: str):
    """FastAPI 依赖：校验当前用户是否拥有指定权限。"""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if permission not in user.get("permissions", []):
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return _check

# 使用方式:
@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_permission("ask"))):
    ...
```

### 5.5 路由保护改造示例

**ask.py 改造前**:
```python
@router.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title=req.question[:50], user_id=req.user_id)
```

**ask.py 改造后**:
```python
@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_permission("ask"))):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title=req.question[:50], user_id=user["user_id"])
```

关键变化:
1. 添加 `user: dict = Depends(require_permission("ask"))`
2. `user_id` 从 JWT 注入，不再信任 `req.user_id`

### 5.6 初始管理员创建

在 `api/app.py` 的 `lifespan()` 中，`init_db()` 之后调用:

```python
from api.database import ensure_default_roles, ensure_default_admin
ensure_default_roles()  # 插入 4 个预置角色
ensure_default_admin()  # 若 users 表为空，从 ADMIN_EMAIL/ADMIN_PASSWORD 创建
```

> 注意: 现有 `lifespan()` 在 yield 前调用 `init_db()`，yield 后调用 `on_shutdown()`。auth 初始化应在 `init_db()` 之后、yield 之前。

### 5.7 邮件服务降级

```python
class MailService:
    async def send_verification_email(self, email: str, token: str) -> bool:
        if not self._config.enabled:
            logger.warning("邮件服务未配置，验证邮件未发送")
            return False
        try:
            # aiosmtplib 发送
            return True
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False
```

- 返回 `False` 时，注册端点返回提示"验证邮件发送失败，请联系管理员激活"
- 管理员可通过 `PATCH /api/admin/users/{id}` 手动激活用户

---

## 六、关键技术问题

### 6.1 需要验证的技术假设

- [ ] **SQLite 并发写入**: auth 写操作（注册、登录记录）与现有写入（消息、反馈）并发时，WAL 模式 + busy_timeout=30s 是否足够 → 内部工具低并发，预期可行
- [ ] **argon2-cffi Windows wheel**: 预编译 wheel 是否覆盖 Windows 10 + Python 3.x → argon2-cffi 官方提供 Win wheel，预期可行
- [ ] **aiosmtplib SMTP TLS**: 企业 SMTP 通常用 465 端口（隐式 TLS），aiosmtplib 的 `SMTP_TLS` 是否正常工作 → 需实际测试
- [ ] **SPA 路由冲突**: `app.py` 的 `/{full_path:path}` catch-all 是否会拦截 `/api/auth/*` → 不会：catch-all 仅在 `web/dist` 目录存在时注册，且 API 路由优先级高于 catch-all
- [ ] **JWT permissions 过期不一致**: 角色权限修改后，未过期 token 中的 permissions 仍是旧的 → spec 已明确"下次登录时刷新"，可接受

### 6.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 邮件服务不可用导致注册流程中断 | 中 | 高 | 管理员手动激活降级方案；前端提示联系管理员 |
| argon2-cffi 在目标环境安装失败 | 低 | 高 | fallback 到 bcrypt（requirements 中加 bcrypt 作为备选） |
| SQLite 并发写入冲突（注册 + 审核同时写） | 低 | 中 | WAL 模式 + busy_timeout=30s 已配置；内部工具并发极低 |
| JWT secret 泄露 | 低 | 极高 | 仅通过环境变量配置；不写入任何配置文件或日志；.gitignore 排除 .env |
| 暴力破解登录 | 低 | 中 | 5 次失败锁定 15 分钟；login_attempts 表记录 |
| user_id 冒充（memory/ask 端点） | 高 | 高 | 认证后从 JWT 注入 user_id，忽略请求参数中的 user_id |

---

## 七、Schema 设计

### 7.1 新增 `api/schemas/auth.py`

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

### 7.2 新增 `api/schemas/admin.py`

```python
class InviteCodeCreate(BaseModel):
    role_id: str = Field(..., pattern=r'^(admin|actuary|compliance|viewer)$')
    expires_hours: int = Field(72, ge=1, le=720)  # 默认 3 天

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
    password: str | None = Field(None, min_length=8, max_length=128)  # 管理员重置密码
    email_verified: bool | None = None  # 手动激活

class RoleUpdate(BaseModel):
    permissions: list[str]
```

---

## 八、测试策略

### 8.1 测试文件

| 文件 | 测试内容 |
|------|---------|
| `tests/api/test_auth.py` | 注册、登录、邮箱验证、密码重置、JWT 编解码 |
| `tests/api/test_admin.py` | 邀请码管理、用户管理、角色管理 |
| `tests/lib/test_password.py` | argon2 哈希/验证 |
| `tests/lib/test_jwt.py` | JWT 创建/解码/过期 |
| `tests/lib/test_permissions.py` | require_permission 依赖 |

### 8.2 测试 fixture

```python
# conftest.py 新增
@pytest.fixture
def auth_client(app_client):
    """已认证的测试客户端（viewer 角色）"""
    ...

@pytest.fixture
def admin_client(app_client):
    """已认证的测试客户端（admin 角色）"""
    ...
```

### 8.3 关键测试场景

1. 注册 → 验证邮箱 → 登录成功
2. 注册 → 未验证 → 登录失败（"请先验证邮箱"）
3. 登录 5 次失败 → 锁定 15 分钟
4. viewer 请求 compliance 端点 → 403
5. 无 token 请求受保护端点 → 401
6. JWT 过期 → 401
7. 管理员禁用自己 → 错误
8. 邀请码过期 → 注册失败
9. 并发注册同一邮箱 → 仅一个成功
10. memory 端点 user_id 从 JWT 注入，忽略请求参数

---

## 九、参考实现

- [FastAPI Security - OAuth2 with Password (and hashing), Bearer with JWT cookies](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) — FastAPI 官方 JWT 示例
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) — argon2id 参数推荐
- [PyJWT Documentation](https://pyjwt.readthedocs.io/) — JWT 编解码 API
- [aiosmtplib Documentation](https://aiosmtplib.readthedocs.io/) — 异步 SMTP 客户端
- [argon2-cffi Documentation](https://argon2-cffi.readthedocs.io/) — 密码哈希 API

---

## 十、代码审查修正记录

基于实际代码库验证，以下为修正项：

| # | 原始描述 | 修正后 | 原因 |
|---|---------|--------|------|
| 1 | "56 个 API 端点" | 66 个 API 端点 | eval.py 实际 31 个端点（非 21） |
| 2 | "api.database.get_connection()" | `get_connection` 从 `lib.common.database` 导入 | `api.database` 本身不定义 `get_connection`，而是从 `lib.common.database` 导入 |
| 3 | "api.database._deserialize_json_fields() 可复用" | ✅ 确认存在（line 229） | 验证后确认 |
| 4 | "lib.config._get_config() 单例模式" | 删除此项 | `_get_config()` 不存在；Config 直接实例化 |
| 5 | "dependencies.py 有 get_db() 和 get_settings()" | 现有: `get_rag_engine`, `get_memory_service`, `get_ask_graph`, `on_shutdown` | 实际依赖与报告不符 |
| 6 | "配置在 settings.json" | 配置全部来自环境变量，通过 `lib/config.py` 加载 | 项目无 settings.json |
| 7 | "SPA catch-all 路由始终注册" | 仅在 `web/dist` 存在时注册 | `app.py` 中有 `os.path.exists` 检查 |
| 8 | "lifespan 中 init_auth()" | `ensure_default_roles()` + `ensure_default_admin()` | 更准确的函数命名 |