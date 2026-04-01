from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    message_id: int = Field(..., gt=0)
    rating: str = Field(..., pattern="^(up|down)$")
    reason: str = ""
    correction: str = ""


class FeedbackOut(BaseModel):
    id: str
    message_id: int
    conversation_id: str
    rating: str
    reason: str
    correction: str
    source_channel: str
    auto_quality_score: Optional[float] = None
    auto_quality_details: Optional[Dict] = None
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    status: str
    compliance_risk: int
    fix_action: str = ""
    resolved_at: Optional[str] = None
    created_at: str
    updated_at: str
    user_question: str = ""
    assistant_answer: str = ""


class FeedbackUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|classified|fixing|fixed|rejected|converted)$")
    classified_type: Optional[str] = None
    classified_reason: Optional[str] = None
    classified_fix_direction: Optional[str] = None
    compliance_risk: Optional[int] = Field(None, ge=0, le=2)
    fix_action: Optional[str] = None


class FeedbackStats(BaseModel):
    total: int
    up_count: int
    down_count: int
    satisfaction_rate: float
    by_type: Dict[str, int]
    by_status: Dict[str, int]
    by_risk: Dict[str, int]


class FeedbackActionLog(BaseModel):
    id: int
    feedback_id: str
    action: str
    detail: str
    created_at: str
