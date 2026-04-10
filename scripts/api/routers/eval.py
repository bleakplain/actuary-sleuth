"""评估管理路由 — 数据集 CRUD + 快照 + 评估运行。"""

import uuid
import asyncio
import logging
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from api.schemas.eval import (
    EvalSampleCreate, EvalSampleOut, ImportSamplesRequest,
    EvaluationRequest, EvalConfigCreate, CompareRequest, SnapshotCreate,
    HumanReviewCreate, ReviewSampleRequest, KbSearchRequest, KbSearchResult,
    SynthesizeRequest,
)
from api.database import (
    eval_sample_count, import_eval_samples, get_eval_samples,
    upsert_eval_sample, get_eval_sample, delete_eval_sample,
    create_snapshot, get_snapshots, restore_snapshot,
    get_snapshot_samples, compute_dataset_fingerprint,
    insert_evaluation, get_evaluation, get_evaluations,
    update_evaluation_status, update_evaluation_config,
    save_evaluation_report, save_sample_result, get_sample_results,
    fetch_evaluation_trends, get_eval_config, get_active_config, get_eval_configs,
    insert_eval_config, remove_eval_config, activate_eval_config,
    remove_snapshot,
    insert_human_review,
    get_human_reviews, get_human_review_stats,
    batch_delete_evaluations,
    get_review_stats,
)
from lib.rag_engine.eval_dataset import EvalSample, ReviewStatus
from lib.rag_engine.config import RAGConfig
from lib.rag_engine.rag_engine import RAGEngine
from lib.rag_engine import RetrievalEvaluator, GenerationEvaluator, load_eval_dataset
from lib.rag_engine.eval_rating import generate_eval_summary
from lib.rag_engine.dataset_validator import validate_dataset
from lib.llm import LLMClientFactory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/eval", tags=["评估管理"])

_eval_tasks: dict = {}
_MAX_EVAL_TASKS = 100


def _cleanup_completed_tasks():
    completed = [
        eid for eid, info in _eval_tasks.items()
        if info.get('status') in ('completed', 'failed')
    ]
    for eid in completed[:20]:
        _eval_tasks.pop(eid, None)


# ── 数据集管理 ───────────────────────────────────────


def _ensure_default_dataset():
    if eval_sample_count() > 0:
        return
    try:
        samples = load_eval_dataset()
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
    review_status: Optional[str] = Query(None, pattern="^(pending|approved)$"),
):
    return get_eval_samples(
        question_type=question_type,
        difficulty=difficulty,
        topic=topic,
        review_status=review_status,
    )


@router.post("/dataset/samples", response_model=EvalSampleOut)
async def create_eval_sample(sample: EvalSampleCreate):
    upsert_eval_sample(sample.model_dump())
    result = get_eval_sample(sample.id)
    if result is None:
        raise HTTPException(status_code=500, detail="创建失败")
    return result


@router.put("/dataset/samples/{sample_id}", response_model=EvalSampleOut)
async def update_eval_sample(sample_id: str, sample: EvalSampleCreate):
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    update_data = sample.model_dump()
    update_data["id"] = sample_id
    update_data["review_status"] = ReviewStatus.PENDING.value
    update_data["reviewer"] = ""
    update_data["reviewed_at"] = ""
    upsert_eval_sample(update_data)
    return get_eval_sample(sample_id)


@router.delete("/dataset/samples/{sample_id}")
async def remove_eval_sample(sample_id: str):
    if not delete_eval_sample(sample_id):
        raise HTTPException(status_code=404, detail="样本不存在")
    return {"deleted": True}


@router.post("/dataset/import")
async def import_dataset(req: ImportSamplesRequest):
    samples = [s.model_dump() for s in req.samples]
    count = import_eval_samples(samples)
    return {"imported": count, "total": len(samples), "skipped": len(samples) - count}


@router.post("/dataset/snapshots")
async def add_snapshot(req: SnapshotCreate):
    snap_id = create_snapshot(req.name, req.description)
    return {"snapshot_id": snap_id, "name": req.name}


@router.get("/dataset/snapshots")
async def list_snapshots():
    return get_snapshots()


@router.post("/dataset/snapshots/{snapshot_id}/restore")
async def apply_snapshot(snapshot_id: str):
    snap_ids = [s["id"] for s in get_snapshots()]
    if snapshot_id not in snap_ids:
        raise HTTPException(status_code=404, detail="快照不存在")
    count = restore_snapshot(snapshot_id)
    return {"restored": count}


@router.delete("/dataset/snapshots/{snapshot_id}")
async def delete_snapshot(snapshot_id: str):
    if not remove_snapshot(snapshot_id):
        raise HTTPException(
            status_code=400,
            detail="该快照有关联评测记录，请先删除关联的评测记录",
        )


# ── 评估运行 ─────────────────────────────────────────


