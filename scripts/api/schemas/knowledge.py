from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    name: str
    file_path: str
    clause_count: int = 0
    file_size: int = 0
    indexed_at: Optional[str] = None
    status: str = "indexed"


class ImportRequest(BaseModel):
    file_path: Optional[str] = Field(None, description="服务器端文件路径")
    file_pattern: str = Field("*.md", description="文件匹配模式")


class RebuildRequest(BaseModel):
    file_pattern: str = Field("*.md", description="文件匹配模式")
    force: bool = Field(False, description="是否强制重建")


class IndexStatus(BaseModel):
    vector_db: Dict[str, object] = {}
    bm25: Dict[str, object] = {}
    document_count: int = 0


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: str = ""
    result: Optional[Dict[str, object]] = None
