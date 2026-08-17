"""Thread-safe admission control for physical LLM calls.

Reservations happen before a provider request so concurrent workers cannot each
observe the same remaining budget.  The UTF-8 byte count is deliberately used
as a tokenizer-independent upper bound; this favors stopping early over making
an unbudgeted external call.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Optional, Sequence


_DEFAULT_INPUT_SAFETY_FACTOR = 1.25
_DEFAULT_MESSAGE_OVERHEAD_BYTES = 16
_DEFAULT_REQUEST_OVERHEAD_BYTES = 8


class CallBudgetExhaustionReason(str, Enum):
    """Machine-readable reason for rejecting a call before provider I/O."""

    TOKEN = "token"
    DEADLINE = "deadline"
    CALL_LIMIT = "call_limit"


@dataclass(frozen=True)
class CallBudgetLimits:
    """Immutable limits shared by every worker participating in one run."""

    deadline: float
    max_total_tokens: int
    max_physical_calls: int
    input_safety_factor: float = _DEFAULT_INPUT_SAFETY_FACTOR
    message_overhead_bytes: int = _DEFAULT_MESSAGE_OVERHEAD_BYTES
    request_overhead_bytes: int = _DEFAULT_REQUEST_OVERHEAD_BYTES
    minimum_call_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not math.isfinite(self.deadline):
            raise ValueError("deadline must be finite")
        if self.max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        if self.max_physical_calls <= 0:
            raise ValueError("max_physical_calls must be positive")
        if not math.isfinite(self.input_safety_factor) or self.input_safety_factor < 1:
            raise ValueError("input_safety_factor must be finite and at least 1")
        if self.message_overhead_bytes < 0:
            raise ValueError("message_overhead_bytes cannot be negative")
        if self.request_overhead_bytes < 0:
            raise ValueError("request_overhead_bytes cannot be negative")
        if (
            not math.isfinite(self.minimum_call_seconds)
            or self.minimum_call_seconds <= 0
        ):
            raise ValueError("minimum_call_seconds must be finite and positive")


@dataclass(frozen=True)
class CallBudgetLease:
    """Token reservation authorizing exactly one physical provider call."""

    lease_id: str
    reserved_prompt_tokens: int
    reserved_completion_tokens: int

    @property
    def reserved_total_tokens(self) -> int:
        return self.reserved_prompt_tokens + self.reserved_completion_tokens


@dataclass(frozen=True)
class CallBudgetUsage:
    """Actual provider usage for a successful call."""

    prompt_tokens: int
    completion_tokens: int

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0:
            raise ValueError("prompt_tokens cannot be negative")
        if self.completion_tokens < 0:
            raise ValueError("completion_tokens cannot be negative")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class CallBudgetSnapshot:
    """Point-in-time accounting view suitable for logs and test reports."""

    deadline: float
    observed_at: float
    max_total_tokens: int
    consumed_tokens: int
    reserved_tokens: int
    remaining_tokens: int
    max_physical_calls: int
    physical_calls: int
    active_leases: int

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self.observed_at)


class CallBudgetExceededError(RuntimeError):
    """Base exception raised before provider I/O when admission is unsafe."""

    def __init__(
        self,
        reason: CallBudgetExhaustionReason,
        snapshot: CallBudgetSnapshot,
        requested_tokens: int,
    ) -> None:
        self.reason = reason
        self.snapshot = snapshot
        self.requested_tokens = requested_tokens
        super().__init__(
            f"LLM call budget exhausted: {reason.value}; "
            f"requested_tokens={requested_tokens}, "
            f"remaining_tokens={snapshot.remaining_tokens}"
        )


class CallTokenBudgetExceededError(CallBudgetExceededError):
    """The next call's worst-case token reservation does not fit."""

    def __init__(self, snapshot: CallBudgetSnapshot, requested_tokens: int) -> None:
        super().__init__(CallBudgetExhaustionReason.TOKEN, snapshot, requested_tokens)


class CallDeadlineExceededError(CallBudgetExceededError):
    """The absolute run deadline has already been reached."""

    def __init__(self, snapshot: CallBudgetSnapshot, requested_tokens: int) -> None:
        super().__init__(CallBudgetExhaustionReason.DEADLINE, snapshot, requested_tokens)


