# Feature Specification: 用户认证与权限控制

**Feature Branch**: `015-user-auth`
**Created**: 2026-04-18
**Updated**: 2026-05-10
**Status**: Draft
**Input**: 实现用户注册登录，邮箱密码方式，邀请码注册，邮箱验证，角色权限管理

## 项目现状分析

当前系统零认证：所有 API 端点公开访问，无 User 模型、无 auth 中间件、无权限校验。
数据库使用 SQLite + 原生 SQL（非 ORM），连接池模式，DDL 在 `api/database.py` 的 `_SCHEMA_SQL` 中管理。
API 路由在 `api/routers/` 下，依赖注入在 `api/dependencies.py`。

## User Scenarios & Testing

### User Story 1 - 邀请码注册 (Priority: P1)

管理员生成邀请码，新用户通过邀请码 + 邮箱 + 密码自助注册，注册后需验证邮箱才能登录。

**Why this priority**: 邀请码控制准入，邮箱验证确保身份真实，自助注册减少管理员操作负担。

**Independent Test**:
1. 管理员生成邀请码
2. 新用户使用邀请码注册
3. 收到验证邮件，点击链接激活
4. 用户可登录

**Acceptance Scenarios**:

1. **Given** 有效邀请码, **When** 提交邮箱、密码、邀请码注册, **Then** 创建 pending 状态用户，发送验证邮件，邀请码标记已使用
2. **Given** 邀请码无效或已使用, **When** 提交注册, **Then** 返回"邀请码无效"
3. **Given** 邮箱已存在, **When** 提交注册, **Then** 返回"邮箱已注册"
4. **Given** 注册成功, **When** 点击验证邮件链接, **Then** 用户状态变为 active，可正常登录
5. **Given** 验证链接过期（24h）, **When** 点击链接, **Then** 提示"链接已过期"，可重新发送验证邮件
6. **Given** 用户状态为 pending, **When** 尝试登录, **Then** 返回"请先验证邮箱"
7. **Given** 邮件发送服务不可用, **When** 注册成功, **Then** 返回提示"验证邮件发送失败，请稍后重试"，管理员可手动激活用户作为降级方案

---

### User Story 2 - 用户登录 (Priority: P1)

已创建用户通过邮箱密码登录系统，获取 JWT Token。

**Why this priority**: 登录是所有后续功能的前提。

**Independent Test**:
1. 管理员创建用户
2. 用户使用邮箱密码登录
3. 返回 JWT Token

**Acceptance Scenarios**:

1. **Given** 用户状态为 active, **When** 提交正确邮箱密码, **Then** 返回 JWT Token（含 user_id、role、permissions）
2. **Given** 用户状态为 disabled, **When** 提交登录, **Then** 返回"账户已被禁用"
3. **Given** 密码错误, **When** 提交登录, **Then** 返回"邮箱或密码错误"
4. **Given** 用户不存在, **When** 提交登录, **Then** 返回"邮箱或密码错误"（不泄露用户是否存在）
5. **Given** 连续 5 次密码错误, **When** 再次提交登录, **Then** 返回"登录尝试过多，请稍后再试"

---

### User Story 3 - API 权限校验 (Priority: P1)

所有现有 API 端点根据用户角色权限进行访问控制。

**Why this priority**: 认证不做权限校验等于没有认证，必须与登录同步实现。

**Independent Test**:
1. viewer 角色用户登录
2. 请求 `/api/compliance/check/document` → 返回 403
3. 请求 `/api/ask/chat` → 返回正常

**Acceptance Scenarios**:

1. **Given** 用户拥有 ask 权限, **When** 请求 `/api/ask/*` 端点, **Then** 正常响应
2. **Given** 用户无 compliance 权限, **When** 请求 `/api/compliance/*` 端点, **Then** 返回 403
3. **Given** 用户无 eval 权限, **When** 请求 `/api/eval/*` 端点, **Then** 返回 403
4. **Given** 用户无 admin 权限, **When** 请求 `/api/admin/*` 端点, **Then** 返回 403
5. **Given** 请求无 JWT Token, **When** 请求任何受保护端点, **Then** 返回 401
6. **Given** JWT Token 过期, **When** 请求受保护端点, **Then** 返回 401

