from typing import Optional, List
from pydantic import BaseModel, Field


class TraceListItem(BaseModel):
    trace_id: str
    message_id: Optional[int] = None
    session_id: Optional[str] = None
    created_at: str
    status: str = "ok"
    total_duration_ms: float = 0
    span_count: int = 0
    llm_call_count: int = 0
    trace_name: Optional[str] = None


class TraceListResponse(BaseModel):
    items: List[TraceListItem] = []
    total: int = 0


class CleanupRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    status: str = ""
    preview: bool = True


class CacheEntry(BaseModel):
    key: str
    namespace: str
    created_at: float
    ttl: int
    kb_version: str
    size_bytes: int


class CacheEntryListResponse(BaseModel):
    items: List[CacheEntry] = []
    total: int = 0


class CacheTrendPoint(BaseModel):
    timestamp: str
    hits: int
    misses: int
    hit_rate: float
    memory_size: int
    evictions: int = 0
    l2_size: int = 0


class CacheTrendResponse(BaseModel):
    points: List[CacheTrendPoint] = []
