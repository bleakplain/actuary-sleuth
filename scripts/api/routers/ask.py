"""法规问答路由 — 对话式问答 + 精确检索。"""

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from api.database import (
    add_message,
    batch_delete_sessions,
    create_session,
    create_feedback,
    delete_message,
    delete_session,
    get_sessions,
    get_messages,
    get_trace_by_message_id,
    get_session_context,
    save_session_context,
    save_spans,
    save_trace,
    search_sessions,
    update_feedback,
)
from api.dependencies import get_rag_engine, get_memory_service, get_ask_graph
from api.schemas.ask import ChatRequest, SessionOut, MessageOut
from lib.config import is_debug
from lib.llm.trace import cleanup_trace_counters, get_llm_call_count, reset_llm_call_count, trace_span
from lib.rag_engine.graph import AskState, GraphContext
from lib.rag_engine.quality_detector import detect_quality

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ask", tags=["法规问答"])


def _persist_trace(root_span, message_id: int, session_id: str = "",
                   name: str = "", summary: Optional[dict] = None,
                   trace_id: Optional[str] = None) -> None:
    """将 trace 树中所有 span 批量写入数据库。"""
    spans = list(root_span.iter_spans())
    if summary is None:
        error_count = sum(1 for s in spans if s.status == "error")
        llm_count = get_llm_call_count(trace_id)
        summary = {
            "status": "error" if error_count > 0 else "ok",
            "total_duration_ms": root_span.duration_ms,
            "span_count": len(spans),
            "llm_call_count": llm_count,
        }
    save_trace(
        root_span.trace_id, message_id, session_id, name,
        status=summary["status"],
        total_duration_ms=summary["total_duration_ms"],
        span_count=summary["span_count"],
        llm_call_count=summary["llm_call_count"],
    )
    save_spans([s.to_dict() for s in spans])


def _build_trace_payload(root_span, trace_id: Optional[str] = None) -> dict:
    """从 trace 树构建 SSE 推送的 trace 数据（与 TraceData 格式对齐）。"""
    spans = list(root_span.iter_spans())
    error_count = sum(1 for s in spans if s.status == "error")
    llm_count = get_llm_call_count(trace_id)
    flat_spans = [{k: v for k, v in s.to_dict().items() if k != "children"} for s in spans]
    return {
        "trace_id": root_span.trace_id,
        "root": root_span.to_dict(),
        "spans": flat_spans,
        "summary": {
            "total_duration_ms": root_span.duration_ms,
            "span_count": len(spans),
            "llm_call_count": llm_count,
            "error_count": error_count,
            "status": "error" if error_count > 0 else "ok",
        },
    }


