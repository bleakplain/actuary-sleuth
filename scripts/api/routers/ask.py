"""法规问答路由 — 对话式问答 + 精确检索。"""

import json
import uuid
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.schemas.ask import (
    ChatRequest, ConversationOut, MessageOut,
)
from api.dependencies import get_rag_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ask", tags=["法规问答"])


@router.post("/chat")
async def chat(req: ChatRequest):
    conversation_id = req.conversation_id or f"conv_{uuid.uuid4().hex[:8]}"
    from api.database import create_conversation, add_message
    create_conversation(conversation_id, title=req.question[:50])
    add_message(conversation_id, "user", req.question)

    engine = get_rag_engine()

    if req.mode == "search":
        try:
            results = engine.search(req.question)
            content = json.dumps(results, ensure_ascii=False)
            add_message(conversation_id, "assistant", content, sources=results)
            return {
                "conversation_id": conversation_id,
                "mode": "search",
                "content": content,
                "sources": results,
            }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    async def event_stream():
        try:
            result = await asyncio.to_thread(engine.ask, req.question)
            answer = result.get("answer", "")
            chunk_size = 4
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i : i + chunk_size]
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "token", "data": chunk}, ensure_ascii=False
                    ),
                }
                await asyncio.sleep(0.01)

            msg_id = add_message(
                conversation_id,
                "assistant",
                answer,
                citations=result.get("citations", []),
                sources=result.get("sources", []),
                faithfulness_score=result.get("faithfulness_score"),
                unverified_claims=result.get("unverified_claims", []),
            )

            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "done",
                        "data": {
                            "conversation_id": conversation_id,
                            "message_id": msg_id,
                            "citations": result.get("citations", []),
                            "sources": result.get("sources", []),
                            "faithfulness_score": result.get("faithfulness_score"),
                            "unverified_claims": result.get("unverified_claims", []),
                        },
                    },
                    ensure_ascii=False,
                ),
            }
            # 自动质量检测 — 低于阈值自动创建 feedback
            try:
                from lib.rag_engine.quality_detector import detect_quality
                quality = detect_quality(
                    query=req.question,
                    answer=answer,
                    sources=result.get("sources", []),
                    faithfulness_score=result.get("faithfulness_score"),
                )
                if quality["overall"] < 0.4:
                    from api.database import create_feedback, update_feedback
                    fb_id = create_feedback(
                        message_id=msg_id,
                        conversation_id=conversation_id,
                        rating="down",
                        reason="auto_detected",
                        source_channel="auto_detect",
                    )
                    update_feedback(fb_id, {
                        "auto_quality_score": quality["overall"],
                        "auto_quality_details_json": json.dumps(quality, ensure_ascii=False),
                    })
            except Exception as e:
                logger.warning(f"Auto quality detection failed: {e}")
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_stream())


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations():
    from api.database import get_conversations
    return get_conversations()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str):
    from api.database import get_messages
    msgs = get_messages(conversation_id)
    if not msgs:
        raise HTTPException(status_code=404, detail="对话不存在")
    return msgs


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    from api.database import delete_conversation
    count = delete_conversation(conversation_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"deleted_messages": count}
