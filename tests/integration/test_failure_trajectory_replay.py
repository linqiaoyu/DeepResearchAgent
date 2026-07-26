from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from deepresearch_agent.schemas import (
    ResearchPlan,
    Source,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    CninfoDisclosureSource,
    DisclosureSourceError,
    ReliableToolExecutor,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.disclosure_source import DISCLOSURE_TOOL_SPEC
from deepresearch_agent.trajectory import (
    ToolCallTrace,
    TrajectoryRecorder,
    TrajectoryTermination,
    active_trajectory_recorder,
    load_trajectory,
)
from deepresearch_agent.trajectory_replay import replay_trajectory
from deepresearch_agent.workflow import DeepResearchEngine


class FixedPlanner:
    last_stats: dict[str, object] = {}

    def __init__(self, *, financial: bool) -> None:
        self.financial = financial

    def plan(
        self,
        topic: str,
        depth_level: int = 1,
        research_id: str | None = None,
    ) -> ResearchPlan:
        del research_id
        requests = (
            [
                StructuredDataRequest(
                    capability="financial_indicators",
                    company_name="贵州茅台",
                    symbol="600519",
                    periods=["2025"],
                    metrics=["营业收入"],
                )
            ]
            if self.financial
            else []
        )
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=[
                SubQuestion(
                    id="q",
                    question=(
                        "贵州茅台 600519 2025 年营业收入是多少？"
                        if self.financial
                        else "研究 provider budget failure"
                    ),
                    search_queries=["贵州茅台 600519 营业收入"],
                    expected_source_types=["company_report"],
                    structured_data_requests=requests,
                )
            ],
        )