def _build_eval_record(config: RAGConfig, mode: str, total_samples: int,
                       config_id=None, config_version=None) -> Dict:
    result = config.to_dict()
    result["evaluation"] = {"mode": mode}
    result["dataset"] = {"total_samples": total_samples}
    if config_id is not None:
        result["dataset"]["config_id"] = config_id
    if config_version is not None:
        result["dataset"]["config_version"] = config_version
    return result


def _load_config(config_id: int):
    """从 eval_configs 表加载 RAGConfig。"""
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise ValueError(f"配置不存在: {config_id}")
    config = RAGConfig.from_dict(cfg["config_json"])
    return config, cfg["version"]


@router.post("/evaluations")
async def create_evaluation(req: EvaluationRequest):
    evaluation_id = f"eval_{uuid.uuid4().hex[:8]}"

    config, config_version = _load_config(req.config_id)

    if req.snapshot_id:
        samples_data = get_snapshot_samples(req.snapshot_id)
        if samples_data is None:
            raise HTTPException(status_code=404, detail=f"快照不存在: {req.snapshot_id}")
        dataset_version = f"snapshot:{req.snapshot_id}"
    else:
        samples_data = get_eval_samples()
        dataset_version = compute_dataset_fingerprint()

    insert_evaluation(
        evaluation_id, req.mode, {"mode": req.mode},
        config_version=config_version,
        dataset_version=dataset_version,
    )

    if len(_eval_tasks) >= _MAX_EVAL_TASKS:
        _cleanup_completed_tasks()

    _eval_tasks[evaluation_id] = {"status": "pending"}

    async def _run_eval():
        try:
            _eval_tasks[evaluation_id]["status"] = "running"

            if req.filters:
                for key, val in req.filters.items():
                    samples_data = [s for s in samples_data if s.get(key) == val]
            samples = [EvalSample.from_dict(s) for s in samples_data]
            total = len(samples)

            update_evaluation_config(
                evaluation_id,
                _build_eval_record(config, req.mode, total,
                                   req.config_id, config_version),
                total=total,
            )
            update_evaluation_status(evaluation_id, "running", progress=0, total=total)

            from lib.rag_engine.kb_manager import KBManager
            kb_config = KBManager().load_kb()
            config.vector_db_path = kb_config.vector_db_path

            eval_engine = RAGEngine(config)
            if not eval_engine.initialize():
                raise RuntimeError("评测引擎初始化失败")

            if req.mode in ("retrieval", "full"):
                ret_eval = RetrievalEvaluator(eval_engine)
                ret_report, ret_details = ret_eval.evaluate_batch(
                    samples, top_k=config.rerank.rerank_top_k,
                )
                for detail in ret_details:
                    sample_id = detail.get("sample_id", "")
                    save_sample_result(evaluation_id, sample_id, retrieval_metrics=detail)
                    current = _eval_tasks[evaluation_id].get("progress", 0) + 1
                    _eval_tasks[evaluation_id]["progress"] = current
                    update_evaluation_status(evaluation_id, "running", progress=current, total=total)

            gen_report = None
            if req.mode in ("generation", "full"):
                gen_eval = GenerationEvaluator(
                    rag_engine=eval_engine,
                    llm=LLMClientFactory.create_ragas_llm(),
                    embeddings=LLMClientFactory.create_ragas_embed_model(),
                )
                gen_report = gen_eval.evaluate_batch(samples, rag_engine=eval_engine)

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
            eval_engine.cleanup()

        except Exception as e:
            logger.error(f"Eval run {evaluation_id} failed: {e}")
            update_evaluation_status(evaluation_id, "failed")
            _eval_tasks[evaluation_id]["status"] = "failed"
            _eval_tasks[evaluation_id]["error"] = str(e)

    asyncio.create_task(_run_eval())
    return {"evaluation_id": evaluation_id, "status": "pending"}


@router.get("/evaluations/{evaluation_id}/status")
async def get_evaluation_status(evaluation_id: str):
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
        "config": run.get("config"),
    }


@router.get("/evaluations/{evaluation_id}/report")
async def get_evaluation_report(evaluation_id: str):
    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"评估尚未完成，当前状态: {run['status']}")
    return run.get("report", {})


@router.get("/evaluations/{evaluation_id}/details")
async def get_evaluation_details(evaluation_id: str):
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
    return get_evaluations()


@router.delete("/evaluations")
async def remove_evaluations(ids: str = Query(..., description="逗号分隔的评测ID列表")):
    evaluation_ids = [eid.strip() for eid in ids.split(",") if eid.strip()]
    if not evaluation_ids:
        raise HTTPException(status_code=400, detail="未提供有效的评测ID")
    deleted = batch_delete_evaluations(evaluation_ids)
    return {"deleted": deleted}


@router.get("/evaluations/trends")
async def get_evaluation_trends(
    metric: str = Query(..., description="指标名，如 retrieval.precision_at_k"),
    limit: int = Query(20, ge=1, le=50),
):
    return fetch_evaluation_trends(metric, limit)


@router.post("/evaluations/compare")
async def compare_evaluations(req: CompareRequest):
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


