#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 适配器
将 BaseLLMClient 接口适配到 LlamaIndex
"""
import asyncio
import requests  # type: ignore[import-untyped]
from typing import List, Optional

from llama_index.core.llms import LLM, CompletionResponse, ChatResponse, ChatMessage, LLMMetadata
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.callbacks import CallbackManager

# 模型上下文窗口和输出限制
_MODEL_LIMITS = {
    'glm-4-flash': {'context': 128000, 'output': 8192},
    'glm-4-plus': {'context': 128000, 'output': 8192},
    'glm-z1-air': {'context': 128000, 'output': 8192},
    'nomic-embed-text': {'context': 8192, 'output': 512},
    'embedding-3': {'context': 8192, 'output': 2048},
    'jinaai/jina-embeddings-v5-text-small': {'context': 8192, 'output': 1024},
}


class ClientLLMAdapter(LLM):
    """LLM 客户端适配器"""

    def __init__(self, client):
        super().__init__(
            callback_manager=CallbackManager(),
        )
        self._client = client

    @property
    def metadata(self) -> LLMMetadata:
        limits = _MODEL_LIMITS.get(
            self._client.model,
            {'context': 8192, 'output': 4096}
        )
        return LLMMetadata(
            context_window=limits['context'],
            num_output=limits['output'],
            model_name=self._client.model,
        )

    def complete(self, prompt: str, **kwargs) -> CompletionResponse:  # type: ignore[override]
        response = self._client.generate(str(prompt), **kwargs)
        return CompletionResponse(text=response)

    async def acomplete(self, prompt: str, **kwargs) -> CompletionResponse:  # type: ignore[override]
        response = await asyncio.to_thread(
            self._client.generate, str(prompt), **kwargs
        )
        return CompletionResponse(text=response)

    def stream_complete(self, prompt: str, **kwargs):  # type: ignore[override]
        async def _stream():
            response = await asyncio.to_thread(
                self._client.generate, str(prompt), **kwargs
            )
            yield CompletionResponse(text=response)
        return _stream()

    async def astream_complete(self, prompt: str, **kwargs):  # type: ignore[override]
        response = await asyncio.to_thread(
            self._client.generate, str(prompt), **kwargs
        )
        yield CompletionResponse(text=response)

    def chat(self, messages: list, **kwargs) -> ChatResponse:  # type: ignore[override]
        if not messages:
            return ChatResponse(message=ChatMessage(role='assistant', content=''))

        formatted_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                formatted_messages.append(msg)
            else:
                formatted_messages.append({"role": "user", "content": str(msg)})

        response = self._client.chat(formatted_messages, **kwargs)
        return ChatResponse(message=ChatMessage(role='assistant', content=response))

    async def achat(self, messages: list, **kwargs) -> ChatResponse:  # type: ignore[override]
        response = await asyncio.to_thread(
            self._client.chat, messages, **kwargs
        )
        return ChatResponse(message=ChatMessage(role='assistant', content=response))

    def stream_chat(self, messages: list, **kwargs):  # type: ignore[override]
        async def _stream():
            response = await asyncio.to_thread(
                self._client.chat, messages, **kwargs
            )
            yield ChatResponse(message=ChatMessage(role='assistant', content=response))
        return _stream()

    async def astream_chat(self, messages: list, **kwargs):  # type: ignore[override]
        response = await asyncio.to_thread(
            self._client.chat, messages, **kwargs
        )
        yield ChatResponse(message=ChatMessage(role='assistant', content=response))


class ZhipuEmbeddingAdapter(BaseEmbedding):
    """智谱 embedding-3 适配器"""

    _api_key: str = PrivateAttr()
    _base_url: str = PrivateAttr()
    _model: str = PrivateAttr()
    _session: requests.Session = PrivateAttr()

    def __init__(
        self,
        api_key: str,
        model: str = "embedding-3",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        embed_batch_size: int = 50,
    ):
        super().__init__(
            model_name=model,
            embed_batch_size=embed_batch_size,
        )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._session = requests.Session()

    def _get_embeddings(
        self, texts: List[str], encoding_type: str = "document"
    ) -> List[List[float]]:
        if not texts:
            return []

        payload = {"model": self._model, "input": texts}
        if encoding_type:
            payload["encoding_type"] = encoding_type

        response = self._session.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()

        embeddings = []
        for item in result.get("data", []):
            embeddings.append(item.get("embedding", []))
        return embeddings

    def _get_embedding(self, text: str) -> List[float]:
        result = self._get_embeddings([text])
        return result[0] if result else []

    def _get_query_embedding(self, query: str) -> List[float]:
        result = self._get_embeddings([query], encoding_type="query")
        return result[0] if result else []

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._get_embedding(text)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._get_embeddings(texts)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await asyncio.to_thread(self._get_query_embedding, query)

    def get_text_embedding(self, text: str) -> List[float]:
        return self._get_embedding(text)

    def close(self):
        if hasattr(self, '_session') and self._session:
            self._session.close()
            self._session = None

    def __del__(self):
        self.close()

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._get_embeddings(texts)

    async def aget_text_embedding(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.get_text_embedding, text)

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self.get_text_embeddings, texts)

    @property  # type: ignore[misc]
    def model_name(self) -> str:  # type: ignore[override]
        return self._model


class JinaEmbeddingAdapter(BaseEmbedding):
    """Jina v5 嵌入适配器（通过 Ollama 调用，自动添加 task-specific 前缀）"""

    _PREFIX_QUERY = "search_query: "
    _PREFIX_PASSAGE = "passage: "

    def __init__(
        self,
        model_name: str = "jinaai/jina-embeddings-v5-text-small",
        base_url: str = "http://localhost:11434",
        embed_batch_size: int = 50,
    ):
        from llama_index.embeddings.ollama import OllamaEmbedding
        super().__init__(
            model_name=model_name,
            embed_batch_size=embed_batch_size,
        )
        self._ollama_embed = OllamaEmbedding(
            model_name=model_name,
            base_url=base_url,
            embed_batch_size=embed_batch_size,
        )

    def _get_query_embedding(self, query: str) -> List[float]:
        prefixed = self._PREFIX_QUERY + query
        return self._ollama_embed.get_text_embedding(prefixed)

    def _get_text_embedding(self, text: str) -> List[float]:
        prefixed = self._PREFIX_PASSAGE + text
        return self._ollama_embed.get_text_embedding(prefixed)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        prefixed = [self._PREFIX_PASSAGE + t for t in texts]
        return self._ollama_embed._get_text_embeddings(prefixed)  # type: ignore[attr-defined]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await asyncio.to_thread(self._get_query_embedding, query)

    async def aget_text_embedding(self, text: str) -> List[float]:
        return await asyncio.to_thread(self.get_text_embedding, text)

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)


def _create_embedding_model(config: dict):
    """创建嵌入模型适配器（内部工厂函数，通过 LLMClientFactory.create_embed_model() 调用）"""
    from llama_index.embeddings.ollama import OllamaEmbedding

    provider = config.get('provider', 'ollama')

    if provider == 'zhipu':
        return ZhipuEmbeddingAdapter(
            api_key=config['api_key'],
            model=config.get('model', 'embedding-3'),
            base_url=config.get('base_url', 'https://open.bigmodel.cn/api/paas/v4'),
            embed_batch_size=config.get('embed_batch_size', 50),
        )
    elif provider == 'ollama':
        model = config.get('model', 'nomic-embed-text')
        if 'jina' in model:
            return JinaEmbeddingAdapter(
                model_name=model,
                base_url=config.get('host', 'http://localhost:11434'),
                embed_batch_size=config.get('embed_batch_size', 50),
            )
        return OllamaEmbedding(
            model_name=model,
            base_url=config.get('host', 'http://localhost:11434'),
            embed_batch_size=config.get('embed_batch_size', 50),
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")
