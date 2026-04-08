"""记忆管理 API。"""
import json

from fastapi import APIRouter, HTTPException

from api.dependencies import get_memory_service
from api.schemas.memory import (
    MemoryAddRequest,
    MemoryBatchDeleteRequest,
    MemoryItem,
    MemoryListResponse,
    MemorySearchRequest,
    ProfileUpdateRequest,
    UserProfile,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _to_memory_items(results, user_id: str) -> list[MemoryItem]:
    return [
        MemoryItem(
            id=m["id"], memory=m["memory"], user_id=user_id,
            created_at=m.get("created_at", ""),
            category=m.get("metadata", {}).get("category", "fact"),
        )
        for m in results
    ]


@router.get("/list", response_model=MemoryListResponse)
def list_memories(user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        return MemoryListResponse(memories=[])
    return MemoryListResponse(memories=_to_memory_items(svc.get_all(user_id), user_id))


@router.get("/search", response_model=MemoryListResponse)
def search_memories(req: MemorySearchRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        return MemoryListResponse(memories=[])
    return MemoryListResponse(memories=_to_memory_items(svc.search(req.query, user_id, limit=req.limit), user_id))


@router.delete("/batch")
def batch_delete_memories(req: MemoryBatchDeleteRequest):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    results = []
    for mid in req.memory_ids:
        results.append(svc.delete(mid))
    return {"deleted": sum(results), "total": len(req.memory_ids)}


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    success = svc.delete(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="记忆不存在或删除失败")
    return {"status": "ok"}


@router.post("/add", response_model=MemoryItem)
def add_memory(req: MemoryAddRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc or not svc.available:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    ids = svc.add(
        [{"role": "user", "content": req.content}],
        user_id,
        metadata={"category": req.category},
    )
    if not ids:
        raise HTTPException(status_code=500, detail="记忆写入失败")
    return MemoryItem(id=ids[0], memory=req.content, user_id=user_id, created_at="", category=req.category)


@router.get("/profile", response_model=UserProfile | None)
def get_profile(user_id: str = "default"):
    svc = get_memory_service()
    if not svc:
        return None
    profile = svc.get_profile(user_id)
    if not profile:
        return None
    return UserProfile(**profile)


@router.put("/profile", response_model=UserProfile)
def update_profile(req: ProfileUpdateRequest, user_id: str = "default"):
    svc = get_memory_service()
    if not svc:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    existing = svc.get_profile(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="用户画像不存在")
    profile = svc.update_profile(req, user_id)
    return profile
