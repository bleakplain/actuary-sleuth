"""LlamaIndex → LangChain Embedding 接口适配。"""
from langchain_core.embeddings import Embeddings
from lib.llm.factory import LLMClientFactory


class EmbeddingBridge(Embeddings):
    """将 LlamaIndex Embedding 桥接为 LangChain Embeddings 接口。

    Embedding 模型由 settings.json 的 llm.embed 配置决定，通过
    LLMClientFactory.create_embed_model() 创建，不引入任何新配置项。
    """

    def __init__(self):
        self._adapter = LLMClientFactory.create_embed_model()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._adapter._get_text_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._adapter._get_query_embedding(text)
