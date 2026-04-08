"""可测性路由 — Trace 查看与清理。"""

from fastapi import APIRouter, HTTPException, Query

from api.database import (
    search_traces,
    get_trace_by_id,
    batch_delete_traces,
    count_traces_for_cleanup,
    cleanup_traces,
)
from api.schemas.observability import TraceListResponse, CleanupRequest

router = APIRouter(prefix="/api/observability", tags=["可测性"])


@router.get("/traces", response_model=TraceListResponse)
async def list_traces(
    trace_id: str = Query("", description="精确匹配 trace ID"),
    session_id: str = Query("", description="精确匹配 session ID"),
    message_id: int = Query(0, description="精确匹配 message ID"),
    status: str = Query("", description="状态过滤: ok / error"),
    start_date: str = Query("", description="起始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="截止日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = search_traces(
        trace_id=trace_id,
        session_id=session_id,
        message_id=message_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )
    return TraceListResponse(items=items, total=total)


@router.get("/traces/{trace_id}")
async def get_trace_detail(trace_id: str):
    trace = get_trace_by_id(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.delete("/traces")
async def delete_traces(ids: str = Query(..., description="逗号分隔的 trace ID 列表")):
    trace_ids = [tid.strip() for tid in ids.split(",") if tid.strip()]
    deleted = batch_delete_traces(trace_ids)
    return {"deleted": deleted}


@router.post("/traces/cleanup")
async def cleanup_traces_endpoint(req: CleanupRequest):
    if req.preview:
        count = count_traces_for_cleanup(req.start_date, req.end_date, req.status)
        return {"count": count}
    deleted = cleanup_traces(req.start_date, req.end_date, req.status)
    return {"deleted": deleted}
