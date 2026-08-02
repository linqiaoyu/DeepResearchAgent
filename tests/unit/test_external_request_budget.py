from __future__ import annotations

import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.orchestration import RunScope, SearchQuota
from deepresearch_agent.schemas import (
    ResearchState,
    Source,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.tools import (
    ContractSearchProvider,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
)
from deepresearch_agent.tools.tavily_search import TavilySearchProvider
from deepresearch_agent.trajectory import (
    TrajectoryRecorder,
    load_trajectory,
    trajectory_recording,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "stub",
                    "url": "https://example.test/source",
                    "content": "stub content",
                }
            ]
        }


class _HttpStub:
    def __init__(self) -> None:
        self.posts = 0

    def post(self, _url: str, **_kwargs: Any) -> _Response:
        self.posts += 1
        return _Response()


class ExternalRequestBudgetTests(unittest.TestCase):
    def test_default_authority_lane_covers_bounded_disclosure_retries(self) -> None:
        snapshot = RunToolContext.for_run().external_request_budget.snapshot()

        self.assertEqual(snapshot["max_authority_search_requests"], 3)
        self.assertEqual(snapshot["max_authority_fetch_requests"], 18)

    def test_default_web_lane_remains_twenty_requests_per_kind(self) -> None:
        context = RunToolContext.for_run()
        for _ in range(20):
            context.consume_external_request("search", tool="tavily_search")
            context.consume_external_request("fetch", tool="tavily_search")

        with self.assertRaises(ToolExecutionError):
            context.consume_external_request("search", tool="tavily_search")
        with self.assertRaises(ToolExecutionError):
            context.consume_external_request("fetch", tool="tavily_search")
        snapshot = context.external_request_budget.snapshot()

        self.assertEqual(snapshot["search_requests"], 20)
        self.assertEqual(snapshot["fetch_requests"], 20)
        self.assertEqual(snapshot["authority_search_requests"], 0)
        self.assertEqual(snapshot["authority_fetch_requests"], 0)
        self.assertEqual(
            snapshot["accepted_by_tool"]["tavily_search"],
            {"search": 20, "fetch": 20},
        )
        self.assertEqual(
            snapshot["rejected_by_tool"]["tavily_search"],
            {"search": 1, "fetch": 1},
        )

    def test_external_budget_consumption_is_thread_safe(self) -> None:
        context = RunToolContext.for_run(max_external_fetch_requests=20)

        def consume() -> bool:
            try:
                context.consume_external_request(
                    "fetch",
                    tool="tavily_search",
                )
            except ToolExecutionError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=16) as executor:
            accepted = list(executor.map(lambda _: consume(), range(64)))
        snapshot = context.external_request_budget.snapshot()

        self.assertEqual(sum(accepted), 20)
        self.assertEqual(snapshot["fetch_requests"], 20)
        self.assertEqual(
            snapshot["accepted_by_tool"]["tavily_search"]["fetch"],
            20,
        )
        self.assertEqual(
            snapshot["rejected_by_tool"]["tavily_search"]["fetch"],
            44,
        )

    def test_structured_provider_runs_before_web_budget_failure(self) -> None:
        events: list[str] = []

        class OrderingResearcher:
            def structured_evidence(
                self,
                _research_id: str,
                _sub_question: SubQuestion,
            ) -> tuple[list[Any], dict[str, int], list[dict[str, str]]]:
                events.append("structured")
                return [], {"requests": 1, "records": 0, "symbol_resolution_failures": 0, "execution_failures": 0}, []

            def research_with_budget(
                self,
                _sub_question: SubQuestion,
                **_kwargs: Any,
            ) -> tuple[Any, ...]:
                events.append("web")
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED,
                    "web budget exhausted",
                )

        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                )
            )
            engine.researcher = OrderingResearcher()
            sub_question = SubQuestion(
                id="finance",
                question="贵州茅台 2025 年营业收入",
                search_queries=["600519 营业收入 年度报告"],
                structured_data_requests=[
                    StructuredDataRequest(
                        capability="financial_indicators",
                        symbol="600519",
                        periods=["20251231"],
                        metrics=["营业收入"],
                    )
                ],
            )
            state = ResearchState(topic=sub_question.question)
            state.metadata["capability_selections"] = {
                sub_question.id: {
                    "selected_capabilities": [
                        "structured_data_provider",
                        "web_search",
                    ]
                }
            }
            try:
                with self.assertRaises(ToolExecutionError):
                    engine._research_one_node(
                        {
                            "research_state": state.model_dump(mode="json"),
                            "fanout_sub_question": sub_question.model_dump(
                                mode="json"
                            ),
                        },
                        run_scope=RunScope(
                            tool_context=RunToolContext.for_run(),
                            search_quota=SearchQuota(engine.settings.max_searches_per_run),
                        ),
                    )
            finally:
                engine._checkpoint_conn.close()

        self.assertEqual(events, ["structured", "web"])

    def test_critic_retry_style_search_is_refused_and_traced_at_run_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _HttpStub()
            context = RunToolContext.for_run(max_external_search_requests=1)
            provider = ContractSearchProvider(
                TavilySearchProvider(
                    "test-key",
                    client=client,
                    ledger_path=Path(tmp) / "ledger.jsonl",
                    context=context,
                ),
                context=context,
            )
            researcher = ResearcherAgent(search_tool=provider, max_searches_per_run=3)
            scope = RunScope(context, SearchQuota(3))
            recorder = TrajectoryRecorder(run_id="budget", request={})
            with trajectory_recording(recorder):
                sources, _record = researcher.retry("first", run_scope=scope)
                self.assertEqual(len(sources), 1)
                with self.assertRaises(ToolExecutionError) as raised:
                    researcher.retry("critic retry", run_scope=scope)

        self.assertEqual(raised.exception.kind, ToolErrorKind.BUDGET_EXCEEDED)
        self.assertEqual(client.posts, 1)
        self.assertEqual(
            recorder.trajectory.tool_calls[-1].error["kind"], "budget_exceeded"
        )
        self.assertEqual(
            context.external_request_budget.rejected_events[0]["request_kind"],
            "search",
        )

    def test_all_httpx_egress_sites_are_explicitly_budgeted(self) -> None:
        root = Path(__file__).resolve().parents[2] / "src" / "deepresearch_agent" / "tools"
        httpx_files = {
            path.name
            for path in root.glob("*.py")
            if "import httpx" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(
            httpx_files,
            {"tavily_search.py", "disclosure_source.py", "sec_companyfacts.py"},
        )

        expected = {
            "tavily_search.py": 2,
            "disclosure_source.py": 3,
            "sec_companyfacts.py": 1,
        }
        for filename, count in expected.items():
            text = (root / filename).read_text(encoding="utf-8")
            calls = list(re.finditer(r"self\.client\.(?:get|post)\(", text))
            self.assertEqual(len(calls), count, filename)
            for call in calls:
                preceding = text[max(0, call.start() - 160):call.start()]
                self.assertIn("self._consume_egress(", preceding, filename)

    def test_fixture_default_path_consumes_the_search_budget(self) -> None:
        class FixtureLike:
            search_counts_toward_budget = True

            def __init__(self) -> None:
                self.calls = 0

            def search(self, query: str, **_kwargs: Any) -> list[Source]:
                self.calls += 1
                return [
                    Source(
                        id=str(self.calls), title=query,
                        url=f"https://fixture.test/{self.calls}", source_type="web",
                        published_at=date(2026, 1, 1), content=query,
                    )
                ]

        provider = FixtureLike()
        researcher = ResearcherAgent(search_tool=provider, max_searches_per_run=1)
        scope = RunScope(RunToolContext.for_run(), SearchQuota(1))
        researcher.retry("one", run_scope=scope)
        sources, record = researcher.retry("two", run_scope=scope)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(sources, [])
        self.assertTrue(record.query.startswith("[search_limit_exceeded]"))

    def test_engine_records_budget_refusal_as_a_gated_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=_HttpStub(),
                ledger_path=Path(tmp) / "ledger.jsonl",
            )
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    runs_root=Path(tmp) / "runs",
                    max_external_search_requests_per_run=0,
                    structured_logging_enabled=False,
                    run_manifest_enabled=False,
                    trajectory_record_enabled=True,
                ),
                search_tool=provider,
            )
            state = engine.run(topic="budget refusal", depth_level=1)
            trajectory = load_trajectory(
                Path(tmp)
                / "runs"
                / state.research_id
                / "trajectory.json"
            )
            engine._checkpoint_conn.close()

        self.assertEqual(state.status, "budget_exceeded")
        self.assertEqual(
            state.agent_decisions[-1].decision_type,
            "external_request_budget_rejected",
        )
        self.assertEqual(
            state.metadata["external_request_budget"]["search_requests"], 0,
        )
        self.assertTrue(state.final_report)
        self.assertIn("数据缺失与资源耗尽", state.final_report or "")
        self.assertIn("0/0", state.final_report or "")
        self.assertEqual(
            trajectory.termination.status,
            "budget_exceeded",
        )
        self.assertEqual(
            trajectory.termination.error_type,
            "ToolExecutionError",
        )
        self.assertEqual(
            trajectory.artifacts["report.md"],
            state.final_report,
        )
        self.assertGreaterEqual(
            state.metadata["external_request_budget"][
                "rejected_by_tool"
            ]["tavily_search"]["search"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
