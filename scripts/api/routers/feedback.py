"""反馈管理路由 — 用户反馈提交 + Badcase 管理。"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas.feedback import (
    FeedbackCreate, FeedbackOut, FeedbackUpdate, FeedbackStats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["反馈管理"])


@router.post("/submit", response_model=FeedbackOut)
async def submit_feedback(req: FeedbackCreate):
    from api.database import create_feedback, get_feedback, get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (req.message_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    conversation_id = row[0]
    fb_id = create_feedback(
        message_id=req.message_id,
        conversation_id=conversation_id,
        rating=req.rating,
        reason=req.reason,
        correction=req.correction,
        source_channel="user_button",
    )
    result = get_feedback(fb_id)
    if result is None:
        raise HTTPException(status_code=500, detail="反馈创建失败")
    return result


@router.get("/badcases", response_model=list[FeedbackOut])
async def list_badcases(
    status: Optional[str] = Query(None),
    classified_type: Optional[str] = Query(None),
    compliance_risk: Optional[int] = Query(None),
):
    from api.database import list_feedbacks
    return list_feedbacks(
        status=status,
        classified_type=classified_type,
        compliance_risk=compliance_risk,
    )


@router.get("/badcases/{feedback_id}", response_model=FeedbackOut)
async def get_badcase(feedback_id: str):
    from api.database import get_feedback
    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return fb


@router.put("/badcases/{feedback_id}", response_model=FeedbackOut)
async def update_badcase(feedback_id: str, req: FeedbackUpdate):
    from api.database import get_feedback, update_feedback
    existing = get_feedback(feedback_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    updates = req.model_dump(exclude_none=True)
    if updates:
        update_feedback(feedback_id, updates)
    return get_feedback(feedback_id)


@router.get("/stats", response_model=FeedbackStats)
async def get_stats():
    from api.database import get_feedback_stats
    return get_feedback_stats()