---

### User Story 4 - 密码重置 (Priority: P2)

用户忘记密码时通过邮箱重置。

**Why this priority**: 重要体验功能，但不阻塞核心流程。邮件服务依赖需单独解决。

**Independent Test**:
1. 已注册用户
2. 请求重置密码
3. 收到邮件并设置新密码

**Acceptance Scenarios**:

1. **Given** 用户邮箱存在, **When** 请求重置密码, **Then** 发送重置链接邮件
2. **Given** 用户邮箱不存在, **When** 请求重置密码, **Then** 静默返回成功（不泄露用户是否存在）
3. **Given** 有效重置链接, **When** 提交新密码, **Then** 密码更新成功
4. **Given** 重置链接过期（24h）, **When** 提交新密码, **Then** 返回"链接已过期"
5. **Given** 邮件发送服务不可用, **When** 请求重置密码, **Then** 返回错误提示，管理员可手动重置密码作为降级方案

---

### User Story 5 - 用户管理 (Priority: P2)

管理员查看用户列表、禁用/启用用户、修改用户角色。

**Why this priority**: 管理功能，不影响核心用户流程。

**Independent Test**:
1. 管理员登录
2. 查看用户列表
3. 禁用某用户
4. 该用户无法登录

**Acceptance Scenarios**:

1. **Given** 管理员登录, **When** 查看用户列表, **Then** 显示所有用户及其状态、角色
2. **Given** 用户状态为 active, **When** 管理员禁用, **Then** 状态变为 disabled
3. **Given** 用户状态为 disabled, **When** 管理员启用, **Then** 状态变为 active
4. **Given** 用户被禁用, **When** 用户尝试登录, **Then** 返回"账户已被禁用"
5. **Given** 管理员登录, **When** 修改用户角色, **Then** 用户下次请求时权限按新角色校验

---

### User Story 6 - 角色权限管理 (Priority: P3)

管理员查看角色、修改角色权限。

**Why this priority**: 权限细化功能，初期可用默认角色。

**Independent Test**:
1. 管理员登录
2. 查看角色列表及权限
3. 修改某角色权限
4. 该角色用户下次请求权限生效

**Acceptance Scenarios**:

1. **Given** 管理员登录, **When** 查看角色列表, **Then** 显示所有角色及权限
2. **Given** 管理员登录, **When** 修改角色权限, **Then** 权限更新成功
3. **Given** 角色权限被修改, **When** 该角色用户请求 API, **Then** 按新权限校验（JWT 中 permissions 在下次登录时刷新）

---

### Edge Cases

- JWT Token 过期 → 返回 401，前端跳转登录页
- 验证邮件/重置邮件发送失败 → 返回错误提示用户重试；管理员可手动激活用户或重置密码作为降级
- 邀请码过期 → 注册时返回"邀请码无效"
- 邀请码已被使用 → 注册时返回"邀请码无效"
- 用户修改邮箱 → 暂不支持
- 并发注册同一邮箱 → 数据库 UNIQUE 约束保证唯一
- 并发使用同一邀请码 → 数据库 used_by 字段 + 事务保证仅一次使用
- 管理员禁用自己 → 不允许（返回错误）
- 管理员删除唯一管理员角色用户 → 不允许（返回错误）
- 重复发送验证邮件 → 使旧 token 失效，发送新 token

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持邀请码注册（邮箱、密码、邀请码），注册后需验证邮箱，密码 argon2id 加密存储
- **FR-002**: 系统 MUST 支持管理员生成邀请码（指定角色、有效期）
- **FR-003**: 系统 MUST 支持邮箱验证（发送验证链接，24h 有效）
- **FR-004**: 系统 MUST 支持邮箱 + 密码登录，返回 JWT Token
- **FR-005**: 系统 MUST 对所有现有 API 端点进行权限校验，无权限返回 403，无 Token 返回 401
- **FR-006**: 系统 MUST 支持通过邮箱重置密码（依赖邮件服务，提供管理员手动重置降级方案）
- **FR-007**: 系统 MUST 支持管理员管理用户（查看、禁用/启用、修改角色）
- **FR-008**: 系统 MUST 支持基于角色的权限控制（RBAC），单角色单用户
- **FR-009**: 系统 MUST 防止登录暴力破解（5 次失败后锁定 15 分钟）
- **FR-010**: 系统 MUST 不泄露用户是否存在（登录、密码重置统一错误消息）
- **FR-011**: 系统 MUST 保护管理员自我禁用/删除（不允许操作）
- **FR-012**: 系统 MUST 支持管理员手动激活用户（邮件服务不可用时的降级方案）

