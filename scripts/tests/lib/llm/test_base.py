from typing import Dict, List

import pytest

from lib.llm.base import BaseLLMClient


class _Client(BaseLLMClient):
    def _do_generate(self, prompt: str, **kwargs) -> str:
        return prompt

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return messages[-1]["content"]

    def health_check(self) -> bool:
        return True


def test_chat_rejects_combined_messages_over_prompt_budget() -> None:
    client = _Client("test")
    client.MAX_PROMPT_LENGTH = 10
    with pytest.raises(ValueError, match="消息内容过长"):
        client.chat([
            {"role": "system", "content": "123456"},
            {"role": "user", "content": "78901"},
        ])


def test_chat_accepts_messages_within_prompt_budget() -> None:
    client = _Client("test")
    client.MAX_PROMPT_LENGTH = 10
    assert client.chat([{"role": "user", "content": "1234567890"}]) == "1234567890"
