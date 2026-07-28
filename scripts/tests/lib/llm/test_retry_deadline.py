import time

import pytest
import requests

from lib.llm.metrics import _retry_with_backoff


def test_retry_deadline_stops_before_starting_an_attempt() -> None:
    calls = []

    @_retry_with_backoff(max_retries=3, base_delay=1)
    def always_fails() -> None:
        calls.append("called")
        raise requests.exceptions.Timeout("provider timeout")

    with pytest.raises(requests.exceptions.Timeout, match="retry deadline"):
        always_fails(_retry_deadline=time.monotonic() - 1)

    assert calls == []
