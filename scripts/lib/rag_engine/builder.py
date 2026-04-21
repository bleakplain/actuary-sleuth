#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库构建模块，将法规文档构建为向量索引和 BM25 索引。"""
import logging
from pathlib import Path
from typing import List, Dict, Optional

from llama_index.core import Settings, Document
from llama_index.core.schema import TextNode

from .index_manager import VectorIndexManager
from .config import RAGConfig
from .quality_checker import QualityChecker
from lib.llm import LLMClientFactory
from lib.doc_parser.kb.md_parser import MdParser

logger = logging.getLogger(__name__)


class KnowledgeBuilder:
    """知识库构建器

    将 preprocessor.py 生成的预处理 Markdown 文件构建为：
    1. 向量数据库 (LanceDB) - 用于语义检索
    2. BM25 索引 - 用于关键词检索

    使用 MdParser 按 ## 第N项 分块，提取 frontmatter 和 blockquote 元数据。
    """

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        quality_checker: Optional[QualityChecker] = None,
    ):
        self.config = config or RAGConfig()
        self.chunker = MdParser(chunk_config=self.config.chunking)
        self.index_manager = VectorIndexManager(self.config)
        self.quality_checker = quality_checker or QualityChecker()
        self._embedding_setup_done = False

    def _ensure_embedding_setup(self):
        if not self._embedding_setup_done:
            Settings.embed_model = LLMClientFactory.create_embed_model()
            self._embedding_setup_done = True

    @staticmethod
    def _read_file(file_path: Path) -> str:
        """读取文件内容，支持 UTF-8 和 GBK 编码。"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='gbk') as f:
                return f.read()

    def parse(self, file_pattern: str = "**/*.md") -> List[Document]:
        regulations_dir = Path(self.config.regulations_dir)
        if not regulations_dir.exists():
            logger.error(f"目录不存在: {regulations_dir}")
            return []

        md_files = sorted(regulations_dir.glob(file_pattern))
        if not md_files:
            logger.error(f"未找到匹配 {file_pattern} 的文件")
            return []

        documents: List[Document] = []
        for md_file in md_files:
            text = self._read_file(md_file)
            if text.strip():
                doc = Document(text=text, metadata={'file_name': md_file.name})
                documents.append(doc)

        logger.info(f"从 {regulations_dir} 加载了 {len(documents)} 个文档")
        return documents

    def chunk(self, documents: List[Document]) -> List[TextNode]:
        all_nodes: List[TextNode] = []
        for doc in documents:
            nodes = self.chunker.parse_document(doc)
            all_nodes.extend(nodes)
        return all_nodes

    def build(
        self,
        file_pattern: str = "**/*.md",
        force_rebuild: bool = False,
        skip_vector: bool = False,
    ) -> Dict[str, int]:
        stats = {'parsed': 0, 'quality_passed': 0, 'vector': 0, 'bm25': 0}

        logger.info("步骤 1: 加载文档")
        documents = self.parse(file_pattern)
        stats['parsed'] = len(documents)
        if not documents:
            logger.warning("没有找到任何文档")
            return stats

        logger.info(f"步骤 2: 文档质量检查 ({len(documents)} 个文档)")
        valid_docs: List[Document] = []
        for doc in documents:
            report = self.quality_checker.check_document(doc)
            if report.passed:
                valid_docs.append(doc)
            else:
                file_name = doc.metadata.get('file_name', 'unknown')
                logger.warning(f"文档质量检查失败 [{file_name}]: {report.error_count} errors, {report.warning_count} warnings")
        stats['quality_passed'] = len(valid_docs)
        logger.info(f"通过质量检查: {stats['quality_passed']}/{stats['parsed']}")

        if not valid_docs:
            logger.warning("没有通过质量检查的文档")
            return stats

        logger.info(f"步骤 3: 分块 ({len(valid_docs)} 个文档)")
        chunks = self.chunk(valid_docs)
        logger.info(f"生成 {len(chunks)} 个 chunk")

        # Chunk级质量检查
        chunks = self.quality_checker.check_chunks(chunks)
        logger.info(f"质量过滤后: {len(chunks)} 个 chunk")

        if not chunks:
            return stats

        if not skip_vector:
            logger.info("步骤 4: 创建向量索引")
            self._ensure_embedding_setup()
            if self.index_manager.create_index(chunks, force_rebuild=force_rebuild):
                stats['vector'] = len(chunks)

        logger.info("步骤 5: 构建 BM25 索引")
        from .bm25_index import BM25Index
        if not self.config.vector_db_path:
            return stats
        data_dir = Path(self.config.vector_db_path).parent
        bm25_path = data_dir / "bm25_index.pkl"
        try:
            BM25Index.build(chunks, bm25_path)
            stats['bm25'] = len(chunks)
        except Exception as e:
            logger.error(f"BM25 索引构建失败: {e}")

        if not skip_vector and stats['vector'] > 0 and stats['bm25'] > 0:
            if stats['vector'] != stats['bm25']:
                logger.warning(
                    f"索引一致性检查失败: 向量 {stats['vector']}, BM25 {stats['bm25']}"
                )

        logger.info(f"构建完成: 文档 {stats['parsed']}, 质量 {stats['quality_passed']}, 向量 {stats['vector']}, BM25 {stats['bm25']}")
        return stats

    def incremental_build(
        self,
        added_files: List[str],
        modified_files: List[str],
        deleted_files: List[str],
    ) -> Dict[str, int]:
        """增量更新知识库。

        Args:
            added_files: 新增的文件名列表（相对路径或文件名）
            modified_files: 修改的文件名列表
            deleted_files: 删除的文件名列表

        Returns:
            统计信息字典
        """
        stats = {'added': 0, 'modified': 0, 'deleted': 0}

        # 删除旧节点
        if deleted_files:
            self.index_manager.remove_nodes(deleted_files)
            self._bm25_remove_nodes(deleted_files)
            stats['deleted'] = len(deleted_files)

        # 处理修改的文件（先删后增）
        if modified_files:
            self.index_manager.remove_nodes(modified_files)
            self._bm25_remove_nodes(modified_files)

        # 新增/修改的文件
        files_to_add = added_files + modified_files
        if files_to_add:
            self._ensure_embedding_setup()
            new_nodes = self._process_files(files_to_add)
            if new_nodes:
                new_nodes = self.quality_checker.check_chunks(new_nodes)
                self.index_manager.add_nodes(new_nodes)
                self._bm25_add_nodes(new_nodes)
            stats['added'] = len(added_files)
            stats['modified'] = len(modified_files)

        logger.info(f"增量更新完成: 新增 {stats['added']}, 修改 {stats['modified']}, 删除 {stats['deleted']}")
        return stats

    def _process_files(self, file_names: List[str]) -> List[TextNode]:
        """处理文件列表，返回分块结果。"""
        regulations_dir = Path(self.config.regulations_dir)
        documents: List[Document] = []

        for file_name in file_names:
            file_path = regulations_dir / file_name
            if not file_path.exists():
                logger.warning(f"文件不存在: {file_name}")
                continue

            text = self._read_file(file_path)
            if text.strip():
                doc = Document(text=text, metadata={'file_name': file_path.name})
                report = self.quality_checker.check_document(doc)
                if report.passed:
                    documents.append(doc)
                else:
                    logger.warning(f"文档质量检查失败 [{file_name}]: {report.error_count} errors")

        return self.chunk(documents)

    def _get_bm25_path(self) -> Optional[Path]:
        """获取 BM25 索引路径。"""
        if not self.config.vector_db_path:
            return None
        return Path(self.config.vector_db_path).parent / "bm25_index.pkl"

    def _bm25_remove_nodes(self, source_files: List[str]) -> None:
        """从 BM25 索引删除节点。"""
        from .bm25_index import BM25Index
        bm25_path = self._get_bm25_path()
        if not bm25_path:
            return
        bm25_index = BM25Index.load(bm25_path)
        if bm25_index:
            bm25_index.remove_nodes(source_files, bm25_path)

    def _bm25_add_nodes(self, nodes: List[TextNode]) -> None:
        """向 BM25 索引添加节点。"""
        from .bm25_index import BM25Index
        bm25_path = self._get_bm25_path()
        if not bm25_path:
            return
        bm25_index = BM25Index.load(bm25_path)
        if bm25_index:
            bm25_index.add_nodes(nodes, bm25_path)
        else:
            BM25Index.build(nodes, bm25_path)
