from typing import Optional, List
from pydantic import BaseModel, Field


class TraceListItem(BaseModel):
    trace_id: str
    message_id: Optional[int] = None
    conversation_id: Optional[str] = None
    created_at: str
    status: str = "ok"
    total_duration_ms: float = 0
    span_count: int = 0


class TraceListResponse(BaseModel):
    items: List[TraceListItem] = []
    total: int = 0


class CleanupRequest(BaseModel):
    start_date: str = ""
    end_date: str = ""
    status: str = ""
    preview: bool = True
