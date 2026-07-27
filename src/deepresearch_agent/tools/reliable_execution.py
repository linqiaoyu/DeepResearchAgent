from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
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


# Bounded at process scope: detached synchronous providers can occupy workers,
# but cannot create one unbounded daemon thread per attempt.
_TOOL_CALL_EXECUTOR = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="deepresearch-tool",
)


class ToolExecutionError(RuntimeError):
    def __init__(self, kind: ToolErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class DetachedToolOperationError(ToolExecutionError):
    """Timeout raised when Python cannot stop the synchronous worker thread."""


class ToolExecutionScope:
    """Cooperative cancellation state shared with a synchronous tool adapter.

    A Python thread cannot be killed safely.  The executor therefore marks an
    overdue attempt as cancelled and never retries it concurrently.  Adapters
    that can perform more than one external request must call
    :meth:`raise_if_cancelled` at every request boundary so the detached worker
    cannot start another request after its deadline.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._finished = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def begin_attempt(self) -> None:
        if self.cancelled:
            raise DetachedToolOperationError(
                ToolErrorKind.TIMEOUT,
                "tool operation was cancelled after its deadline",
            )
        self._finished.clear()

    def cancel(self) -> None:
        self._cancelled.set()

    def mark_finished(self) -> None:
        self._finished.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise DetachedToolOperationError(
                ToolErrorKind.TIMEOUT,
                "tool operation was cancelled after its deadline",
            )


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
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def consume(self) -> bool:
        with self._lock:
            if self.consumed >= self.max_retries:
                return False
            self.consumed += 1
            return True


@dataclass
class ExternalRequestBudget:
    """Run-wide, fail-closed allowance for actual network egress."""

    max_search_requests: int
    max_fetch_requests: int
    max_authority_search_requests: int = 3
    max_authority_fetch_requests: int = 18
    search_requests: int = 0
    fetch_requests: int = 0
    authority_search_requests: int = 0
    authority_fetch_requests: int = 0
    accepted_by_tool: dict[str, dict[str, int]] = field(default_factory=dict)
    rejected_by_tool: dict[str, dict[str, int]] = field(default_factory=dict)
    rejected_events: list[dict[str, int | str]] = field(default_factory=list)
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def consume(self, request_kind: str, *, tool: str) -> None:
        if request_kind not in {"search", "fetch"}:
            raise ValueError(f"unknown external request kind: {request_kind}")
        lane = "authority" if tool == "disclosure_source" else "web"
        prefix = "authority_" if lane == "authority" else ""
        count_name = f"{prefix}{request_kind}_requests"
        limit_name = f"max_{prefix}{request_kind}_requests"
        with self._lock:
            consumed = getattr(self, count_name)
            limit = getattr(self, limit_name)
            if consumed >= limit:
                self._increment(self.rejected_by_tool, tool, request_kind)
                self.rejected_events.append(
                    {
                        "tool": tool,
                        "request_kind": request_kind,
                        "lane": lane,
                        "consumed": consumed,
                        "limit": limit,
                    }
                )
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED,
                    f"run-wide {lane} {request_kind} request budget exhausted "
                    f"for {tool}: {consumed}/{limit}",
                )
            setattr(self, count_name, consumed + 1)
            self._increment(self.accepted_by_tool, tool, request_kind)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "search_requests": self.search_requests,
                "max_search_requests": self.max_search_requests,
                "fetch_requests": self.fetch_requests,
                "max_fetch_requests": self.max_fetch_requests,
                "authority_search_requests": self.authority_search_requests,
                "max_authority_search_requests": (
                    self.max_authority_search_requests
                ),
                "authority_fetch_requests": self.authority_fetch_requests,
                "max_authority_fetch_requests": (
                    self.max_authority_fetch_requests
                ),
                "total_search_requests": (
                    self.search_requests + self.authority_search_requests
                ),
                "total_fetch_requests": (
                    self.fetch_requests + self.authority_fetch_requests
                ),
                "accepted_by_tool": self._counter_snapshot(
                    self.accepted_by_tool
                ),
                "rejected_by_tool": self._counter_snapshot(
                    self.rejected_by_tool
                ),
            }

    def _increment(
        self,
        counters: dict[str, dict[str, int]],
        tool: str,
        request_kind: str,
    ) -> None:
        tool_counts = counters.setdefault(tool, {"search": 0, "fetch": 0})
        tool_counts[request_kind] += 1

    def _counter_snapshot(
        self,
        counters: dict[str, dict[str, int]],
    ) -> dict[str, dict[str, int]]:
        return {
            tool: dict(counts)
            for tool, counts in sorted(counters.items())
        }


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_s: float = 30.0
    half_open_max_calls: int = 1
    clock: Callable[[], float] = time.monotonic
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    _half_open_probes_taken: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def allow_call(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if self.opened_at is None or self.clock() - self.opened_at < self.cooldown_s:
                    return False
                self.state = CircuitState.HALF_OPEN
                self._half_open_probes_taken = 0
            if self._half_open_probes_taken >= self.half_open_max_calls:
                return False
            self._half_open_probes_taken += 1
            return True

    def record_success(self) -> None:
        with self._lock:
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            self._half_open_probes_taken = 0

    def record_failure(self) -> None:
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._open()
                return
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.failure_threshold:
                self._open()

    def _open(self) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = self.clock()
        self._half_open_probes_taken = 0


@dataclass
class RunToolContext:
    retry_budget: RetryBudget
    external_request_budget: ExternalRequestBudget | None = None
    degradation_events: list[DegradationEvent] = field(default_factory=list)
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    @classmethod
    def for_run(
        cls,
        *,
        max_retries: int = 6,
        max_external_search_requests: int = 20,
        max_external_fetch_requests: int = 20,
        max_authority_search_requests: int = 3,
        max_authority_fetch_requests: int = 18,
    ) -> "RunToolContext":
        return cls(
            retry_budget=RetryBudget(max_retries=max_retries),
            external_request_budget=ExternalRequestBudget(
                max_search_requests=max_external_search_requests,
                max_fetch_requests=max_external_fetch_requests,
                max_authority_search_requests=(
                    max_authority_search_requests
                ),
                max_authority_fetch_requests=(
                    max_authority_fetch_requests
                ),
            ),
        )

    def consume_external_request(self, request_kind: str, *, tool: str) -> None:
        if self.external_request_budget is not None:
            self.external_request_budget.consume(request_kind, tool=tool)


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
        operation_scope: ToolExecutionScope | None = None,
    ) -> ToolResult:
        started = self._clock()
        scope = operation_scope or ToolExecutionScope()
        breaker = context.breakers.setdefault(
            spec.name,
            CircuitBreaker(
                failure_threshold=spec.circuit_breaker.failure_threshold,
                cooldown_s=spec.circuit_breaker.cooldown_s,
                half_open_max_calls=spec.circuit_breaker.half_open_max_calls,
                clock=self._clock,
            ),
        )
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
        last_failure_kind: ToolErrorKind | None = None
        while True:
            remaining = self._remaining_timeout(spec, started)
            if remaining is not None and remaining <= 0:
                breaker.record_failure()
                return self._failure(
                    spec,
                    ToolErrorKind.TIMEOUT,
                    f"tool total deadline exceeded after {spec.total_timeout_s:g}s",
                    attempts,
                    started,
                    context,
                    degrade,
                    degraded_value,
                    impact,
                )
            attempts += 1
            try:
                scope.begin_attempt()
                attempt_timeout = (
                    min(spec.timeout_s, remaining)
                    if remaining is not None
                    else spec.timeout_s
                )
                value = self._call_with_timeout(
                    operation,
                    attempt_timeout,
                    scope,
                )
            except Exception as exc:
                kind = classify_tool_error(exc)
                last_failure_kind = kind
                policy = spec.retry_policy.get(kind, ERROR_RETRY_POLICIES[kind])
                # The worker for a detached timeout is still executing.  A
                # retry would overlap it and could duplicate egress or writes,
                # so this boundary always fails fast regardless of the normal
                # timeout retry policy.
                if (
                    isinstance(exc, DetachedToolOperationError)
                    or not policy.retryable
                    or attempts >= policy.max_attempts
                ):
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
                delay = policy.base_backoff_s * (2 ** (attempts - 1))
                delay *= 0.5 + self._random()
                remaining = self._remaining_timeout(spec, started)
                if remaining is not None and remaining <= delay:
                    breaker.record_failure()
                    return self._failure(
                        spec,
                        ToolErrorKind.TIMEOUT,
                        f"tool total deadline exceeded after {spec.total_timeout_s:g}s",
                        attempts,
                        started,
                        context,
                        degrade,
                        degraded_value,
                        impact,
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
                self._sleep(delay)
                continue
            breaker.record_success()
            if attempts > 1 and last_failure_kind is not None:
                context.degradation_events.append(
                    DegradationEvent(
                        tool=spec.name,
                        reason=last_failure_kind,
                        impact="transient tool degradation recovered after bounded retry",
                        attempts=attempts,
                    )
                )
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

    def _remaining_timeout(
        self,
        spec: ToolSpec,
        started: float,
    ) -> float | None:
        if spec.total_timeout_s is None:
            return None
        return spec.total_timeout_s - (self._clock() - started)

    @staticmethod
    def _call_with_timeout(
        operation: Callable[[], Any],
        timeout_s: float,
        scope: ToolExecutionScope,
    ) -> Any:
        """Return promptly on timeout without waiting for an uncooperative tool.

        Python cannot safely kill an arbitrary synchronous thread.  The worker is
        deliberately daemonized so an overdue provider cannot keep the run (or
        process shutdown) hostage; providers should still use their own transport
        timeout for cancellation at the I/O layer.
        """
        def invoke() -> Any:
            try:
                return operation()
            finally:
                scope.mark_finished()

        future = _TOOL_CALL_EXECUTOR.submit(invoke)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeoutError as exc:
            # ``concurrent.futures.TimeoutError`` is an alias of the builtin
            # ``TimeoutError``.  If the future already finished, this was the
            # provider's own retryable timeout, not a detached worker.
            if future.done():
                return future.result()
            scope.cancel()
            future.cancel()
            raise DetachedToolOperationError(
                ToolErrorKind.TIMEOUT,
                f"tool operation timed out after {timeout_s:g}s; "
                "detached worker quarantined",
            ) from exc
