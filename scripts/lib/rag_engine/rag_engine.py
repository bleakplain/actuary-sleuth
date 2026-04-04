#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 查询引擎（线程安全版本）
统一的检索增强生成引擎，通过策略模式支持不同使用场景
"""
import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from llama_index.core import Settings
except ImportError:
    Settings = None  # type: ignore[assignment]

from .config import RAGConfig
from .index_manager import VectorIndexManager
from .llamaindex_adapter import ClientLLMAdapter
from .retrieval import hybrid_search
from .bm25_index import BM25Index
from .reranker_base import BaseReranker
from .llm_reranker import LLMReranker, RerankConfig
from .query_preprocessor import QueryPreprocessor
from .exceptions import EngineInitializationError, RetrievalError
from .attribution import parse_citations, AttributionResult
from ._gguf_cli import GGUFReranker as GGUFCliReranker
from .gguf_reranker_adapter import GGUFReranker
from .evaluator import GenerationEvaluator
from lib.llm import BaseLLMClient, LLMClientFactory
from lib.llm.trace import trace_span

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是一位保险法规专家。你必须**仅依据**用户提供的编号法规条款回答问题，不得使用任何外部知识。

## 回答规则
1. 只能使用法规条款中**明确提及**的信息，不得补充、推断或混合自身知识
2. 每个事实性陈述（包括数字、金额、期限、比例、条款号、法规名称）必须在句末标注 [来源X]
3. 引用时必须标注来源编号，编号对应上方法规条款的序号
4. 对于关键数字（金额、天数、年限、比例），必须与原文**完全一致**，不得近似或四舍五入
5. 如果不同条款存在矛盾，优先引用编号靠前的条款，并说明矛盾之处
6. 如果法规条款中没有足够信息回答问题，直接说明"提供的法规条款中未找到相关信息"，不得猜测或编造
7. 如果法规条款涉及多个不同法规文件，分别针对每个法规文件回答，明确标注信息来源
8. 回答简洁专业，面向保险从业人员"""

_USER_PROMPT_TEMPLATE = """## 法规条款

{context}

## 用户问题

{question}

## 重要提醒
请仅依据上方编号的法规条款回答。每个事实性陈述必须标注 [来源X]。如果条款中没有相关信息，请说明"提供的法规条款中未找到相关信息"。"""

_SENTENCE_BOUNDARY = re.compile(r'(?<=[。；！？\n])\s*')


