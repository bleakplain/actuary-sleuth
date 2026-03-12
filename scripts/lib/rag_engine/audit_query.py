#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计查询模块
用于保险产品审计时检索相关法规条款
"""
from typing import List, Dict, Any, Optional

from llama_index.core import Settings
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding

from .config import RAGConfig
from .index_manager import VectorIndexManager


class AuditQueryEngine:
    """审计法规查询引擎

    用于保险产品审计时，根据产品条款内容检索相关的监管法规。
    提供精确的法规引用和合规性分析依据。
    """

    def __init__(self, config: RAGConfig = None):
        """
        初始化审计查询引擎

        Args:
            config: RAG 配置
        """
        self.config = config or RAGConfig()
        self.index_manager = VectorIndexManager(self.config)
        self.query_engine = None

        # 配置 LLM
        self._setup_llm()

    def _setup_llm(self):
        """配置 LLM 设置"""
        Settings.llm = Ollama(
            model=self.config.llm_model,
            base_url=self.config.ollama_host,
            request_timeout=360.0,
            context_window=8000,
        )
        Settings.embed_model = OllamaEmbedding(
            model_name=self.config.embedding_model,
            base_url=self.config.ollama_host,
        )

    def initialize(self, force_rebuild: bool = False) -> bool:
        """
        初始化查询引擎

        Args:
            force_rebuild: 是否强制重建索引

        Returns:
            bool: 成功返回 True
        """
        # 尝试加载已有索引
        index = self.index_manager.create_index(
            documents=None,
            force_rebuild=force_rebuild
        )

        if index is None:
            print("索引初始化失败")
            return False

        self.query_engine = self.index_manager.create_query_engine()
        return self.query_engine is not None

    def search_regulations(
        self,
        query_text: str,
        top_k: int = None
    ) -> List[Dict[str, Any]]:
        """
        搜索相关法规条款

        Args:
            query_text: 查询文本（如产品条款内容）
            top_k: 返回结果数量

        Returns:
            List[Dict]: 相关法规列表
        """
        if self.query_engine is None:
            if not self.initialize():
                return []

        try:
            top_k = top_k or self.config.top_k_results
            response = self.query_engine.query(query_text)

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

        except Exception as e:
            print(f"搜索法规时出错: {e}")
            return []

    def check_compliance(
        self,
        product_clause: str,
        regulation_type: str = None
    ) -> Dict[str, Any]:
        """
        检查产品条款合规性

        Args:
            product_clause: 产品条款内容
            regulation_type: 法规类型（可选，用于过滤）

        Returns:
            Dict: 合规性检查结果
        """
        # 构建查询
        query = f"请分析以下保险条款是否符合相关监管规定：\n\n{product_clause}"

        # 搜索相关法规
        regulations = self.search_regulations(query, top_k=5)

        # TODO: 使用 LLM 进行合规性分析
        # 这里可以扩展为使用 LLM 对比条款和法规，给出合规性建议

        return {
            'product_clause': product_clause,
            'relevant_regulations': regulations,
            'compliance_analysis': '待实现: 使用 LLM 进行合规性分析'
        }

    def get_regulation_by_article(
        self,
        law_name: str,
        article_number: str
    ) -> Optional[Dict[str, Any]]:
        """
        根据法律名称和条款号获取具体法规

        Args:
            law_name: 法律/法规名称
            article_number: 条款号（如"第十六条"）

        Returns:
            Optional[Dict]: 法规内容
        """
        # 构建精确查询
        query = f"{law_name} {article_number}"

        results = self.search_regulations(query, top_k=3)

        # 查找最匹配的结果
        for result in results:
            if (result['law_name'] == law_name and
                result['article_number'] == article_number):
                return result

        return results[0] if results else None
