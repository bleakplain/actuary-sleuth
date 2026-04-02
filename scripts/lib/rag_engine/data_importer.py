#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入模块
负责将法规文档导入到向量数据库和 BM25 索引
"""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from llama_index.core import Settings
from llama_index.core import Document

from .index_manager import VectorIndexManager
from .config import RAGConfig
from .llamaindex_adapter import get_embedding_model
from lib.llm import LLMClientFactory

logger = logging.getLogger(__name__)


class KBDataImporter:
    """KB 检查清单数据导入器

    将 excel_to_kb.py 生成的预处理 Markdown 文件导入到：
    1. 向量数据库 (LanceDB) - 用于语义检索
    2. BM25 索引 - 用于关键词检索

    使用 KBChecklistChunker 按 ## 第N项 分块，提取 frontmatter 和 blockquote 元数据。
    """

    def __init__(self, config: Optional[RAGConfig] = None):
        self.config = config or RAGConfig()
        from .kb_chunker import KBChecklistChunker
        self.chunker = KBChecklistChunker()
        self.index_manager = VectorIndexManager(self.config)
        self._embedding_setup_done = False

    def _ensure_embedding_setup(self):
        """确保 Embedding 模型已设置"""
        if not self._embedding_setup_done:
            embed_config = LLMClientFactory.get_embedding_config()
            Settings.embed_model = get_embedding_model(embed_config)
            self._embedding_setup_done = True

    def import_to_vector_db(self, documents: List, force_rebuild: bool = False) -> bool:
        """导入到向量数据库"""
        self._ensure_embedding_setup()
        index = self.index_manager.create_index(
            documents=documents,
            force_rebuild=force_rebuild
        )
        return index is not None

    def parse_documents(self, file_pattern: str = "**/*.md") -> List:
        """递归加载所有 Markdown 文件。"""
        regulations_dir = Path(self.config.regulations_dir)
        if not regulations_dir.exists():
            logger.error(f"目录不存在: {regulations_dir}")
            return []

        from llama_index.core.readers import SimpleDirectoryReader
        md_files = sorted(regulations_dir.glob(file_pattern))
        if not md_files:
            logger.error(f"未找到匹配 {file_pattern} 的文件")
            return []

        reader = SimpleDirectoryReader(input_files=[str(f) for f in md_files])
        documents = reader.load_data()
        logger.info(f"从 {regulations_dir} 加载了 {len(documents)} 个文档")
        return documents

    def chunk_documents(self, documents: List) -> List:
        """使用 KBChecklistChunker 分块。"""
        text_nodes = self.chunker.chunk(documents)
        return [Document(text=node.text, metadata=node.metadata) for node in text_nodes]

    def import_all(
        self,
        file_pattern: str = "**/*.md",
        force_rebuild: bool = False,
        skip_vector: bool = False,
    ) -> Dict[str, int]:
        """完整导入流程：加载 → 分块 → 向量索引 → BM25 索引。"""
        stats = {'parsed': 0, 'vector': 0, 'bm25': 0}

        logger.info("步骤 1: 加载文档")
        documents = self.parse_documents(file_pattern)
        stats['parsed'] = len(documents)
        if not documents:
            logger.warning("没有找到任何文档")
            return stats

        logger.info(f"步骤 2: 分块 ({len(documents)} 个文档)")
        chunks = self.chunk_documents(documents)
        logger.info(f"生成 {len(chunks)} 个 chunk")
        if not chunks:
            return stats

        if not skip_vector:
            logger.info("步骤 3: 创建向量索引")
            self._ensure_embedding_setup()
            if self.index_manager.create_index(chunks, force_rebuild=force_rebuild):
                stats['vector'] = len(chunks)

        logger.info("步骤 4: 构建 BM25 索引")
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

        logger.info(f"导入完成: 文档 {stats['parsed']}, 向量 {stats['vector']}, BM25 {stats['bm25']}")
        return stats