@router.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    create_session(session_id, title=req.question[:50], user_id=req.user_id)
    add_message(session_id, "user", req.question)

    engine = get_rag_engine()

    # debug: 前端显式传值时以请求为准，否则读取配置默认值
    if req.debug is None:
        req.debug = is_debug()

    if req.mode == "search":
        try:
            results = engine.search(req.question)
            content = json.dumps(results, ensure_ascii=False)
            add_message(session_id, "assistant", content, sources=results)
            return {
                "session_id": session_id,
                "mode": "search",
                "content": content,
                "sources": results,
            }
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise HTTPException(status_code=500, detail=f"检索失败: {e}")

    async def event_stream():
        root_span = None
        exc_info = (None, None, None)
        try:
            if req.debug:
                _span_ctx = trace_span("root", "root")
                root_span = _span_ctx.__enter__()
                reset_llm_call_count(root_span.trace_id)
                root_span.input = {"question": req.question, "mode": req.mode}

            cache = engine.cache

            if cache:
                cached = cache.get("generation", req.question)
                if cached is not None:
                    answer = cached.get("answer", "")
                    chunk_size = 4
                    for i in range(0, len(answer), chunk_size):
                        chunk = answer[i : i + chunk_size]
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {"type": "token", "data": chunk}, ensure_ascii=False
                            ),
                        }

                    msg_id = add_message(
                        session_id,
                        "assistant",
                        answer,
                        citations=cached.get("citations", []),
                        sources=cached.get("sources", []),
                    )

                    if root_span:
                        root_span.output = {"answer_length": len(answer), "cached": True}
                        root_span.metadata = {"mode": req.mode, "cache_hit": True}
                        _span_ctx.__exit__(*exc_info)
                        exc_info = (None, None, None)

                    trace_summary = None
                    if root_span:
                        tid = root_span.trace_id
                        trace_summary = _build_trace_payload(root_span, tid)
                        _persist_trace(root_span, msg_id, session_id,
                                       name=req.question, summary=trace_summary["summary"])
                        cleanup_trace_counters(tid)

                    response_meta: dict = {
                        "session_id": session_id,
                        "message_id": msg_id,
                        "citations": cached.get("citations", []),
                        "sources": cached.get("sources", []),
                        "unverified_claims": cached.get("unverified_claims", []),
                        "content_mismatches": cached.get("content_mismatches", []),
                        "cached": True,
                    }
                    if trace_summary:
                        response_meta["trace"] = trace_summary

                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "done", "data": response_meta}, ensure_ascii=False),
                    }
                    return

            # 正常路径：graph.invoke
            memory_svc = get_memory_service()
            graph = get_ask_graph()
            state = AskState(
                question=req.question, mode=req.mode, user_id=req.user_id,
                session_id=session_id, search_results=[], memory_context="",
                answer="", sources=[], citations=[], unverified_claims=[],
                content_mismatches=[], faithfulness_score=None, error=None,
                messages=[], session_context={}, skip_clarify=req.skip_clarify,
                iteration_count=0, next_action="search",
                clarification_message=None, clarification_options=None,
                loop_detected=None, loop_hint=None,
            )
            context = GraphContext(
                rag_engine=engine, llm_client=engine._llm_client,
                memory_service=memory_svc,
            )
            result = await asyncio.to_thread(graph.invoke, state, context=context)

            # 检查是否需要澄清
            if result.get("next_action") == "clarify":
                yield {
                    "event": "clarify",
                    "data": json.dumps({
                        "message": result.get("clarification_message", ""),
                        "options": result.get("clarification_options", []),
                        "session_context": result.get("session_context", {}),
                    }, ensure_ascii=False)
                }
                return

            if cache:
                cache.set("generation", req.question, result)

            if root_span:
                root_span.output = {
                    "answer_length": len(result.get("answer", "")),
                    "answer": result.get("answer", ""),
                    "source_count": len(result.get("sources", [])),
                }
                root_span.metadata = {
                    "mode": req.mode,
                    "retrieval": "hybrid",
                    "reranker": engine.active_reranker_type,
                }

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

            msg_id = add_message(
                session_id,
                "assistant",
                answer,
                citations=result.get("citations", []),
                sources=result.get("sources", []),
                faithfulness_score=result.get("faithfulness_score"),
                unverified_claims=result.get("unverified_claims", []),
            )

            if root_span:
                _span_ctx.__exit__(*exc_info)
                exc_info = (None, None, None)

            trace_summary = None
            if root_span:
                tid = root_span.trace_id
                trace_summary = _build_trace_payload(root_span, tid)
                _persist_trace(root_span, msg_id, session_id,
                               name=req.question, summary=trace_summary["summary"])
                cleanup_trace_counters(tid)

            response_meta: dict = {
                "session_id": session_id,
                "message_id": msg_id,
                "citations": result.get("citations", []),
                "sources": result.get("sources", []),
                "faithfulness_score": result.get("faithfulness_score"),
                "unverified_claims": result.get("unverified_claims", []),
                "content_mismatches": result.get("content_mismatches", []),
                "session_context": result.get("session_context", {}),
                "loop_detected": result.get("loop_detected"),
                "loop_hint": result.get("loop_hint"),
            }
            if trace_summary:
                response_meta["trace"] = trace_summary

            yield {
                "event": "message",
                "data": json.dumps({"type": "done", "data": response_meta}, ensure_ascii=False),
            }

            # 自动质量检测 — 低于阈值自动创建 feedback
            try:
                quality = detect_quality(
                    query=req.question,
                    answer=answer,
                    sources=result.get("sources", []),
                    faithfulness_score=result.get("faithfulness_score"),
                )
                if quality["overall"] < 0.4:
                    fb_id = create_feedback(
                        message_id=msg_id,
                        session_id=session_id,
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
            exc_info = (type(e), e, e.__traceback__)
            logger.error(f"Chat failed: {e}")
            if root_span:
                _span_ctx.__exit__(*exc_info)
                cleanup_trace_counters(root_span.trace_id)
            yield {
                "event": "message",
                "data": json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_stream())


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(search: str = Query("", description="按标题模糊搜索")):
    if search:
        rows, _ = search_sessions(search=search, page=1, size=100)
        return rows
    return get_sessions()


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: str):
    msgs = get_messages(session_id)
    if not msgs:
        raise HTTPException(status_code=404, detail="对话不存在")
    return msgs


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    count = delete_session(session_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"deleted_messages": count}


@router.delete("/sessions")
async def batch_remove_sessions(ids: str = Query(..., description="逗号分隔的会话 ID")):
    session_ids = [sid.strip() for sid in ids.split(",") if sid.strip()]
    deleted = batch_delete_sessions(session_ids)
    return {"deleted": deleted}


@router.get("/messages/{message_id}/trace")
async def get_message_trace(message_id: int):
    trace = get_trace_by_message_id(message_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.delete("/messages/{message_id}")
async def remove_message(message_id: int):
    deleted = delete_message(message_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"deleted_messages": deleted}


@router.get("/sessions/{session_id}/context")
async def get_session_context_endpoint(session_id: str):
    """获取会话上下文"""
    ctx = get_session_context(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "context": ctx}


ALLOWED_CONTEXT_KEYS = frozenset({
    "product_type", "mentioned_entities", "current_topic",
    "query_history", "user_preference", "focus_area",
})


@router.put("/sessions/{session_id}/context")
async def update_session_context_endpoint(session_id: str, context: dict):
    """更新会话上下文（澄清选择后调用）"""
    # 输入验证：只允许白名单中的 key
    invalid_keys = set(context.keys()) - ALLOWED_CONTEXT_KEYS
    if invalid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"不允许的上下文字段: {', '.join(invalid_keys)}"
        )

    existing = get_session_context(session_id) or {}
    merged = {**existing, **context}
    success = save_session_context(session_id, merged)
    if not success:
        raise HTTPException(status_code=500, detail="保存失败")
    return {"session_id": session_id, "context": merged}
