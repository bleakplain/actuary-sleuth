import time

import pytest
import requests

import lib.llm.metrics as metrics_module
from lib.llm.metrics import LLMRateLimitError, _retry_with_backoff


def test_explicit_single_attempt_succeeds_without_forwarding_control_kwarg() -> None:
    calls = []

    @_retry_with_backoff(max_retries=3, base_delay=0)
    def succeeds(*, payload: str) -> str:
        calls.append(payload)
        return payload

    assert succeeds(payload="ok", _max_attempts=1) == "ok"
    assert calls == ["ok"]


@pytest.mark.parametrize(
    "provider_error",
    [
        LLMRateLimitError("429 rate limited"),
        requests.exceptions.Timeout("provider timeout"),
    ],
)
def test_explicit_single_attempt_does_not_retry_transport_failure(
    provider_error: requests.exceptions.RequestException,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = []
    monkeypatch.setattr(
        time,
        "sleep",
        lambda _: pytest.fail("单次模式不得进入退避等待"),
    )

    @_retry_with_backoff(max_retries=3, base_delay=1)
    def fails() -> None:
        calls.append("called")
        raise provider_error

    with pytest.raises(type(provider_error)):
        fails(_max_attempts=1)

    assert calls == ["called"]
    assert "no retry attempts remain" in caplog.text
    assert "retrying in" not in caplog.text


def test_default_attempt_limit_keeps_decorator_retry_behavior() -> None:
    calls = []

    @_retry_with_backoff(max_retries=3, base_delay=0)
    def succeeds_on_third_attempt() -> str:
        calls.append("called")
        if len(calls) < 3:
            raise requests.exceptions.Timeout("provider timeout")
        return "ok"

    assert succeeds_on_third_attempt() == "ok"
    assert calls == ["called", "called", "called"]


def test_instance_attempt_limit_disables_hidden_retry() -> None:
    class ControlledClient:
        _retry_attempt_limit = 1

        def __init__(self) -> None:
            self.calls = 0

        @_retry_with_backoff(max_retries=3, base_delay=0)
        def call(self) -> None:
            self.calls += 1
            raise requests.exceptions.Timeout("provider timeout")

    client = ControlledClient()
    with pytest.raises(requests.exceptions.Timeout):
        client.call()

    assert client.calls == 1


@pytest.mark.parametrize("invalid_limit", [0, -1, 4, True, 1.5, None, "1"])
def test_invalid_attempt_limit_fails_before_business_call(
    invalid_limit: object,
) -> None:
    calls = []

    @_retry_with_backoff(max_retries=3, base_delay=0)
    def should_not_run() -> None:
        calls.append("called")

    with pytest.raises(ValueError, match="_max_attempts"):
        should_not_run(_max_attempts=invalid_limit)

    assert calls == []


def test_retry_deadline_stops_before_starting_an_attempt() -> None:
    calls = []

    @_retry_with_backoff(max_retries=3, base_delay=1)
    def always_fails() -> None:
        calls.append("called")
        raise requests.exceptions.Timeout("provider timeout")

    with pytest.raises(requests.exceptions.Timeout, match="retry deadline"):
        always_fails(_retry_deadline=time.monotonic() - 1)

    assert calls == []


def test_each_retry_clamps_request_timeout_to_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_timeouts = []
    clock_values = iter((100.0, 100.0, 104.0))
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(metrics_module.time, "sleep", lambda _seconds: None)

    @_retry_with_backoff(max_retries=2, base_delay=0)
    def succeeds_on_retry(*, timeout: float) -> str:
        observed_timeouts.append(timeout)
        if len(observed_timeouts) == 1:
            raise requests.exceptions.Timeout("provider timeout")
        return "ok"

    result = succeeds_on_retry(timeout=20.0, _retry_deadline=110.0)

    assert result == "ok"
    assert observed_timeouts == [10.0, 6.0]
