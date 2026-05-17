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
    if user_id == admin["user_id"] and req.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用自己")
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
