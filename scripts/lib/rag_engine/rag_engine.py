#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 查询引擎
统一的检索增强生成引擎，通过策略模式支持不同使用场景
"""
import logging
import threading
from typing import Callable, Dict, Any, List, Optional

try:
    from llama_index.core import Settings
except ImportError:
    Settings = None

from .config import RAGConfig
from .index_manager import VectorIndexManager
from .llamaindex_adapter import ClientLLMAdapter, get_embedding_model
from .retrieval import hybrid_search
from .tokenizer import tokenize_chinese
from lib.llm import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)

# 引擎初始化锁，防止并发初始化时的 Settings 竞争
_engine_init_lock = threading.Lock()


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
        from lib.llm import LLMClientFactory

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
        self._avg_doc_len = 100
        self._setup_llm()

    def _setup_llm(self):
        llm_client = self.llm_provider()
        embed_config = LLMClientFactory.get_embedding_config()

        self._llm = ClientLLMAdapter(llm_client)
        self._embed_model = get_embedding_model(embed_config)

    def initialize(self, force_rebuild: bool = False) -> bool:
        """
        初始化查询引擎（资源安全版本）

        Args:
            force_rebuild: 是否强制重建索引

        Returns:
            bool: 初始化是否成功
        """
        if Settings is None:
            logger.error("llama_index 未安装，无法初始化 RAG 引擎")
            return False

        with _engine_init_lock:
            old_llm = getattr(Settings, 'llm', None)
            old_embed = getattr(Settings, 'embed_model', None)

            try:
                Settings.llm = self._llm
                Settings.embed_model = self._embed_model

                index = self.index_manager.create_index(
                    documents=None,
                    force_rebuild=force_rebuild
                )

                if index is None:
                    raise RuntimeError("索引初始化失败")

                self._calculate_avg_doc_len(index)
                self.query_engine = self.index_manager.create_query_engine()

                if self.query_engine is None:
                    raise RuntimeError("查询引擎创建失败")

                logger.info("RAG 引擎初始化成功")
                return True

            except Exception as e:
                logger.error(f"RAG 引擎初始化失败: {e}")
                self._cleanup_resources(old_llm, old_embed)
                self.query_engine = None
                self._avg_doc_len = 100
                return False

    def _cleanup_resources(self, old_llm=None, old_embed=None) -> None:
        """清理已分配的资源"""
        try:
            if old_llm is not None:
                Settings.llm = old_llm
            else:
                if hasattr(Settings, 'llm'):
                    delattr(Settings, 'llm')

            if old_embed is not None:
                Settings.embed_model = old_embed
            else:
                if hasattr(Settings, 'embed_model'):
                    delattr(Settings, 'embed_model')

            logger.debug("已清理 RAG 引擎资源")
        except Exception as e:
            logger.warning(f"清理资源时出错: {e}")

    def cleanup(self) -> None:
        """显式清理引擎资源"""
        with _engine_init_lock:
            self._cleanup_resources()
            self.query_engine = None
            logger.info("RAG 引擎已清理")

    def _calculate_avg_doc_len(self, index) -> None:
        doc_lengths = []
        for node in index.docstore.docs.values():
            tokens = tokenize_chinese(node.text)
            doc_lengths.append(len(tokens))

        if doc_lengths:
            self._avg_doc_len = sum(doc_lengths) / len(doc_lengths)
            logger.info(f"Calculated average document length: {self._avg_doc_len:.1f} tokens")

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
        """混合检索（向量 + 关键词）"""
        config = self.config.hybrid_config
        index = self.index_manager.get_index()
        if not index:
            return []

        return hybrid_search(
            index=index,
            query_text=query_text,
            vector_top_k=config.vector_top_k,
            keyword_top_k=config.keyword_top_k,
            alpha=config.alpha,
            filters=filters
        )

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

    def search_by_metadata(
        self,
        query: str,
        law_name: str = None,
        category: str = None,
        hierarchy_level: str = None,
        issuing_authority: str = None
    ) -> List[Dict[str, Any]]:
        """
        使用增强元数据进行检索

        Args:
            query: 查询文本
            law_name: 法规名称过滤
            category: 分类过滤
            hierarchy_level: 层级过滤
            issuing_authority: 发布机关过滤

        Returns:
            List[Dict]: 检索结果
        """
        filters = {}
        if law_name:
            filters['law_name'] = law_name
        if category:
            filters['category'] = category
        if hierarchy_level:
            filters['hierarchy_level'] = hierarchy_level
        if issuing_authority:
            filters['issuing_authority'] = issuing_authority

        return self.search(query, filters=filters)


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
