"""FastAPI 共享依赖。"""

from fastapi import HTTPException


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
