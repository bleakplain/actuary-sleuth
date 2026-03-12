#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入模块
负责将法规文档导入到向量数据库和 SQLite
"""
from typing import List, Dict, Any

from .document_parser import RegulationDocumentParser
from .index_manager import VectorIndexManager
from .config import RAGConfig


class RegulationDataImporter:
    """法规数据导入器

    负责将法规文档导入到：
    1. 向量数据库 (LanceDB) - 用于语义检索
    2. SQLite - 用于结构化查询
    """

    def __init__(self, config: RAGConfig = None):
        """
        初始化导入器

        Args:
            config: RAG 配置
        """
        self.config = config or RAGConfig()
        self.parser = RegulationDocumentParser(self.config.regulations_dir)
        self.index_manager = VectorIndexManager(self.config)

    def parse_documents(self, file_pattern: str = "*.md") -> List:
        """
        解析法规文档

        Args:
            file_pattern: 文件匹配模式

        Returns:
            List: 文档列表
        """
        return self.parser.parse_all(file_pattern)

    def parse_single_file(self, file_name: str) -> List:
        """
        解析单个文件

        Args:
            file_name: 文件名

        Returns:
            List: 文档列表
        """
        return self.parser.parse_single_file(file_name)

    def import_to_vector_db(
        self,
        documents: List,
        force_rebuild: bool = False
    ) -> bool:
        """
        导入到向量数据库

        Args:
            documents: 文档列表
            force_rebuild: 是否强制重建索引

        Returns:
            bool: 成功返回 True
        """
        index = self.index_manager.create_index(
            documents=documents,
            force_rebuild=force_rebuild
        )
        return index is not None

    def import_to_sqlite(self, documents: List) -> int:
        """
        导入到 SQLite

        Args:
            documents: 文档列表

        Returns:
            int: 成功导入的数量
        """
        from lib.database import get_connection, add_regulation

        sqlite_records = self.parser.documents_to_sqlite_format(documents)
        imported = 0

        try:
            with get_connection() as conn:
                for record in sqlite_records:
                    if add_regulation(record):
                        imported += 1

            print(f"已导入 {imported} 条法规到 SQLite")
            return imported

        except Exception as e:
            print(f"导入到 SQLite 时出错: {e}")
            return imported

    def import_all(
        self,
        file_pattern: str = "*.md",
        force_rebuild: bool = False,
        skip_sqlite: bool = False,
        skip_vector: bool = False
    ) -> Dict[str, int]:
        """
        导入所有数据

        Args:
            file_pattern: 文件匹配模式
            force_rebuild: 是否强制重建向量索引
            skip_sqlite: 是否跳过 SQLite 导入
            skip_vector: 是否跳过向量数据库导入

        Returns:
            Dict: 导入统计
        """
        stats = {
            'parsed': 0,
            'sqlite': 0,
            'vector': 0
        }

        # 解析文档
        print("\n" + "=" * 60)
        print("步骤 1: 解析法规文档")
        print("=" * 60)

        documents = self.parse_documents(file_pattern)
        stats['parsed'] = len(documents)

        if not documents:
            print("没有找到任何文档")
            return stats

        # 导入到 SQLite
        if not skip_sqlite:
            print("\n" + "=" * 60)
            print("步骤 2: 导入到 SQLite")
            print("=" * 60)

            stats['sqlite'] = self.import_to_sqlite(documents)

        # 导入到向量数据库
        if not skip_vector:
            print("\n" + "=" * 60)
            print("步骤 3: 创建向量索引")
            print("=" * 60)

            if self.import_to_vector_db(documents, force_rebuild):
                stats['vector'] = len(documents)

        # 显示统计
        print("\n" + "=" * 60)
        print("导入完成")
        print("=" * 60)
        print(f"解析文档: {stats['parsed']} 条")
        print(f"SQLite: {stats['sqlite']} 条")
        print(f"向量索引: {stats['vector']} 条")
        print("=" * 60)

        return stats
