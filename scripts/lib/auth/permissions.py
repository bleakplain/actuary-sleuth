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
