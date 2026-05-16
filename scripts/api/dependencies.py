"""FastAPI 共享依赖。"""

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

_memory_service = None
_ask_graph = None


def on_shutdown():
    """应用关闭时清理连接池。"""
    from lib.common.database import close_pool
    close_pool()


def get_rag_engine():
    """获取 RAG 引擎实例，未初始化时返回 503。"""
    from api.app import rag_engine
    if rag_engine is None:
        raise HTTPException(status_code=503, detail="RAG 引擎未初始化")
    return rag_engine


def init_memory_service():
    """初始化记忆服务，失败时降级为无记忆模式。"""
    global _memory_service
    from lib.memory.service import MemoryService
    _memory_service = MemoryService.create()
    return _memory_service


def get_memory_service():
    """获取记忆服务实例。"""
    return _memory_service


def init_ask_graph():
    """编译 LangGraph 工作流图（启动时编译一次，复用）。"""
    global _ask_graph
    from lib.rag_engine.graph import create_ask_graph
    _ask_graph = create_ask_graph()
    return _ask_graph


def get_ask_graph():
    """获取已编译的 LangGraph 工作流图。"""
    return _ask_graph


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """从 JWT 解析当前用户。返回 {user_id, email, role_id, permissions}。"""
    if token is None:
        raise HTTPException(status_code=401, detail="未提供认证凭据")
    try:
        from lib.auth.jwt import decode_token
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="无效的认证凭据")
    from api.database import get_user_by_id
    user = get_user_by_id(payload["user_id"])
    if not user or user["status"] != "active":
        raise HTTPException(status_code=401, detail="账户已被禁用")
    return payload
