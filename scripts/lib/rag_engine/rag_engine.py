#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 查询引擎（线程安全版本）
统一的检索增强生成引擎，通过策略模式支持不同使用场景
"""
import asyncio
import logging
import threading
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional

try:
    from llama_index.core import Settings
except ImportError:
    Settings = None

from .config import RAGConfig
from .index_manager import VectorIndexManager
from .llamaindex_adapter import ClientLLMAdapter, get_embedding_model
from .retrieval import hybrid_search
from .bm25_index import BM25Index
from .reranker import LLMReranker, RerankConfig
from .query_preprocessor import QueryPreprocessor
from .exceptions import EngineInitializationError, RetrievalError
from lib.llm import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)

_engine_init_lock = threading.Lock()

_QA_PROMPT_TEMPLATE = """请根据以下法规条款回答用户的问题。

## 法规条款

{context}

## 用户问题

{question}

## 回答要求
1. 基于上述法规条款回答，不要编造信息
2. 如果法规条款不足以回答问题，请说明并建议查阅相关法规
3. 引用具体条款时请注明法规名称和条款号
4. 回答简洁专业"""


class ThreadLocalSettings:
    """线程本地 Settings 管理"""

    def __init__(self):
        self._local = threading.local()
        self._lock = threading.Lock()
        self._global_backup = {}

    def set(self, llm, embed_model) -> None:
        """设置当前线程的配置"""
        with self._lock:
            if not self._global_backup:
                self._global_backup['llm'] = getattr(Settings, 'llm', None)
                self._global_backup['embed_model'] = getattr(Settings, 'embed_model', None)

        if not hasattr(self._local, 'initialized'):
            self._local.llm = llm
            self._local.embed_model = embed_model
            self._local.initialized = True

    def apply(self) -> None:
        """应用线程配置到全局 Settings"""
        if hasattr(self._local, 'initialized') and self._local.initialized:
            Settings.llm = self._local.llm
            Settings.embed_model = self._local.embed_model

    def reset(self) -> None:
        """重置为全局默认配置"""
        with self._lock:
            if self._global_backup:
                Settings.llm = self._global_backup['llm']
                Settings.embed_model = self._global_backup['embed_model']


_MAX_CONTEXT_CHARS = 4000

_thread_settings = ThreadLocalSettings()


class RAGEngine:
    """统一的 RAG 查询引擎"""

    def __init__(
        self,
        config: RAGConfig = None,
        llm_provider: Callable[[], BaseLLMClient] = None
    ):
        self.config = config or RAGConfig()
        self.llm_provider = llm_provider or LLMClientFactory.get_qa_llm
        self.index_manager = VectorIndexManager(self.config)
        self.query_engine = None

        self._llm = None
        self._embed_model = None
        self._llm_client: Optional[BaseLLMClient] = None
        self._preprocessor: Optional[QueryPreprocessor] = None
        self._reranker: Optional[LLMReranker] = None
        self._bm25_index: Optional[BM25Index] = None
        self._initialized = False
        self._init_lock = threading.Lock()

        self._setup_llm()

    def _setup_llm(self):
        self._llm_client = self.llm_provider()
        embed_config = LLMClientFactory.get_embedding_config()

        self._llm = ClientLLMAdapter(self._llm_client)
        self._embed_model = get_embedding_model(embed_config)

        rerank_config = RerankConfig(
            enabled=self.config.hybrid_config.enable_rerank,
            top_k=self.config.hybrid_config.rerank_top_k,
        )
        self._reranker = LLMReranker(self._llm_client, rerank_config)
        self._preprocessor = QueryPreprocessor(llm_client=self._llm_client)

    def initialize(self, force_rebuild: bool = False) -> bool:
        """初始化查询引擎（线程安全版本）"""
        if Settings is None:
            logger.error("llama_index 未安装，无法初始化 RAG 引擎")
            return False

        with self._init_lock:
            if self._initialized:
                return True

            try:
                _thread_settings.set(self._llm, self._embed_model)
                _thread_settings.apply()

                index = self.index_manager.create_index(
                    documents=None,
                    force_rebuild=force_rebuild
                )

                if index is None:
                    raise RuntimeError("索引初始化失败")

                self._load_bm25_index()
                self.query_engine = self.index_manager.create_query_engine()

                if self.query_engine is None:
                    raise RuntimeError("查询引擎创建失败")

                self._initialized = True
                logger.info("RAG 引擎初始化成功")
                return True

            except (RuntimeError, ValueError, AttributeError) as e:
                logger.error(f"RAG 引擎初始化失败: {e}")
                _thread_settings.reset()
                self.query_engine = None
                self._cleanup_resources()
                return False

    def cleanup(self) -> None:
        """显式清理引擎资源"""
        with _engine_init_lock:
            self._cleanup_resources()
            self.query_engine = None
            logger.info("RAG 引擎已清理")

    def _cleanup_resources(self) -> None:
        """清理引擎内部资源"""
        self._bm25_index = None
        self._reranker = None
        self._preprocessor = None
        self._initialized = False

    def _load_bm25_index(self) -> None:
        """加载 BM25 索引"""
        data_dir = Path(self.config.vector_db_path).parent
        index_path = data_dir / "bm25_index.pkl"
        self._bm25_index = BM25Index.load(index_path)
        if self._bm25_index:
            logger.info(f"BM25 索引已加载 ({self._bm25_index.doc_count} 个文档)")
        else:
            logger.warning("BM25 索引加载失败，混合检索将仅使用向量检索")

    def _do_ask(self, question: str, include_sources: bool) -> Dict[str, Any]:
        if not self._initialized:
            if not self.initialize():
                raise EngineInitializationError("RAG 引擎初始化失败")

        _thread_settings.apply()

        try:
            search_results = self._hybrid_search(question, top_k=self.config.top_k_results)
            if not search_results:
                return {'answer': '未找到相关法规条款，请尝试换个描述方式。', 'sources': []}

            prompt = self._build_qa_prompt(question, search_results)
            assert self._llm_client is not None
            answer = self._llm_client.generate(prompt)

            return {
                'answer': str(answer),
                'sources': search_results if include_sources else [],
            }

        except EngineInitializationError:
            raise
        except Exception as e:
            raise RetrievalError(f"问答出错: {e}") from e

    def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        """问答模式：返回自然语言答案"""
        return self._do_ask(question, include_sources)

    async def aask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        """异步问答模式"""
        return await asyncio.to_thread(self._do_ask, question, include_sources)

    def _build_qa_prompt(self, question: str, search_results: List[Dict[str, Any]]) -> str:
        context_parts: List[str] = []
        total_chars = 0

        for i, result in enumerate(search_results, 1):
            law_name = result.get('law_name', '未知法规')
            article = result.get('article_number', '')
            content = result.get('content', '')
            part = f"{i}. 【{law_name}】{article}\n{content}"

            if total_chars + len(part) > _MAX_CONTEXT_CHARS:
                break

            context_parts.append(part)
            total_chars += len(part)

        context = "\n\n".join(context_parts)
        return _QA_PROMPT_TEMPLATE.format(context=context, question=question)

    def search(
        self,
        query_text: str,
        top_k: int = None,
        use_hybrid: bool = True,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """检索模式：返回结构化法规列表"""
        if not self._initialized:
            if not self.initialize():
                return []

        _thread_settings.apply()

        try:
            if use_hybrid:
                results = self._hybrid_search(query_text, top_k, filters)
            else:
                response = self.query_engine.query(query_text)
                results = self._extract_results_from_response(response)

            if filters:
                results = self._apply_filters(results, filters)

            if top_k:
                results = results[:top_k]

            return results

        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"搜索出错: {e}")
            return []

    def _hybrid_search(
        self,
        query_text: str,
        top_k: int = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """混合检索（向量 + BM25 关键词 + RRF 融合 + Rerank）"""
        config = self.config.hybrid_config
        index = self.index_manager.get_index()
        if not index:
            return []

        results = hybrid_search(
            index=index,
            bm25_index=self._bm25_index,
            query_text=query_text,
            vector_top_k=config.vector_top_k,
            keyword_top_k=config.keyword_top_k,
            k=config.rrf_k,
            filters=filters,
            preprocessor=self._preprocessor,
            vector_weight=config.vector_weight,
            keyword_weight=config.keyword_weight,
            max_chunks_per_article=config.max_chunks_per_article,
        )

        if self._reranker:
            results = self._reranker.rerank(query_text, results, top_k=top_k)

        return results

    def _apply_filters(self, results: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            r for r in results
            if all(r.get(k) == v for k, v in filters.items())
        ]

    def _extract_results_from_response(self, response) -> List[Dict[str, Any]]:
        results = []
        if hasattr(response, 'source_nodes'):
            for node in response.source_nodes:
                results.append({
                    'law_name': node.node.metadata.get('law_name', '未知'),
                    'article_number': node.node.metadata.get('article_number', '未知'),
                    'category': node.node.metadata.get('category', ''),
                    'content': node.node.text,
                    'source_file': node.node.metadata.get('source_file', ''),
                    'hierarchy_path': node.node.metadata.get('hierarchy_path', ''),
                    'score': node.score if hasattr(node, 'score') else None
                })
        return results

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
