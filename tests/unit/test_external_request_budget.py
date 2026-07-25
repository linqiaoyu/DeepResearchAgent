from __future__ import annotations

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import Source
from deepresearch_agent.tools import (
    ContractSearchProvider,
    RunToolContext,
    ToolErrorKind,
    ToolExecutionError,
)
from deepresearch_agent.tools.tavily_search import TavilySearchProvider
from deepresearch_agent.trajectory import TrajectoryRecorder, trajectory_recording
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
            recorder = TrajectoryRecorder(run_id="budget", request={})
            with trajectory_recording(recorder):
                sources, _record = researcher.retry("first")
                self.assertEqual(len(sources), 1)
                with self.assertRaises(ToolExecutionError) as raised:
                    researcher.retry("critic retry")

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
        self.assertEqual(httpx_files, {"tavily_search.py", "disclosure_source.py"})

        expected = {"tavily_search.py": 2, "disclosure_source.py": 3}
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
        researcher.retry("one")
        sources, record = researcher.retry("two")
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
                ),
                search_tool=provider,
            )
            state = engine.run(topic="budget refusal", depth_level=1)
            engine._checkpoint_conn.close()

        self.assertEqual(state.status, "budget_exceeded")
        self.assertEqual(
            state.agent_decisions[-1].decision_type,
            "external_request_budget_rejected",
        )
        self.assertEqual(
            state.metadata["external_request_budget"]["search_requests"], 0,
        )


if __name__ == "__main__":
    unittest.main()