def _truncate_at_sentence_boundary(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_boundary = 0
    for match in _SENTENCE_BOUNDARY.finditer(truncated):
        last_boundary = match.end()

    if last_boundary > max_chars * 0.5:
        return truncated[:last_boundary].rstrip() + '\n[注：此条款内容已被截断]'
    return truncated + '……'


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
                try:
                    self._global_backup['llm'] = Settings._llm
                    self._global_backup['embed_model'] = Settings._embed_model
                except AttributeError:
                    pass

        self._local.llm = llm
        self._local.embed_model = embed_model

    def apply(self) -> None:
        """应用线程配置到全局 Settings（线程安全）"""
        with self._lock:
            if not hasattr(self._local, 'llm'):
                return
            Settings.llm = self._local.llm
            Settings.embed_model = self._local.embed_model

    def reset(self) -> None:
        """重置为全局默认配置"""
        with self._lock:
            if self._global_backup:
                Settings.llm = self._global_backup['llm']
                Settings.embed_model = self._global_backup['embed_model']


_thread_settings = ThreadLocalSettings()


class RAGEngine:
    """统一的 RAG 查询引擎"""

    def __init__(
        self,
        config: Optional[RAGConfig] = None,
        llm_client: Optional[BaseLLMClient] = None
    ):
        self.config = config or RAGConfig()
        self.index_manager = VectorIndexManager(self.config)
        self.query_engine = None

        self._llm = None
        self._embed_model = None
        self._llm_client = llm_client
        self._preprocessor: Optional[QueryPreprocessor] = None
        self._reranker: Optional[BaseReranker] = None
        self._bm25_index: Optional[BM25Index] = None
        self._initialized = False
        self._init_lock = threading.Lock()

        self._setup_llm()

    def _setup_llm(self):
        if not self._llm_client:
            self._llm_client = LLMClientFactory.create_qa_llm()

        self._llm = ClientLLMAdapter(self._llm_client)
        self._embed_model = LLMClientFactory.create_embed_model()

        self._reranker = self._create_reranker()
        self._preprocessor = QueryPreprocessor(llm_client=self._llm_client)

    def _create_reranker(self) -> Optional[BaseReranker]:
        config = self.config.hybrid_config
        assert config is not None

        if not config.enable_rerank or config.reranker_type == "none":
            return None

        rerank_config = RerankConfig(
            enabled=True,
            top_k=config.rerank_top_k,
        )

        if config.reranker_type == "llm":
            return LLMReranker(self._llm_client, rerank_config)

        if config.reranker_type == "gguf":
            try:
                gguf = GGUFCliReranker()
                return GGUFReranker(gguf)
            except FileNotFoundError as e:
                logger.warning(f"GGUF reranker 不可用，回退到 LLM reranker: {e}")
                return LLMReranker(self._llm_client, rerank_config)

        return None

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

                index = self.index_manager.load_index()

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
        with self._init_lock:
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
        assert self.config.vector_db_path is not None
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
                return {
                    'answer': '未找到相关法规条款，请尝试换个描述方式。',
                    'sources': [],
                    'citations': [],
                    'unverified_claims': [],
                }

            user_prompt, included_count = self._build_qa_prompt(self.config, question, search_results)
            if not self._llm_client:
                raise RetrievalError("LLM 客户端未初始化")

            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            with trace_span("llm_generate", "llm", model=getattr(self._llm_client, 'model', '')) as span:
                span.input = {
                    "question": question,
                    "context_chunk_count": len(search_results),
                    "system_prompt": _SYSTEM_PROMPT,
                    "user_prompt": user_prompt,
                }
                answer = self._llm_client.chat(messages)
                answer_str = str(answer)
                span.output = {"answer_length": len(answer_str), "answer": answer_str}

            included_sources = search_results[:included_count]
            attribution = parse_citations(answer_str, included_sources) if include_sources else AttributionResult()

            result: Dict[str, Any] = {
                'answer': answer_str,
                'sources': search_results if include_sources else [],
                'citations': [
                    {
                        'source_idx': c.source_idx,
                        'law_name': c.law_name,
                        'article_number': c.article_number,
                        'content': c.content,
                    }
                    for c in attribution.citations
                ],
                'unverified_claims': attribution.unverified_claims,
                'content_mismatches': attribution.content_mismatches,
            }

            if self.config.enable_faithfulness:
                included_contexts = [r.get('content', '') for r in included_sources]
                result['faithfulness_score'] = self._compute_faithfulness(included_contexts, answer_str)

            return result

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

    @staticmethod
    def _build_qa_prompt(config: 'RAGConfig', question: str, search_results: List[Dict[str, Any]]) -> tuple[str, int]:
        context_parts: List[str] = []
        total_chars = 0
        max_chars = config.max_context_chars

        for i, result in enumerate(search_results, 1):
            law_name = result.get('law_name', '未知法规')
            article = result.get('article_number', '')
            content = result.get('content', '')
            header = f"{i}. 【{law_name}】{article}\n"
            full_part = header + content

            if total_chars + len(full_part) > max_chars:
                remaining = max_chars - total_chars - 50
                if remaining > 100:
                    truncated_content = _truncate_at_sentence_boundary(content, remaining)
                    context_parts.append(header + truncated_content)
                break

            context_parts.append(full_part)
            total_chars += len(full_part)

        context = "\n\n".join(context_parts)
        user_prompt = _USER_PROMPT_TEMPLATE.format(context=context, question=question)
        return user_prompt, len(context_parts)

    @staticmethod
    def _compute_faithfulness(contexts: List[str], answer: str) -> float:
        if not contexts or not answer:
            return 0.0
        return GenerationEvaluator._compute_faithfulness(contexts, answer)

    def search(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        use_hybrid: bool = True,
        filters: Optional[Dict[str, Any]] = None
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
                if self.query_engine is None:
                    raise EngineInitializationError("Query engine not initialized")
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
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """混合检索（向量 + BM25 关键词 + RRF 融合 + Rerank）"""
        config = self.config.hybrid_config
        assert config is not None
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

        if results and config.min_rrf_score > 0:
            max_score = results[0].get('score', 0)
            if max_score < config.min_rrf_score:
                logger.debug(f"最高 RRF 分数 {max_score:.4f} 低于阈值 {config.min_rrf_score}")
                return []

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
        law_name: Optional[str] = None,
        category: Optional[str] = None,
        hierarchy_level: Optional[str] = None,
        issuing_authority: Optional[str] = None
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

def create_qa_engine(config: Optional[RAGConfig] = None) -> RAGEngine:
    """
    创建问答引擎

    使用快速响应模型 (glm-4-flash)，适合面向终端用户的问答场景。

    Args:
        config: RAG 配置，可选

    Returns:
        RAGEngine: 配置为问答模式的引擎实例
    """
    return RAGEngine(config or RAGConfig(), LLMClientFactory.create_qa_llm())
