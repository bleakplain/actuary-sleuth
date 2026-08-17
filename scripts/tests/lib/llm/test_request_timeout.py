from unittest.mock import MagicMock

import requests
import pytest

from lib.llm.ollama import OllamaClient
from lib.llm.zhipu import ZhipuClient
from lib.llm.call_budget import (
    CallBudgetSnapshot,
    CallTokenBudgetExceededError,
)
from lib.llm.metrics import LLMRateLimitError, _get_circuit_breaker


def _response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


def test_zhipu_chat_accepts_per_request_timeout() -> None:
    client = ZhipuClient(api_key="test")
    session = MagicMock()
    session.post.return_value = _response(
        {"choices": [{"message": {"content": "{}"}}]},
    )
    client._session = session
    client._do_chat([{"role": "user", "content": "test"}], timeout=17)
    assert session.post.call_args.kwargs["timeout"] == 17


def test_zhipu_chat_forwards_json_response_format() -> None:
    client = ZhipuClient(api_key="test")
    session = MagicMock()
    session.post.return_value = _response(
        {"choices": [{"message": {"content": "{}"}}]},
    )
    client._session = session

    client._do_chat(
        [{"role": "user", "content": "test"}],
        response_format={"type": "json_object"},
    )

    assert session.post.call_args.kwargs["json"]["response_format"] == {
        "type": "json_object",
    }


def test_ollama_chat_accepts_per_request_timeout() -> None:
    client = OllamaClient()
    client._session = MagicMock()
    client._session.post.return_value = _response(
        {"message": {"content": "{}"}},
    )
    client._do_chat([{"role": "user", "content": "test"}], timeout=19)
    assert client._session.post.call_args.kwargs["timeout"] == 19


def test_zhipu_session_disables_transport_level_retries() -> None:
    client = ZhipuClient(api_key="test")

    session = client._get_session()
    adapter = session.get_adapter("https://")

    assert isinstance(adapter, requests.adapters.HTTPAdapter)
    assert adapter.max_retries.total == 0
    client.close()


def test_zhipu_records_provider_usage() -> None:
    client = ZhipuClient(api_key="test")
    session = MagicMock()
    session.post.return_value = _response({
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    })
    client._session = session

    client._do_chat([{"role": "user", "content": "test"}])

    assert client.usage_records[0].prompt_tokens == 12
    assert client.usage_records[0].completion_tokens == 3
    assert client.usage_records[0].total_tokens == 15


def test_zhipu_raises_typed_rate_limit_error() -> None:
    client = ZhipuClient(api_key="test")
    response = MagicMock(status_code=429, text="busy")
    client._session = MagicMock()
    client._session.post.return_value = response

    with pytest.raises(LLMRateLimitError):
        client._do_chat([{"role": "user", "content": "test"}])


def test_rate_limit_does_not_open_circuit_breaker() -> None:
    key = "test-rate-limit-isolation"
    breaker = _get_circuit_breaker(key)
    for _ in range(5):
        try:
            from lib.llm.metrics import _with_circuit_breaker

            @_with_circuit_breaker(key)
            def limited() -> None:
                raise LLMRateLimitError("429")

            limited()
        except LLMRateLimitError:
            pass

    assert breaker.can_attempt()


def test_local_budget_rejection_does_not_open_provider_circuit() -> None:
    from lib.llm.metrics import _with_circuit_breaker

    key = "test-budget-isolation"
    breaker = _get_circuit_breaker(key)
    snapshot = CallBudgetSnapshot(
        deadline=10,
        observed_at=1,
        max_total_tokens=1,
        consumed_tokens=1,
        reserved_tokens=0,
        remaining_tokens=0,
        max_physical_calls=1,
        physical_calls=0,
        active_leases=0,
    )

    @_with_circuit_breaker(key)
    def rejected() -> None:
        raise CallTokenBudgetExceededError(snapshot, 2)

    for _ in range(5):
        with pytest.raises(CallTokenBudgetExceededError):
            rejected()

    assert breaker.can_attempt()
