from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import threading
from typing import List

import pytest

from lib.llm.call_budget import (
    CallBudgetController,
    CallBudgetExhaustionReason,
    CallBudgetLimits,
    CallBudgetUsage,
    CallDeadlineExceededError,
    CallTokenBudgetExceededError,
    PhysicalCallLimitExceededError,
)


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _controller(
    *,
    max_total_tokens: int = 10_000,
    max_physical_calls: int = 10,
    deadline: float = 100.0,
    clock: FakeClock | None = None,
) -> CallBudgetController:
    return CallBudgetController(
        CallBudgetLimits(
            deadline=deadline,
            max_total_tokens=max_total_tokens,
            max_physical_calls=max_physical_calls,
        ),
        clock=clock or FakeClock(1.0),
    )


def test_token_reservation_accepts_exact_fit_and_rejects_one_less() -> None:
    probe = _controller()
    prompt_tokens = probe.estimate_prompt_tokens([{"role": "user", "content": "x"}])
    exact = _controller(max_total_tokens=prompt_tokens + 20)

    lease = exact.reserve([{"role": "user", "content": "x"}], max_tokens=20)

    assert exact.snapshot().remaining_tokens == 0
    assert lease.reserved_total_tokens == prompt_tokens + 20

    short = _controller(max_total_tokens=prompt_tokens + 19)
    with pytest.raises(CallTokenBudgetExceededError) as caught:
        short.reserve([{"role": "user", "content": "x"}], max_tokens=20)
    assert caught.value.reason is CallBudgetExhaustionReason.TOKEN
    assert short.snapshot().physical_calls == 0


def test_utf8_estimate_is_conservative_for_chinese() -> None:
    controller = _controller()

    chinese = controller.estimate_prompt_tokens([{"role": "user", "content": "等待期"}])
    ascii_text = controller.estimate_prompt_tokens([{"role": "user", "content": "abc"}])

    assert chinese > ascii_text
    assert chinese >= len("等待期".encode("utf-8"))


def test_budget_models_are_frozen() -> None:
    limits = CallBudgetLimits(
        deadline=100.0,
        max_total_tokens=1_000,
        max_physical_calls=1,
    )

    with pytest.raises(FrozenInstanceError):
        limits.max_total_tokens = 2_000  # type: ignore[misc]


def test_deadline_is_checked_before_call_admission() -> None:
    clock = FakeClock(10.0)
    controller = _controller(deadline=10.0, clock=clock)

    with pytest.raises(CallDeadlineExceededError) as caught:
        controller.reserve([{"role": "user", "content": "test"}], max_tokens=10)

    assert caught.value.reason is CallBudgetExhaustionReason.DEADLINE
    assert controller.snapshot().physical_calls == 0


def test_call_is_rejected_when_only_subminimum_time_remains() -> None:
    clock = FakeClock(9.6)
    controller = _controller(deadline=10.0, clock=clock)

    with pytest.raises(CallDeadlineExceededError):
        controller.reserve([{"role": "user", "content": "test"}], max_tokens=10)

    assert controller.snapshot().physical_calls == 0


def test_physical_call_limit_counts_failed_or_unsettled_calls() -> None:
    controller = _controller(max_physical_calls=1)
    controller.reserve([{"role": "user", "content": "first"}], max_tokens=10)

    with pytest.raises(PhysicalCallLimitExceededError) as caught:
        controller.reserve([{"role": "user", "content": "second"}], max_tokens=10)

    assert caught.value.reason is CallBudgetExhaustionReason.CALL_LIMIT
    assert controller.snapshot().physical_calls == 1


def test_success_settles_actual_usage_and_releases_unused_reservation() -> None:
    controller = _controller(max_total_tokens=1_000)
    lease = controller.reserve([{"role": "user", "content": "test"}], max_tokens=100)
    reserved = lease.reserved_total_tokens

    snapshot = controller.settle(
        lease,
        CallBudgetUsage(prompt_tokens=5, completion_tokens=10),
    )

    assert snapshot.consumed_tokens == 15
    assert snapshot.reserved_tokens == 0
    assert snapshot.remaining_tokens == 985
    assert reserved > snapshot.consumed_tokens
    assert snapshot.active_leases == 0


def test_failure_or_missing_usage_consumes_full_reservation() -> None:
    controller = _controller(max_total_tokens=1_000)
    lease = controller.reserve([{"role": "user", "content": "test"}], max_tokens=100)

    snapshot = controller.settle(lease)

    assert snapshot.consumed_tokens == lease.reserved_total_tokens
    assert snapshot.remaining_tokens == 1_000 - lease.reserved_total_tokens
    with pytest.raises(ValueError, match="unknown"):
        controller.settle(lease)


def test_concurrent_reservations_are_atomic() -> None:
    probe = _controller()
    messages = [{"role": "user", "content": "same request"}]
    per_call = probe.estimate_prompt_tokens(messages) + 50
    controller = _controller(max_total_tokens=per_call, max_physical_calls=20)
    worker_count = 12
    barrier = threading.Barrier(worker_count)

    def reserve_once() -> bool:
        barrier.wait()
        try:
            controller.reserve(messages, max_tokens=50)
        except CallTokenBudgetExceededError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        admitted: List[bool] = list(executor.map(lambda _: reserve_once(), range(worker_count)))

    assert sum(admitted) == 1
    snapshot = controller.snapshot()
    assert snapshot.reserved_tokens == per_call
    assert snapshot.physical_calls == 1
    assert snapshot.active_leases == 1
