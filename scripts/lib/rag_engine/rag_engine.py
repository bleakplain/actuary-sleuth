#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 查询引擎
统一的检索增强生成引擎，通过策略模式支持不同使用场景
"""
import logging
import re
import threading
from typing import Callable, Dict, Any, List, Optional, Union

from llama_index.core import Settings
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters, FilterOperator

from .config import RAGConfig, HybridQueryConfig
from .index_manager import VectorIndexManager
from .llamaindex_adapter import ClientLLMAdapter, get_embedding_model
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)

# 引擎初始化锁，防止并发初始化时的 Settings 竞争
_engine_init_lock = threading.Lock()


def _tokenize_chinese(text: str) -> List[str]:
    """简单中文分词"""
    return re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text.lower())


def _normalize_scores(scores: List[float]) -> List[float]:
    """归一化分数到 [0, 1]"""
    if not scores:
        return []
    max_score = max(scores)
    min_score = min(scores)
    if max_score == min_score:
        return [1.0] * len(scores)
    return [(s - min_score) / (max_score - min_score) for s in scores]


class RAGEngine:
    """
    统一的 RAG 查询引擎

    通过策略模式（llm_provider）支持不同场景：
    - QA 场景：使用快速响应模型 (glm-4-flash)
    - 审计场景：使用高质量分析模型 (glm-4-plus)

    使用示例:
        # 方式1: 使用工厂函数（推荐）
        from lib.rag_engine import create_qa_engine, create_audit_engine

        qa_engine = create_qa_engine()
        answer = qa_engine.ask("健康保险等待期有什么规定？")

        audit_engine = create_audit_engine()
        results = audit_engine.search("产品条款是否符合规定")

        # 方式2: 直接构造
        from lib.rag_engine import RAGEngine
        from lib.llm_client import LLMClientFactory

        engine = RAGEngine(llm_provider=LLMClientFactory.get_qa_llm)
    """

    def __init__(
        self,
        config: RAGConfig = None,
        llm_provider: Callable[[], BaseLLMClient] = None
    ):
        """
        初始化 RAG 引擎

        Args:
            config: RAG 配置，默认使用 RAGConfig()
            llm_provider: 返回 LLM 客户端的可调用对象
                         默认使用 QA 场景的 LLM (glm-4-flash)
        """
        self.config = config or RAGConfig()
        self.llm_provider = llm_provider or LLMClientFactory.get_qa_llm
        self.index_manager = VectorIndexManager(self.config)
        self.query_engine = None

        self._llm = None
        self._embed_model = None
        self._setup_llm()

    def _setup_llm(self):
        llm_client = self.llm_provider()
        embed_config = LLMClientFactory.get_embedding_config()

        self._llm = ClientLLMAdapter(llm_client)
        self._embed_model = get_embedding_model(embed_config)

    def initialize(self, force_rebuild: bool = False) -> bool:
        """
        初始化查询引擎

        Args:
            force_rebuild: 是否强制重建索引

        Returns:
            bool: 初始化是否成功
        """
        with _engine_init_lock:
            # 确保使用当前引擎的 LLM 和嵌入模型
            Settings.llm = self._llm
            Settings.embed_model = self._embed_model

            index = self.index_manager.create_index(
                documents=None,
                force_rebuild=force_rebuild
            )

            if index is None:
                logger.error("索引初始化失败")
                return False

            self.query_engine = self.index_manager.create_query_engine()
            return self.query_engine is not None

    def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        """
        问答模式：返回自然语言答案

        Args:
            question: 用户问题
            include_sources: 是否在结果中包含相关法规来源

        Returns:
            Dict: {
                'answer': str,  # LLM 生成的答案
                'sources': List[Dict]  # 相关法规来源
            }
        """
        if self.query_engine is None:
            if not self.initialize():
                return {
                    'answer': '引擎初始化失败',
                    'sources': []
                }

        try:
            response = self.query_engine.query(question)

            result = {
                'answer': str(response),
                'sources': self._extract_sources(response) if include_sources else []
            }
            return result

        except Exception as e:
            logger.error(f"问答出错: {e}")
            return {
                'answer': f'问答出错: {str(e)}',
                'sources': []
            }

    async def aask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        """
        异步问答模式

        Args:
            question: 用户问题
            include_sources: 是否在结果中包含相关法规来源

        Returns:
            Dict: 同 ask() 方法
        """
        if self.query_engine is None:
            if not self.initialize():
                return {
                    'answer': '引擎初始化失败',
                    'sources': []
                }

        try:
            response = await self.query_engine.aquery(question)

            result = {
                'answer': str(response),
                'sources': self._extract_sources(response) if include_sources else []
            }
            return result

        except Exception as e:
            logger.error(f"异步问答出错: {e}")
            return {
                'answer': f'问答出错: {str(e)}',
                'sources': []
            }

    def search(
        self,
        query_text: str,
        top_k: int = None,
        use_hybrid: bool = True,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """
        检索模式：返回结构化法规列表

        适用于审计场景，需要查看原始法规条款时使用。
        支持混合检索（向量 + 关键词）和元数据过滤。

        Args:
            query_text: 查询文本（如产品条款内容）
            top_k: 返回结果数量，默认使用配置中的 top_k_results
            use_hybrid: 是否使用混合检索，默认 True
            filters: 元数据过滤条件，如 {'law_name': '保险法', 'category': '未分类'}

        Returns:
            List[Dict]: [{
                'law_name': str,        # 法律/法规名称
                'article_number': str,  # 条款号
                'category': str,        # 分类
                'content': str,         # 条款内容
                'score': float          # 相似度得分
            }]
        """
        if self.query_engine is None:
            if not self.initialize():
                return []

        try:
            if use_hybrid:
                results = self._hybrid_search(query_text, top_k, filters)
            else:
                response = self.query_engine.query(query_text)
                results = self._extract_results_from_response(response)

            # 应用元数据过滤
            if filters:
                results = self._apply_filters(results, filters)

            if top_k:
                results = results[:top_k]

            return results

        except Exception as e:
            logger.error(f"搜索出错: {e}")
            return []

    def _hybrid_search(
        self,
        query_text: str,
        top_k: int = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        config = self.config.hybrid_config
        index = self.index_manager.get_index()
        if not index:
            return []

        metadata_filters = None
        if filters:
            filter_list = [
                ExactMatchFilter(key=k, value=v)
                for k, v in filters.items()
            ]
            metadata_filters = MetadataFilters(filters=filter_list)

        vector_retriever = index.as_retriever(
            similarity_top_k=config.vector_top_k,
            filters=metadata_filters
        )
        from llama_index.core import QueryBundle
        query_bundle = QueryBundle(query_str=query_text)
        vector_nodes = vector_retriever.retrieve(query_bundle)

        keyword_nodes = self._keyword_search(
            query_text, config.keyword_top_k, filters
        )

        fused_results = self._fuse_results(
            vector_nodes, keyword_nodes, config.alpha
        )

        return fused_results

    def _keyword_search(
        self,
        query_text: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List:
        index = self.index_manager.get_index()
        if not index:
            return []

        all_nodes = list(index.docstore.docs.values())

        if filters:
            all_nodes = [
                node for node in all_nodes
                if all(node.metadata.get(k) == v for k, v in filters.items())
            ]

        query_tokens = _tokenize_chinese(query_text)

        scores = []
        for node in all_nodes:
            node_tokens = _tokenize_chinese(node.text)
            score = self._compute_bm25_score(query_tokens, node_tokens)
            scores.append((node, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        from llama_index.core.schema import NodeWithScore
        return [
            NodeWithScore(node=node, score=score)
            for node, score in scores[:top_k] if score > 0
        ]

    def _compute_bm25_score(self, query_tokens: List[str], doc_tokens: List[str]) -> float:
        """
        计算 BM25 分数

        Args:
            query_tokens: 查询分词
            doc_tokens: 文档分词

        Returns:
            float: BM25 分数
        """
        if not query_tokens or not doc_tokens:
            return 0.0

        k1 = 1.5
        b = 0.75
        avg_doc_len = 100

        doc_len = len(doc_tokens)
        doc_freq = {}
        for token in doc_tokens:
            doc_freq[token] = doc_freq.get(token, 0) + 1

        score = 0.0
        for token in query_tokens:
            if token in doc_freq:
                tf = doc_freq[token]
                idf = 1.0
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))

        return score

    def _fuse_results(
        self,
        vector_nodes: List,
        keyword_nodes: List,
        alpha: float
    ) -> List[Dict[str, Any]]:
        """
        融合向量检索和关键词检索结果

        Args:
            vector_nodes: 向量检索结果
            keyword_nodes: 关键词检索结果
            alpha: 向量检索权重

        Returns:
            List[Dict]: 融合后的结果列表
        """
        # 归一化分数
        vector_scores = _normalize_scores([n.score for n in vector_nodes])
        keyword_scores = _normalize_scores([n.score for n in keyword_nodes])

        # 合并结果
        merged = {}

        for node, norm_score in zip(vector_nodes, vector_scores):
            node_id = id(node.node)
            merged[node_id] = {
                'node': node.node,
                'vector_score': norm_score,
                'keyword_score': 0.0,
            }

        for node, norm_score in zip(keyword_nodes, keyword_scores):
            node_id = id(node.node)
            if node_id in merged:
                merged[node_id]['keyword_score'] = norm_score
            else:
                merged[node_id] = {
                    'node': node.node,
                    'vector_score': 0.0,
                    'keyword_score': norm_score,
                }

        # 计算融合分数并格式化结果
        results = []
        for item in merged.values():
            fused_score = alpha * item['vector_score'] + (1 - alpha) * item['keyword_score']
            node = item['node']
            results.append({
                'law_name': node.metadata.get('law_name', '未知'),
                'article_number': node.metadata.get('article_number', '未知'),
                'category': node.metadata.get('category', ''),
                'content': node.text,
                'score': fused_score
            })

        return sorted(results, key=lambda x: x['score'], reverse=True)

    def _apply_filters(self, results: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            r for r in results
            if all(r.get(k) == v for k, v in filters.items())
        ]

    def _extract_results_from_response(self, response) -> List[Dict[str, Any]]:
        """从响应中提取结果"""
        results = []
        if hasattr(response, 'source_nodes'):
            for node in response.source_nodes:
                results.append({
                    'law_name': node.node.metadata.get('law_name', '未知'),
                    'article_number': node.node.metadata.get('article_number', '未知'),
                    'category': node.node.metadata.get('category', ''),
                    'content': node.node.text,
                    'score': node.score if hasattr(node, 'score') else None
                })
        return results

    def _extract_sources(self, response) -> List[Dict[str, Any]]:
        """
        从 LlamaIndex 响应中提取源信息

        Args:
            response: LlamaIndex 查询响应对象

        Returns:
            List[Dict]: 源信息列表
        """
        sources = []
        if hasattr(response, 'source_nodes'):
            for node in response.source_nodes:
                text_preview = node.node.text
                if len(text_preview) > 200:
                    text_preview = text_preview[:200] + '...'

                sources.append({
                    'law_name': node.node.metadata.get('law_name', '未知'),
                    'article_number': node.node.metadata.get('article_number', '未知'),
                    'content': text_preview,
                    'score': node.score if hasattr(node, 'score') else None
                })
        return sources

    def chat(self, message: str) -> str:
        """
        聊天模式（简化接口）

        Args:
            message: 用户消息

        Returns:
            str: 回复文本
        """
        result = self.ask(message, include_sources=False)
        return result['answer']


# 工厂函数：创建不同场景的引擎

def create_qa_engine(config: RAGConfig = None) -> RAGEngine:
    """
    创建问答引擎

    使用快速响应模型 (glm-4-flash)，适合面向终端用户的问答场景。

    Args:
        config: RAG 配置，可选

    Returns:
        RAGEngine: 配置为问答模式的引擎实例
    """
    return RAGEngine(config or RAGConfig(), LLMClientFactory.get_qa_llm)


def create_audit_engine(config: RAGConfig = None) -> RAGEngine:
    """
    创建审计引擎

    使用高质量分析模型 (glm-4-plus)，适合保险产品审计场景。

    Args:
        config: RAG 配置，可选

    Returns:
        RAGEngine: 配置为审计模式的引擎实例
    """
    return RAGEngine(config or RAGConfig(), LLMClientFactory.get_audit_llm)
