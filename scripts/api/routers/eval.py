"""评估管理路由 — 数据集 CRUD + 快照 + 评估运行。"""

import uuid
import asyncio
import json
import logging
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas.eval import (
    EvalSampleCreate, EvalSampleOut, ImportSamplesRequest,
    EvaluationRequest, CompareRequest, SnapshotCreate,
    HumanReviewCreate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/eval", tags=["评估管理"])

_eval_tasks: dict = {}


# ── 数据集管理 ───────────────────────────────────────


def _ensure_default_dataset():
    from api.database import eval_sample_count
    if eval_sample_count() > 0:
        return
    try:
        from lib.rag_engine import load_eval_dataset
        samples = load_eval_dataset()
        from api.database import import_eval_samples
        count = import_eval_samples([s.to_dict() for s in samples])
        if count > 0:
            logger.info(f"已导入 {count} 条默认评测数据")
    except Exception as e:
        logger.warning(f"导入默认数据集失败: {e}")


@router.get("/dataset", response_model=list[EvalSampleOut])
async def list_eval_samples(
    question_type: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
):
    from api.database import get_eval_samples
    return get_eval_samples(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
    )


@router.post("/dataset/samples", response_model=EvalSampleOut)
async def create_eval_sample(sample: EvalSampleCreate):
    from api.database import upsert_eval_sample, get_eval_sample
    upsert_eval_sample(sample.model_dump())
    result = get_eval_sample(sample.id)
    if result is None:
        raise HTTPException(status_code=500, detail="创建失败")
    return result


@router.put("/dataset/samples/{sample_id}", response_model=EvalSampleOut)
async def update_eval_sample(sample_id: str, sample: EvalSampleCreate):
    from api.database import get_eval_sample, upsert_eval_sample
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    update_data = sample.model_dump()
    update_data["id"] = sample_id
    upsert_eval_sample(update_data)
    return get_eval_sample(sample_id)


@router.delete("/dataset/samples/{sample_id}")
async def delete_eval_sample(sample_id: str):
    from api.database import delete_eval_sample
    if not delete_eval_sample(sample_id):
        raise HTTPException(status_code=404, detail="样本不存在")
    return {"deleted": True}


@router.post("/dataset/import")
async def import_dataset(req: ImportSamplesRequest):
    from api.database import import_eval_samples
    samples = [s.model_dump() for s in req.samples]
    count = import_eval_samples(samples)
    return {"imported": count, "total": len(samples), "skipped": len(samples) - count}


@router.post("/dataset/snapshots")
async def create_snapshot(req: SnapshotCreate):
    from api.database import create_snapshot
    snap_id = create_snapshot(req.name, req.description)
    return {"snapshot_id": snap_id, "name": req.name}


@router.get("/dataset/snapshots")
async def list_snapshots():
    from api.database import get_snapshots
    return get_snapshots()


@router.post("/dataset/snapshots/{snapshot_id}/restore")
async def restore_snapshot(snapshot_id: str):
    from api.database import restore_snapshot, get_snapshots
    snap_ids = [s["id"] for s in get_snapshots()]
    if snapshot_id not in snap_ids:
        raise HTTPException(status_code=404, detail="快照不存在")
    count = restore_snapshot(snapshot_id)
    return {"restored": count}


# ── 评估运行 ─────────────────────────────────────────


@router.post("/evaluations")
async def create_evaluation(req: EvaluationRequest):
    evaluation_id = f"eval_{uuid.uuid4().hex[:8]}"

    from api.database import create_evaluation
    create_evaluation(evaluation_id, req.mode, {
        "top_k": req.top_k,
        "chunking": req.chunking,
    })

    _eval_tasks[evaluation_id] = {"status": "pending"}

    async def _run_eval():
        try:
            _eval_tasks[evaluation_id]["status"] = "running"

            from api.app import rag_engine
            if rag_engine is None:
                raise RuntimeError("RAG 引擎未就绪")

            from api.database import (
                get_eval_samples, update_evaluation_status,
                save_evaluation_report, save_sample_result,
            )
            from lib.rag_engine import RetrievalEvaluator, GenerationEvaluator
            from lib.rag_engine.llm_judge import LLMPJudge
            from lib.llm import LLMClientFactory

            samples_data = get_eval_samples()
            samples = [EvalSample.from_dict(s) for s in samples_data]
            total = len(samples)
            update_evaluation_status(evaluation_id, "running", progress=0, total=total)

            if req.mode in ("retrieval", "full"):
                ret_eval = RetrievalEvaluator(rag_engine)
                ret_report, ret_details = ret_eval.evaluate_batch(samples, top_k=req.top_k)
                for detail in ret_details:
                    sample_id = detail.get("sample_id", "")
                    save_sample_result(
                        evaluation_id, sample_id,
                        retrieval_metrics=detail,
                    )
                    current = _eval_tasks[evaluation_id].get("progress", 0) + 1
                    _eval_tasks[evaluation_id]["progress"] = current
                    update_evaluation_status(evaluation_id, "running", progress=current, total=total)

            gen_report = None
            if req.mode in ("generation", "full", "llm_judge"):
                llm_judge = None
                if req.mode == "llm_judge":
                    eval_llm = LLMClientFactory.create_eval_llm()
                    llm_judge = LLMPJudge(eval_llm)
                gen_eval = GenerationEvaluator(rag_engine=rag_engine, llm_judge=llm_judge)
                gen_report = gen_eval.evaluate_batch(samples, rag_engine=rag_engine)

            report: Dict = {}
            if req.mode in ("retrieval", "full"):
                report["retrieval"] = ret_report.to_dict() if hasattr(ret_report, "to_dict") else vars(ret_report)
            if gen_report is not None:
                report["generation"] = gen_report.to_dict() if hasattr(gen_report, "to_dict") else vars(gen_report)
            report["total_samples"] = total
            report["failed_samples"] = []

            save_evaluation_report(evaluation_id, report)
            update_evaluation_status(evaluation_id, "completed")
            _eval_tasks[evaluation_id]["status"] = "completed"

        except Exception as e:
            logger.error(f"Eval run {evaluation_id} failed: {e}")
            from api.database import update_evaluation_status
            update_evaluation_status(evaluation_id, "failed")
            _eval_tasks[evaluation_id]["status"] = "failed"
            _eval_tasks[evaluation_id]["error"] = str(e)

    asyncio.create_task(_run_eval())
    return {"evaluation_id": evaluation_id, "status": "pending"}


@router.get("/evaluations/{evaluation_id}/status")
async def get_evaluation_status(evaluation_id: str):
    from api.database import get_evaluation
    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    return {
        "evaluation_id": run["id"],
        "mode": run["mode"],
        "status": run["status"],
        "progress": run["progress"],
        "total": run["total"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
    }


@router.get("/evaluations/{evaluation_id}/report")
async def get_evaluation_report(evaluation_id: str):
    from api.database import get_evaluation
    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"评估尚未完成，当前状态: {run['status']}")
    return run.get("report", {})


@router.get("/evaluations/{evaluation_id}/details")
async def get_evaluation_details(evaluation_id: str):
    from api.database import get_evaluation, get_sample_results
    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    results = get_sample_results(evaluation_id)
    return {
        "evaluation_id": evaluation_id,
        "mode": run["mode"],
        "status": run["status"],
        "total_samples": run["total"],
        "details": results,
    }


@router.get("/evaluations")
async def list_evaluations():
    from api.database import get_evaluations
    return get_evaluations()


@router.post("/evaluations/compare")
async def compare_evaluations(req: CompareRequest):
    from api.database import get_evaluation

    baseline = get_evaluation(req.baseline_id)
    compare = get_evaluation(req.compare_id)
    if baseline is None or compare is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")

    baseline_report = baseline.get("report", {})
    compare_report = compare.get("report", {})

    diff = {}
    improved = []
    regressed = []

    for key in ["retrieval", "generation"]:
        b = baseline_report.get(key, {})
        c = compare_report.get(key, {})
        if not b or not c:
            continue
        for metric in ["precision_at_k", "recall_at_k", "mrr", "ndcg",
                        "faithfulness", "answer_relevancy", "answer_correctness"]:
            b_val = b.get(metric)
            c_val = c.get(metric)
            if b_val is None or c_val is None:
                continue
            delta = c_val - b_val
            pct = (delta / b_val * 100) if b_val != 0 else 0
            diff[f"{key}.{metric}"] = {
                "baseline": b_val,
                "compare": c_val,
                "delta": round(delta, 4),
                "pct_change": round(pct, 2),
            }
            if delta > 0:
                improved.append(f"{key}.{metric}")
            elif delta < 0:
                regressed.append(f"{key}.{metric}")

    return {
        "baseline_id": req.baseline_id,
        "compare_id": req.compare_id,
        "metrics_diff": diff,
        "improved": improved,
        "regressed": regressed,
    }


@router.get("/evaluations/{evaluation_id}/export")
async def export_evaluation_report(evaluation_id: str, format: str = "json"):
    from api.database import get_evaluation
    from fastapi.responses import JSONResponse, Response

    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="评估尚未完成")

    report = run.get("report", {})
    if format == "json":
        return JSONResponse({
            "timestamp": run["started_at"],
            "report": report,
        })
    elif format == "md":
        from lib.rag_engine.eval_guide import generate_eval_summary

        lines = [f"# 评估报告 {evaluation_id}", f"模式: {run['mode']}", f"时间: {run['started_at']}", ""]
        for section, metrics in report.items():
            if isinstance(metrics, dict):
                lines.append(f"## {section}")
                for k, v in metrics.items():
                    if isinstance(v, (int, float)):
                        lines.append(f"- {k}: {v:.4f}" if isinstance(v, float) else f"- {k}: {v}")
        summary = generate_eval_summary(report)
        lines.append("\n## 评估摘要")
        for level, label in [('excellent', '优秀'), ('good', '良好'), ('needs_improvement', '需改进')]:
            items = summary.get(level, [])
            if items:
                lines.append(f"\n### {label}")
                for item in items:
                    lines.append(f"- **{item['metric']}**: {item['value']}")
                    if item['suggestion']:
                        lines.append(f"  - {item['suggestion']}")
        return Response(content="\n".join(lines), media_type="text/markdown")
    else:
        raise HTTPException(status_code=400, detail="不支持的格式，可选: json, md")


# ── 数据集质量审查 ─────────────────────────────────────


@router.get("/dataset/audit")
async def audit_dataset():
    from api.database import get_eval_samples
    from lib.rag_engine.dataset_validator import validate_dataset

    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    report = validate_dataset(samples)
    return report.to_dict()


# ── 人工抽检 ──────────────────────────────────────────


@router.post("/human-reviews")
async def create_human_review(req: HumanReviewCreate):
    from api.database import create_human_review as db_create
    review_id = db_create(
        evaluation_id=req.evaluation_id,
        sample_id=req.sample_id,
        reviewer=req.reviewer,
        faithfulness_score=req.faithfulness_score,
        correctness_score=req.correctness_score,
        relevancy_score=req.relevancy_score,
        comment=req.comment,
    )
    return {"review_id": review_id}


@router.get("/human-reviews/{evaluation_id}")
async def list_human_reviews(evaluation_id: str):
    from api.database import get_human_reviews, get_human_review_stats
    reviews = get_human_reviews(evaluation_id)
    stats = get_human_review_stats(evaluation_id)
    return {"reviews": reviews, "stats": stats}
