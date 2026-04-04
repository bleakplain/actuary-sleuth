"""知识库版本管理路由 — 创建、切换、删除版本。"""

import uuid
import asyncio
import logging
from typing import Dict

from fastapi import APIRouter, HTTPException

from api.schemas.kb_version import (
    VersionOut, VersionListOut, CreateVersionRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb/versions", tags=["知识库版本管理"])

_tasks: Dict[str, Dict[str, object]] = {}


def _get_kb_manager():
    from lib.rag_engine.kb_manager import KBManager
    return KBManager()


def reload_rag_engine(kb_mgr):
    """热替换全局 RAG 引擎为指定版本的实例。"""
    import api.app as app_module
    try:
        old_engine = getattr(app_module, "rag_engine", None)
        if old_engine is not None:
            old_engine.cleanup()

        config = kb_mgr.load_kb()
        from lib.rag_engine import create_qa_engine
        new_engine = create_qa_engine(config)
        initialized = new_engine.initialize()
        if initialized:
            app_module.rag_engine = new_engine
            app_module._rag_initialized = True
            logger.info(
                f"RAG 引擎已切换到版本 {kb_mgr.active_version}"
            )
        else:
            logger.warning("RAG 引擎初始化失败")
    except Exception as e:
        logger.error(f"RAG 引擎重载失败: {e}")


@router.get("", response_model=VersionListOut)
async def list_versions():
    kb_mgr = _get_kb_manager()
    versions = kb_mgr.list_versions()
    return VersionListOut(
        versions=[VersionOut(**vars(v)) for v in versions],
        active_version=kb_mgr.active_version or "",
    )


@router.post("")
async def create_version(req: CreateVersionRequest):
    """创建新版本：快照当前 references + 重建索引 + 自动激活。"""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {"status": "pending", "progress": "", "result": None}

    async def _run():
        try:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = "正在创建版本..."

            kb_mgr = _get_kb_manager()

            from lib.rag_engine.config import RAGConfig
            working_config = RAGConfig()

            result = kb_mgr.build_kb(
                regulations_dir=working_config.regulations_dir,
                description=req.description,
                force_rebuild=True,
            )

            reload_rag_engine(kb_mgr)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = {
                "version_id": result["version_id"],
                "stats": result["stats"],
            }
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)
            logger.error(f"创建版本失败: {e}")

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "pending"}


@router.post("/{version_id}/activate")
async def activate_version(version_id: str):
    kb_mgr = _get_kb_manager()
    if not kb_mgr.get_version_meta(version_id):
        raise HTTPException(status_code=404, detail="版本不存在")
    kb_mgr.activate_version(version_id)
    reload_rag_engine(kb_mgr)
    return {"status": "activated", "version_id": version_id}


@router.delete("/{version_id}")
async def delete_version(version_id: str):
    kb_mgr = _get_kb_manager()
    if not kb_mgr.delete_version(version_id):
        raise HTTPException(status_code=400, detail="不能删除当前激活的版本")
    return {"status": "deleted", "version_id": version_id}


@router.get("/tasks/{task_id}")
async def get_version_task_status(task_id: str):
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", ""),
        "result": task.get("result"),
    }