### Key Entities

- **User**: 用户，包含邮箱、密码哈希、角色、状态（pending/active/disabled）
- **Role**: 角色，包含名称、权限列表（JSON）
- **InviteCode**: 邀请码，包含角色、有效期、使用状态
- **EmailVerificationToken**: 邮箱验证令牌
- **PasswordResetToken**: 密码重置令牌
- **LoginAttempt**: 登录尝试记录，用于暴力破解防护

## Data Models

> 集成到现有 `api/database.py` 的 `_SCHEMA_SQL` 和 `_migrate_db()` 中，使用原生 SQL DDL（与现有模式一致）。

### users 表

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,                    -- UUID，与现有 sessions/eval_samples 等表风格一致
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,            -- argon2id
    display_name TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL REFERENCES roles(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'disabled')),
    email_verified_at TEXT,                 -- 验证时间，NULL 表示未验证
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
```

### roles 表

```sql
CREATE TABLE IF NOT EXISTS roles (
    id TEXT PRIMARY KEY,                    -- 如 'admin', 'actuary', 'compliance', 'viewer'
    display_name TEXT NOT NULL,
    permissions_json TEXT NOT NULL DEFAULT '[]',  -- JSON: ['ask', 'compliance', 'eval', 'knowledge', 'memory', 'admin']
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### invite_codes 表

```sql
CREATE TABLE IF NOT EXISTS invite_codes (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,              -- 邀请码（随机生成，8 位字母数字）
    role_id TEXT NOT NULL REFERENCES roles(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    used_by TEXT REFERENCES users(id),
    used_at TEXT,
    expires_at TEXT NOT NULL,               -- 有效期
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
```

### email_verification_tokens 表

```sql
CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,        -- SHA-256 of verification token
    expires_at TEXT NOT NULL,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_email_verify_hash ON email_verification_tokens(token_hash);
```

### login_attempts 表

```sql
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    attempted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email);
```

### password_reset_tokens 表

```sql
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,        -- SHA-256 of reset token
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_hash ON password_reset_tokens(token_hash);
```

### 预置角色

| 角色 ID | 显示名称 | 权限 |
|---------|----------|------|
| admin | 管理员 | ask, compliance, eval, knowledge, memory, admin |
| actuary | 精算师 | ask, compliance, memory |
| compliance | 合规专员 | ask, compliance, memory |
| viewer | 查看者 | ask |

### 权限-端点映射

| 权限 | 端点前缀 | 说明 |
|------|----------|------|
| ask | `/api/ask/*` | 法规问答 |
| compliance | `/api/compliance/*` | 合规检查 |
| eval | `/api/eval/*` | 评测管理 |
| knowledge | `/api/knowledge/*` | 知识库管理 |
| memory | `/api/memory/*` | 记忆服务 |
| admin | `/api/admin/*` | 用户/角色管理 |
| — | `/api/health` | 无需认证（健康检查） |

## API Design

### 认证 API

| 端点 | 方法 | 功能 | 认证要求 |
|------|------|------|----------|
| `/api/auth/register` | POST | 注册（邮箱、密码、邀请码） | 无 |
| `/api/auth/login` | POST | 登录，返回 JWT | 无 |
| `/api/auth/verify-email` | POST | 验证邮箱（token） | 无 |
| `/api/auth/resend-verification` | POST | 重发验证邮件（邮箱） | 无 |
| `/api/auth/me` | GET | 获取当前用户信息 | 任意已认证用户 |
| `/api/auth/change-password` | POST | 修改自己密码 | 任意已认证用户 |
| `/api/auth/forgot-password` | POST | 请求重置密码（邮箱） | 无 |
| `/api/auth/reset-password` | POST | 重置密码（token、新密码） | 无 |

### 管理 API（需 admin 权限）

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/admin/invite-codes` | GET | 列出邀请码 |
| `/api/admin/invite-codes` | POST | 创建邀请码（指定角色、有效期） |
| `/api/admin/invite-codes/{id}/disable` | PATCH | 禁用邀请码 |
| `/api/admin/users` | GET | 列出用户 |
| `/api/admin/users/{id}` | PATCH | 修改用户（状态、角色、手动激活、密码重置） |
| `/api/admin/roles` | GET | 列出角色 |
| `/api/admin/roles/{id}` | PATCH | 修改角色权限 |

## JWT 策略

- **算法**: HS256
- **密钥**: 环境变量 `AUTH_JWT_SECRET`
- **过期时间**: 8 小时
- **Payload**: `{user_id, email, role_id, permissions}`
- **Refresh Token**: 暂不实现，过期后重新登录
- **登出**: JWT 无状态，不实现黑名单；前端删除 Token 即视为登出
- **权限刷新**: 角色权限变更后，用户下次登录时 JWT 中 permissions 更新；未过期 Token 中 permissions 不变（简化实现，避免黑名单）

## 集成方案

### 依赖注入

在 `api/dependencies.py` 中新增：

```python
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """从 JWT 解析当前用户，返回 {user_id, email, role_id, permissions}"""
```

### 路由保护

现有路由通过 `Depends(get_current_user)` + 权限装饰器保护：

```python
@router.post("/chat")
@require_permission("ask")
async def chat(req: ChatRequest, user=Depends(get_current_user)):
```

### 初始管理员

通过启动脚本或 `_migrate_db()` 自动创建：若 users 表为空，插入默认 admin 用户（邮箱/密码从环境变量读取），状态为 active（跳过邮箱验证）。

### 邮件服务

- **首选**: SMTP（配置通过环境变量 `MAIL_SMTP_*` 系列）
- **降级**: 邮件不可用时，管理员可通过 `/api/admin/users/{id}` PATCH 直接重置用户密码
- 密码重置 Token 存数据库（`password_reset_tokens` 表），不依赖邮件也能生成和管理

## Success Criteria

- **SC-001**: 管理员可创建用户，新用户可登录获取 Token
- **SC-002**: 所有现有 API 端点正确执行权限校验（无 Token → 401，无权限 → 403）
- **SC-003**: 管理员可管理用户（禁用/启用/修改角色）
- **SC-004**: 暴力破解防护生效（5 次失败后锁定）
- **SC-005**: 不泄露用户是否存在（统一错误消息）

## Assumptions

- JWT 密钥通过环境变量 `AUTH_JWT_SECRET` 配置
- 初始管理员账户通过 `_migrate_db()` 自动创建（邮箱/密码从 `ADMIN_EMAIL` / `ADMIN_PASSWORD` 环境变量读取），状态直接为 active
- 邀请码由管理员生成，8 位随机字母数字，可指定角色和有效期
- 邮箱验证和密码重置均依赖邮件服务（SMTP，配置通过环境变量 `MAIL_SMTP_*` 系列）
- 邮件不可用时，管理员可手动激活用户或重置密码作为降级方案
- 暂不支持多角色（一个用户一个角色）
- 暂不支持角色继承
- 暂不实现登录日志（仅 login_attempts 表用于暴力破解防护）
- `/api/health` 端点无需认证