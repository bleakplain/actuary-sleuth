#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LangChain 适配器，将 BaseLLMClient 适配到 LangChain 接口。

仅依赖 langchain_core，不依赖 langchain_openai。
复用 lib/llm 的重试、熔断、metrics 等中间件能力。
"""
import asyncio
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ChatMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

from .base import BaseLLMClient


def _message_to_dict(msg: BaseMessage) -> Dict[str, str]:
    if isinstance(msg, ChatMessage):
        return {"role": msg.role, "content": msg.content}
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content}
    if isinstance(msg, AIMessage):
        return {"role": "assistant", "content": msg.content}
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    raise ValueError(f"Unsupported message type: {type(msg).__name__}")


class ChatAdapter(BaseChatModel):
    """LangChain BaseChatModel 适配器，委托给 BaseLLMClient.chat()"""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    client: Any = Field(default=None)

    def __init__(self, client: BaseLLMClient, **kwargs: Any):
        super().__init__(client=client, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "lib-llm-adapter"

    @property
    def model_name(self) -> str:
        return self.client.model

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        dict_messages = [_message_to_dict(m) for m in messages]
        response_text = self.client.chat(dict_messages, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=response_text))])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        dict_messages = [_message_to_dict(m) for m in messages]
        response_text = await asyncio.to_thread(self.client.chat, dict_messages, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=response_text))])


class EmbeddingAdapter(Embeddings):
    """将 BaseEmbedding 适配为 LangChain Embeddings"""

    def __init__(self, model: 'BaseEmbedding'):
        self.model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.get_text_embeddings(texts)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.model.get_text_embeddings, texts)

    def embed_query(self, text: str) -> List[float]:
        return self.model.get_text_embedding(text)

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.model.get_text_embedding, text)
