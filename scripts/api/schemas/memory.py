"""记忆和用户画像 Pydantic schemas。"""
from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: str
    memory: str
    user_id: str
    created_at: str
    category: str = "fact"


class UserProfile(BaseModel):
    user_id: str
    focus_areas: list[str] = Field(default_factory=list)
    preference_tags: list[str] = Field(default_factory=list)
    audit_stats: dict = Field(default_factory=dict)
    summary: str = ""


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 5


class MemoryAddRequest(BaseModel):
    content: str
    category: str = "fact"


class MemoryBatchDeleteRequest(BaseModel):
    memory_ids: list[str]


class ProfileUpdateRequest(BaseModel):
    focus_areas: list[str] | None = None
    preference_tags: list[str] | None = None
    summary: str | None = None
