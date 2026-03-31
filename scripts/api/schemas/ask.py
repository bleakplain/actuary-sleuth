from typing import Optional, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="对话 ID，为空则新建对话")
    mode: str = Field("qa", pattern="^(qa|search)$", description="qa=智能问答, search=精确检索")


class CitationOut(BaseModel):
    source_idx: int
    law_name: str
    article_number: str
    content: str


class SourceOut(BaseModel):
    law_name: str
    article_number: str = ""
    category: str = ""
    content: str
    source_file: str = ""
    hierarchy_path: str = ""


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    citations: List[CitationOut] = []
    sources: List[SourceOut] = []
    timestamp: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int = 0


class ChatSSEEvent(BaseModel):
    type: str
    data: Optional[object] = None
