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