# ── 评测配置管理 ─────────────────────────────────────


@router.get("/configs")
async def list_eval_configs():
    return get_eval_configs()


@router.get("/configs/active")
async def get_active_eval_config():
    cfg = get_active_config()
    if cfg is None:
        raise HTTPException(status_code=404, detail="无激活的评测配置")
    return cfg


@router.post("/configs")
async def add_eval_config(req: EvalConfigCreate):
    config_id, version = insert_eval_config(req.description, req.to_config_dict())
    return {"id": config_id, "version": version}


@router.delete("/configs/{config_id}")
async def delete_eval_config(config_id: int):
    if not remove_eval_config(config_id):
        raise HTTPException(
            status_code=400,
            detail="不能删除：配置不存在、正在生效、或有关联评测记录",
        )


@router.get("/configs/{config_id}")
async def get_single_eval_config(config_id: int):
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    return cfg


@router.post("/configs/{config_id}/activate")
async def activate_config(config_id: int):
    cfg = get_eval_config(config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="配置不存在")
    if not activate_eval_config(config_id):
        raise HTTPException(status_code=500, detail="激活失败")
    return {"id": config_id, "version": cfg["version"]}


# ── 数据集质量审查 ─────────────────────────────────────


@router.get("/dataset/audit")
async def audit_dataset():
    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    report = validate_dataset(samples)
    return report.to_dict()


# ── 人工抽检 ──────────────────────────────────────────


@router.post("/human-reviews")
async def create_human_review(req: HumanReviewCreate):
    review_id = insert_human_review(
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
    reviews = get_human_reviews(evaluation_id)
    stats = get_human_review_stats(evaluation_id)
    return {"reviews": reviews, "stats": stats}


# ── 人工审核工作台 ─────────────────────────────────────


@router.patch("/dataset/samples/{sample_id}/review", response_model=EvalSampleOut)
async def approve_sample(sample_id: str, req: ReviewSampleRequest):
    existing = get_eval_sample(sample_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="样本不存在")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    existing["review_status"] = ReviewStatus.APPROVED.value
    existing["reviewer"] = req.reviewer
    existing["reviewed_at"] = now
    existing["review_comment"] = req.comment
    upsert_eval_sample(existing)
    return get_eval_sample(sample_id)


@router.get("/dataset/review-stats")
async def review_stats():
    return get_review_stats()


@router.post("/dataset/kb-search", response_model=list[KbSearchResult])
async def search_knowledge_base(req: KbSearchRequest):
    try:
        from api.dependencies import get_rag_engine
        engine = get_rag_engine()
        results = engine.search(req.query, top_k=req.top_k)
        return [
            KbSearchResult(
                doc_name=r.get("source_file", ""),
                article=r.get("article_number", ""),
                excerpt=r.get("content", "")[:500],
                hierarchy_path=r.get("hierarchy_path", ""),
                chunk_id="",
            )
            for r in results
            if r.get("content")
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"KB 搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"知识库搜索失败: {str(e)}")


@router.post("/dataset/synthesize")
async def synthesize_samples(req: SynthesizeRequest = SynthesizeRequest()):
    from lib.rag_engine.sample_synthesizer import SynthQA, SynthConfig
    from lib.rag_engine.eval_dataset import load_eval_dataset, save_eval_dataset

    synth = SynthQA(SynthConfig())
    chunks = synth.load_chunks()
    chunks = chunks[:req.max_chunks]

    existing = load_eval_dataset()
    result = synth.synthesize(chunks=chunks, existing_samples=existing)

    if result.samples:
        merged = existing + result.samples
        save_eval_dataset(merged)

    return result.to_dict()


@router.get("/dataset/coverage")
async def get_dataset_coverage():
    from lib.rag_engine.dataset_coverage import compute_coverage, get_kb_doc_names
    from lib.rag_engine.eval_dataset import EvalSample
    from lib.rag_engine.kb_manager import KBManager

    kb_mgr = KBManager()
    paths = kb_mgr.get_active_paths()
    if not paths:
        raise HTTPException(status_code=404, detail="无活跃知识库版本")

    kb_docs = get_kb_doc_names(paths["regulations_dir"])
    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    report = compute_coverage(samples, kb_docs)
    return report.to_dict()


@router.get("/evaluations/{evaluation_id}/weakness")
async def get_evaluation_weakness(evaluation_id: str):
    from lib.rag_engine.weakness_analyzer import generate_weakness_report
    from lib.rag_engine.dataset_coverage import compute_coverage, get_kb_doc_names
    from lib.rag_engine.eval_dataset import EvalSample
    from lib.rag_engine.kb_manager import KBManager

    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="评估尚未完成")

    results = get_sample_results(evaluation_id)

    kb_mgr = KBManager()
    paths = kb_mgr.get_active_paths()
    kb_docs = get_kb_doc_names(paths["regulations_dir"]) if paths else []
    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    coverage = compute_coverage(samples, kb_docs)

    report = generate_weakness_report(results, coverage)
    return report.to_dict()
