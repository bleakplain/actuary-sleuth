# Feature Specification: 用户注册登录

**Feature Branch**: `015-user-auth`
**Created**: 2026-04-18
**Status**: Draft
**Input**: 实现用户注册登录，邮箱密码方式，邀请码注册，邮箱验证，角色权限管理

## User Scenarios & Testing

### User Story 1 - 用户注册 (Priority: P1)

内部员工通过邀请码注册账户，完成邮箱验证后可使用系统。

**Why this priority**: 注册是用户入口，必须首先实现。

**Independent Test**:
1. 生成有效邀请码
2. 使用邀请码 + 邮箱 + 密码注册
3. 收到验证邮件并点击链接
4. 账户状态变为 active

**Acceptance Scenarios**:

1. **Given** 存在有效邀请码, **When** 用户提交邮箱、密码、邀请码, **Then** 创建 pending 状态用户，发送验证邮件
2. **Given** 邀请码已使用或无效, **When** 用户提交注册, **Then** 返回"邀请码无效"错误
3. **Given** 邮箱已注册, **When** 用户提交注册, **Then** 返回"邮箱已存在"错误
4. **Given** 用户状态为 pending, **When** 点击验证邮件链接, **Then** 状态变为 active，邀请码标记为已使用

---

### User Story 2 - 用户登录 (Priority: P1)

已注册用户通过邮箱密码登录系统。

**Why this priority**: 登录是核心功能，与注册同等重要。

**Independent Test**:
1. 注册并验证用户
2. 使用邮箱密码登录
3. 返回 JWT Token

**Acceptance Scenarios**:

1. **Given** 用户状态为 active, **When** 提交正确邮箱密码, **Then** 返回 JWT Token
2. **Given** 用户状态为 pending, **When** 提交登录, **Then** 返回"请先验证邮箱"
3. **Given** 用户状态为 disabled, **When** 提交登录, **Then** 返回"账户已被禁用"
4. **Given** 密码错误, **When** 提交登录, **Then** 返回"邮箱或密码错误"
5. **Given** 用户不存在, **When** 提交登录, **Then** 返回"邮箱或密码错误"（不泄露用户是否存在）

---

### User Story 3 - 密码重置 (Priority: P2)

用户忘记密码时通过邮箱重置。

**Why this priority**: 重要体验功能，但不阻塞核心流程。

**Independent Test**:
1. 已注册用户
2. 请求重置密码
3. 收到邮件并设置新密码

**Acceptance Scenarios**:

1. **Given** 用户邮箱存在, **When** 请求重置密码, **Then** 发送重置链接邮件
2. **Given** 用户邮箱不存在, **When** 请求重置密码, **Then** 静默返回成功（不泄露用户是否存在）
3. **Given** 有效重置链接, **When** 提交新密码, **Then** 密码更新成功
4. **Given** 重置链接过期（24h）, **When** 提交新密码, **Then** 返回"链接已过期"

---

### User Story 4 - 邀请码管理 (Priority: P2)

管理员创建、查看、禁用邀请码。

**Why this priority**: 注册依赖邀请码，但可先用脚本生成。

**Independent Test**:
1. 管理员登录
2. 创建邀请码
3. 查看邀请码列表
4. 禁用邀请码

**Acceptance Scenarios**:

1. **Given** 管理员登录, **When** 创建邀请码, **Then** 生成唯一邀请码，状态为 active
2. **Given** 管理员登录, **When** 查看邀请码列表, **Then** 显示所有邀请码及使用状态
3. **Given** 邀请码状态为 active, **When** 管理员禁用, **Then** 状态变为 disabled，不可用于注册
4. **Given** 邀请码已被使用, **When** 管理员查看, **Then** 显示使用者信息

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
5. **Given** 管理员登录, **When** 修改用户角色, **Then** 用户权限立即更新

---

### User Story 6 - 角色权限管理 (Priority: P3)

管理员查看角色、修改角色权限。

**Why this priority**: 权限细化功能，初期可用默认角色。

**Independent Test**:
1. 管理员登录
2. 查看角色列表及权限
3. 修改某角色权限
4. 该角色用户权限立即生效

