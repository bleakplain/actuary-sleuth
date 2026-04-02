#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入模块
负责将法规文档导入到向量数据库和 BM25 索引
"""
import logging
from pathlib import Path
from typing import List, Dict, Any

from llama_index.core import Settings
from llama_index.core import Document

from .doc_parser import RegulationDocParser
from .index_manager import VectorIndexManager
from .config import RAGConfig
from .llamaindex_adapter import get_embedding_model
from lib.llm import LLMClientFactory

logger = logging.getLogger(__name__)


class RegulationDataImporter:
    """法规数据导入器

    负责将法规文档导入到：
    1. 向量数据库 (LanceDB) - 用于语义检索
    2. BM25 索引 - 用于关键词检索

    支持的分块策略:
    - semantic: 语义感知分块（推荐）
    - fixed: 固定长度分块
    """

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.parser = RegulationDocParser(
            self.config.regulations_dir,
            self.config
        )
        self.index_manager = VectorIndexManager(self.config)
        self._embedding_setup_done = False

    def _ensure_embedding_setup(self):
        """确保 Embedding 模型已设置"""
        if not self._embedding_setup_done:
            embed_config = LLMClientFactory.get_embedding_config()
            Settings.embed_model = get_embedding_model(embed_config)
            self._embedding_setup_done = True

    def parse_documents(self, file_pattern: str = "*.md") -> List:
        """解析法规文档"""
        return self.parser.parse_all(file_pattern)

    def parse_single_file(self, file_name: str) -> List:
        """解析单个文件"""
        return self.parser.parse_single_file(file_name)

    def import_to_vector_db(
        self,
        documents: List,
        force_rebuild: bool = False
    ) -> bool:
        """导入到向量数据库"""
        self._ensure_embedding_setup()
        index = self.index_manager.create_index(
            documents=documents,
            force_rebuild=force_rebuild
        )
        return index is not None

    def import_all(
        self,
        file_pattern: str = "*.md",
        force_rebuild: bool = False,
        skip_vector: bool = False
    ) -> Dict[str, int]:
        """导入所有数据

        Args:
            file_pattern: 文件匹配模式
            force_rebuild: 是否强制重建向量索引
            skip_vector: 是否跳过向量索引创建

        Returns:
            Dict[str, int]: 导入统计信息
        """
        stats = {
            'parsed': 0,
            'vector': 0,
            'bm25': 0
        }

        # 显示分块策略信息
        logger.info("=" * 60)
        logger.info(f"分块策略: {self.config.chunking_strategy}")
        logger.info("=" * 60)

        logger.info("步骤 1: 解析法规文档")
        logger.info("=" * 60)

        documents = self.parse_documents(file_pattern)
        stats['parsed'] = len(documents)

        if not documents:
            logger.warning("没有找到任何文档")
            return stats

        # 显示解析统计
        total_chars = sum(len(doc.text) for doc in documents)
        avg_chars = total_chars // len(documents) if documents else 0
        logger.info(f"解析统计: {len(documents)} 个文档块")
        logger.info(f"总字符数: {total_chars:,}, 平均块大小: {avg_chars:,}")

        # 显示元数据样本
        if documents:
            sample_meta = documents[0].metadata
            logger.info(f"元数据字段: {list(sample_meta.keys())}")

        step_num = 2

        if not skip_vector:
            logger.info("=" * 60)
            logger.info(f"步骤 {step_num}: 创建向量索引")
            logger.info("=" * 60)
            if self.import_to_vector_db(documents, force_rebuild):
                stats['vector'] = len(documents)
                logger.info(f"向量索引已创建，共 {len(documents)} 个文档块")
            step_num += 1

        # 构建 BM25 索引
        logger.info("=" * 60)
        logger.info(f"步骤 {step_num}: 构建 BM25 索引")
        logger.info("=" * 60)
        from .bm25_index import BM25Index
        data_dir = Path(self.config.vector_db_path).parent
        bm25_path = data_dir / "bm25_index.pkl"
        try:
            BM25Index.build(documents, bm25_path)
            stats['bm25'] = len(documents)
        except Exception as e:
            logger.error(f"BM25 索引构建失败: {e}")
            stats['bm25_error'] = str(e)

        # 一致性校验
        if not skip_vector and stats['vector'] > 0 and stats['bm25'] > 0:
            if stats['vector'] != stats['bm25']:
                logger.warning(
                    f"索引一致性检查失败: 向量索引 {stats['vector']} 条, "
                    f"BM25 索引 {stats['bm25']} 条, 建议重新构建"
                )

        logger.info("=" * 60)
        logger.info("导入完成")
        logger.info("=" * 60)
        logger.info(f"解析文档: {stats['parsed']} 个块")
        logger.info(f"向量索引: {stats['vector']} 个块")
        logger.info(f"BM25 索引: {stats['bm25']} 个块")
        logger.info("=" * 60)

        return stats

    def rebuild_knowledge_base(
        self,
        backup: bool = True,
        file_pattern: str = "*.md"
    ) -> Dict[str, Any]:
        """重建知识库

        Args:
            backup: 是否备份现有数据
            file_pattern: 文件匹配模式

        Returns:
            Dict[str, Any]: 重建结果和统计信息
        """
        logger.info("=" * 60)
        logger.info("开始重建知识库")
        logger.info("=" * 60)

        result = {
            'success': False,
            'backup_path': None,
            'stats': {},
            'errors': []
        }

        try:
            # 步骤 1: 备份现有数据
            if backup:
                logger.info("步骤 1: 备份现有数据")
                import shutil
                from datetime import datetime

                backup_dir = Path(self.config.vector_db_path).parent / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                backup_dir.mkdir(parents=True, exist_ok=True)

                # 备份向量数据库
                vector_db_path = Path(self.config.vector_db_path)
                if vector_db_path.exists():
                    shutil.copytree(vector_db_path, backup_dir / "lancedb")
                    result['backup_path'] = str(backup_dir)
                    logger.info(f"备份完成: {backup_dir}")

            # 步骤 2: 重新导入
            logger.info("步骤 2: 重新导入数据")
            stats = self.import_all(
                file_pattern=file_pattern,
                force_rebuild=True,
                skip_vector=False
            )

            result['stats'] = stats
            result['success'] = True

            logger.info("=" * 60)
            logger.info("知识库重建完成")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"重建知识库时出错: {e}")
            result['errors'].append(str(e))

        return result


class KBDataImporter:
    """KB 检查清单数据导入器

    将 excel_to_kb.py 生成的预处理 Markdown 文件导入到：
    1. 向量数据库 (LanceDB) - 用于语义检索
    2. BM25 索引 - 用于关键词检索

    使用 KBChecklistChunker 按 ## 第N项 分块，提取 frontmatter 和 blockquote 元数据。
    """

    def __init__(self, config: RAGConfig = None):
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
