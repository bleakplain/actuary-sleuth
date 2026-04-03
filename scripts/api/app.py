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
    from lib.rag_engine.version_manager import KBVersionManager
    from lib.rag_engine.config import RAGConfig
    from lib.rag_engine.index_manager import VectorIndexManager

    vm = KBVersionManager()

    # 无版本时从当前 references 创建 v1
    if not vm.list_versions():
        working_config = RAGConfig()
        refs_dir = Path(working_config.regulations_dir)
        if refs_dir.exists() and list(refs_dir.glob("**/*.md")):
            vm.create_version(
                regulations_dir=working_config.regulations_dir,
                description="初始版本",
            )
        else:
            logger.warning("未找到源文件，跳过知识库初始化")
            return

    # 检查 active 版本是否有索引
    config = vm.get_rag_config()
    vm_check = VectorIndexManager(config)
    if not vm_check.index_exists():
        logger.info(f"版本 {vm.active_version} 的向量库为空，开始导入...")
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

    try:
        from api.routers.eval import _ensure_default_dataset
        _ensure_default_dataset()
    except Exception as e:
        logger.warning(f"默认数据集初始化失败: {e}")

    try:
        _ensure_knowledge_base()

        from lib.rag_engine.version_manager import KBVersionManager
        vm = KBVersionManager()
        from lib.rag_engine import create_qa_engine
        rag_engine = create_qa_engine(vm.get_rag_config())
        _rag_initialized = rag_engine.initialize()
        if _rag_initialized:
            logger.info("RAG 引擎初始化完成")
        else:
            logger.warning("RAG 引擎初始化失败（问答功能不可用）")
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

from api.routers import ask, knowledge, eval as eval_router, compliance, kb_version, feedback
app.include_router(ask.router)
app.include_router(knowledge.router)
app.include_router(eval_router.router)
app.include_router(compliance.router)
app.include_router(kb_version.router)
app.include_router(feedback.router)


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
