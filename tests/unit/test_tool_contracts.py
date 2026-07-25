from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    ERROR_RETRY_POLICIES,
    CircuitBreaker,
    CircuitState,
    ContractSearchProvider,
    CircuitBreakerPolicy,
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.contract_adapter import SEARCH_TOOL_SPEC
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.tools.reliable_execution import ToolExecutionError
from deepresearch_agent.trajectory import TrajectoryRecorder, trajectory_recording
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

    def test_timeout_is_enforced_and_counts_as_a_breaker_failure(self) -> None:
        timeout_policy = dict(SEARCH_TOOL_SPEC.retry_policy)
        timeout_policy[ToolErrorKind.TIMEOUT] = ERROR_RETRY_POLICIES[
            ToolErrorKind.TIMEOUT
        ].model_copy(update={"max_attempts": 1})
        spec = SEARCH_TOOL_SPEC.model_copy(
            update={"timeout_s": 0.03, "retry_policy": timeout_policy}
        )
        context = RunToolContext(retry_budget=RetryBudget(max_retries=0))
        started = time.monotonic()
        result = ReliableToolExecutor().execute(
            spec, lambda: time.sleep(0.3), context
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.kind, ToolErrorKind.TIMEOUT)
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertEqual(context.breakers[spec.name].consecutive_failures, 1)

        class SlowProvider:
            def search(self, *_args: object, **_kwargs: object) -> list[object]:
                raise ToolExecutionError(ToolErrorKind.TIMEOUT, "timed out")

        traced_context = RunToolContext(retry_budget=RetryBudget(max_retries=3))
        provider = ContractSearchProvider(
            SlowProvider(),
            executor=ReliableToolExecutor(sleep=lambda _: None),
            context=traced_context,
        )
        recorder = TrajectoryRecorder(run_id="timeout", request={})
        with trajectory_recording(recorder):
            self.assertEqual(provider.search("slow"), [])
        self.assertEqual(
            recorder.trajectory.tool_calls[-1].error["kind"], "timeout"
        )

    def test_per_tool_circuit_policies_are_independent(self) -> None:
        fast_open = SEARCH_TOOL_SPEC.model_copy(
            update={
                "name": "fast_open",
                "circuit_breaker": CircuitBreakerPolicy(failure_threshold=1),
            }
        )
        slow_open = SEARCH_TOOL_SPEC.model_copy(
            update={
                "name": "slow_open",
                "circuit_breaker": CircuitBreakerPolicy(failure_threshold=2),
            }
        )
        context = RunToolContext(retry_budget=RetryBudget(max_retries=0))
        executor = ReliableToolExecutor()
        def failure() -> None:
            raise ConnectionError("down")

        executor.execute(fast_open, failure, context)
        executor.execute(slow_open, failure, context)
        self.assertEqual(context.breakers["fast_open"].state, CircuitState.OPEN)
        self.assertEqual(context.breakers["slow_open"].state, CircuitState.CLOSED)
        executor.execute(slow_open, failure, context)
        self.assertEqual(context.breakers["slow_open"].state, CircuitState.OPEN)

    def test_run_context_factory_does_not_leak_retry_or_breaker_state(self) -> None:
        spec = SEARCH_TOOL_SPEC.model_copy(update={"name": "run_scoped"})
        first = RunToolContext.for_run(max_retries=0)
        ReliableToolExecutor().execute(
            spec,
            lambda: (_ for _ in ()).throw(ConnectionError("first run failure")),
            first,
        )
        second = RunToolContext.for_run(max_retries=0)
        self.assertEqual(second.retry_budget.consumed, 0)
        self.assertEqual(second.breakers, {})
        self.assertNotIn(spec.name, second.breakers)

    def test_engine_replaces_tool_context_for_each_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    runs_root=Path(tmp) / "runs",
                    max_critic_iter=1,
                    structured_logging_enabled=False,
                ),
                search_tool=FixtureSearchTool(),
            )
            engine.run(topic="first", depth_level=1)
            first = engine.run_tool_context
            assert first is not None
            first.retry_budget.consumed = 1
            engine.run(topic="second", depth_level=1)
            second = engine.run_tool_context
            assert second is not None
            self.assertIsNot(first, second)
            self.assertEqual(second.retry_budget.consumed, 0)
            engine._checkpoint_conn.close()

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

    def test_explicit_flag_off_preserves_provider_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    tool_contract_enabled=False,
                ),
                search_tool=FixtureSearchTool(),
            )
        self.assertIsInstance(engine.search_tool, FixtureSearchTool)
        self.assertNotIsInstance(engine.search_tool, ContractSearchProvider)

    def test_flag_defaults_on_and_wraps_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
            )
            engine = DeepResearchEngine(settings=settings, search_tool=FixtureSearchTool())
        self.assertIsInstance(engine.search_tool, ContractSearchProvider)


if __name__ == "__main__":
    unittest.main()
