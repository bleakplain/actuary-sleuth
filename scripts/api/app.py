import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

rag_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_engine
    from api.database import init_db
    init_db()
    logger.info("数据库初始化完成")

    try:
        from api.routers.eval import _ensure_default_dataset
        _ensure_default_dataset()
    except Exception as e:
        logger.warning(f"默认数据集初始化失败: {e}")

    try:
        from lib.rag_engine import create_qa_engine
        rag_engine = create_qa_engine()
        rag_engine.initialize()
        logger.info("RAG 引擎初始化完成")
    except Exception as e:
        logger.warning(f"RAG 引擎初始化失败（问答功能不可用）: {e}")

    yield

    if rag_engine is not None:
        rag_engine.cleanup()
        logger.info("RAG 引擎已清理")

    from api.dependencies import on_shutdown
    on_shutdown()


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

from api.routers import ask, knowledge, eval as eval_router, compliance
app.include_router(ask.router)
app.include_router(knowledge.router)
app.include_router(eval_router.router)
app.include_router(compliance.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "rag_engine": rag_engine is not None}
