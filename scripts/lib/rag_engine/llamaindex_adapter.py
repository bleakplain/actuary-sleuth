#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LlamaIndex 适配器
将 BaseLLMClient 接口适配到 LlamaIndex
"""
import asyncio
import requests  # type: ignore[import-untyped]
from typing import Any, Dict, List, Optional

from llama_index.core.llms import LLM, CompletionResponse, ChatResponse, ChatMessage, LLMMetadata
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.callbacks import CallbackManager

from lib.common.cache import get_cache_manager, SCOPE_EMBEDDING

# 模型上下文窗口和输出限制
_MODEL_LIMITS = {
    'glm-4-flash': {'context': 128000, 'output': 8192},
    'glm-4-plus': {'context': 128000, 'output': 8192},
    'glm-z1-air': {'context': 128000, 'output': 8192},
    'embedding-3': {'context': 8192, 'output': 2048},
    'qllama/bge-m3:q4_k_m': {'context': 8192, 'output': 1024},
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

        cache = get_cache_manager()
        cached_results: Dict[int, List[float]] = {}
        uncached_texts: List[str] = []
        uncached_indices: List[int] = []

        if cache:
            for i, text in enumerate(texts):
                cache_key = f"{self._model}:{encoding_type}:{text}"
                cached = cache.get(SCOPE_EMBEDDING, cache_key)
                if cached is not None:
                    cached_results[i] = cached
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)

            if not uncached_texts:
                return [cached_results[i] for i in range(len(texts))]
        else:
            uncached_texts = texts
            uncached_indices = list(range(len(texts)))

        payload = {"model": self._model, "input": uncached_texts}
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
        new_embeddings = [item.get("embedding", []) for item in response.json().get("data", [])]

        if cache:
            for text, emb in zip(uncached_texts, new_embeddings):
                cache_key = f"{self._model}:{encoding_type}:{text}"
                cache.set(SCOPE_EMBEDDING, cache_key, emb)

        if cached_results:
            all_embeddings: List[List[float]] = [[] for _ in range(len(texts))]
            for i, emb in cached_results.items():
                all_embeddings[i] = emb
            for idx, emb in zip(uncached_indices, new_embeddings):
                all_embeddings[idx] = emb
            return all_embeddings

        return new_embeddings

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


def _create_embedding_model(cfg):
    provider = cfg.provider
    model = cfg.model
    base_url = cfg.base_url
    api_key = cfg.api_key

    from llama_index.embeddings.ollama import OllamaEmbedding

    if provider == 'zhipu':
        return ZhipuEmbeddingAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
            embed_batch_size=50,
        )
    elif provider == 'ollama':
        return OllamaEmbedding(
            model_name=model,
            base_url=base_url,
            embed_batch_size=50,
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")


def get_embedding_model(config: Dict[str, Any]):
    """Create embedding model from config dict.

    Args:
        config: Dict with keys 'provider', 'model', 'host'/'base_url'

    Returns:
        Embedding model instance
    """
    from llama_index.embeddings.ollama import OllamaEmbedding

    provider = config.get('provider', 'ollama')
    model = config.get('model', '')
    base_url = config.get('host') or config.get('base_url', 'http://localhost:11434')

    return OllamaEmbedding(
        model_name=model,
        base_url=base_url,
        embed_batch_size=50,
    )
