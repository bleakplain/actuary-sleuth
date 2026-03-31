"""FastAPI 共享依赖。"""


def on_shutdown():
    """应用关闭时清理连接池。"""
    from lib.common.database import close_pool
    close_pool()