class PhysicalCallLimitExceededError(CallBudgetExceededError):
    """The run has already admitted its maximum physical call count."""

    def __init__(self, snapshot: CallBudgetSnapshot, requested_tokens: int) -> None:
        super().__init__(CallBudgetExhaustionReason.CALL_LIMIT, snapshot, requested_tokens)


class CallBudgetController:
    """Atomically reserve and settle one run's time, token, and call budgets."""

    def __init__(
        self,
        limits: CallBudgetLimits,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._controller_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._consumed_tokens = 0
        self._reserved_tokens = 0
        self._physical_calls = 0
        self._next_lease_number = 1
        self._active_leases: dict[str, CallBudgetLease] = {}

    @property
    def limits(self) -> CallBudgetLimits:
        return self._limits

    def estimate_prompt_tokens(self, messages: Sequence[Mapping[str, str]]) -> int:
        """Return a conservative tokenizer-independent prompt-token bound."""
        if not messages:
            raise ValueError("messages cannot be empty")
        byte_count = self._limits.request_overhead_bytes
        for message in messages:
            if not message:
                raise ValueError("messages cannot contain an empty mapping")
            byte_count += self._limits.message_overhead_bytes
            for key, value in message.items():
                byte_count += len(key.encode("utf-8"))
                byte_count += len(value.encode("utf-8"))
        return max(1, math.ceil(byte_count * self._limits.input_safety_factor))

    def reserve(
        self,
        messages: Sequence[Mapping[str, str]],
        max_tokens: int,
    ) -> CallBudgetLease:
        """Reserve one physical call before any network I/O occurs."""
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        prompt_tokens = self.estimate_prompt_tokens(messages)
        requested_tokens = prompt_tokens + max_tokens
        with self._lock:
            now = self._clock()
            snapshot = self._snapshot_locked(now)
            if now + self._limits.minimum_call_seconds > self._limits.deadline:
                raise CallDeadlineExceededError(snapshot, requested_tokens)
            if self._physical_calls >= self._limits.max_physical_calls:
                raise PhysicalCallLimitExceededError(snapshot, requested_tokens)
            if requested_tokens > snapshot.remaining_tokens:
                raise CallTokenBudgetExceededError(snapshot, requested_tokens)
            lease = CallBudgetLease(
                lease_id=f"{self._controller_id}:{self._next_lease_number}",
                reserved_prompt_tokens=prompt_tokens,
                reserved_completion_tokens=max_tokens,
            )
            self._next_lease_number += 1
            self._physical_calls += 1
            self._reserved_tokens += lease.reserved_total_tokens
            self._active_leases[lease.lease_id] = lease
            return lease

    def settle(
        self,
        lease: CallBudgetLease,
        usage: Optional[CallBudgetUsage] = None,
    ) -> CallBudgetSnapshot:
        """Settle actual usage, or consume the full reservation when unavailable."""
        with self._lock:
            active_lease = self._active_leases.get(lease.lease_id)
            if active_lease != lease:
                raise ValueError("lease is unknown, belongs to another controller, or is settled")
            if usage is not None:
                if usage.prompt_tokens > lease.reserved_prompt_tokens:
                    raise ValueError("actual prompt usage exceeds its conservative reservation")
                if usage.completion_tokens > lease.reserved_completion_tokens:
                    raise ValueError("actual completion usage exceeds max_tokens reservation")
                consumed = usage.total_tokens
            else:
                consumed = lease.reserved_total_tokens
            del self._active_leases[lease.lease_id]
            self._reserved_tokens -= lease.reserved_total_tokens
            self._consumed_tokens += consumed
            return self._snapshot_locked(self._clock())

    def snapshot(self) -> CallBudgetSnapshot:
        """Return an internally consistent accounting snapshot."""
        with self._lock:
            return self._snapshot_locked(self._clock())

    def _snapshot_locked(self, observed_at: float) -> CallBudgetSnapshot:
        allocated_tokens = self._consumed_tokens + self._reserved_tokens
        return CallBudgetSnapshot(
            deadline=self._limits.deadline,
            observed_at=observed_at,
            max_total_tokens=self._limits.max_total_tokens,
            consumed_tokens=self._consumed_tokens,
            reserved_tokens=self._reserved_tokens,
            remaining_tokens=max(0, self._limits.max_total_tokens - allocated_tokens),
            max_physical_calls=self._limits.max_physical_calls,
            physical_calls=self._physical_calls,
            active_leases=len(self._active_leases),
        )
