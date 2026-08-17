from typing import Dict, List

import pytest
import requests  # type: ignore[import-untyped]

from lib.llm.call_budget import (
    CallBudgetController,
    CallBudgetLimits,
    CallTokenBudgetExceededError,
)
from lib.llm.zhipu import ZhipuClient


class _Clock:
    def __init__(self, value: float = 1.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _budget(
    clock: _Clock,
    *,
    max_tokens: int = 10_000,
    deadline: float = 20.0,
) -> CallBudgetController:
    return CallBudgetController(
        CallBudgetLimits(
            deadline=deadline,
            max_total_tokens=max_tokens,
            max_physical_calls=5,
        ),
        clock=clock,
    )


def test_budget_rejects_chat_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    probe = _budget(clock)
    messages = [{"role": "user", "content": "等待期"}]
    required = probe.estimate_prompt_tokens(messages) + 20
    controller = _budget(clock, max_tokens=required - 1)
    client = ZhipuClient("test-key", call_budget=controller)
    calls: List[str] = []
    def provider_call(
        _messages: List[Dict[str, str]],
        **_kwargs: object,
    ) -> str:
        calls.append("provider")
        return "{}"

    monkeypatch.setattr(client, "_do_chat", provider_call)

    with pytest.raises(CallTokenBudgetExceededError):
        client.chat(messages, max_tokens=20, _max_attempts=1)

    assert calls == []
    assert controller.snapshot().physical_calls == 0


def test_successful_chat_settles_provider_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    controller = _budget(clock)
    client = ZhipuClient("test-key", call_budget=controller)

    def provider_call(
        _messages: List[Dict[str, str]],
        **_kwargs: object,
    ) -> str:
        client._record_usage({
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
            }
        })
        return '{"ok": true}'

    monkeypatch.setattr(client, "_do_chat", provider_call)

    assert client.chat(
        [{"role": "user", "content": "test"}],
        max_tokens=100,
        _max_attempts=1,
    ) == '{"ok": true}'
    snapshot = controller.snapshot()
    assert snapshot.consumed_tokens == 15
    assert snapshot.reserved_tokens == 0
    assert snapshot.physical_calls == 1


def test_failed_chat_consumes_reservation_without_hidden_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    controller = _budget(clock)
    client = ZhipuClient("test-key", call_budget=controller)
    calls: List[str] = []

    def provider_call(
        _messages: List[Dict[str, str]],
        **_kwargs: object,
    ) -> str:
        calls.append("provider")
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr(client, "_do_chat", provider_call)

    with pytest.raises(requests.exceptions.Timeout):
        client.chat(
            [{"role": "user", "content": "test"}],
            max_tokens=100,
            _max_attempts=1,
        )

    snapshot = controller.snapshot()
    assert calls == ["provider"]
    assert snapshot.consumed_tokens > 100
    assert snapshot.reserved_tokens == 0
    assert snapshot.physical_calls == 1


def test_incomplete_provider_usage_consumes_full_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    controller = _budget(clock)
    client = ZhipuClient("test-key", call_budget=controller)

    def provider_call(
        _messages: List[Dict[str, str]],
        **_kwargs: object,
    ) -> str:
        client._record_usage({
            "usage": {
                "prompt_tokens": "12",
                "completion_tokens": 3,
                "total_tokens": 15,
            }
        })
        return "{}"

    monkeypatch.setattr(client, "_do_chat", provider_call)
    client.chat(
        [{"role": "user", "content": "test"}],
        max_tokens=100,
        _max_attempts=1,
    )

    snapshot = controller.snapshot()
    assert client.usage_records == ()
    assert snapshot.consumed_tokens > 100
    assert snapshot.reserved_tokens == 0


def test_budget_clamps_provider_timeout_to_run_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(5.0)
    controller = _budget(clock, deadline=8.0)
    client = ZhipuClient("test-key", timeout=120, call_budget=controller)
    captured: Dict[str, object] = {}

    def provider_call(
        _messages: List[Dict[str, str]],
        **kwargs: object,
    ) -> str:
        captured.update(kwargs)
        client._record_usage({
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
            }
        })
        return "{}"

    monkeypatch.setattr(client, "_do_chat", provider_call)

    client.chat(
        [{"role": "user", "content": "test"}],
        max_tokens=20,
        timeout=45,
        _max_attempts=1,
    )

    assert captured["timeout"] == pytest.approx(3.0)


def test_budgeted_client_rejects_streaming_before_provider_io() -> None:
    clock = _Clock()
    client = ZhipuClient("test-key", call_budget=_budget(clock))

    with pytest.raises(RuntimeError, match="不支持流式"):
        client.stream_chat([{"role": "user", "content": "test"}])
