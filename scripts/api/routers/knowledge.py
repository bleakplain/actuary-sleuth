"""知识库管理路由 — 文档列表、导入、重建、预览。"""

import uuid
import json
import asyncio
import logging
from typing import Dict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.schemas.knowledge import (
    DocumentOut, ImportRequest, RebuildRequest, IndexStatus, TaskStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb", tags=["知识库管理"])

_tasks: Dict[str, Dict[str, object]] = {}


def _get_config():
    from lib.rag_engine.config import get_config
    return get_config()


def _get_regulations_dir() -> Path:
    config = _get_config()
    return Path(config.regulations_dir)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents():
    import re
    reg_dir = _get_regulations_dir()
    documents = []
    if reg_dir.exists():
        for f in sorted(reg_dir.glob("*.md")):
            stat = f.stat()
            content = f.read_text(encoding="utf-8", errors="ignore")
            # 统计所有法规条款/条目格式
            clause_patterns = [
                r'^第[一二三四五六七八九十百千\d]+条',
                r'^（[一二三四五六七八九十百千\d]+）',
                r'^[一二三四五六七八九十]+、',
                r'^\d+[、.]\s',
            ]
            count = sum(
                1 for l in content.split("\n")
                if any(re.match(p, l.strip()) for p in clause_patterns)
            )
            documents.append(DocumentOut(
                name=f.name,
                file_path=str(f.relative_to(reg_dir.parent)),
                clause_count=count,
                file_size=stat.st_size,
            ))
    return documents


@router.post("/documents/import")
async def import_documents(req: ImportRequest):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {"status": "pending", "progress": "", "result": None}

    async def _run_import():
        try:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = "正在导入..."

            config = _get_config()
            from lib.rag_engine.data_importer import RegulationDataImporter
            importer = RegulationDataImporter(config)

            if req.file_path:
                result = importer.parse_single_file(req.file_path)
                importer.import_to_vector_db([result])
            else:
                result = importer.import_all(file_pattern=req.file_pattern)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = result if isinstance(result, dict) else {"stats": str(result)}
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)

    asyncio.create_task(_run_import())
    return {"task_id": task_id, "status": "pending"}


@router.post("/documents/rebuild")
async def rebuild_index(req: RebuildRequest):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _tasks[task_id] = {"status": "pending", "progress": "", "result": None}

    async def _run_rebuild():
        try:
            _tasks[task_id]["status"] = "running"
            _tasks[task_id]["progress"] = "正在重建索引..."

            config = _get_config()
            from lib.rag_engine.data_importer import RegulationDataImporter
            importer = RegulationDataImporter(config)
            result = importer.rebuild_knowledge_base(file_pattern=req.file_pattern)

            _tasks[task_id]["status"] = "completed"
            _tasks[task_id]["result"] = result
        except Exception as e:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["progress"] = str(e)

    asyncio.create_task(_run_rebuild())
    return {"task_id": task_id, "status": "pending"}


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatus(
        task_id=task_id,
        status=task["status"],  # type: ignore[arg-type]
        progress=task.get("progress", ""),  # type: ignore[arg-type]
        result=task.get("result"),  # type: ignore[arg-type]
    )


@router.get("/documents/{document_name}/preview")
async def preview_document(document_name: str):
    reg_dir = _get_regulations_dir()
    file_path = reg_dir / document_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    return {"name": document_name, "content": content[:5000], "total_chars": len(content)}


@router.get("/documents/{document_name}/chunks")
async def list_document_chunks(document_name: str):
    """返回指定文档在向量库中的所有分块，用于人工验证提取质量"""
    import lancedb
    config = _get_config()
    try:
        db = lancedb.connect(config.vector_db_path)
        table = db.open_table(config.collection_name)
        df = table.to_pandas()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"向量库读取失败: {e}")

    chunks = []
    for _, row in df.iterrows():
        meta = row.get('metadata', {})
        if not isinstance(meta, dict):
            try:
                meta = json.loads(meta) if isinstance(meta, str) else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}

        source_file = meta.get('source_file', '')
        if source_file != document_name:
            continue

        text = str(row.get('text', ''))
        chunks.append({
            "law_name": meta.get('law_name', ''),
            "article_number": meta.get('article_number', ''),
            "category": meta.get('category', ''),
            "hierarchy_path": meta.get('hierarchy_path', ''),
            "source_file": meta.get('source_file', ''),
            "doc_number": meta.get('doc_number', ''),
            "issuing_authority": meta.get('issuing_authority', ''),
            "effective_date": meta.get('effective_date', ''),
            "text": text,
            "text_length": len(text),
        })

    # 按条款号排序：提取数字或中文数字排在前面
    def _article_sort_key(chunk):
        num = chunk.get("article_number", "")
        import re
        m = re.search(r'第([一二三四五六七八九十百千\d]+)条', num)
        if m:
            s = m.group(1)
            cn = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                  '百':100,'千':1000}
            if s.isdigit():
                return (0, int(s))
            val = 0
            for c in s:
                val = val * 10 + cn.get(c, 0)
            return (0, val)
        return (1, num)

    chunks.sort(key=_article_sort_key)

    return {"document_name": document_name, "total_chunks": len(chunks), "chunks": chunks}


@router.get("/status", response_model=IndexStatus)
async def get_index_status():
    try:
        config = _get_config()

        from lib.rag_engine.index_manager import VectorIndexManager
        vm = VectorIndexManager(config)
        vector_stats = vm.get_index_stats()

        from lib.rag_engine.bm25_index import BM25Index
        bm25_path = Path(config.vector_db_path).parent / "bm25_index.pkl"
        bm25_index = BM25Index.load(bm25_path) if bm25_path.exists() else None

        return IndexStatus(
            vector_db=vector_stats,
            bm25={
                "loaded": bm25_index is not None,
                "doc_count": bm25_index.doc_count if bm25_index else 0,
            } if bm25_index else {"loaded": False, "doc_count": 0},
            document_count=vector_stats.get("doc_count", 0),
        )
    except Exception as e:
        return IndexStatus(vector_db={"status": "error", "error": str(e)})
