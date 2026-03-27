#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入模块
负责将法规文档导入到向量数据库和 SQLite
"""
import logging
from pathlib import Path
from typing import List, Dict, Any

from llama_index.core import Settings

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
    2. SQLite - 用于结构化查询

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
        index = self.index_manager.create_index(
            documents=documents,
            force_rebuild=force_rebuild
        )
        return index is not None

    def import_to_sqlite(self, documents: List) -> int:
        """导入到 SQLite"""
        from lib.common.database import get_connection

        sqlite_records = self.parser.documents_to_sqlite_format(documents)
        imported = 0
        failed = 0

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                for record in sqlite_records:
                    try:
                        cur.execute('''
                            INSERT OR REPLACE INTO regulations
                            (id, law_name, article_number, content, category, tags, effective_date,
                             source_file, section_title, hierarchy_path, content_type,
                             is_prohibition, is_mandatory, is_exception, char_count, sentence_count)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            record.get('id'),
                            record.get('law_name'),
                            record.get('article_number'),
                            record.get('content'),
                            record.get('category', ''),
                            record.get('tags', ''),
                            record.get('effective_date', ''),
                            record.get('source_file', ''),
                            record.get('section_title', ''),
                            record.get('hierarchy_path', ''),
                            record.get('content_type', ''),
                            record.get('is_prohibition', 0),
                            record.get('is_mandatory', 0),
                            record.get('is_exception', 0),
                            record.get('char_count', 0),
                            record.get('sentence_count', 0),
                        ))
                        imported += 1
                    except Exception as e:
                        failed += 1
                        logger.warning(f"导入法规失败 [{record.get('article_number', 'N/A')}]: {e}")

            if failed > 0:
                logger.warning(f"部分法规导入失败: {failed} 条")

            logger.info(f"已导入 {imported} 条法规到 SQLite")
            return imported

        except Exception as e:
            logger.error(f"导入到 SQLite 时出错: {e}")
            return imported

    def import_all(
        self,
        file_pattern: str = "*.md",
        force_rebuild: bool = False,
        skip_sqlite: bool = False,
        skip_vector: bool = False
    ) -> Dict[str, int]:
        """导入所有数据

        Args:
            file_pattern: 文件匹配模式
            force_rebuild: 是否强制重建向量索引
            skip_sqlite: 是否跳过 SQLite 导入
            skip_vector: 是否跳过向量索引创建

        Returns:
            Dict[str, int]: 导入统计信息
        """
        stats = {
            'parsed': 0,
            'sqlite': 0,
            'vector': 0,
            'bm25': 0
        }

        # 显示分块策略信息
        logger.info("=" * 60)
        logger.info(f"分块策略: {self.config.chunking_strategy}")
        if self.config.chunking_strategy == "semantic":
            logger.info("使用语义分块 - 保留文档结构和语义完整性")
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

        if not skip_sqlite:
            logger.info("=" * 60)
            logger.info("步骤 2: 导入到 SQLite")
            logger.info("=" * 60)
            stats['sqlite'] = self.import_to_sqlite(documents)

        if not skip_vector:
            logger.info("=" * 60)
            logger.info("步骤 3: 创建向量索引")
            logger.info("=" * 60)
            if self.import_to_vector_db(documents, force_rebuild):
                stats['vector'] = len(documents)

                # 显示索引统计
                index_stats = self.index_manager.get_index_stats()
                logger.info(f"索引统计: {index_stats}")

        # 构建 BM25 索引
        logger.info("=" * 60)
        logger.info("步骤 4: 构建 BM25 索引")
        logger.info("=" * 60)
        from .bm25_index import BM25Index
        data_dir = Path(self.config.vector_db_path).parent
        bm25_path = data_dir / "bm25_index.pkl"
        BM25Index.build(documents, bm25_path)
        stats['bm25'] = len(documents)

        logger.info("=" * 60)
        logger.info("导入完成")
        logger.info("=" * 60)
        logger.info(f"解析文档: {stats['parsed']} 个块")
        logger.info(f"SQLite: {stats['sqlite']} 条")
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
                skip_sqlite=False,
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
