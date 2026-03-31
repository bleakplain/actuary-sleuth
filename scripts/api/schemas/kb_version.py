"""知识库版本管理相关 Schema。"""

from pydantic import BaseModel


class VersionOut(BaseModel):
    version_id: str
    created_at: str
    document_count: int
    chunk_count: int
    active: bool
    description: str


class VersionListOut(BaseModel):
    versions: list[VersionOut]
    active_version: str


class CreateVersionRequest(BaseModel):
    description: str = ""
