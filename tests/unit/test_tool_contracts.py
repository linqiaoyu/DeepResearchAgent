from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    ERROR_RETRY_POLICIES,
    CircuitBreaker,
    CircuitState,
    ContractSearchProvider,
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.contract_adapter import SEARCH_TOOL_SPEC
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.tools.reliable_execution import ToolExecutionError
from deepresearch_agent.workflow import DeepResearchEngine


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ToolContractTests(unittest.TestCase):
    def test_error_policy_truth_table_is_complete_and_explicit(self) -> None:
        self.assertEqual(set(ERROR_RETRY_POLICIES), set(ToolErrorKind))
        for kind in {ToolErrorKind.TRANSIENT, ToolErrorKind.RATE_LIMITED, ToolErrorKind.TIMEOUT}:
            self.assertTrue(ERROR_RETRY_POLICIES[kind].retryable)
        for kind in {
            ToolErrorKind.AUTH,
            ToolErrorKind.NOT_FOUND,
            ToolErrorKind.PERMANENT,
            ToolErrorKind.BUDGET_EXCEEDED,
        }:
            self.assertFalse(ERROR_RETRY_POLICIES[kind].retryable)

    def test_backoff_sequence_is_deterministic_with_injected_random(self) -> None:
        delays: list[float] = []
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ToolExecutionError(ToolErrorKind.TRANSIENT, "retry")
            return "ok"

        executor = ReliableToolExecutor(sleep=delays.append, random_source=lambda: 0.5)
        result = executor.execute(
            SEARCH_TOOL_SPEC,
            operation,
            RunToolContext(retry_budget=RetryBudget(max_retries=3)),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(delays, [0.5, 1.0])

    def test_per_run_retry_budget_exhaustion_fails_fast(self) -> None:
        context = RunToolContext(retry_budget=RetryBudget(max_retries=1))
        executor = ReliableToolExecutor(sleep=lambda _: None, random_source=lambda: 0.5)

        result = executor.execute(
            SEARCH_TOOL_SPEC,
            lambda: (_ for _ in ()).throw(ConnectionError("down")),
            context,
        )

        self.assertEqual(result.error.kind, ToolErrorKind.BUDGET_EXCEEDED)
        self.assertEqual(context.retry_budget.consumed, 1)

    def test_circuit_breaker_closed_open_half_open_closed(self) -> None:
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=2, cooldown_s=10, clock=clock)
        self.assertTrue(breaker.allow_call())
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        self.assertFalse(breaker.allow_call())
        clock.value = 10
        self.assertTrue(breaker.allow_call())
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)
        self.assertFalse(breaker.allow_call())
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_degradation_is_returned_and_recorded(self) -> None:
        context = RunToolContext(retry_budget=RetryBudget(max_retries=0))
        result = ReliableToolExecutor().execute(
            SEARCH_TOOL_SPEC,
            lambda: (_ for _ in ()).throw(ToolExecutionError(ToolErrorKind.AUTH, "bad key")),
            context,
            degrade=True,
            degraded_value=[],
            impact="no sources",
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.degraded)
        self.assertEqual(result.value, [])
        self.assertEqual(context.degradation_events[0].reason, ToolErrorKind.AUTH)
        self.assertEqual(context.degradation_events[0].impact, "no sources")

    def test_flag_defaults_off_and_preserves_provider_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(storage_path=Path(tmp) / "research.db"),
                search_tool=FixtureSearchTool(),
            )
        self.assertIsInstance(engine.search_tool, FixtureSearchTool)
        self.assertNotIsInstance(engine.search_tool, ContractSearchProvider)

    def test_flag_on_wraps_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                tool_contract_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings, search_tool=FixtureSearchTool())
        self.assertIsInstance(engine.search_tool, ContractSearchProvider)


if __name__ == "__main__":
    unittest.main()
