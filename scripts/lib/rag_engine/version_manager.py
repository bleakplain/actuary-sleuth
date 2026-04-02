#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库版本管理器

管理法规知识库的多版本：每个版本独立保存向量索引和 BM25 索引。
源文件统一存放在外部目录（如项目根目录 references/），不随版本复制。
版本元数据持久化到 SQLite 数据库（kb_versions 表）。
"""
import shutil
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

from lib.config import get_kb_version_dir

logger = logging.getLogger(__name__)


@dataclass
class VersionMeta:
    """单个知识库版本的元数据"""
    version_id: str
    created_at: str
    document_count: int = 0
    chunk_count: int = 0
    active: bool = False
    description: str = ""
    regulations_dir: str = ""


def _get_connection():
    from lib.common.database import get_connection
    return get_connection()


class KBVersionManager:
    """知识库版本管理器

    管理版本创建、激活、删除，以及版本路径到 RAGConfig 的映射。
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = get_kb_version_dir()
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保 kb_versions 表已创建（支持非 app 启动场景）。"""
        try:
            from api.database import init_db
            init_db()
        except Exception:
            pass

    # ── 辅助 ──────────────────────────────────────────────────

    @staticmethod
    def _row_to_meta(row) -> VersionMeta:
        return VersionMeta(
            version_id=row["version_id"],
            created_at=row["created_at"],
            document_count=row["document_count"],
            chunk_count=row["chunk_count"],
            active=bool(row["active"]),
            description=row["description"],
            regulations_dir=row["regulations_dir"],
        )

    # ── 查询 ──────────────────────────────────────────────────

    @property
    def active_version(self) -> Optional[str]:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT version_id FROM kb_versions WHERE active = 1"
            ).fetchone()
            return row["version_id"] if row else None

    def list_versions(self) -> List[VersionMeta]:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM kb_versions ORDER BY created_at"
            ).fetchall()
            return [self._row_to_meta(r) for r in rows]

    def get_version_meta(self, version_id: str) -> Optional[VersionMeta]:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM kb_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            return self._row_to_meta(row) if row else None

    def next_version_id(self) -> str:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT version_id FROM kb_versions "
                "WHERE version_id LIKE 'v%' ORDER BY version_id DESC LIMIT 1"
            ).fetchone()
            if row:
                try:
                    return f"v{int(row['version_id'][1:]) + 1}"
                except ValueError:
                    pass
        return "v1"

    # ── 版本操作 ──────────────────────────────────────────────

    def create_version(
        self,
        regulations_dir: str,
        description: str = "",
    ) -> VersionMeta:
        """创建新版本：仅管理索引，源文件保持在 regulations_dir。"""
        version_id = self.next_version_id()
        version_dir = self.base_dir / version_id
        version_dir.mkdir(parents=True, exist_ok=True)

        reg_path = Path(regulations_dir)
        doc_count = len(list(reg_path.rglob("*.md"))) if reg_path.exists() else 0

        now = datetime.now(timezone.utc).isoformat()

        with _get_connection() as conn:
            conn.execute("UPDATE kb_versions SET active = 0")
            conn.execute(
                "INSERT INTO kb_versions "
                "(version_id, created_at, document_count, chunk_count, "
                "description, regulations_dir, active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                (version_id, now, doc_count, 0, description, str(reg_path)),
            )

        meta = VersionMeta(
            version_id=version_id,
            created_at=now,
            document_count=doc_count,
            chunk_count=0,
            active=True,
            description=description,
            regulations_dir=str(reg_path),
        )

        logger.info(f"创建知识库版本 {version_id}: {doc_count} 个文档")
        return meta

    def activate_version(self, version_id: str) -> bool:
        """切换 active 版本。"""
        meta = self.get_version_meta(version_id)
        if not meta:
            return False
        with _get_connection() as conn:
            conn.execute("UPDATE kb_versions SET active = 0")
            conn.execute(
                "UPDATE kb_versions SET active = 1 WHERE version_id = ?",
                (version_id,),
            )
        logger.info(f"切换到知识库版本 {version_id}")
        return True

    def delete_version(self, version_id: str) -> bool:
        """删除非 active 版本。"""
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT active FROM kb_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            if not row:
                return False
            if row["active"]:
                logger.warning(f"不能删除当前激活的版本 {version_id}")
                return False
            conn.execute(
                "DELETE FROM kb_versions WHERE version_id = ?",
                (version_id,),
            )

        version_dir = self.base_dir / version_id
        if version_dir.exists():
            shutil.rmtree(version_dir)
            logger.info(f"删除知识库版本 {version_id}")
        return True

    def update_version_chunk_count(self, version_id: str, chunk_count: int) -> None:
        """更新版本的 chunk 数量（索引构建完成后调用）。"""
        with _get_connection() as conn:
            conn.execute(
                "UPDATE kb_versions SET chunk_count = ? WHERE version_id = ?",
                (chunk_count, version_id),
            )

    # ── 路径解析 ──────────────────────────────────────────────

    def get_version_paths(self, version_id: str) -> Dict[str, str]:
        """返回指定版本的路径映射。"""
        version_dir = self.base_dir / version_id
        meta = self.get_version_meta(version_id)
        reg_dir = meta.regulations_dir if meta and meta.regulations_dir else str(version_dir / "references")
        return {
            "regulations_dir": reg_dir,
            "vector_db_path": str(version_dir / "lancedb"),
            "bm25_index_path": str(version_dir / "bm25_index.pkl"),
        }

    def get_active_paths(self) -> Optional[Dict[str, str]]:
        """返回 active 版本的路径映射。"""
        vid = self.active_version
        if not vid:
            return None
        return self.get_version_paths(vid)

    def get_rag_config(self, version_id: str = None) -> "RAGConfig":
        """创建指定版本的 RAGConfig 实例。"""
        from .config import RAGConfig
        vid = version_id or self.active_version
        if not vid:
            return RAGConfig()
        paths = self.get_version_paths(vid)
        return RAGConfig(
            regulations_dir=paths["regulations_dir"],
            vector_db_path=paths["vector_db_path"],
        )
