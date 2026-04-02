#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库版本管理器

管理法规知识库的多版本：每个版本独立保存向量索引和 BM25 索引。
源文件统一存放在外部目录（如项目根目录 references/），不随版本复制。
"""
import json
import shutil
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

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


@dataclass
class _VersionRegistry:
    """版本注册表（持久化到 version_meta.json）"""
    versions: List[VersionMeta] = field(default_factory=list)
    active_version: str = ""


class KBVersionManager:
    """知识库版本管理器

    管理版本创建、激活、删除，以及版本路径到 RAGConfig 的映射。
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            import os
            # 优先使用环境变量，否则使用项目内路径
            base_dir = os.environ.get(
                "KB_VERSION_DIR",
                str(Path(__file__).parent / "data" / "kb"),
            )
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path = self.base_dir / "version_meta.json"
        self._registry = self._load_registry()

    # ── 持久化 ──────────────────────────────────────────────

    def _load_registry(self) -> _VersionRegistry:
        if self._registry_path.exists():
            with open(self._registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _VersionRegistry(
                versions=[VersionMeta(**v) for v in data.get("versions", [])],
                active_version=data.get("active_version", ""),
            )
        return _VersionRegistry()

    def _save_registry(self) -> None:
        self._registry_path.write_text(
            json.dumps(asdict(self._registry), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── 查询 ──────────────────────────────────────────────────

    @property
    def active_version(self) -> Optional[str]:
        return self._registry.active_version or None

    def list_versions(self) -> List[VersionMeta]:
        return list(self._registry.versions)

    def get_version_meta(self, version_id: str) -> Optional[VersionMeta]:
        for v in self._registry.versions:
            if v.version_id == version_id:
                return v
        return None

    def next_version_id(self) -> str:
        max_num = 0
        for v in self._registry.versions:
            if v.version_id.startswith("v"):
                try:
                    max_num = max(max_num, int(v.version_id[1:]))
                except ValueError:
                    pass
        return f"v{max_num + 1}"

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

        # 不再复制源文件，仅统计文档数
        reg_path = Path(regulations_dir)
        doc_count = len(list(reg_path.rglob("*.md"))) if reg_path.exists() else 0

        # 设为 active
        for v in self._registry.versions:
            v.active = False

        meta = VersionMeta(
            version_id=version_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            document_count=doc_count,
            chunk_count=0,
            active=True,
            description=description,
            regulations_dir=str(reg_path),
        )
        self._registry.versions.append(meta)
        self._registry.active_version = version_id
        self._save_registry()

        # 写入版本目录下的 meta.json
        (version_dir / "meta.json").write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(f"创建知识库版本 {version_id}: {doc_count} 个文档")
        return meta

    def activate_version(self, version_id: str) -> bool:
        """切换 active 版本。"""
        meta = self.get_version_meta(version_id)
        if not meta:
            return False
        for v in self._registry.versions:
            v.active = (v.version_id == version_id)
        self._registry.active_version = version_id
        self._save_registry()
        logger.info(f"切换到知识库版本 {version_id}")
        return True

    def delete_version(self, version_id: str) -> bool:
        """删除非 active 版本。"""
        if version_id == self._registry.active_version:
            logger.warning(f"不能删除当前激活的版本 {version_id}")
            return False
        self._registry.versions = [
            v for v in self._registry.versions if v.version_id != version_id
        ]
        version_dir = self.base_dir / version_id
        if version_dir.exists():
            shutil.rmtree(version_dir)
            logger.info(f"删除知识库版本 {version_id}")
        self._save_registry()
        return True

    def update_version_chunk_count(self, version_id: str, chunk_count: int) -> None:
        """更新版本的 chunk 数量（索引构建完成后调用）。"""
        for v in self._registry.versions:
            if v.version_id == version_id:
                v.chunk_count = chunk_count
                break
        self._save_registry()

    # ── 路径解析 ──────────────────────────────────────────────

    def get_version_paths(self, version_id: str) -> Dict[str, str]:
        """返回指定版本的路径映射。"""
        version_dir = self.base_dir / version_id
        meta = self.get_version_meta(version_id)
        # 优先使用版本元数据中存储的 regulations_dir 绝对路径
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

    # ── 旧数据迁移 ────────────────────────────────────────────

    def migrate_legacy_data(
        self,
        legacy_lancedb: str,
        legacy_bm25: str,
        legacy_references: str,
    ) -> bool:
        """将旧版非版本化数据迁移到 v1。仅当无任何版本时执行。"""
        if self._registry.versions:
            return False

        v1_dir = self.base_dir / "v1"
        v1_dir.mkdir(parents=True, exist_ok=True)

        # 复制 references
        src_refs = Path(legacy_references)
        dst_refs = v1_dir / "references"
        if src_refs.exists() and not dst_refs.exists():
            shutil.copytree(src_refs, dst_refs)
            logger.info(f"迁移源文件: {src_refs} → {dst_refs}")

        # 复制 lancedb
        src_ldb = Path(legacy_lancedb)
        dst_ldb = v1_dir / "lancedb"
        if src_ldb.exists() and not dst_ldb.exists():
            shutil.copytree(src_ldb, dst_ldb)
            logger.info(f"迁移向量索引: {src_ldb} → {dst_ldb}")

        # 复制 bm25
        src_bm25 = Path(legacy_bm25)
        dst_bm25 = v1_dir / "bm25_index.pkl"
        if src_bm25.exists() and not dst_bm25.exists():
            shutil.copy2(src_bm25, dst_bm25)
            logger.info(f"迁移 BM25 索引: {src_bm25} → {dst_bm25}")

        doc_count = (
            len(list(dst_refs.glob("*.md"))) if dst_refs.exists() else 0
        )

        meta = VersionMeta(
            version_id="v1",
            created_at=datetime.now(timezone.utc).isoformat(),
            document_count=doc_count,
            chunk_count=0,
            active=True,
            description="从旧数据自动迁移",
        )
        self._registry.versions.append(meta)
        self._registry.active_version = "v1"
        self._save_registry()

        logger.info(f"旧数据迁移完成: {v1_dir}")
        return True
