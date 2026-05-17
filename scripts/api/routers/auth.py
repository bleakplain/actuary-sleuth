"""认证路由 — 注册、登录、邮箱验证、密码管理。"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.database import (
    create_email_token,
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
    if get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="邮箱已注册")
    invite = get_invite_code_by_code(req.invite_code)
    if not invite:
        raise HTTPException(status_code=400, detail="邀请码无效")
    now = datetime.now(timezone.utc).isoformat()
    if invite["used_by"] is not None or invite["expires_at"] < now:
        raise HTTPException(status_code=400, detail="邀请码无效")
    user_id = create_user(req.email, hash_password(req.password), invite["role_id"])
    use_invite_code(invite["id"], user_id)
    raw_token = uuid.uuid4().hex
    token_hash = _generate_token_hash(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    create_email_token(user_id, token_hash, expires_at)
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
    if get_recent_failed_attempts(req.email, cfg.lockout_minutes) >= cfg.max_login_attempts:
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        record_login_attempt(req.email, False)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="请先验证邮箱")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="账户已被禁用")
    role = get_role(user["role_id"])
    permissions = json.loads(role["permissions_json"]) if role else []
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
    verify_user_email(token_record["user_id"])
    verify_email_token(token_hash)
    return {"message": "邮箱验证成功"}


@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest):
    """重发验证邮件。"""
    user = get_user_by_email(req.email)
    if not user or user["email_verified_at"] is not None:
        return {"message": "如果该邮箱已注册且未验证，验证邮件已发送"}
    invalidate_pending_email_tokens(user["id"])
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
    update_user_password(token_record["user_id"], hash_password(req.new_password))
    use_reset_token(token_hash)
    return {"message": "密码重置成功"}
