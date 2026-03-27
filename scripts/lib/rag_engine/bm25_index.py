#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BM25 索引模块

基于 jieba 分词 + rank_bm25 构建、持久化和查询 BM25 索引。
"""
import logging
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from rank_bm25 import BM25Okapi

from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)


class BM25Index:
    """BM25 索引管理器

    构建、持久化和查询 BM25 索引。
    索引在导入阶段构建并序列化到磁盘，查询时从磁盘加载。
    """

    def __init__(self, bm25: BM25Okapi, doc_ids: List[str], nodes: list):
        self._bm25 = bm25
        self._doc_ids = doc_ids
        self._nodes = nodes

    @classmethod
    def build(cls, documents: List, index_path: Path) -> 'BM25Index':
        """构建 BM25 索引并持久化

        Args:
            documents: 文档列表 (Document 或 TextNode)，需有 .text 和 .metadata
            index_path: 索引文件路径

        Returns:
            BM25Index: 构建好的索引实例
        """
        if not documents:
            logger.warning("构建 BM25 索引: 文档列表为空")
            index = cls.__new__(cls)
            index._bm25 = None
            index._doc_ids = []
            index._nodes = []
            cls._save(index, index_path)
            return index

        logger.info(f"构建 BM25 索引: {len(documents)} 个文档")

        tokenized_corpus = [tokenize_chinese(doc.text) for doc in documents]
        bm25 = BM25Okapi(tokenized_corpus)

        doc_ids = [getattr(doc, 'id_', f'doc_{i}') for i, doc in enumerate(documents)]
        nodes = list(documents)

        index = cls(bm25, doc_ids, nodes)
        cls._save(index, index_path)

        logger.info(f"BM25 索引已保存: {index_path}")
        return index

    @classmethod
    def load(cls, index_path: Path) -> Optional['BM25Index']:
        """从磁盘加载 BM25 索引

        Args:
            index_path: 索引文件路径

        Returns:
            Optional[BM25Index]: 索引实例，加载失败返回 None
        """
        index_path = Path(index_path)
        if not index_path.exists():
            logger.warning(f"BM25 索引文件不存在: {index_path}")
            return None

        try:
            with open(index_path, 'rb') as f:
                data = pickle.load(f)
            index = cls(data['bm25'], data['doc_ids'], data['nodes'])
            logger.info(f"BM25 索引已加载: {index_path} ({len(data['doc_ids'])} 个文档)")
            return index
        except Exception as e:
            logger.error(f"加载 BM25 索引失败: {e}")
            return None

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple]:
        """查询 BM25 索引

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 元数据过滤条件

        Returns:
            List[Tuple]: [(node, score), ...] 按分数降序
        """
        if not self._nodes or self._bm25 is None:
            return []

        query_tokens = tokenize_chinese(query)
        scores = self._bm25.get_scores(query_tokens)

        # 按分数排序取 top_k
        scored_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:top_k]

        results = []
        for idx in scored_indices:
            if scores[idx] <= 0:
                continue

            node = self._nodes[idx]
            if filters:
                if not all(node.metadata.get(k) == v for k, v in filters.items()):
                    continue

            results.append((node, float(scores[idx])))

        return results

    @classmethod
    def _save(cls, index: 'BM25Index', path: Path) -> None:
        """序列化索引到磁盘"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'wb') as f:
            pickle.dump({
                'bm25': index._bm25,
                'doc_ids': index._doc_ids,
                'nodes': index._nodes,
            }, f)

    @property
    def doc_count(self) -> int:
        return len(self._nodes)
