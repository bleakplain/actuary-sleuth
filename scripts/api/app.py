import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

rag_engine = None
_rag_initialized = False


def _ensure_knowledge_base():
    """初始化知识库：创建初始版本。"""
    from lib.rag_engine.kb_manager import KBManager
    from lib.rag_engine.config import RAGConfig
    from lib.rag_engine.index_manager import VectorIndexManager

    kb_mgr = KBManager()

    # 无版本时从当前 references 创建 v1
    if not kb_mgr.list_versions():
        from lib.config import get_regulations_dir
        refs_dir = Path(get_regulations_dir())
        if refs_dir.exists() and list(refs_dir.glob("**/*.md")):
            kb_mgr.create_version(
                description="初始版本",
            )
        else:
            logger.warning("未找到源文件，跳过知识库初始化")
            return

    # 检查 active 版本是否有索引
    config = kb_mgr.load_kb()
    index_check = VectorIndexManager(config)
    if not index_check.index_exists():
        logger.info(f"版本 {kb_mgr.active_version} 的向量库为空，开始导入...")
        from lib.rag_engine.builder import KnowledgeBuilder
        builder = KnowledgeBuilder(config)
        stats = builder.build()
        logger.info(
            f"知识库导入完成: 解析 {stats['parsed']} 块, "
            f"向量 {stats.get('vector', 0)} 块, BM25 {stats.get('bm25', 0)} 块"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_engine, _rag_initialized
    from api.database import init_db
    init_db()
    logger.info("数据库初始化完成")

    from api.dependencies import init_memory_service
    init_memory_service()

    try:
        from api.routers.eval import _ensure_default_dataset
        _ensure_default_dataset()
        from api.database import _ensure_default_config
        _ensure_default_config()
    except Exception as e:
        logger.warning(f"默认数据初始化失败: {e}")

    auto_classify_task = asyncio.create_task(_auto_classify_loop())

    try:
        _ensure_knowledge_base()

        from lib.rag_engine import init_engine
        rag_engine = init_engine()
        _rag_initialized = rag_engine is not None
        if _rag_initialized:
            logger.info("RAG 引擎初始化完成")
            from api.dependencies import init_ask_graph
            init_ask_graph()
            # 启动缓存指标采集器
            from lib.common.cache import get_cache_manager
            cache = get_cache_manager()
            if cache:
                from lib.common.cache_metrics import start_metrics_collector
                start_metrics_collector(get_cache_manager)
                logger.info("缓存指标采集器已启动")
        else:
            logger.warning("RAG 引擎初始化失败（问答功能不可用）")
    except Exception as e:
        logger.warning(f"RAG 引擎初始化失败（问答功能不可用）: {e}")

    memory_cleanup_task = asyncio.create_task(_memory_cleanup_loop())

    auto_classify_task.cancel()
    yield

    memory_cleanup_task.cancel()

    # 停止缓存指标采集器并关闭缓存连接
    from lib.common.cache_metrics import stop_metrics_collector
    stop_metrics_collector()
    from lib.common.cache import get_cache_manager, reset_cache_manager
    cache = get_cache_manager()
    if cache:
        cache.close()
    reset_cache_manager()

    if rag_engine is not None:
        rag_engine.cleanup()
        logger.info("RAG 引擎已清理")

    from api.dependencies import on_shutdown
    on_shutdown()


async def _auto_classify_loop():
    while True:
        try:
            from api.routers.feedback import classify_pending_badcases
            result = await classify_pending_badcases()
            if result["classified"] > 0:
                logger.info(f"自动分类完成: {result}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"自动分类任务失败: {e}")
        await asyncio.sleep(3600)


async def _memory_cleanup_loop():
    """每日清理过期记忆。"""
    from api.dependencies import get_memory_service
    try:
        while True:
            await asyncio.sleep(86400)
            svc = get_memory_service()
            if svc and svc.available:
                try:
                    count = svc.cleanup_expired()
                    if count:
                        logger.info(f"清理过期记忆 {count} 条")
                except Exception as e:
                    logger.warning(f"记忆清理失败: {e}")
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Actuary Sleuth - 法规知识平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import ask, knowledge, eval as eval_router, compliance, kb_version, feedback, observability
from api.routers.memory import router as memory_router
app.include_router(ask.router)
app.include_router(knowledge.router)
app.include_router(eval_router.router)
app.include_router(compliance.router)
app.include_router(kb_version.router)
app.include_router(feedback.router)
app.include_router(observability.router)
app.include_router(memory_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "rag_engine": _rag_initialized}

# 托管前端静态文件（生产环境）
_static_dir = Path(__file__).parent.parent / "web" / "dist"
if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file = _static_dir / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_static_dir / "index.html")
