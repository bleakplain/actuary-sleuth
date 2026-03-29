#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BM25 索引模块

基于 jieba 分词 + rank_bm25 构建、持久化和查询 BM25 索引。
"""
import heapq
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import joblib
from rank_bm25 import BM25Okapi

from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_INDEX_VERSION = "1.0"


class BM25Index:
    """BM25 索引管理器

    构建、持久化和查询 BM25 索引。
    索引在导入阶段构建并序列化到磁盘，查询时从磁盘加载。
    """

    def __init__(self, bm25: BM25Okapi, nodes: list):
        self._bm25 = bm25
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
            index._nodes = []
            cls._save(index, index_path)
            return index

        logger.info(f"构建 BM25 索引: {len(documents)} 个文档")

        tokenized_corpus = [tokenize_chinese(doc.text) for doc in documents]
        bm25 = BM25Okapi(tokenized_corpus)
        nodes = list(documents)

        index = cls(bm25, nodes)
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
        try:
            with open(index_path, 'rb') as f:
                payload = joblib.load(f)

            if not isinstance(payload, dict) or 'version' not in payload:
                logger.warning(f"BM25 索引格式无效: {index_path}")
                return None

            version = payload['version']
            if version != _INDEX_VERSION:
                logger.warning(
                    f"BM25 索引版本不匹配: 期望 {_INDEX_VERSION}, 实际 {version}, "
                    f"请重新构建索引"
                )
                return None

            index = cls(payload['bm25'], payload['nodes'])
            logger.info(f"BM25 索引已加载: {index_path} ({len(payload['nodes'])} 个文档)")
            return index
        except FileNotFoundError:
            logger.warning(f"BM25 索引文件不存在: {index_path}")
            return None
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
        if not self._nodes:
            return []

        query_tokens = tokenize_chinese(query)
        scores = self._bm25.get_scores(query_tokens)

        if not filters:
            top_indices = heapq.nlargest(top_k, range(len(scores)), key=lambda i: scores[i])
            return [
                (self._nodes[idx], float(scores[idx]))
                for idx in top_indices if scores[idx] > 0
            ]

        candidates = [
            (idx, float(scores[idx]))
            for idx in range(len(scores))
            if scores[idx] > 0 and all(
                self._nodes[idx].metadata.get(k) == v for k, v in filters.items()
            )
        ]
        top_candidates = heapq.nlargest(top_k, candidates, key=lambda x: x[1])
        return [(self._nodes[idx], score) for idx, score in top_candidates]

    @classmethod
    def _save(cls, index: 'BM25Index', path: Path) -> None:
        """序列化索引到磁盘"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            'version': _INDEX_VERSION,
            'bm25': index._bm25,
            'nodes': index._nodes,
        }
        joblib.dump(payload, path, compress=3)
        logger.info(f"BM25 索引已保存: {path}")

    @property
    def doc_count(self) -> int:
        return len(self._nodes)
