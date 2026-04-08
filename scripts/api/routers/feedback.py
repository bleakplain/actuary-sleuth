"""反馈管理路由 — 用户反馈提交 + Badcase 管理。"""

import json
import logging
from typing import Dict, Optional

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
            "SELECT session_id FROM messages WHERE id = ?", (req.message_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    session_id = row[0]
    fb_id = create_feedback(
        message_id=req.message_id,
        session_id=session_id,
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


@router.post("/badcases/classify")
async def classify_badcases():
    """对所有 pending 状态的 badcase 执行自动分类"""
    return await classify_pending_badcases()


async def classify_pending_badcases() -> Dict[str, int]:
    from api.database import list_feedbacks, update_feedback, get_connection
    from lib.rag_engine.badcase_classifier import classify_badcase, assess_compliance_risk
    from lib.rag_engine.quality_detector import detect_quality
    from api.dependencies import get_rag_engine

    pending = list_feedbacks(status="pending")
    classified_count = 0
    engine = get_rag_engine()
    llm_client = engine._llm_client if engine else None

    for fb in pending:
        if fb["rating"] != "down":
            update_feedback(fb["id"], {"status": "rejected"})
            continue

        with get_connection() as conn:
            msgs = conn.execute(
                "SELECT role, content, sources_json, unverified_claims_json FROM messages WHERE id = ?",
                (fb["message_id"],),
            ).fetchone()
            if msgs is None:
                continue
            user_msg = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
                (fb["session_id"], fb["message_id"]),
            ).fetchone()

        query = user_msg[0] if user_msg else ""
        sources = json.loads(msgs["sources_json"]) if msgs["sources_json"] else []
        answer = msgs["content"] or ""
        unverified = json.loads(msgs["unverified_claims_json"]) if msgs["unverified_claims_json"] else []

        try:
            classification = classify_badcase(query, sources, answer, unverified, llm_client=llm_client)
            quality = detect_quality(query, answer, sources)
            risk = assess_compliance_risk(classification["type"], classification["reason"], answer)

            update_feedback(fb["id"], {
                "classified_type": classification["type"],
                "classified_reason": classification["reason"],
                "classified_fix_direction": classification["fix_direction"],
                "auto_quality_score": quality["overall"],
                "auto_quality_details_json": json.dumps(quality, ensure_ascii=False),
                "compliance_risk": risk,
                "status": "classified",
            })
            classified_count += 1
        except Exception as e:
            logger.error(f"Classification failed for {fb['id']}: {e}")

    return {"classified": classified_count, "total": len(pending)}


@router.post("/badcases/{feedback_id}/verify")
async def verify_badcase(feedback_id: str):
    """重跑 badcase 的原始问题，返回当前引擎的回答用于对比"""
    from api.database import get_feedback, get_connection

    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")

    with get_connection() as conn:
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (fb["session_id"], fb["message_id"]),
        ).fetchone()

    if user_msg is None:
        raise HTTPException(status_code=400, detail="无法找到原始问题")

    query = user_msg[0]

    try:
        from api.app import rag_engine
        if rag_engine is None:
            raise RuntimeError("RAG 引擎未就绪")

        result = rag_engine.ask(query, include_sources=True)

        from lib.rag_engine.evaluator import GenerationEvaluator
        contexts = [s.get('content', '') for s in result.get('sources', [])]
        answer = result.get('answer', '')
        faithfulness = GenerationEvaluator._compute_faithfulness(contexts, answer) if contexts and answer else None

        return {
            "feedback_id": feedback_id,
            "original_answer": fb.get("correction") or "",
            "new_answer": answer,
            "new_sources": result.get("sources", []),
            "new_citations": result.get("citations", []),
            "new_faithfulness": faithfulness,
            "new_unverified_claims": result.get("unverified_claims", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {e}")


@router.post("/badcases/{feedback_id}/convert")
async def convert_to_eval_sample(feedback_id: str, ground_truth: str = ""):
    """将 badcase 转化为评估样本"""
    from api.database import get_feedback, upsert_eval_sample, update_feedback, get_connection

    fb = get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")

    with get_connection() as conn:
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND id < ? ORDER BY id DESC LIMIT 1",
            (fb["session_id"], fb["message_id"]),
        ).fetchone()
        assistant_msg = conn.execute(
            "SELECT sources_json FROM messages WHERE id = ?",
            (fb["message_id"],),
        ).fetchone()

    if user_msg is None:
        raise HTTPException(status_code=400, detail="无法找到原始问题")

    sources = json.loads(assistant_msg["sources_json"]) if assistant_msg else []
    evidence_docs = list({s.get("source_file", "") for s in sources if s.get("source_file")})

    sample_id = f"bc_{feedback_id}"
    upsert_eval_sample({
        "id": sample_id,
        "question": user_msg[0],
        "ground_truth": ground_truth or fb.get("correction", ""),
        "evidence_docs": evidence_docs,
        "evidence_keywords": [],
        "question_type": fb.get("classified_type", "factual") or "factual",
        "difficulty": "medium",
        "topic": "",
    })

    update_feedback(feedback_id, {"status": "converted"})
    return {"sample_id": sample_id, "feedback_id": feedback_id}
