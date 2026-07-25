from __future__ import annotations

import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    CircuitBreaker,
    CircuitState,
    ContractSearchProvider,
    FixtureSearchTool,
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.reliable_execution import ToolExecutionError
from deepresearch_agent.workflow import DeepResearchEngine


class FaultProvider:
    def __init__(self, behavior: Callable[[int, str], None]) -> None:
        self.fixture = FixtureSearchTool()
        self.behavior = behavior
        self.calls = 0
        self._lock = threading.Lock()

    def search(self, query: str, top_k: int = 3, source_type: str | None = None):
        with self._lock:
            self.calls += 1
            call = self.calls
        self.behavior(call, query)
        return self.fixture.search(query, top_k=top_k, source_type=source_type)

    def fetch(self, url: str):
        return self.fixture.fetch(url)


class ToolFailureChaosTests(unittest.TestCase):
    def _run(
        self,
        behavior: Callable[[int, str], None],
        *,
        retry_budget: int = 6,
        breaker_threshold: int = 3,
    ):
        provider = FaultProvider(behavior)
        delays: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                tool_contract_enabled=True,
                structured_logging_enabled=False,
                run_manifest_enabled=True,
                max_critic_iter=1,
            )
            engine = DeepResearchEngine(settings=settings, search_tool=provider)
            self.assertIsInstance(engine.search_tool, ContractSearchProvider)
            engine.search_tool.executor = ReliableToolExecutor(
                sleep=delays.append,
                random_source=lambda: 0.5,
            )
            run_context = RunToolContext(
                retry_budget=RetryBudget(max_retries=retry_budget),
                breakers={
                    "web_search": CircuitBreaker(
                        failure_threshold=breaker_threshold,
                    )
                },
            )
            with patch(
                "deepresearch_agent.workflow.engine.RunToolContext.for_run",
                return_value=run_context,
            ):
                state = engine.run(topic="AI Agent 财富管理可靠性研究", depth_level=1)
            breaker = run_context.breakers["web_search"]
            engine._checkpoint_conn.close()
        self.assertEqual(state.status, "done")
        self.assertTrue(state.metadata.get("degradation_events"))
        self.assertIn("## 数据获取降级", state.final_report or "")
        self.assertIsNotNone(state.evaluation)
        return state, provider, delays, breaker

    def test_transient_failure_retries_once_then_recovers(self) -> None:
        def behavior(call: int, _: str) -> None:
            if call == 1:
                raise ConnectionError("temporary reset")

        state, _, delays, _ = self._run(behavior)
        event = state.metadata["degradation_events"][0]
        self.assertEqual(event["reason"], "transient")
        self.assertEqual(event["attempts"], 2)
        self.assertEqual(delays[0], 0.5)
        self.assertEqual(state.evaluation.task_success_rate, 1.0)

    def test_continuous_failure_exhausts_run_retry_budget(self) -> None:
        def behavior(_: int, __: str) -> None:
            raise ConnectionError("still down")

        state, _, _, _ = self._run(behavior, retry_budget=1)
        reasons = {event["reason"] for event in state.metadata["degradation_events"]}
        self.assertIn("budget_exceeded", reasons)
        self.assertIn("budget_exceeded", state.metadata["tool_error_summary"])

    def test_timeout_is_bounded_and_visible(self) -> None:
        def behavior(_: int, __: str) -> None:
            raise TimeoutError("deadline exceeded")

        state, _, delays, _ = self._run(behavior)
        reasons = {event["reason"] for event in state.metadata["degradation_events"]}
        self.assertIn("timeout", reasons)
        self.assertIn(1.0, delays)

    def test_rate_limit_uses_rate_limit_backoff(self) -> None:
        def behavior(call: int, _: str) -> None:
            if call == 1:
                raise ToolExecutionError(ToolErrorKind.RATE_LIMITED, "429")

        state, _, delays, _ = self._run(behavior)
        event = state.metadata["degradation_events"][0]
        self.assertEqual(event["reason"], "rate_limited")
        self.assertEqual(event["attempts"], 2)
        self.assertEqual(delays[0], 2.0)

    def test_auth_failure_is_not_retried(self) -> None:
        def behavior(call: int, _: str) -> None:
            if call == 1:
                raise ToolExecutionError(ToolErrorKind.AUTH, "bad credential")

        state, _, delays, _ = self._run(behavior)
        event = state.metadata["degradation_events"][0]
        self.assertEqual(event["reason"], "auth")
        self.assertEqual(event["attempts"], 1)
        self.assertEqual(delays, [])

    def test_open_circuit_fast_fails_then_remains_visible(self) -> None:
        def behavior(_: int, __: str) -> None:
            raise ConnectionError("supplier down")

        state, _, _, breaker = self._run(behavior, retry_budget=30)
        self.assertEqual(breaker.state, CircuitState.OPEN)
        self.assertTrue(
            any(
                event["reason"] == "transient" and event["attempts"] == 0
                for event in state.metadata["degradation_events"]
            )
        )
        assert breaker.opened_at is not None
        breaker.opened_at -= breaker.cooldown_s
        self.assertTrue(breaker.allow_call())
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_partial_subquestion_failure_still_produces_marked_report(self) -> None:
        def behavior(_: int, query: str) -> None:
            if "pain point" in query.lower() or "market demand" in query.lower():
                raise ToolExecutionError(ToolErrorKind.AUTH, "subquestion denied")

        state, _, _, _ = self._run(behavior, breaker_threshold=100)
        self.assertEqual(state.evaluation.task_success_rate, 1.0)
        self.assertGreater(len(state.evidence_store), 0)
        self.assertIn("downstream evidence coverage may decrease", state.final_report or "")

    def test_total_retrieval_failure_produces_explicit_empty_evidence_warning(self) -> None:
        def behavior(_: int, __: str) -> None:
            raise ToolExecutionError(ToolErrorKind.AUTH, "all retrieval denied")

        state, _, _, _ = self._run(behavior)
        self.assertEqual(state.evaluation.task_success_rate, 0.0)
        self.assertEqual(state.evidence_store, [])
        self.assertIn("本次研究尚未收集到足够证据", state.final_report or "")
        self.assertIn("search results unavailable", state.final_report or "")


if __name__ == "__main__":
    unittest.main()
