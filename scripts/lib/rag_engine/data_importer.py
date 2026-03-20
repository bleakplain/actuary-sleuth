#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入模块
负责将法规文档导入到向量数据库和 SQLite
"""
import logging
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
    """

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self.parser = RegulationDocParser(self.config.regulations_dir)
        self.index_manager = VectorIndexManager(self.config)
        self._setup_embedding()

    def _setup_embedding(self):
        embed_config = LLMClientFactory.get_embedding_config()
        Settings.embed_model = get_embedding_model(embed_config)

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
                            (id, law_name, article_number, content, category, tags, effective_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            record.get('id'),
                            record.get('law_name'),
                            record.get('article_number'),
                            record.get('content'),
                            record.get('category', ''),
                            record.get('tags', ''),
                            record.get('effective_date', '')
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
        """导入所有数据"""
        stats = {
            'parsed': 0,
            'sqlite': 0,
            'vector': 0
        }

        logger.info("=" * 60)
        logger.info("步骤 1: 解析法规文档")
        logger.info("=" * 60)

        documents = self.parse_documents(file_pattern)
        stats['parsed'] = len(documents)

        if not documents:
            logger.warning("没有找到任何文档")
            return stats

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

        logger.info("=" * 60)
        logger.info("导入完成")
        logger.info("=" * 60)
        logger.info(f"解析文档: {stats['parsed']} 条")
        logger.info(f"SQLite: {stats['sqlite']} 条")
        logger.info(f"向量索引: {stats['vector']} 条")
        logger.info("=" * 60)

        return stats