class ReplayableWebProvider:
    search_counts_toward_budget = True

    def __init__(self) -> None:
        self.context: RunToolContext | None = None
        self.source = Source(
            id="web-fallback",
            title="贵州茅台网页资料",
            url="https://example.test/moutai",
            source_type="company_report",
            published_at=date(2026, 6, 1),
            content="贵州茅台营业收入应以年度报告为准。",
            credibility=0.7,
            source_tier="secondary",
        )

    def set_run_context(self, context: RunToolContext) -> None:
        self.context = context

    def search(
        self,
        _query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        del top_k, source_type
        return [self.source]

    def fetch(self, url: str) -> Source | None:
        return self.source if url == self.source.url else None


class BudgetSearchProvider(ReplayableWebProvider):
    def search(
        self,
        _query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        del top_k, source_type
        assert self.context is not None
        self.context.consume_external_request(
            "search",
            tool="tavily_search",
        )
        return [self.source]


class FatalDisclosureSource:
    def set_run_context(self, context: RunToolContext) -> None:
        self.context = context

    def search(
        self,
        security_code: str,
        keyword: str,
        start_date: date,
        end_date: date,
        *,
        preferred_terms: tuple[str, ...] = (),
    ) -> list[Source]:
        del preferred_terms
        error = {
            "kind": ToolErrorKind.PERMANENT,
            "message": "injected disclosure contract failure",
            "exception_type": "DisclosureSourceError",
        }
        recorder = active_trajectory_recorder()
        if recorder:
            recorder.record_tool_call(
                ToolCallTrace(
                    tool_spec=DISCLOSURE_TOOL_SPEC.model_dump(mode="json"),
                    inputs={
                        "security_code": security_code,
                        "keyword": keyword,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    },
                    error=error,
                    attempts=1,
                )
            )
        raise DisclosureSourceError(
            ToolErrorKind.PERMANENT,
            "injected disclosure contract failure",
        )


class ConnectionDisclosureClient:
    def get(self, url: str, **_kwargs: Any) -> Any:
        raise httpx.ConnectError(
            "recorded connection failure",
            request=httpx.Request("GET", url),
        )

    def post(self, _url: str, **_kwargs: Any) -> Any:
        raise AssertionError("connection failure must not reach announcement POST")


class FailureTrajectoryReplayTests(unittest.TestCase):
    def _settings(self, root: Path, **updates: Any) -> Settings:
        values = {
            "storage_path": root / "research.db",
            "runs_root": root / "runs",
            "as_of": date(2026, 7, 26),
            "trajectory_record_enabled": True,
            "structured_logging_enabled": False,
            "run_manifest_enabled": False,
            "max_critic_iter": 1,
        }
        values.update(updates)
        return Settings(**values)

    def test_degraded_disclosure_then_web_fallback_strictly_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = DeepResearchEngine(
                settings=self._settings(root),
                search_tool=ReplayableWebProvider(),
                disclosure_source=CninfoDisclosureSource(
                    client=ConnectionDisclosureClient(),
                    executor=ReliableToolExecutor(sleep=lambda _delay: None),
                ),
            )
            engine.planner = FixedPlanner(financial=True)
            state = engine.run(
                topic="贵州茅台 600519 2025 年营业收入研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root / "runs" / state.research_id / "trajectory.json"
            )

            result = replay_trajectory(trajectory, mode="strict")

        self.assertEqual(result.status, "reproduced", result.cache_miss)
        self.assertTrue(result.termination_matches)
        self.assertEqual(result.artifact_matches, {"report.md": True})
        disclosure_call = next(
            call
            for call in trajectory.tool_calls
            if call.tool_spec.get("name") == "disclosure_source"
        )
        self.assertEqual(
            disclosure_call.degradation_event["reason"],
            "transient",
        )

    def test_recorded_provider_failure_replays_same_terminal_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = DeepResearchEngine(
                settings=self._settings(root),
                search_tool=ReplayableWebProvider(),
                disclosure_source=FatalDisclosureSource(),
            )
            engine.planner = FixedPlanner(financial=True)
            with self.assertRaises(DisclosureSourceError):
                engine.run(
                    topic="贵州茅台 600519 provider failure",
                    depth_level=1,
                )
            path = next(root.glob("runs/*/trajectory.json"))
            trajectory = load_trajectory(path)
            engine._checkpoint_conn.close()

            result = replay_trajectory(trajectory, mode="strict")
            mutated = trajectory.model_copy(deep=True)
            failed_transition = next(
                item
                for item in mutated.node_transitions
                if item.status == "failed"
            )
            failed_transition.node = "critic"
            control_flow_mismatch = replay_trajectory(
                mutated,
                mode="strict",
            )

        self.assertEqual(result.status, "reproduced", result.cache_miss)
        self.assertTrue(result.termination_matches)
        self.assertEqual(result.expected_termination, result.actual_termination)
        self.assertEqual(result.artifact_matches, {})
        self.assertTrue(result.failure_control_flow_matches)
        self.assertEqual(
            result.expected_failure_control_flow,
            result.actual_failure_control_flow,
        )
        self.assertEqual(
            result.expected_failure_control_flow[-1],
            {
                "node": "research_one",
                "status": "failed",
                "error_type": "DisclosureSourceError",
            },
        )
        self.assertEqual(control_flow_mismatch.status, "mismatch")
        self.assertFalse(
            control_flow_mismatch.failure_control_flow_matches
        )
        self.assertIn(
            "failure control-flow mismatch",
            control_flow_mismatch.cache_miss or "",
        )

    def test_budget_exceeded_partial_report_strictly_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = DeepResearchEngine(
                settings=self._settings(
                    root,
                    max_external_search_requests_per_run=0,
                    dynamic_capability_enabled=False,
                ),
                search_tool=BudgetSearchProvider(),
            )
            engine.planner = FixedPlanner(financial=False)
            state = engine.run(
                topic="provider budget failure",
                depth_level=1,
            )
            engine._checkpoint_conn.close()
            trajectory = load_trajectory(
                root / "runs" / state.research_id / "trajectory.json"
            )

            result = replay_trajectory(trajectory, mode="strict")

        self.assertEqual(state.status, "budget_exceeded")
        self.assertEqual(result.status, "reproduced", result.cache_miss)
        self.assertTrue(result.termination_matches)
        self.assertEqual(result.artifact_matches, {"report.md": True})

    def test_failure_before_recorded_plan_is_explicitly_unreplayable(self) -> None:
        recorder = TrajectoryRecorder(
            run_id="pre-plan-failure",
            request={
                "topic": "pre-plan failure",
                "mode": "deterministic",
                "depth_level": 1,
            },
        )
        recorder.finalize(
            manifest_ref=None,
            artifacts={},
            termination=TrajectoryTermination(
                status="failed",
                phase="planning",
                error_type="RuntimeError",
                error_message="planner exploded",
            ),
        )

        result = replay_trajectory(recorder.trajectory, mode="strict")

        self.assertEqual(result.status, "cache_miss")
        self.assertIn("unreplayable_internal_failure", result.cache_miss)
        self.assertEqual(
            result.expected_termination["error_type"],
            "RuntimeError",
        )


if __name__ == "__main__":
    unittest.main()
