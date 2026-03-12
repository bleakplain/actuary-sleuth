#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户问答模块
提供面向用户的法规智能问答功能
"""
from typing import List, Dict, Any

from llama_index.core import Settings
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding

from .config import RAGConfig
from .index_manager import VectorIndexManager


class UserQAEngine:
    """用户问答引擎

    面向用户的法规智能问答系统，支持：
    - 自然语言问答
    - 多轮对话
    - 法规解释
    - 相关案例引用
    """

    def __init__(self, config: RAGConfig = None):
        """
        初始化问答引擎

        Args:
            config: RAG 配置
        """
        self.config = config or RAGConfig()
        self.index_manager = VectorIndexManager(self.config)
        self.query_engine = None
        self.chat_history = []

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
        初始化问答引擎

        Args:
            force_rebuild: 是否强制重建索引

        Returns:
            bool: 成功返回 True
        """
        index = self.index_manager.create_index(
            documents=None,
            force_rebuild=force_rebuild
        )

        if index is None:
            print("索引初始化失败")
            return False

        self.query_engine = self.index_manager.create_query_engine()
        return self.query_engine is not None

    def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        """
        提问并获取回答

        Args:
            question: 问题文本
            include_sources: 是否包含相关法规来源

        Returns:
            Dict: 回答结果
        """
        if self.query_engine is None:
            if not self.initialize():
                return {
                    'answer': '问答引擎初始化失败',
                    'sources': []
                }

        try:
            response = self.query_engine.query(question)

            # 保存到对话历史
            self.chat_history.append({
                'role': 'user',
                'content': question
            })
            self.chat_history.append({
                'role': 'assistant',
                'content': str(response)
            })

            result = {
                'answer': str(response),
                'sources': []
            }

            # 提取源信息
            if include_sources and hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    text_preview = node.node.text
                    if len(text_preview) > 200:
                        text_preview = text_preview[:200] + '...'

                    result['sources'].append({
                        'law_name': node.node.metadata.get('law_name', '未知'),
                        'article_number': node.node.metadata.get('article_number', '未知'),
                        'content': text_preview,
                        'score': node.score if hasattr(node, 'score') else None
                    })

            return result

        except Exception as e:
            print(f"问答出错: {e}")
            return {
                'answer': f'问答出错: {str(e)}',
                'sources': []
            }

    async def aask(self, question: str) -> Dict[str, Any]:
        """
        异步提问

        Args:
            question: 问题文本

        Returns:
            Dict: 回答结果
        """
        if self.query_engine is None:
            if not self.initialize():
                return {
                    'answer': '问答引擎初始化失败',
                    'sources': []
                }

        try:
            response = await self.query_engine.aquery(question)

            self.chat_history.append({
                'role': 'user',
                'content': question
            })
            self.chat_history.append({
                'role': 'assistant',
                'content': str(response)
            })

            result = {
                'answer': str(response),
                'sources': []
            }

            if hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    text_preview = node.node.text
                    if len(text_preview) > 200:
                        text_preview = text_preview[:200] + '...'

                    result['sources'].append({
                        'law_name': node.node.metadata.get('law_name', '未知'),
                        'article_number': node.node.metadata.get('article_number', '未知'),
                        'content': text_preview,
                        'score': node.score if hasattr(node, 'score') else None
                    })

            return result

        except Exception as e:
            print(f"异步问答出错: {e}")
            return {
                'answer': f'问答出错: {str(e)}',
                'sources': []
            }

    def chat(self, message: str) -> str:
        """
        聊天模式（简化接口）

        Args:
            message: 用户消息

        Returns:
            str: 回复文本
        """
        result = self.ask(message)
        return result['answer']

    def clear_history(self):
        """清空对话历史"""
        self.chat_history = []

    def get_history(self) -> List[Dict[str, str]]:
        """
        获取对话历史

        Returns:
            List[Dict]: 对话历史
        """
        return self.chat_history.copy()
