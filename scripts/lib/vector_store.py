#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量检索模块 - LanceDB integration
提供向量数据库的连接、搜索和管理功能
"""
import lancedb
import pyarrow as pa
from pathlib import Path
from typing import List, Dict, Optional, Any
import json

# 数据库路径配置
DB_URI = str(Path(__file__).parent.parent.parent / 'data' / 'lancedb')


class VectorDB:
    """LanceDB 向量数据库管理类"""

    _instance = None
    _tables = {}

    @classmethod
    def connect(cls):
        """
        连接到 LanceDB 数据库（单例模式）

        Returns:
            LanceDB 数据库连接对象

        Raises:
            Exception: 当连接失败时抛出异常
        """
        try:
            if cls._instance is None:
                # 确保数据目录存在
                db_path = Path(DB_URI)
                db_path.mkdir(parents=True, exist_ok=True)

                # 连接到数据库
                cls._instance = lancedb.connect(DB_URI)
                print(f"Connected to LanceDB at: {DB_URI}")
            return cls._instance
        except Exception as e:
            raise Exception(f"Failed to connect to LanceDB: {str(e)}")

    @classmethod
    def get_table(cls, table_name: str = 'regulations_vectors'):
        """
        获取或创建向量表

        Args:
            table_name: 表名称，默认为 'regulations_vectors'

        Returns:
            表对象，如果表不存在则返回 None
        """
        try:
            if table_name not in cls._tables:
                db = cls.connect()

                try:
                    # 尝试打开已存在的表
                    cls._tables[table_name] = db.open_table(table_name)
                    print(f"Opened existing table: {table_name}")
                except Exception as e:
                    # 表不存在，返回 None 让调用者决定是否创建
                    print(f"Table '{table_name}' does not exist yet: {str(e)}")
                    return None

            return cls._tables[table_name]
        except Exception as e:
            print(f"Error getting table '{table_name}': {str(e)}")
            return None

    @classmethod
    def create_table(cls, table_name: str = 'regulations_vectors', vector_dim: int = 768):
        """
        创建新的向量表

        Args:
            table_name: 表名称
            vector_dim: 向量维度，默认为 768（nomic-embed-text 的维度）

        Returns:
            新创建的表对象

        Raises:
            Exception: 当创建表失败时抛出异常
        """
        try:
            db = cls.connect()

            # 定义表结构
            schema = pa.schema([
                pa.field('id', pa.string(), nullable=False),
                pa.field('regulation_id', pa.string()),
                pa.field('chunk_text', pa.string()),
                pa.field('vector', pa.list_(pa.float32()), nullable=False),
                pa.field('metadata', pa.string())
            ])

            # 创建表
            table = db.create_table(table_name, schema=schema)
            cls._tables[table_name] = table
            print(f"Created new table: {table_name} with vector dimension {vector_dim}")
            return table

        except Exception as e:
            raise Exception(f"Failed to create table '{table_name}': {str(e)}")

    @classmethod
    def search(cls, query_vector: List[float], top_k: int = 5, table_name: str = 'regulations_vectors') -> List[Dict[str, Any]]:
        """
        执行向量相似性搜索

        Args:
            query_vector: 查询向量（浮点数列表）
            top_k: 返回结果数量，默认为 5
            table_name: 表名称，默认为 'regulations_vectors'

        Returns:
            List[Dict]: 搜索结果列表，每个结果包含 content, metadata, score
        """
        try:
            table = cls.get_table(table_name)
            if table is None:
                print(f"Table '{table_name}' not found")
                return []

            # 执行向量搜索
            results = table.vectorSearch(query_vector).limit(top_k).to_pydict()

            # 格式化结果
            formatted_results = []
            for idx in range(len(results['id'])):
                formatted_results.append({
                    'id': results['id'][idx],
                    'content': results['chunk_text'][idx],
                    'metadata': json.loads(results['metadata'][idx]) if results.get('metadata') else {},
                    'score': 1 / (1 + results.get('_distance', [0])[idx]) if '_distance' in results else 1.0
                })

            return formatted_results

        except Exception as e:
            print(f"Error searching in table '{table_name}': {str(e)}")
            return []

    @classmethod
    def add_vectors(cls, data: List[Dict[str, Any]], table_name: str = 'regulations_vectors') -> bool:
        """
        向表中添加向量数据

        Args:
            data: 要添加的数据列表，每个元素包含 id, regulation_id, chunk_text, vector, metadata
            table_name: 表名称，默认为 'regulations_vectors'

        Returns:
            bool: 成功返回 True，失败返回 False
        """
        try:
            db = cls.connect()

            # 检查表是否存在
            existing_tables = db.table_names()
            if table_name not in existing_tables:
                # 表不存在，自动创建
                cls.create_table(table_name)

            table = cls.get_table(table_name)

            # 准备数据
            vectors_data = []
            for item in data:
                vectors_data.append({
                    'id': item.get('id', ''),
                    'regulation_id': item.get('regulation_id', ''),
                    'chunk_text': item.get('chunk_text', ''),
                    'vector': item.get('vector', []),
                    'metadata': json.dumps(item.get('metadata', {}), ensure_ascii=False)
                })

            # 添加数据到表
            table.add(vectors_data)
            print(f"Added {len(vectors_data)} vectors to table '{table_name}'")
            return True

        except Exception as e:
            print(f"Error adding vectors to table '{table_name}': {str(e)}")
            return False

    @classmethod
    def delete_table(cls, table_name: str) -> bool:
        """
       删除指定的表

        Args:
            table_name: 要删除的表名称

        Returns:
            bool: 成功返回 True，失败返回 False
        """
        try:
            db = cls.connect()
            db.drop_table(table_name)
            if table_name in cls._tables:
                del cls._tables[table_name]
            print(f"Dropped table: {table_name}")
            return True
        except Exception as e:
            print(f"Error dropping table '{table_name}': {str(e)}")
            return False

    @classmethod
    def table_exists(cls, table_name: str) -> bool:
        """
        检查表是否存在

        Args:
            table_name: 表名称

        Returns:
            bool: 表存在返回 True，否则返回 False
        """
        try:
            db = cls.connect()
            return table_name in db.list_tables()
        except Exception as e:
            print(f"Error checking table existence: {str(e)}")
            return False

    @classmethod
    def get_table_count(cls, table_name: str = 'regulations_vectors') -> int:
        """
        获取表中的记录数量

        Args:
            table_name: 表名称

        Returns:
            int: 记录数量，失败返回 0
        """
        try:
            table = cls.get_table(table_name)
            if table is None:
                return 0
            return len(table)
        except Exception as e:
            print(f"Error getting table count: {str(e)}")
            return 0


# 便捷函数
def search_regulations(query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    搜索相关法规（便捷函数）

    Args:
        query_vector: 查询向量
        top_k: 返回结果数量

    Returns:
        List[Dict]: 搜索结果列表
    """
    return VectorDB.search(query_vector, top_k=top_k, table_name='regulations_vectors')


def add_regulation_vectors(data: List[Dict[str, Any]]) -> bool:
    """
    添加法规向量（便捷函数）

    Args:
        data: 向量数据列表

    Returns:
        bool: 成功返回 True
    """
    return VectorDB.add_vectors(data, table_name='regulations_vectors')


if __name__ == '__main__':
    # 测试代码
    print("Testing LanceDB module...")

    try:
        # 测试连接
        db = VectorDB.connect()
        print(f"Database connected: {db}")

        # 测试表是否存在
        exists = VectorDB.table_exists('regulations_vectors')
        print(f"Table exists: {exists}")

        # 如果不存在，创建表
        if not exists:
            VectorDB.create_table('regulations_vectors')

        # 获取表数量
        count = VectorDB.get_table_count('regulations_vectors')
        print(f"Table count: {count}")

        print("LanceDB module test completed successfully!")

    except Exception as e:
        print(f"Test failed: {str(e)}")
