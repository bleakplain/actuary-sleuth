#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LangChain 适配器单元测试"""
from unittest.mock import MagicMock

import pytest

from langchain_core.messages import AIMessage, BaseMessage, ChatMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult

from lib.llm.langchain_adapter import ChatAdapter, EmbeddingAdapter, _message_to_dict


class MockLLMClient:
    """Mock BaseLLMClient"""

    def __init__(self, model: str = "glm-4-flash"):
        self.model = model

    def chat(self, messages, **kwargs):
        return f"response to: {messages[-1]['content']}"


class MockEmbeddingClient:
    """Mock BaseLLMClient with embed support"""

    def __init__(self, model: str = "embedding-3"):
        self.model = model

    def embed(self, texts, **kwargs):
        return [[float(i) for i in range(3)] for _ in texts]


@pytest.fixture
def mock_chat_client():
    return MockLLMClient()


@pytest.fixture
def mock_embed_client():
    return MockEmbeddingClient()


class TestMessageConversion:

    def test_human_message(self):
        result = _message_to_dict(HumanMessage(content="hello"))
        assert result == {"role": "user", "content": "hello"}

    def test_ai_message(self):
        result = _message_to_dict(AIMessage(content="hi"))
        assert result == {"role": "assistant", "content": "hi"}

    def test_system_message(self):
        result = _message_to_dict(SystemMessage(content="you are helpful"))
        assert result == {"role": "system", "content": "you are helpful"}

    def test_chat_message(self):
        result = _message_to_dict(ChatMessage(role="user", content="hello"))
        assert result == {"role": "user", "content": "hello"}

    def test_unsupported_type_raises(self):
        msg = MagicMock(spec=BaseMessage)
        msg.__class__.__name__ = "UnknownMessage"
        with pytest.raises(ValueError, match="Unsupported message type"):
            _message_to_dict(msg)


class TestChatAdapter:

    def test_llm_type(self, mock_chat_client):
        adapter = ChatAdapter(client=mock_chat_client)
        assert adapter._llm_type == "lib-llm-adapter"

    def test_model_name(self, mock_chat_client):
        adapter = ChatAdapter(client=mock_chat_client)
        assert adapter.model_name == "glm-4-flash"

    def test_generate_single_message(self, mock_chat_client):
        adapter = ChatAdapter(client=mock_chat_client)
        result = adapter._generate([HumanMessage(content="test")])
        assert isinstance(result, ChatResult)
        assert len(result.generations) == 1
        assert isinstance(result.generations[0].message, AIMessage)
        assert "test" in result.generations[0].message.content

    def test_generate_multi_turn(self, mock_chat_client):
        adapter = ChatAdapter(client=mock_chat_client)
        messages = [
            SystemMessage(content="be helpful"),
            HumanMessage(content="hi"),
        ]
        result = adapter._generate(messages)
        assert isinstance(result.generations[0].message, AIMessage)

    def test_generate_delegates_to_chat(self, mock_chat_client):
        mock_chat_client.chat = MagicMock(return_value="response")
        adapter = ChatAdapter(client=mock_chat_client)
        adapter._generate([HumanMessage(content="query")])
        mock_chat_client.chat.assert_called_once()

    def test_generate_preserves_kwargs(self):
        client = MockLLMClient()
        client.chat = MagicMock(return_value="response")
        adapter = ChatAdapter(client=client)
        adapter._generate([HumanMessage(content="test")], temperature=0.5)
        client.chat.assert_called_once()
        call_kwargs = client.chat.call_args[1]
        assert call_kwargs.get("temperature") == 0.5


class TestEmbeddingAdapter:

    def test_embed_documents(self, mock_embed_client):
        adapter = EmbeddingAdapter(client=mock_embed_client)
        result = adapter.embed_documents(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.0, 1.0, 2.0]

    def test_embed_query(self, mock_embed_client):
        adapter = EmbeddingAdapter(client=mock_embed_client)
        result = adapter.embed_query("hello")
        assert result == [0.0, 1.0, 2.0]

    def test_embed_empty_list(self, mock_embed_client):
        adapter = EmbeddingAdapter(client=mock_embed_client)
        result = adapter.embed_documents([])
        assert result == []

    def test_embed_single_text(self, mock_embed_client):
        adapter = EmbeddingAdapter(client=mock_embed_client)
        result = adapter.embed_documents(["only one"])
        assert len(result) == 1
