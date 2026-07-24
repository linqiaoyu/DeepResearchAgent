from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from deepresearch_agent.tools.contracts import (
    ERROR_RETRY_POLICIES,
    DegradationEvent,
    ToolError,
    ToolErrorKind,
    ToolResult,
    ToolSpec,
)


class ToolExecutionError(RuntimeError):
    def __init__(self, kind: ToolErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def classify_tool_error(error: BaseException) -> ToolErrorKind:
    if isinstance(error, ToolExecutionError):
        return error.kind
    if isinstance(error, TimeoutError):
        return ToolErrorKind.TIMEOUT
    if isinstance(error, (ConnectionError, ConnectionResetError)):
        return ToolErrorKind.TRANSIENT
    return ToolErrorKind.PERMANENT


@dataclass
class RetryBudget:
    max_retries: int
    consumed: int = 0

    def consume(self) -> bool:
        if self.consumed >= self.max_retries:
            return False
        self.consumed += 1
        return True


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    _half_open_probe_taken: bool = False

    def allow_call(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.opened_at is None or self.clock() - self.opened_at < self.cooldown_s:
                return False
            self.state = CircuitState.HALF_OPEN
            self._half_open_probe_taken = False
        if self._half_open_probe_taken:
            return False
        self._half_open_probe_taken = True
        return True

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = None
        self._half_open_probe_taken = False

    def record_failure(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._open()
            return
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = self.clock()
        self._half_open_probe_taken = False


@dataclass
class RunToolContext:
    retry_budget: RetryBudget
    degradation_events: list[DegradationEvent] = field(default_factory=list)
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)


class ReliableToolExecutor:
    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sleep = sleep
        self._random = random_source
        self._clock = clock

    def execute(
        self,
        spec: ToolSpec,
        operation: Callable[[], Any],
        context: RunToolContext,
        *,
        degrade: bool = False,
        degraded_value: Any = None,
        impact: str = "tool output unavailable",
    ) -> ToolResult:
        started = self._clock()
        breaker = context.breakers.setdefault(spec.name, CircuitBreaker(clock=self._clock))
        if not breaker.allow_call():
            return self._failure(
                spec,
                ToolErrorKind.TRANSIENT,
                "supplier circuit is open",
                0,
                started,
                context,
                degrade,
                degraded_value,
                impact,
            )

        attempts = 0
        while True:
            attempts += 1
            try:
                value = operation()
            except Exception as exc:
                kind = classify_tool_error(exc)
                policy = spec.retry_policy.get(kind, ERROR_RETRY_POLICIES[kind])
                if not policy.retryable or attempts >= policy.max_attempts:
                    breaker.record_failure()
                    return self._failure(
                        spec,
                        kind,
                        str(exc),
                        attempts,
                        started,
                        context,
                        degrade,
                        degraded_value,
                        impact,
                        exception_type=type(exc).__name__,
                    )
                if not context.retry_budget.consume():
                    breaker.record_failure()
                    return self._failure(
                        spec,
                        ToolErrorKind.BUDGET_EXCEEDED,
                        "per-run retry budget exhausted",
                        attempts,
                        started,
                        context,
                        degrade,
                        degraded_value,
                        impact,
                    )
                delay = policy.base_backoff_s * (2 ** (attempts - 1))
                delay *= 0.5 + self._random()
                self._sleep(delay)
                continue
            breaker.record_success()
            return ToolResult(
                ok=True,
                value=value,
                attempts=attempts,
                elapsed_ms=self._elapsed_ms(started),
            )

    def _failure(
        self,
        spec: ToolSpec,
        kind: ToolErrorKind,
        message: str,
        attempts: int,
        started: float,
        context: RunToolContext,
        degrade: bool,
        degraded_value: Any,
        impact: str,
        exception_type: str | None = None,
    ) -> ToolResult:
        if degrade:
            context.degradation_events.append(
                DegradationEvent(
                    tool=spec.name,
                    reason=kind,
                    impact=impact,
                    attempts=attempts,
                )
            )
        return ToolResult(
            ok=False,
            value=degraded_value if degrade else None,
            error=ToolError(kind=kind, message=message, exception_type=exception_type),
            attempts=attempts,
            elapsed_ms=self._elapsed_ms(started),
            degraded=degrade,
        )

    def _elapsed_ms(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))