**Acceptance Scenarios**:

1. **Given** 管理员登录, **When** 查看角色列表, **Then** 显示所有角色及权限
2. **Given** 管理员登录, **When** 修改角色权限, **Then** 权限更新成功
3. **Given** 角色权限被修改, **When** 该角色用户请求 API, **Then** 按新权限校验

---

### Edge Cases

- 邀请码过期后还能使用吗？→ 可以设置邀请码过期时间，或暂不实现
- 验证邮件/重置邮件发送失败？→ 返回错误提示用户重试
- JWT Token 过期？→ 返回 401，前端跳转登录页
- 用户修改邮箱？→ 暂不支持

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持邮箱 + 密码注册，密码加密存储
- **FR-002**: 系统 MUST 验证邀请码有效性后才允许注册
- **FR-003**: 系统 MUST 发送验证邮件，用户验证后账户激活
- **FR-004**: 系统 MUST 支持邮箱 + 密码登录，返回 JWT Token
- **FR-005**: 系统 MUST 支持通过邮箱重置密码
- **FR-006**: 系统 MUST 支持管理员管理邀请码（创建、查看、禁用）
- **FR-007**: 系统 MUST 支持管理员管理用户（查看、禁用/启用、修改角色）
- **FR-008**: 系统 MUST 支持基于角色的权限控制（RBAC）
- **FR-009**: 系统 MUST 校验用户权限后允许访问对应功能

### Key Entities

- **User**: 用户，包含邮箱、密码、角色、状态
- **Role**: 角色，包含名称、权限列表（JSON）
- **InviteCode**: 邀请码，包含码值、状态、创建者、使用者

## Data Models

### users 表

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'active' | 'disabled'
    email_verified_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### roles 表

```sql
CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,              -- 'admin' | 'actuary' | 'compliance' | 'viewer'
    display_name TEXT NOT NULL,
    permissions TEXT NOT NULL               -- JSON: ['ask', 'compliance', 'eval', 'knowledge', 'memory', 'admin']
);
```

### invite_codes 表

```sql
CREATE TABLE invite_codes (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'used' | 'disabled'
    created_by INTEGER NOT NULL,
    used_by INTEGER,
    used_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (used_by) REFERENCES users(id)
);
```

### 预置角色

| 角色 | 权限 |
|------|------|
| admin | ask, compliance, eval, knowledge, memory, admin |
| actuary | ask, compliance, memory |
| compliance | ask, compliance, memory |
| viewer | ask |

## API Design

### 认证 API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/auth/register` | POST | 注册（邮箱、密码、邀请码） |
| `/api/auth/login` | POST | 登录，返回 JWT |
| `/api/auth/verify-email` | POST | 验证邮箱（token） |
| `/api/auth/forgot-password` | POST | 请求重置密码（邮箱） |
| `/api/auth/reset-password` | POST | 重置密码（token、新密码） |
| `/api/auth/me` | GET | 获取当前用户信息 |
| `/api/auth/logout` | POST | 登出（可选，JWT 无状态） |

### 管理 API（需 admin 权限）

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/admin/invite-codes` | GET | 列出邀请码 |
| `/api/admin/invite-codes` | POST | 创建邀请码 |
| `/api/admin/invite-codes/{id}/disable` | PATCH | 禁用邀请码 |
| `/api/admin/users` | GET | 列出用户 |
| `/api/admin/users/{id}` | PATCH | 修改用户（状态、角色） |
| `/api/admin/roles` | GET | 列出角色 |
| `/api/admin/roles/{id}` | PATCH | 修改角色权限 |

## Success Criteria

- **SC-001**: 用户可通过邀请码注册并验证邮箱
- **SC-002**: 已验证用户可登录并获取 Token
- **SC-003**: 管理员可创建邀请码并管理用户
- **SC-004**: 权限校验正确，无权限返回 403

## Assumptions

- 邮件发送服务已配置（SMTP 或第三方服务）
- JWT 密钥通过环境变量配置
- 初始管理员账户通过脚本创建
- 暂不实现登录日志、使用记录
- 暂不支持多角色（一个用户一个角色）
- 暂不支持角色继承
