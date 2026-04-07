"""FastAPI 共享依赖。"""

from fastapi import HTTPException

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
