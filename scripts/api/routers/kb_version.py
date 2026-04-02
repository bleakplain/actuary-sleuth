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


def _get_version_manager():
    from lib.rag_engine.version_manager import KBVersionManager
    return KBVersionManager()


def reload_rag_engine(version_manager):
    """热替换全局 RAG 引擎为指定版本的实例。"""
    import api.app as app_module
    try:
        old_engine = getattr(app_module, "rag_engine", None)
        if old_engine is not None:
            old_engine.cleanup()

        config = version_manager.get_rag_config()
        from lib.rag_engine import create_qa_engine
        new_engine = create_qa_engine(config)
        initialized = new_engine.initialize()
        if initialized:
            app_module.rag_engine = new_engine
            app_module._rag_initialized = True
            logger.info(
                f"RAG 引擎已切换到版本 {version_manager.active_version}"
            )
        else:
            logger.warning("RAG 引擎初始化失败")
    except Exception as e:
        logger.error(f"RAG 引擎重载失败: {e}")


@router.get("", response_model=VersionListOut)
async def list_versions():
    vm = _get_version_manager()
    versions = vm.list_versions()
    return VersionListOut(
        versions=[VersionOut(**vars(v)) for v in versions],
        active_version=vm.active_version or "",
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

            vm = _get_version_manager()

            # 从工作目录 references/ 快照源文件
            from lib.rag_engine.config import RAGConfig
            working_config = RAGConfig()
            meta = vm.create_version(
                regulations_dir=working_config.regulations_dir,
                description=req.description,
            )
            _tasks[task_id]["progress"] = f"已创建 {meta.version_id}，正在构建索引..."

            # 使用版本路径构建索引
            version_config = vm.get_rag_config(meta.version_id)
            from lib.rag_engine.indexer import KBIndexer
            importer = KBIndexer(version_config)
            stats = importer.import_all(force_rebuild=True)

            vm.update_version_chunk_count(meta.version_id, stats.get("vector", 0))

            reload_rag_engine(vm)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = {
                "version_id": meta.version_id,
                "stats": stats,
            }
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)
            logger.error(f"创建版本失败: {e}")

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "pending"}


@router.post("/{version_id}/activate")
async def activate_version(version_id: str):
    vm = _get_version_manager()
    if not vm.get_version_meta(version_id):
        raise HTTPException(status_code=404, detail="版本不存在")
    vm.activate_version(version_id)
    reload_rag_engine(vm)
    return {"status": "activated", "version_id": version_id}


@router.delete("/{version_id}")
async def delete_version(version_id: str):
    vm = _get_version_manager()
    if not vm.delete_version(version_id):
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
